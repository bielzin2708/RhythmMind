"""Contratos de interpretação: sugestões sem autoridade para confirmar uma sessão."""

import re
import unicodedata
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, StringConstraints, field_validator, model_validator


Categoria = Literal[
    "feliz", "animado", "foco", "calmo", "disposto", "reflexivo", "triste",
    "cansado", "sofrendo", "ansioso", "raiva", "explosivo", "amor", "normal",
]
CATEGORIAS = (
    "feliz", "animado", "foco", "calmo", "disposto", "reflexivo", "triste",
    "cansado", "sofrendo", "ansioso", "raiva", "explosivo", "amor", "normal",
)
Objetivo = Literal["treinar", "relaxar", "estudar", "reflexao", "entender", "trabalhar", "social"]
Contexto = Literal["treinar", "relaxar", "estudar", "reflexao", "entender", "trabalhar", "social"]
ReferenciaBase = Literal["RM01", "RM02", "RM03", "RM04", "RM05", "RM06", "RM07", "RM08"]
OBJETIVOS = ("treinar", "relaxar", "estudar", "reflexao", "entender", "trabalhar", "social")
CONTEXTOS = OBJETIVOS
REFERENCIAS_BASE = ("RM01", "RM02", "RM03", "RM04", "RM05", "RM06", "RM07", "RM08")
TextoCurto = Annotated[StrictStr, StringConstraints(min_length=1, max_length=500)]
Resumo = Annotated[StrictStr, StringConstraints(min_length=1, max_length=600)]
TextoIntencao = Annotated[StrictStr, StringConstraints(min_length=1, max_length=4000)]


class _Contrato(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SugestaoCategoria(_Contrato):
    categoria: Categoria
    evidencias: list[TextoCurto] = Field(default_factory=list, max_length=3)
    confianca_autodeclarada: Literal["baixa", "media", "alta"] | None = None

    @field_validator("evidencias")
    @classmethod
    def evidencias_nao_brancas(cls, valor):
        if any(not trecho.strip() for trecho in valor):
            raise ValueError("Evidências não podem ser vazias ou apenas espaços.")
        return valor


class ParteInterpretacao(_Contrato):
    estado: Literal["sugestoes", "sem_correspondencia", "ambigua"]
    sugestoes: list[SugestaoCategoria] = Field(default_factory=list, max_length=14)
    ambiguidades: list[TextoCurto] = Field(default_factory=list, max_length=5)
    resumo: Resumo

    @field_validator("resumo")
    @classmethod
    def resumo_nao_branco(cls, valor):
        if not valor.strip():
            raise ValueError("O resumo não pode ser apenas espaços.")
        return valor

    @field_validator("ambiguidades")
    @classmethod
    def ambiguidades_nao_brancas(cls, valor):
        if any(not mensagem.strip() for mensagem in valor):
            raise ValueError("As ambiguidades precisam de uma descrição.")
        return valor

    @model_validator(mode="after")
    def validar_coerencia(self):
        categorias = [sugestao.categoria for sugestao in self.sugestoes]
        if len(categorias) != len(set(categorias)):
            raise ValueError("Categorias sugeridas não podem se repetir.")
        if self.estado == "sugestoes" and not self.sugestoes:
            raise ValueError("O estado sugestoes requer pelo menos uma categoria.")
        if self.estado == "sem_correspondencia" and self.sugestoes:
            raise ValueError("Sem correspondência não pode conter categorias.")
        if self.estado == "ambigua" and not self.ambiguidades:
            raise ValueError("Uma interpretação ambígua requer uma descrição.")
        if self.estado != "ambigua" and self.ambiguidades:
            raise ValueError("Descrições de ambiguidade requerem o estado ambigua.")
        return self


class PropostaInterpretacao(_Contrato):
    estado_atual: ParteInterpretacao
    estado_desejado: ParteInterpretacao
    texto_intencao: TextoIntencao | None = None
    objetivos: list[Objetivo] = Field(default_factory=list, max_length=len(OBJETIVOS))
    contextos: list[Contexto] = Field(default_factory=list, max_length=len(CONTEXTOS))
    resumo_reflexivo: Resumo | None = None
    precisa_esclarecimento: StrictBool = False
    referencias_base: list[ReferenciaBase] = Field(default_factory=list, max_length=len(REFERENCIAS_BASE))

    @field_validator("objetivos", "contextos", "referencias_base")
    @classmethod
    def sem_repeticoes(cls, valores):
        if len(valores) != len(set(valores)):
            raise ValueError("Objetivos, contextos e referências não podem se repetir.")
        return valores

    @field_validator("resumo_reflexivo")
    @classmethod
    def resumo_reflexivo_nao_branco(cls, valor):
        if valor is not None and not valor.strip():
            raise ValueError("O resumo reflexivo não pode ser apenas espaços.")
        return valor

    @field_validator("texto_intencao")
    @classmethod
    def intencao_nao_branca(cls, valor):
        if valor is not None and not valor.strip():
            raise ValueError("O trecho de intenção não pode ser apenas espaços.")
        return valor


def _validar_linguagem_gerada(texto):
    """Barreira conservadora para alegações clínicas e percentuais em devolutivas.

    Não se aplica a evidências literais ou ao relato. Não constitui um detector
    semântico completo; a revisão humana continua sendo parte do fluxo.
    """
    normalizado = "".join(
        caractere for caractere in unicodedata.normalize("NFKD", texto.casefold())
        if not unicodedata.combining(caractere)
    )
    if re.search(r"%|\bpor\s+cento\b", normalizado):
        raise ValueError("A devolutiva não pode apresentar percentuais de certeza emocional.")
    if re.search(
        r"\b(?:diagnostic\w*|transtorno\w*|depressa\w*|depressiv\w*|"
        r"bipolar\w*|esquizofren\w*|patologi\w*|sindrome\w*|doenca\w*|"
        r"tratamento\w*|terapeutic\w*|clinicamente|cura\w*|tdah|toc|tept|"
        r"ansiedade\s+generalizada|(?:crise|sindrome)\s+de\s+panico)\b",
        normalizado,
    ):
        raise ValueError("A devolutiva deve usar linguagem cotidiana e não clínica.")
    if re.search(
        r"https?://|www\.|\b(?:musica\w*|faixas?|artistas?|cancoes?|cancao|"
        r"playlists?|bpm|ouca|escute|batimentos?|cardiac\w*|fisiologic\w*)\b",
        normalizado,
    ):
        raise ValueError("A devolutiva deve se limitar ao estado, à intenção e à atividade.")


class PropostaLLM(PropostaInterpretacao):
    """Resposta externa completa; defaults legados não completam omissões da LLM."""

    texto_intencao: TextoIntencao | None
    objetivos: list[Objetivo] = Field(max_length=len(OBJETIVOS))
    contextos: list[Contexto] = Field(max_length=len(CONTEXTOS))
    resumo_reflexivo: Resumo
    precisa_esclarecimento: StrictBool
    referencias_base: list[ReferenciaBase] = Field(min_length=1, max_length=len(REFERENCIAS_BASE))

    @model_validator(mode="after")
    def validar_devolutiva(self):
        partes = (self.estado_atual, self.estado_desejado)
        if (any(parte.estado == "ambigua" for parte in partes)
                or self.estado_atual.estado == "sem_correspondencia") and not self.precisa_esclarecimento:
            raise ValueError("Entradas insuficientes ou ambíguas precisam de esclarecimento.")
        textos = [self.resumo_reflexivo]
        for parte in partes:
            textos.extend([parte.resumo, *parte.ambiguidades])
            if any(sugestao.confianca_autodeclarada is not None for sugestao in parte.sugestoes):
                raise ValueError("A LLM não deve declarar certeza emocional.")
        for texto in textos:
            _validar_linguagem_gerada(texto)
        return self
