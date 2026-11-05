"""
api/main.py
------------
Camada web do RhythmMind.

IMPORTANTE: as consultas compartilham a interpretação de feedback do núcleo. Este arquivo só
expõe via HTTP as mesmas funções de core/analisador_texto.py,
core/recomendador.py e core/storage.py utilizadas pela CLI (main.py).
Isso preserva a "Continuidade" do projeto: a CLI continua funcionando
em paralelo, e o front-end web vai falar com este servidor.

Como rodar:
    python -m api.desenvolvimento
    (somente local, com dados fictícios temporários)

Docs automáticas (Swagger):
    http://localhost:8000/docs
"""
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from api.autenticacao import router as router_autenticacao, usuario_autenticado
from api.interpretacao import router as router_interpretacao
from api.titular import router as router_titular
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator

from core.analisador_texto import detectar_emocoes_no_texto, remover_acentos, separar_papeis_texto
from core.recomendador import recomendar_musicas, explicar_recomendacoes, validar_limite_recomendacoes
from core.escuta import preparar_escuta
from core.caracterizacao import validar_caracterizacao
from core.sessoes import (
    criar_sessao, salvar_nova_sessao, atualizar_sessao, recomendacoes_registradas,
    validar_metadados_sessao, ConflitoSessao,
)
from core.historico import filtrar_historico
from core.titular import ErroTitular, corrigir_registro
from core.feedback import resumir_avaliacoes, LIMITACAO_POR_FAIXA, INTERPRETACAO_RETORNOS
from core.storage import (
    carregar_todas_musicas,
    salvar_musica_usuario,
    carregar_json,
    salvar_json,
    ARQ_HISTORICO,
)
# Reaproveita as inferências do BLOCO B do main.py (não duplicadas aqui)
from main import (
    validar_duracao,
    validar_bpm,
    inferir_contextos_para_musica,
    inferir_estrategias_para_musica,
    inferir_energia_para_musica,
    inferir_valencia_para_musica,
    inferir_intensidade_para_musica,
)

app = FastAPI(
    title="RhythmMind API",
    description="Desenvolvimento local com dados fictícios. Diário musical emocional — apoio reflexivo, não clínico.",
    version="1.0.0",
)

router = APIRouter(dependencies=[Depends(usuario_autenticado)])


@app.exception_handler(RequestValidationError)
async def erro_de_validacao_sem_segredos(request: Request, erro: RequestValidationError):
    # Nunca devolve o corpo recebido, que pode conter uma senha.
    return JSONResponse(status_code=422, content={
        "detail": [
            {"loc": item["loc"], "msg": item["msg"], "type": item["type"]}
            for item in erro.errors()
        ],
    })


# Libera o Next.js (rodando em outra porta, ex: localhost:3000) a chamar esta API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def restringir_desenvolvimento_local(request: Request, call_next):
    """Proteção operacional temporária; não substitui autenticação/autorização."""
    if (
        request.client is None
        or request.client.host not in {"127.0.0.1", "::1"}
        or request.url.hostname not in {"localhost", "127.0.0.1", "::1"}
    ):
        return JSONResponse(
            status_code=403,
            content={"detail": "API restrita ao desenvolvimento local."},
        )
    diretorio = getattr(app.state, "diretorio_desenvolvimento", None)
    if diretorio is None or Path.cwd().resolve() != Path(diretorio).resolve():
        return JSONResponse(
            status_code=503,
            content={"detail": "Use python -m api.desenvolvimento com dados fictícios temporários."},
        )
    resposta = await call_next(request)
    if request.url.path.startswith("/api/"):
        resposta.headers["Cache-Control"] = "no-store"
        resposta.headers["Pragma"] = "no-cache"
    return resposta


# ============================================================
# SCHEMAS (equivalentes aos inputs que antes vinham de input())
# ============================================================
class MetadadosSessaoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finalidade: Optional[str] = Field(
        default=None, max_length=200,
        description="Objetivo da sessão informado pela pessoa; não altera as recomendações.",
    )
    contexto: Optional[str] = Field(
        default=None, max_length=500,
        description="Situação ou atividade informada pela pessoa, sem inferência automática.",
    )

    @field_validator("finalidade", "contexto")
    @classmethod
    def normalizar_metadados(cls, valor, info):
        return validar_metadados_sessao(**{info.field_name: valor})[info.field_name]


class EstadoEmocionalRequest(MetadadosSessaoRequest):
    texto_atual: str
    emocoes_confirmadas: Optional[List[str]] = Field(
        default=None,
        description="Ausente/null: revisão pendente. []: seguir sem categoria por escolha explícita.",
    )
    texto_desejado: Optional[str] = None  # ausente: pendente; "" explícito: seguir sem definir
    limite_recomendacoes: StrictInt = Field(
        default=3, ge=1, le=10,
        description="Quantidade máxima de sugestões para esta sessão, de 1 a 10.",
    )

    @model_validator(mode="after")
    def validar_relato(self):
        if not self.texto_atual.strip():
            raise ValueError("Informe um relato não vazio.")
        return self


class ReferenciaSessaoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sessao_id: Optional[str] = None
    data_hora: Optional[str] = Field(
        default=None, json_schema_extra={"deprecated": True},
        description="Compatibilidade: chave legada exata do histórico; prefira sessao_id.",
    )

    @model_validator(mode="after")
    def validar_referencia(self):
        if (self.sessao_id is None) == (self.data_hora is None):
            raise ValueError("Informe exatamente um valor não nulo: sessao_id ou data_hora legada.")
        if not self.identificador.strip():
            raise ValueError("O identificador da sessão não pode ser vazio.")
        return self

    @property
    def identificador(self):
        # Apenas chave exata; nunca busca pelo valor descritivo data_hora.
        return self.sessao_id if self.sessao_id is not None else self.data_hora


class RetomarSessaoRequest(ReferenciaSessaoRequest):
    model_config = ConfigDict(extra="forbid")

    emocoes_confirmadas: Optional[List[str]] = Field(
        default=None,
        description="Ausente/null: manter a revisão atual. []: seguir sem categoria por escolha explícita.",
    )
    texto_desejado: Optional[str] = None
    limite_recomendacoes: Optional[StrictInt] = Field(
        default=None, ge=1, le=10,
        description="Ausente/null preserva. Só pode mudar antes das recomendações serem salvas.",
    )


class ContextoSessaoRequest(ReferenciaSessaoRequest, MetadadosSessaoRequest):
    @model_validator(mode="after")
    def exigir_metadados(self):
        if not self.model_fields_set.intersection({"finalidade", "contexto"}):
            raise ValueError("Informe ao menos um campo: finalidade ou contexto.")
        return self


class FeedbackRequest(ReferenciaSessaoRequest):
    ajudou: bool
    motivo: str = ""
    melhoria: str = ""


class FaixaEscutaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indice_recomendacao: StrictInt  # posição na lista da própria sessão, a partir de 1
    ouvida: Optional[StrictBool] = None  # ausente/null não significa que não ouviu


class EscutaRequest(ReferenciaSessaoRequest):
    model_config = ConfigDict(extra="forbid")

    faixas: List[FaixaEscutaRequest]  # lista obrigatória; [] é escolha explícita de nenhuma


class NovaMusicaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: str
    artista: str
    duracao: str             # formato m:ss ou mm:ss
    bpm: Optional[str] = ""  # string porque pode vir vazio do formulário
    sentimentos_texto: str   # texto livre, ex: "calmo reflexivo"
    tags: Optional[str] = "" # separadas por vírgula ou espaço
    caracterizacao: Optional[dict] = None

    @field_validator("caracterizacao", mode="before")
    @classmethod
    def validar_atributos_opcionais(cls, valor):
        if valor is not None:
            try:
                validar_caracterizacao(valor)
            except ValueError as erro:
                # Evita ecoar NaN/Inf na serializacao da resposta de validacao.
                raise HTTPException(status_code=422, detail=str(erro)) from erro
        return valor


# ============================================================
# 1) DETECTAR EMOÇÕES NO TEXTO (passo intermediário do front-end)
# ============================================================
@router.post("/api/detectar-emocoes")
def detectar_emocoes(texto: str):
    """Usado pelo front-end para mostrar 'Acho que você está se sentindo: X, Y.
    Correto?' antes de pedir confirmação, como na CLI. Intenções explícitas
    são separadas para não serem apresentadas como estado atual."""
    emocoes = detectar_emocoes_no_texto(separar_papeis_texto(texto)[0])
    return {"emocoes_detectadas": emocoes}


# ============================================================
# 2) REGISTRAR ESTADO E RECEBER RECOMENDAÇÃO (Opção 1 da CLI)
# ============================================================
def _resposta_estado(registro, detectadas=None):
    analise = registro.get("analise", {})
    progresso = registro.get("progresso")
    return {
        "sessao_id": registro.get("sessao_id"),
        "data_hora": registro.get("data_hora"),
        "texto_usuario": registro.get("texto_usuario"),
        "finalidade": registro.get("finalidade"),
        "contexto": registro.get("contexto"),
        "emocoes_atuais": analise.get("emocoes", []),
        "emocoes_detectadas": detectadas or [],
        "estado_desejado": analise.get("estado_desejado", []),
        "estrategia": registro.get("estrategia"),
        "explicacao": registro.get("explicacao", ""),
        "recomendacoes": registro.get("recomendacoes", []),
        "limite_recomendacoes": registro.get("limite_recomendacoes"),
        "motivos_recomendacoes": registro.get("motivos_recomendacoes"),
        "escuta": registro.get("escuta"),
        "progresso": progresso,
        "pendencias": [chave for chave, concluida in (progresso or {}).items() if not concluida],
    }


def _salvar_etapa_api(identificador, **campos):
    try:
        return atualizar_sessao(ARQ_HISTORICO, identificador, **campos)
    except ConflitoSessao as erro:
        raise HTTPException(status_code=409, detail=str(erro)) from erro
    except OSError as erro:
        raise HTTPException(status_code=503, detail={
            "sessao_id": identificador, "relato_salvo": True,
            "mensagem": "Falha ao salvar etapa. A última versão salva foi preservada.",
        }) from erro


def _avancar_sessao_api(identificador, registro, emocoes_confirmadas, texto_desejado,
                       limite_recomendacoes=None):
    analise = registro.get("analise", {})
    if recomendacoes_registradas(registro):
        # A lista salva ancora os índices de escolha/escuta; não é recalculada.
        if (
            emocoes_confirmadas is not None and emocoes_confirmadas != analise.get("emocoes", [])
        ) or (
            texto_desejado is not None and texto_desejado != registro.get("texto_desejado")
        ) or (
            limite_recomendacoes is not None
            and limite_recomendacoes != registro.get("limite_recomendacoes")
        ):
            raise HTTPException(status_code=409, detail="As recomendações desta sessão já estão registradas.")
        resposta = _resposta_estado(registro)
        resposta["sessao_id"] = identificador  # também funciona com chave legada
        return resposta

    progresso = dict(registro["progresso"])
    if emocoes_confirmadas is not None:
        if any(not emocao.strip() for emocao in emocoes_confirmadas):
            raise HTTPException(status_code=422, detail={
                "sessao_id": identificador, "relato_salvo": True,
                "mensagem": "Informe categorias não vazias, [] para seguir sem categoria, ou null para deixar a revisão pendente.",
            })
        if progresso["emocoes_confirmadas"] and emocoes_confirmadas != analise["emocoes"]:
            raise HTTPException(status_code=409, detail="As categorias desta sessão já foram confirmadas.")
    if progresso["estado_desejado_informado"]:
        if texto_desejado is not None and texto_desejado != registro.get("texto_desejado"):
            raise HTTPException(status_code=409, detail="O estado desejado desta sessão já foi informado.")
    else:
        texto_salvo = registro.get("texto_desejado")
        if texto_salvo is not None and texto_desejado is not None and texto_desejado != texto_salvo:
            raise HTTPException(status_code=409, detail="O texto do estado desejado desta sessão já foi salvo.")

    # Rejeita conflitos antes de salvar a quantidade ou qualquer etapa recebida.
    if limite_recomendacoes is not None and limite_recomendacoes != registro.get("limite_recomendacoes"):
        registro = _salvar_etapa_api(identificador, esperado=registro, limite_recomendacoes=limite_recomendacoes)
    if emocoes_confirmadas is not None and not progresso["emocoes_confirmadas"]:
        analise = dict(analise)
        analise["emocoes"] = emocoes_confirmadas
        progresso["emocoes_confirmadas"] = True
        registro = _salvar_etapa_api(identificador, esperado=registro, analise=analise, progresso=progresso)

    if not progresso["estado_desejado_informado"]:
        texto_salvo = registro.get("texto_desejado")
        texto = texto_salvo if texto_salvo is not None else texto_desejado
        if texto is not None:
            registro = _salvar_etapa_api(identificador, esperado=registro, texto_desejado=texto)
            analise = dict(registro["analise"])
            analise["estado_desejado"] = detectar_emocoes_no_texto(texto) if texto else []
            progresso["estado_desejado_informado"] = True
            registro = _salvar_etapa_api(identificador, esperado=registro, analise=analise, progresso=progresso)

    if not progresso["emocoes_confirmadas"]:
        detectadas = detectar_emocoes_no_texto(separar_papeis_texto(registro["texto_usuario"])[0])
        return _resposta_estado(registro, detectadas)
    if not progresso["estado_desejado_informado"]:
        return _resposta_estado(registro)

    limite = validar_limite_recomendacoes(registro.get("limite_recomendacoes", 3))
    opcoes = {} if limite == 3 else {"limite": limite}
    estrategia, explicacao, recomendacoes = recomendar_musicas(
        registro["analise"]["emocoes"], registro["analise"]["estado_desejado"], **opcoes,
    )
    motivos = explicar_recomendacoes(registro["analise"]["emocoes"], estrategia, recomendacoes)
    progresso["recomendacoes_geradas"] = True
    registro = _salvar_etapa_api(
        identificador, esperado=registro, estrategia=estrategia, explicacao=explicacao,
        recomendacoes=recomendacoes, motivos_recomendacoes=motivos,
        limite_recomendacoes=limite, progresso=progresso,
    )
    return _resposta_estado(registro)


def _executar_avanco_api(identificador, registro, emocoes, desejo, limite=None):
    try:
        return _avancar_sessao_api(identificador, registro, emocoes, desejo, limite)
    except HTTPException:
        raise
    except OSError as erro:
        raise HTTPException(status_code=503, detail={
            "sessao_id": identificador, "relato_salvo": True,
            "mensagem": "Falha de armazenamento. Consulte a última etapa salva.",
        }) from erro
    except Exception as erro:
        raise HTTPException(status_code=500, detail={
            "sessao_id": identificador, "relato_salvo": True,
            "mensagem": "A etapa não foi concluída. O relato permanece salvo e pode ser retomado.",
        }) from erro


@router.post("/api/registrar-estado")
def registrar_estado(req: EstadoEmocionalRequest):
    registro = criar_sessao(
        data_hora=datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        texto_usuario=req.texto_atual,
        finalidade=req.finalidade, contexto=req.contexto,
        limite_recomendacoes=req.limite_recomendacoes,
    )
    try:
        salvar_nova_sessao(ARQ_HISTORICO, registro)
    except OSError as erro:
        raise HTTPException(status_code=503, detail={
            "sessao_id": registro["sessao_id"], "relato_salvo": False,
            "mensagem": "Falha ao salvar o relato. A sessão não foi registrada.",
        }) from erro
    return _executar_avanco_api(
        registro["sessao_id"], registro, req.emocoes_confirmadas, req.texto_desejado
    )


@router.post("/api/retomar-sessao")
def retomar_sessao(req: RetomarSessaoRequest):
    historico = carregar_json(ARQ_HISTORICO, {})
    identificador = req.identificador
    if identificador not in historico:
        raise HTTPException(status_code=404, detail="Registro de histórico não encontrado.")
    return _executar_avanco_api(
        identificador, historico[identificador],
        req.emocoes_confirmadas, req.texto_desejado,
        req.limite_recomendacoes,
    )


@router.post("/api/contexto-sessao")
def registrar_contexto_sessao(req: ContextoSessaoRequest):
    """Mantém o contrato anterior, com a mesma rastreabilidade da correção do titular."""
    campos = {campo: getattr(req, campo) for campo in ("finalidade", "contexto")
              if campo in req.model_fields_set}
    try:
        registro = corrigir_registro(req.identificador, campos)["registro"]
    except ErroTitular as erro:
        raise HTTPException(status_code=erro.status, detail=str(erro)) from erro
    return {"sessao_id": req.identificador, "finalidade": registro.get("finalidade"),
            "contexto": registro.get("contexto")}


# ============================================================
# 3) FEEDBACK SOBRE A RECOMENDAÇÃO
# ============================================================
@router.post("/api/feedback")
def enviar_feedback(req: FeedbackRequest):
    historico = carregar_json(ARQ_HISTORICO, {})
    chave = req.identificador
    if chave not in historico:
        raise HTTPException(status_code=404, detail="Registro de histórico não encontrado.")

    anterior = historico[chave].get("feedback")
    feedback = dict(anterior) if isinstance(anterior, dict) else {}
    feedback["ajudou"] = req.ajudou
    for campo in ("motivo", "melhoria"):
        if campo in req.model_fields_set or campo not in feedback:
            feedback[campo] = getattr(req, campo)
    _salvar_etapa_api(chave, esperado=historico[chave], feedback=feedback)
    return {"status": "ok"}


# ============================================================
# 3b) ESCOLHA E ESCUTA — independentes do feedback da sessão
# ============================================================
@router.post("/api/escuta")
def registrar_escuta(req: EscutaRequest):
    """Substitui apenas escolha/escuta; não altera avaliação ou sugestões."""
    historico = carregar_json(ARQ_HISTORICO, {})
    chave = req.identificador
    if chave not in historico:
        raise HTTPException(status_code=404, detail="Registro de histórico não encontrado.")
    registro = historico[chave]
    try:
        escuta = preparar_escuta(
            registro.get("recomendacoes", []),
            [faixa.model_dump() for faixa in req.faixas],
        )
    except ValueError as erro:
        raise HTTPException(status_code=422, detail=str(erro)) from erro

    _salvar_etapa_api(chave, esperado=registro, escuta=escuta)
    return {"status": "ok", "escuta": escuta}


# ============================================================
# 4) MÚSICAS — listar / filtrar (Opção 2 da CLI)
# ============================================================
@router.get("/api/musicas")
def listar_musicas(sentimento: Optional[str] = None, busca: Optional[str] = None):
    todas = carregar_todas_musicas()

    if sentimento:
        emocoes_buscadas = detectar_emocoes_no_texto(sentimento) or [sentimento]
        todas = [m for m in todas if any(e in m.get("sentimentos_associados", []) for e in emocoes_buscadas)]

    if busca:
        termo_limpo = remover_acentos(busca)
        todas = [
            m for m in todas
            if termo_limpo in remover_acentos(m.get("nome", "")) or termo_limpo in remover_acentos(m.get("artista", ""))
        ]

    return {"total": len(todas), "musicas": todas}


# ============================================================
# 5) ADICIONAR MÚSICA (Opção 3 da CLI)
# ============================================================
@router.post("/api/musicas")
def adicionar_musica(req: NovaMusicaRequest):
    if not validar_duracao(req.duracao):
        raise HTTPException(status_code=422, detail="Duração inválida. Use m:ss ou mm:ss.")

    bpm = validar_bpm(req.bpm or "")
    if bpm == -1:
        raise HTTPException(status_code=422, detail="BPM inválido (deve ser entre 40 e 220).")

    sentimentos = detectar_emocoes_no_texto(req.sentimentos_texto)
    if not sentimentos:
        raise HTTPException(
            status_code=422,
            detail="Sentimentos não reconhecidos pelo dicionário emocional.",
        )

    import re
    tags = [t.strip().lower() for t in re.split(r"[,\s]+", req.tags or "") if t.strip()]
    id_musica = f"{re.sub(r'[^a-z0-9]', '', req.nome.lower())}_{re.sub(r'[^a-z0-9]', '', req.artista.lower())}"

    nova_musica = {
        "id": id_musica,
        "nome": req.nome,
        "artista": req.artista,
        "bpm": bpm,
        "duracao": req.duracao,
        "energia": inferir_energia_para_musica(sentimentos, tags, bpm),
        "valencia": inferir_valencia_para_musica(sentimentos, tags),
        "intensidade": inferir_intensidade_para_musica(sentimentos, tags, bpm),
        "sentimentos_associados": sentimentos,
        "contextos": inferir_contextos_para_musica(sentimentos, tags),
        "estrategias": inferir_estrategias_para_musica(sentimentos, tags, bpm),
        "tags": tags,
    }
    if req.caracterizacao is not None:
        nova_musica["caracterizacao"] = req.caracterizacao
    return salvar_musica_usuario(nova_musica)


# ============================================================
# 6) HISTÓRICO (Opção 4 da CLI)
# ============================================================
@router.get("/api/historico")
def ver_historico(data_inicio: Optional[str] = None, data_fim: Optional[str] = None,
                  finalidade: Optional[str] = None, contexto: Optional[str] = None,
                  avaliacao: Optional[str] = None):
    historico = carregar_json(ARQ_HISTORICO, {})
    try:
        historico = filtrar_historico(
            historico, data_inicio=data_inicio, data_fim=data_fim,
            finalidade=finalidade, contexto=contexto, avaliacao=avaliacao,
        )
    except ValueError as erro:
        raise HTTPException(status_code=422, detail=str(erro)) from erro
    return {
        "total": len(historico),
        "registros": historico,
        "avaliacoes_sessoes": resumir_avaliacoes(historico),
        "limitacao_resultados_por_faixa": LIMITACAO_POR_FAIXA,
        "interpretacao_retornos": INTERPRETACAO_RETORNOS,
    }


@router.get("/api/historico/sessao")
def consultar_sessao(sessao_id: str):
    """Consulta por UUID ou chave legada exata, sem migrar ou alterar o registro."""
    historico = carregar_json(ARQ_HISTORICO, {})
    if sessao_id not in historico:
        raise HTTPException(status_code=404, detail="Registro de histórico não encontrado.")
    return {"sessao_id": sessao_id, "registro": historico[sessao_id]}


# ============================================================
# 7) PADRÕES / RELATÓRIO REFLEXIVO (Opção 6 da CLI)
# ============================================================
@router.get("/api/padroes")
def ver_padroes():
    from collections import Counter

    historico = carregar_json(ARQ_HISTORICO, {})
    avaliacoes = resumir_avaliacoes(historico)
    if not historico:
        return {
            "mensagem": "Sem registros suficientes para gerar um relatório de padrões.",
            "avaliacoes_sessoes": avaliacoes,
            "limitacao_resultados_por_faixa": LIMITACAO_POR_FAIXA,
            "interpretacao_retornos": INTERPRETACAO_RETORNOS,
        }

    emocoes_count, desejos_count, estrategias_count = Counter(), Counter(), Counter()

    for reg in historico.values():
        analise = reg.get("analise", {})

        for e in analise.get("emocoes", []):
            emocoes_count[e] += 1
        for d in analise.get("estado_desejado", []):
            desejos_count[d] += 1

        if reg.get("estrategia"):
            estrategias_count[reg["estrategia"]] += 1

    sintese = None
    if emocoes_count and desejos_count and estrategias_count:
        emocao_top = emocoes_count.most_common(1)[0][0]
        desejo_top = desejos_count.most_common(1)[0][0]
        estrategia_top = estrategias_count.most_common(1)[0][0]
        sintese = (
            f"De acordo com o teu diário, notas uma tendência para procurar apoio musical "
            f"quando te sentes '{emocao_top}', com o objetivo de alcançar um estado de '{desejo_top}'. "
            f"A estratégia mais sugerida nessas sessões é '{estrategia_top}'."
        )

    return {
        "emocoes_frequentes": emocoes_count.most_common(3),
        "desejos_frequentes": desejos_count.most_common(3),
        "estrategias_frequentes": estrategias_count.most_common(2),
        "avaliacoes_sessoes": avaliacoes,
        "limitacao_resultados_por_faixa": LIMITACAO_POR_FAIXA,
        "interpretacao_retornos": INTERPRETACAO_RETORNOS,
        "sintese_reflexiva": sintese,
    }


@router.get("/api/proposta")
def ver_proposta():
    return {
        "titulo": "RhythmMind",
        "descricao": (
            "Funciona como um diário musical emocional e uma ferramenta de apoio reflexivo. "
            "IMPORTANTE: este sistema NÃO é uma ferramenta clínica, médica ou de diagnóstico. "
            "O objetivo é servir como apoio subjetivo para perceber padrões entre estado "
            "emocional, músicas ouvidas e bem-estar."
        ),
    }


app.include_router(router_autenticacao)
app.include_router(router)
app.include_router(router_interpretacao)
app.include_router(router_titular)
