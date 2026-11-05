"""Snapshot do dicionário e conhecimento curado, sem catálogo ou dados pessoais."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from core import storage
from core.interpretacao.contratos import CATEGORIAS, CONTEXTOS, OBJETIVOS, REFERENCIAS_BASE


# Recurso distribuído com o código, independente da pasta de dados pessoais.
ARQ_BASE_CONHECIMENTO = Path(__file__).resolve().parents[2] / "data/base_conhecimento.json"
ESTRATEGIAS = frozenset({
    "transicao_emocional", "foco_cognitivo", "catarse", "ativacao_gradual",
    "descompressao", "ativacao", "espelhamento",
})


class BaseIndisponivel(RuntimeError):
    """A base de conhecimento não pôde ser lida e validada integralmente."""


@dataclass(frozen=True)
class BaseConhecimento:
    sha256: str
    conteudo_json: str

    @property
    def dicionario(self) -> dict[str, list[str]]:
        """Cada leitura entrega uma cópia independente do snapshot serializado."""
        conteudo = json.loads(self.conteudo_json)
        return {categoria: conteudo["taxonomia"][categoria] for categoria in conteudo["ordem_categorias"]}

    @property
    def conhecimento(self) -> dict:
        """Contexto direto curado; não inclui sinônimos, músicas ou relatos."""
        return json.loads(self.conteudo_json)["conhecimento_operacional"]


def _texto(valor, limite=2000):
    return isinstance(valor, str) and bool(valor.strip()) and len(valor) <= limite


def _vocabulário(valor, permitidos):
    return (isinstance(valor, list) and all(isinstance(item, str) for item in valor)
            and len(valor) == len(permitidos) and set(valor) == set(permitidos))


def _validar_conhecimento(conhecimento):
    """Falha fechada: o arquivo curado e o schema público devem concordar."""
    if not isinstance(conhecimento, dict) or set(conhecimento) != {
        "versao", "fonte_documental", "taxonomia", "regras",
    }:
        raise ValueError("Formato de conhecimento inválido.")
    if not _texto(conhecimento["versao"], 100):
        raise ValueError("Versão de conhecimento inválida.")
    fonte = conhecimento["fonte_documental"]
    if (not isinstance(fonte, dict) or set(fonte) != {"titulo", "versao", "nota"}
            or not all(_texto(valor) for valor in fonte.values())):
        raise ValueError("Proveniência documental inválida.")
    taxonomia = conhecimento["taxonomia"]
    if not isinstance(taxonomia, dict) or set(taxonomia) != {
        "categorias", "objetivos", "contextos", "estrategias",
    }:
        raise ValueError("Taxonomia operacional inválida.")
    for campo, permitidos in (("categorias", CATEGORIAS), ("objetivos", OBJETIVOS),
                               ("contextos", CONTEXTOS)):
        if not _vocabulário(taxonomia[campo], permitidos):
            raise ValueError("Vocabulário incompatível com o contrato.")
    estrategias = taxonomia["estrategias"]
    if (not isinstance(estrategias, list) or len(estrategias) != len(ESTRATEGIAS)
            or any(not isinstance(item, dict) or set(item) != {"id", "proposito"}
                   or not _texto(item["id"], 100) or not _texto(item["proposito"])
                   for item in estrategias)
            or {item["id"] for item in estrategias} != ESTRATEGIAS):
        raise ValueError("Estratégias incompatíveis com o motor.")
    regras = conhecimento["regras"]
    if (not isinstance(regras, list) or len(regras) != len(REFERENCIAS_BASE)
            or any(not isinstance(item, dict) or set(item) != {"id", "enunciado", "fontes"}
                   or not _texto(item["id"], 100) or not _texto(item["enunciado"])
                   or not isinstance(item["fontes"], list) or not 1 <= len(item["fontes"]) <= 8
                   or any(not _texto(fonte) for fonte in item["fontes"])
                   for item in regras)
            or {item["id"] for item in regras} != set(REFERENCIAS_BASE)):
        raise ValueError("Regras de conhecimento inválidas.")
    return conhecimento


def _objeto_sem_chaves_repetidas(pares):
    resultado = {}
    for chave, valor in pares:
        if chave in resultado:
            raise ValueError("A base contém uma chave JSON repetida.")
        resultado[chave] = valor
    return resultado


def carregar_base() -> BaseConhecimento:
    """Lê o arquivo configurado estritamente; nunca substitui falhas por defaults."""
    try:
        caminho = Path(storage.resolver_caminho(storage.ARQ_DICIONARIO))
        taxonomia = json.loads(
            caminho.read_text(encoding="utf-8"),
            object_pairs_hook=_objeto_sem_chaves_repetidas,
        )
        if not isinstance(taxonomia, dict) or set(taxonomia) != set(CATEGORIAS):
            raise ValueError("A taxonomia deve conter exatamente as 14 categorias conhecidas.")
        for categoria, sinonimos in taxonomia.items():
            if not isinstance(sinonimos, list) or any(
                not isinstance(sinonimo, str) or not sinonimo.strip()
                for sinonimo in sinonimos
            ):
                raise ValueError(f"Sinônimos inválidos para a categoria {categoria}.")
        conhecimento = _validar_conhecimento(json.loads(
            ARQ_BASE_CONHECIMENTO.read_text(encoding="utf-8"),
            object_pairs_hook=_objeto_sem_chaves_repetidas,
        ))
        conteudo = {
            "versao": "rhythmmind.interpretacao.v2",
            "taxonomia": taxonomia,
            "ordem_categorias": list(taxonomia),
            "conhecimento_operacional": conhecimento,
            "regras": {
                "categorias_sao_sugestoes": True,
                "revisao_humana_obrigatoria": True,
                "separar_estado_atual_e_intencao": True,
                "nao_inferir_categoria_ausente": True,
                "nao_realizar_diagnostico": True,
                "selecao_musical_fora_da_interpretacao": True,
            },
        }
        serializado = json.dumps(
            conteudo, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        return BaseConhecimento(
            sha256=hashlib.sha256(serializado.encode("utf-8")).hexdigest(),
            conteudo_json=serializado,
        )
    except (OSError, UnicodeError, ValueError, TypeError) as erro:
        raise BaseIndisponivel("A base de interpretação está indisponível ou inválida.") from erro
