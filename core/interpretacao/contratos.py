"""Contratos de interpretação: sugestões sem autoridade para confirmar uma sessão."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, StringConstraints, field_validator, model_validator


Categoria = Literal[
    "feliz", "animado", "foco", "calmo", "disposto", "reflexivo", "triste",
    "cansado", "sofrendo", "ansioso", "raiva", "explosivo", "amor", "normal",
]
CATEGORIAS = (
    "feliz", "animado", "foco", "calmo", "disposto", "reflexivo", "triste",
    "cansado", "sofrendo", "ansioso", "raiva", "explosivo", "amor", "normal",
)
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

    @field_validator("texto_intencao")
    @classmethod
    def intencao_nao_branca(cls, valor):
        if valor is not None and not valor.strip():
            raise ValueError("O trecho de intenção não pode ser apenas espaços.")
        return valor
