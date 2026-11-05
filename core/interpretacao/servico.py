"""Rascunho de interpretação e revisão explícita antes da seleção musical.

Não executa chamadas externas por padrão. Adaptadores podem ser injetados sem
dar ao modelo controle sobre identidade, confirmação, arquivos ou músicas.
"""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, field_validator, model_validator

from core import storage
from core.recomendador import recomendar_musicas, explicar_recomendacoes, validar_limite_recomendacoes
from core.sessoes import ConflitoSessao, atualizar_sessao, recomendacoes_registradas
from core.interpretacao.adaptadores import InterpretadorLexical
from core.interpretacao.base import BaseIndisponivel, carregar_base
from core.interpretacao.contratos import Categoria, PropostaInterpretacao, PropostaLLM
from core.interpretacao.llm import SaidaLLMInvalida


class ErroInterpretacao(Exception):
    def __init__(self, status, mensagem):
        super().__init__(mensagem)
        self.status = status


class ContratoServico(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PedidoInterpretacao(ContratoServico):
    sessao_id: UUID
    motor: Literal["dicionario", "llm"] = "dicionario"
    permitir_fallback_dicionario: StrictBool = False
    regenerar: StrictBool = False


class CategoriasRevisadas(ContratoServico):
    emocoes_confirmadas: list[Categoria] = Field(max_length=14)
    estado_desejado_confirmado: list[Categoria] = Field(max_length=14)
    texto_desejado: StrictStr = Field(max_length=4000)

    @field_validator("emocoes_confirmadas", "estado_desejado_confirmado")
    @classmethod
    def sem_repeticao(cls, valores):
        if len(valores) != len(set(valores)):
            raise ValueError("Categorias confirmadas não podem repetir.")
        return valores

    @model_validator(mode="after")
    def validar_desejo(self):
        if self.estado_desejado_confirmado and not self.texto_desejado.strip():
            raise ValueError("Informe o texto desejado ao confirmar suas categorias.")
        return self


class PedidoRevisao(CategoriasRevisadas):
    sessao_id: UUID
    interpretacao_id: UUID


class RevisaoRegistrada(CategoriasRevisadas):
    registrada_em: StrictStr


class InterpretacaoRegistrada(ContratoServico):
    versao_contrato: Literal["rhythmmind-interpretacao-v1"] = "rhythmmind-interpretacao-v1"
    interpretacao_id: UUID
    sessao_id: UUID
    criada_em: StrictStr
    base_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    hash_entrada: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    chave_reuso: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    motor_solicitado: Literal["dicionario", "llm"]
    motor_utilizado: Literal["dicionario", "llm", "mock"]
    motor_versao: StrictStr = Field(min_length=1, max_length=200)
    provedor: StrictStr | None = Field(default=None, min_length=1, max_length=100)
    modelo: StrictStr | None = Field(default=None, min_length=1, max_length=100)
    fallback_motivo: Literal["indisponivel", "saida_invalida", "falha_motor"] | None = None
    estado_revisao: Literal["pendente", "revisada", "superada"] = "pendente"
    proposta: PropostaInterpretacao
    revisao: RevisaoRegistrada | None = None


class ResultadoRevisao(ContratoServico):
    sessao_id: UUID
    interpretacao: InterpretacaoRegistrada
    analise: dict
    texto_desejado: StrictStr
    recomendacoes: list[dict]
    motivos_recomendacoes: list[dict]
    limite_recomendacoes: int
    progresso: dict


class MotoresInterpretacao:
    """Registro do servidor. Mock e LLM nunca são escolhidos pelo texto do modelo."""

    def __init__(self, *, dicionario=None, llm=None):
        self.dicionario = dicionario if dicionario is not None else InterpretadorLexical()
        self.llm = llm


def _hash(dados):
    serializado = json.dumps(dados, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serializado.encode("utf-8")).hexdigest()


def _hash_entrada(registro):
    return _hash({"texto_original": registro.get("texto_usuario"),
                  "texto_desejado": registro.get("texto_desejado")})


def _ler_sessao(identificador):
    try:
        historico = storage.carregar_json(storage.ARQ_HISTORICO, {}, estrito=True)
        if not isinstance(historico, dict):
            raise ValueError("Histórico inválido.")
    except (OSError, ValueError) as erro:
        raise ErroInterpretacao(503, "Histórico indisponível para esta operação.") from erro
    if identificador not in historico:
        raise ErroInterpretacao(404, "Sessão não encontrada.")
    registro = historico[identificador]
    if not isinstance(registro, dict):
        raise ErroInterpretacao(503, "Registro de sessão inválido.")
    return registro


def _exigir_pendente(registro):
    progresso = registro.get("progresso")
    if (not isinstance(progresso, dict) or recomendacoes_registradas(registro)
            or progresso.get("emocoes_confirmadas")):
        raise ErroInterpretacao(409, "Esta sessão já possui decisões confirmadas; crie outra para interpretar.")


def _textos(registro):
    original, desejo = registro.get("texto_usuario"), registro.get("texto_desejado")
    if not isinstance(original, str) or not original.strip() or len(original) > 4000:
        raise ErroInterpretacao(422, "A interpretação exige um relato não vazio de até 4000 caracteres.")
    if desejo is not None and (not isinstance(desejo, str) or len(desejo) > 4000):
        raise ErroInterpretacao(422, "O texto desejado deve ter até 4000 caracteres.")
    return original, desejo


def _rascunho(registro, identificador):
    bruto = registro.get("interpretacao")
    if bruto is None:
        return None
    try:
        rascunho = InterpretacaoRegistrada.model_validate(bruto)
        if str(rascunho.sessao_id) != identificador:
            raise ValueError("Identidade incompatível.")
        if rascunho.revisao is not None:
            rascunho.estado_revisao = "revisada"
        elif (not isinstance(registro.get("progresso"), dict)
              or recomendacoes_registradas(registro)
              or registro["progresso"].get("emocoes_confirmadas")):
            rascunho.estado_revisao = "superada"
        else:
            rascunho.estado_revisao = "pendente"
        return rascunho
    except ValueError as erro:
        raise ErroInterpretacao(503, "A interpretação salva está indisponível.") from erro


def _gravar(identificador, *, esperado, **campos):
    try:
        return atualizar_sessao(storage.ARQ_HISTORICO, identificador, esperado=esperado, **campos)
    except ConflitoSessao as erro:
        raise ErroInterpretacao(409, str(erro)) from erro
    except OSError as erro:
        raise ErroInterpretacao(503, "Não foi possível salvar. A última versão salva foi preservada.") from erro


class _FalhaMotor(Exception):
    def __init__(self, motivo):
        self.motivo = motivo


def _executar_motor(motor, original, desejo, base):
    if motor is None:
        raise _FalhaMotor("indisponivel")
    try:
        saida = motor.interpretar(original, desejo, base)
    except SaidaLLMInvalida as erro:
        raise _FalhaMotor("saida_invalida") from erro
    except Exception as erro:
        raise _FalhaMotor("falha_motor") from erro
    try:
        origem = motor.origem
        identificador = motor.identificador
        if (origem not in {"dicionario", "llm", "mock"}
                or not isinstance(identificador, str) or not identificador.strip()
                or len(identificador) > 200):
            raise ValueError("Motor sem identificação válida.")
        # Revalidar mesmo modelos construídos internamente sem validação.
        if isinstance(saida, BaseModel):
            saida = saida.model_dump()
        contrato = PropostaLLM if origem == "llm" else PropostaInterpretacao
        proposta = (contrato.model_validate_json(saida) if isinstance(saida, str)
                    else contrato.model_validate(saida))
        referencias_validas = {regra["id"] for regra in base.conhecimento["regras"]}
        if not set(proposta.referencias_base) <= referencias_validas:
            raise ValueError("Referência ausente da base utilizada.")
        if origem == "llm" and (getattr(motor, "provedor", None) not in {"openai", "gemini"}
                               or not isinstance(getattr(motor, "modelo", None), str)
                               or not 1 <= len(motor.modelo) <= 100):
            raise ValueError("Metadados de LLM inválidos.")
        for parte, texto in ((proposta.estado_atual, original),
                             (proposta.estado_desejado, desejo if desejo is not None else original)):
            for sugestao in parte.sugestoes:
                if origem == "dicionario":
                    if sugestao.evidencias or sugestao.confianca_autodeclarada is not None:
                        raise ValueError("O analisador lexical não fornece evidências nem confiança.")
                elif not sugestao.evidencias or any(trecho not in texto for trecho in sugestao.evidencias):
                    raise ValueError("Evidência da interpretação não consta no texto.")
        if proposta.texto_intencao is not None:
            fontes = [original] + ([desejo] if desejo is not None else [])
            if not any(proposta.texto_intencao in texto for texto in fontes):
                raise ValueError("A intenção sugerida não consta no texto original.")
        return proposta, origem, identificador
    except (ValueError, AttributeError, TypeError) as erro:
        raise _FalhaMotor("saida_invalida") from erro


def interpretar_sessao(pedido: PedidoInterpretacao, motores: MotoresInterpretacao):
    identificador = str(pedido.sessao_id)
    registro = _ler_sessao(identificador)
    _exigir_pendente(registro)
    original, desejo = _textos(registro)
    try:
        base = carregar_base()
    except (BaseIndisponivel, OSError, ValueError) as erro:
        raise ErroInterpretacao(503, "Base de interpretação indisponível.") from erro
    chave = _hash({"entrada": _hash_entrada(registro), "base": base.sha256,
                   "motor": pedido.motor, "fallback": pedido.permitir_fallback_dicionario,
                   "dicionario": getattr(motores.dicionario, "identificador", None),
                   "llm": getattr(motores.llm, "identificador", None)})
    anterior = _rascunho(registro, identificador)
    if not pedido.regenerar and anterior is not None and anterior.chave_reuso == chave:
        return anterior
    motor = motores.dicionario if pedido.motor == "dicionario" else motores.llm
    fallback = None
    try:
        proposta, origem, versao = _executar_motor(motor, original, desejo, base)
        if origem != "mock" and origem != pedido.motor:
            raise _FalhaMotor("saida_invalida")
    except _FalhaMotor as erro:
        if pedido.motor != "llm" or not pedido.permitir_fallback_dicionario:
            raise ErroInterpretacao(503, "O motor solicitado não concluiu a interpretação. O relato foi preservado.") from erro
        fallback = erro.motivo
        motor = motores.dicionario
        try:
            proposta, origem, versao = _executar_motor(motor, original, desejo, base)
            if origem not in {"dicionario", "mock"}:
                raise _FalhaMotor("saida_invalida")
        except _FalhaMotor as falha:
            raise ErroInterpretacao(503, "A interpretação e sua alternativa estão indisponíveis.") from falha
    rascunho = InterpretacaoRegistrada(
        interpretacao_id=uuid4(), sessao_id=pedido.sessao_id,
        criada_em=datetime.now(timezone.utc).isoformat(), base_sha256=base.sha256,
        hash_entrada=_hash_entrada(registro), chave_reuso=chave,
        motor_solicitado=pedido.motor, motor_utilizado=origem, motor_versao=versao,
        provedor=motor.provedor if origem == "llm" else None,
        modelo=motor.modelo if origem == "llm" else None,
        fallback_motivo=fallback, proposta=proposta,
    )
    _gravar(identificador, esperado=registro, interpretacao=rascunho.model_dump(mode="json"))
    return rascunho


def obter_interpretacao(identificador):
    registro = _ler_sessao(str(identificador))
    rascunho = _rascunho(registro, str(identificador))
    if rascunho is None:
        raise ErroInterpretacao(404, "Esta sessão ainda não tem uma interpretação registrada.")
    if rascunho.estado_revisao == "pendente" and rascunho.hash_entrada != _hash_entrada(registro):
        raise ErroInterpretacao(409, "O texto da sessão mudou; solicite outra interpretação.")
    return rascunho


def _resultado_revisao(registro, rascunho):
    return ResultadoRevisao(
        sessao_id=rascunho.sessao_id, interpretacao=rascunho,
        analise=registro["analise"], texto_desejado=registro["texto_desejado"],
        recomendacoes=registro["recomendacoes"], motivos_recomendacoes=registro["motivos_recomendacoes"],
        limite_recomendacoes=registro["limite_recomendacoes"], progresso=registro["progresso"],
    )


def revisar_interpretacao(pedido: PedidoRevisao):
    identificador = str(pedido.sessao_id)
    registro = _ler_sessao(identificador)
    rascunho = _rascunho(registro, identificador)
    if rascunho is None or rascunho.interpretacao_id != pedido.interpretacao_id:
        raise ErroInterpretacao(409, "A revisão não corresponde à interpretação vigente.")
    decisao = pedido.model_dump(include={"emocoes_confirmadas", "estado_desejado_confirmado", "texto_desejado"})
    if rascunho.revisao is not None:
        anterior = rascunho.revisao.model_dump(exclude={"registrada_em"})
        if decisao != anterior:
            raise ErroInterpretacao(409, "Esta interpretação já foi revisada com outra decisão.")
        return _resultado_revisao(registro, rascunho)
    _exigir_pendente(registro)
    if rascunho.hash_entrada != _hash_entrada(registro):
        raise ErroInterpretacao(409, "O texto da sessão mudou; solicite outra interpretação.")
    salvo = registro.get("texto_desejado")
    if salvo is not None and pedido.texto_desejado != salvo:
        raise ErroInterpretacao(409, "O texto desejado já salvo deve ser preservado.")
    try:
        limite = validar_limite_recomendacoes(registro.get("limite_recomendacoes", 3))
        estrategia, explicacao, recomendacoes = recomendar_musicas(
            pedido.emocoes_confirmadas, pedido.estado_desejado_confirmado, limite=limite,
        )
        motivos = explicar_recomendacoes(pedido.emocoes_confirmadas, estrategia, recomendacoes)
    except Exception as erro:
        raise ErroInterpretacao(500, "A seleção não foi concluída. A interpretação foi preservada para nova revisão.") from erro
    analise = deepcopy(registro.get("analise", {}))
    analise.update(emocoes=pedido.emocoes_confirmadas, estado_desejado=pedido.estado_desejado_confirmado)
    progresso = dict(registro["progresso"])
    progresso.update(emocoes_confirmadas=True, estado_desejado_informado=True, recomendacoes_geradas=True)
    rascunho.revisao = RevisaoRegistrada(**decisao, registrada_em=datetime.now(timezone.utc).isoformat())
    rascunho.estado_revisao = "revisada"
    atualizado = _gravar(
        identificador, esperado=registro, interpretacao=rascunho.model_dump(mode="json"), analise=analise,
        texto_desejado=pedido.texto_desejado, estrategia=estrategia, explicacao=explicacao,
        recomendacoes=recomendacoes, motivos_recomendacoes=motivos,
        limite_recomendacoes=limite, progresso=progresso,
    )
    return _resultado_revisao(atualizado, rascunho)
