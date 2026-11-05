"""Snapshot versionado do dicionário comum, sem catálogo ou dados pessoais."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from core import storage
from core.interpretacao.contratos import CATEGORIAS


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
        conteudo = {
            "versao": "rhythmmind.interpretacao.v1",
            "taxonomia": taxonomia,
            "ordem_categorias": list(taxonomia),
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
