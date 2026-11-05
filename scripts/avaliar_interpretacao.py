"""Compara interpretações de relatos fictícios, sem ler sessões ou histórico.

Execução: python scripts/avaliar_interpretacao.py --llm mock --saida /tmp/avaliacao
Para chamar o provedor configurado no servidor, escolha --llm real explicitamente.
O mock verifica somente integração e schema; não representa desempenho de LLM.
"""

from argparse import ArgumentParser
from collections import Counter
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
import sys
from time import perf_counter_ns
from typing import Literal


RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, ValidationError, field_validator, model_validator

from core.interpretacao.adaptadores import InterpretadorLexical
from core.interpretacao.base import BaseIndisponivel, carregar_base
from core.interpretacao.contratos import CATEGORIAS, Categoria, Contexto, Objetivo, PropostaInterpretacao
from core.interpretacao.llm import (
    FalhaProvedorLLM, InterpretadorLLM, SaidaLLMInvalida,
    criar_interpretador_llm_do_ambiente, validar_proposta_llm,
)


Grupo = Literal["escrita_direta", "variacao_escrita", "negacao", "estado_intencao", "coexistencia", "ambiguidade"]
GRUPOS = ("escrita_direta", "variacao_escrita", "negacao", "estado_intencao", "coexistencia", "ambiguidade")


class _Contrato(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Esperado(_Contrato):
    estado_atual: list[Categoria] = Field(max_length=14)
    estado_desejado: list[Categoria] = Field(max_length=14)
    objetivos: list[Objetivo] = Field(max_length=7)
    contextos: list[Contexto] = Field(max_length=7)
    precisa_esclarecimento: StrictBool

    @field_validator("estado_atual", "estado_desejado", "objetivos", "contextos")
    @classmethod
    def sem_repeticoes(cls, valores):
        if len(valores) != len(set(valores)):
            raise ValueError("Anotações não podem repetir categorias ou atividades.")
        return valores


class Caso(_Contrato):
    id: StrictStr = Field(pattern=r"^[A-Z][A-Z0-9_-]{1,39}$")
    grupo: Grupo
    texto_original: StrictStr = Field(min_length=1, max_length=4000)
    texto_desejado: StrictStr | None = Field(max_length=4000)
    esperado: Esperado
    nota: StrictStr = Field(max_length=2000)

    @field_validator("texto_original")
    @classmethod
    def relato_nao_branco(cls, valor):
        if not valor.strip():
            raise ValueError("Relato fictício não pode ser vazio.")
        return valor


class ConjuntoCasos(_Contrato):
    versao: Literal["rhythmmind.casos-interpretacao.v1"]
    natureza: Literal["sintetico"]
    nota: StrictStr = Field(min_length=1, max_length=4000)
    casos: list[Caso] = Field(min_length=18, max_length=24)

    @model_validator(mode="after")
    def validar_conjunto(self):
        if len({caso.id for caso in self.casos}) != len(self.casos):
            raise ValueError("IDs de casos devem ser únicos.")
        if set(caso.grupo for caso in self.casos) != set(GRUPOS):
            raise ValueError("O conjunto precisa cobrir os seis grupos de problema.")
        return self


def _objeto_sem_repeticao(pares):
    objeto = {}
    for chave, valor in pares:
        if chave in objeto:
            raise ValueError("Chave JSON repetida.")
        objeto[chave] = valor
    return objeto


def carregar_casos(caminho):
    """Valida todo o protocolo antes de qualquer chamada externa."""
    bruto = Path(caminho).read_bytes()
    documento = json.loads(bruto.decode("utf-8"), object_pairs_hook=_objeto_sem_repeticao)
    documento = ConjuntoCasos.model_validate(documento).model_dump(mode="json")
    return documento, hashlib.sha256(bruto).hexdigest()


class _ClienteMockEstrutural:
    """Resposta fixa deliberadamente sem acesso ao gabarito ou a uma LLM."""

    def post_json(self, url, headers, payload, timeout):
        proposta = {
            "estado_atual": {
                "estado": "ambigua", "sugestoes": [],
                "ambiguidades": ["Você pode contar mais sobre como está?"],
                "resumo": "Esta resposta simulada requer revisão.",
            },
            "estado_desejado": {
                "estado": "sem_correspondencia", "sugestoes": [], "ambiguidades": [],
                "resumo": "Esta resposta simulada não interpreta a intenção.",
            },
            "texto_intencao": None, "objetivos": [], "contextos": [],
            "resumo_reflexivo": "Resposta simulada para verificar o contrato; confirme sua leitura.",
            "precisa_esclarecimento": True, "referencias_base": ["RM06"],
        }
        return {"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": json.dumps(proposta, ensure_ascii=False),
        }}]}


def _motor_mock():
    return InterpretadorLLM(provedor="openai", modelo="mock-estrutural-fixo-v1",
                            chave="chave-ficticia-offline", cliente=_ClienteMockEstrutural())


def _executar(motor, caso, base, *, externo, simulado):
    inicio = perf_counter_ns()
    resultado = {
        "valido_estruturalmente": False, "tempo_ms": 0.0,
        "estado_atual": None, "estado_desejado": None, "objetivos": None,
        "contextos": None, "precisa_esclarecimento": None,
        "erro": None, "comparacao": None,
    }
    try:
        proposta = motor.interpretar(caso["texto_original"], caso["texto_desejado"], base)
        dados = proposta.model_dump() if isinstance(proposta, BaseModel) else proposta
        if externo:
            proposta = validar_proposta_llm(dados, caso["texto_original"], caso["texto_desejado"], base)
        else:
            proposta = PropostaInterpretacao.model_validate(dados)
        resultado.update(
            valido_estruturalmente=True,
            estado_atual=[s.categoria for s in proposta.estado_atual.sugestoes],
            estado_desejado=[s.categoria for s in proposta.estado_desejado.sugestoes],
            objetivos=proposta.objetivos, contextos=proposta.contextos,
            precisa_esclarecimento=proposta.precisa_esclarecimento,
        )
        if not simulado:
            comparacao = {
                campo: (set(resultado[campo]) == set(esperado) if isinstance(esperado, list)
                        else resultado[campo] == esperado)
                for campo, esperado in caso["esperado"].items()
            }
            comparacao["estado_atual_e_desejado"] = comparacao["estado_atual"] and comparacao["estado_desejado"]
            comparacao["completa"] = all(comparacao.values())
            resultado["comparacao"] = comparacao
    except (SaidaLLMInvalida, ValidationError, ValueError, TypeError):
        resultado["erro"] = "saida_invalida"
    except FalhaProvedorLLM:
        resultado["erro"] = "falha_provedor"
    except Exception:
        resultado["erro"] = "falha_motor"
    resultado["tempo_ms"] = round((perf_counter_ns() - inicio) / 1_000_000, 4)
    return resultado


def _medidas(tp, fp, fn):
    precisao = tp / (tp + fp) if tp + fp else None
    revocacao = tp / (tp + fn) if tp + fn else None
    f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None
    return {"tp": tp, "fp": fp, "fn": fn, "precisao": precisao, "revocacao": revocacao, "f1": f1}


def _resumir(casos, nome, simulado):
    resultados = [caso["resultados"][nome] for caso in casos]
    resumo = {
        "total": len(casos), "validos_estruturalmente": sum(r["valido_estruturalmente"] for r in resultados),
        "falhas": sum(not r["valido_estruturalmente"] for r in resultados),
        "media_tempo_ms": round(sum(r["tempo_ms"] for r in resultados) / len(resultados), 4),
        "simulado": simulado, "metricas": None, "criterio_minimo": None,
    }
    if simulado:
        return resumo
    metricas = {
        "acertos_estado_atual_e_desejado": sum(bool(r["comparacao"] and r["comparacao"]["estado_atual_e_desejado"]) for r in resultados),
        "acertos_completos": sum(bool(r["comparacao"] and r["comparacao"]["completa"]) for r in resultados),
        "acertos_esclarecimento": sum(bool(r["comparacao"] and r["comparacao"]["precisa_esclarecimento"]) for r in resultados),
        "categorias": {},
    }
    for campo in ("estado_atual", "estado_desejado"):
        por_categoria = {}
        for categoria in CATEGORIAS:
            tp = fp = fn = 0
            for caso, resultado in zip(casos, resultados):
                esperado = categoria in caso["esperado"][campo]
                predito = categoria in (resultado[campo] or [])
                tp += esperado and predito
                fp += not esperado and predito
                fn += esperado and not predito
            por_categoria[categoria] = {**_medidas(tp, fp, fn), "suporte": tp + fn}
        metricas["categorias"][campo] = {
            "por_categoria": por_categoria,
            "micro": _medidas(*(sum(item[chave] for item in por_categoria.values()) for chave in ("tp", "fp", "fn"))),
        }
    grupos = {}
    for grupo in ("negacao", "estado_intencao"):
        itens = [caso["resultados"][nome] for caso in casos if caso["grupo"] == grupo]
        acertos = sum(bool(item["comparacao"] and item["comparacao"]["estado_atual_e_desejado"]) for item in itens)
        grupos[grupo] = {"total": len(itens), "acertos": acertos, "aprovado": bool(itens) and acertos == len(itens)}
    resumo["metricas"] = metricas
    resumo["criterio_minimo"] = {
        "definicao": "Acertar os estados atual e desejado de todos os casos dirigidos de negação e estado/intenção.",
        "grupos": grupos, "aprovado": all(item["aprovado"] for item in grupos.values()),
    }
    return resumo


def avaliar_casos(documento, base, *, modo_llm="mock", motor_llm=None):
    documento = ConjuntoCasos.model_validate(documento).model_dump(mode="json")
    if modo_llm not in {"mock", "real", "nenhum"}:
        raise ValueError("Modo de avaliação inválido.")
    motores = {"dicionario": InterpretadorLexical()}
    if modo_llm == "mock":
        motores["llm"] = _motor_mock()
    elif modo_llm == "real":
        motores["llm"] = motor_llm if motor_llm is not None else criar_interpretador_llm_do_ambiente()
        if motores["llm"] is None:
            raise ValueError("Configuração do provedor ausente ou inválida.")
    casos = []
    for caso in documento["casos"]:
        casos.append({**caso, "resultados": {
            nome: _executar(motor, caso, base, externo=nome == "llm", simulado=nome == "llm" and modo_llm == "mock")
            for nome, motor in motores.items()
        }})
    metadados_motores = {
        nome: {"origem": "mock" if nome == "llm" and modo_llm == "mock" else motor.origem,
               "identificador": motor.identificador,
               "provedor": None if nome == "llm" and modo_llm == "mock" else getattr(motor, "provedor", None),
               "modelo": getattr(motor, "modelo", None)}
        for nome, motor in motores.items()
    }
    return {
        "versao": "rhythmmind.avaliacao-interpretacao.v1",
        "metadados": {
            "gerado_em": datetime.now(timezone.utc).isoformat(), "base_sha256": base.sha256,
            "casos_sha256": hashlib.sha256(json.dumps(documento, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            "conjunto_versao": documento["versao"], "modo_llm": modo_llm,
            "nota": "Relatos e anotações sintéticos; não estimam desempenho em usuários. Mock verifica estrutura, sem métricas semânticas. Tempos de execução única, sem conclusão estatística.",
            "motores": metadados_motores,
        },
        "resumo": {"total_casos": len(casos), "grupos": dict(Counter(c["grupo"] for c in casos)),
                   "motores": {nome: _resumir(casos, nome, nome == "llm" and modo_llm == "mock") for nome in motores}},
        "casos": casos,
    }


def _md(valor):
    texto = html.escape(str(valor), quote=False).replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"([\\`*{}\[\]()#+.!_|>~-])", r"\\\1", texto).replace("\n", "<br>")


def gerar_markdown(relatorio):
    linhas = ["# Comparação de interpretação — casos sintéticos", "", relatorio["metadados"]["nota"], "",
              f"Modo LLM: **{relatorio['metadados']['modo_llm']}**. Base SHA-256: `{relatorio['metadados']['base_sha256']}`.", "",
              "| Motor | Estruturas válidas | Falhas | Média (ms) | Estados corretos | Critério mínimo |",
              "|---|---:|---:|---:|---:|---|"]
    for nome, resumo in relatorio["resumo"]["motores"].items():
        semantica = "Não avaliado (simulado)" if resumo["simulado"] else str(resumo["metricas"]["acertos_estado_atual_e_desejado"])
        criterio = "Não avaliado (simulado)" if resumo["simulado"] else ("Atendido" if resumo["criterio_minimo"]["aprovado"] else "Não atendido")
        linhas.append(f"| {nome} | {resumo['validos_estruturalmente']}/{resumo['total']} | {resumo['falhas']} | {resumo['media_tempo_ms']} | {semantica} | {criterio} |")
    linhas += ["", "| Caso | Grupo | Relato / desejo separado | Motor | Atual | Desejado | Objetivos / contextos | Esclarecimento | Válido / erro | ms | Acerto estados |",
               "|---|---|---|---|---|---|---|---|---|---:|---|"]
    for caso in relatorio["casos"]:
        for nome, resultado in caso["resultados"].items():
            relato = caso["texto_original"]
            if caso["texto_desejado"] is not None:
                relato += "\nDesejo separado: " + (caso["texto_desejado"] or "(vazio)")
            campos = [caso["id"], caso["grupo"], relato, nome,
                      resultado["estado_atual"], resultado["estado_desejado"],
                      f"{resultado['objetivos']} / {resultado['contextos']}", resultado["precisa_esclarecimento"],
                      resultado["valido_estruturalmente"] if resultado["erro"] is None else resultado["erro"], resultado["tempo_ms"],
                      resultado["comparacao"]["estado_atual_e_desejado"] if resultado["comparacao"] else "Não avaliado"]
            linhas.append("| " + " | ".join(_md(campo) for campo in campos) + " |")
    linhas += ["", "## Precisão, revocação e F1 por categoria", "",
               "Amostra dirigida e pequena. Categoria sem suporte ou predições tem medidas indefinidas (—). Respostas inválidas contam como ausência de predição; falhas também aparecem separadamente.", "",
               "| Motor | Papel | Categoria | Suporte | Precisão | Revocação | F1 |", "|---|---|---|---:|---:|---:|---:|"]
    for nome, resumo in relatorio["resumo"]["motores"].items():
        if resumo["metricas"] is None:
            continue
        for papel, medidas in resumo["metricas"]["categorias"].items():
            for categoria, valores in medidas["por_categoria"].items():
                numeros = ["—" if valores[campo] is None else f"{valores[campo]:.4f}" for campo in ("precisao", "revocacao", "f1")]
                linhas.append(f"| {nome} | {papel} | {categoria} | {valores['suporte']} | " + " | ".join(numeros) + " |")
    return "\n".join(linhas) + "\n"


def main(argv=None):
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--casos", type=Path, default=RAIZ / "data/casos_avaliacao_interpretacao.json")
    parser.add_argument("--saida", type=Path, default=RAIZ / "avaliacao/resultados_interpretacao")
    parser.add_argument("--llm", choices=("mock", "real", "nenhum"), default="mock")
    args = parser.parse_args(argv)
    try:
        documento, hash_casos = carregar_casos(args.casos)
        base = carregar_base(caminho_dicionario=RAIZ / "data/dicionario_emocional.json")
        relatorio = avaliar_casos(documento, base, modo_llm=args.llm)
        relatorio["metadados"]["casos_sha256"] = hash_casos
        json_texto = json.dumps(relatorio, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        markdown = gerar_markdown(relatorio)
        args.saida.mkdir(parents=True, exist_ok=True)
        (args.saida / "comparacao_interpretacao.json").write_text(json_texto, encoding="utf-8")
        (args.saida / "comparacao_interpretacao.md").write_text(markdown, encoding="utf-8")
    except (OSError, UnicodeError, ValueError, TypeError, BaseIndisponivel):
        print("Avaliação não iniciada ou relatório não salvo: confira casos, base, saída e configuração do provedor.", file=sys.stderr)
        return 2
    print(f"{len(relatorio['casos'])} casos avaliados; LLM={args.llm}. Relatórios JSON e Markdown em {args.saida}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
