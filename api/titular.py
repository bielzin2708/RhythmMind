"""Exportação, correção rastreável e exclusão do histórico pelo titular."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator, model_validator

from api.autenticacao import usuario_autenticado
from core.sessoes import validar_metadados_sessao
from core.titular import ErroTitular, corrigir_registro, excluir_registros, exportar_registros


router = APIRouter(tags=["titular"], dependencies=[Depends(usuario_autenticado)])


class _Contrato(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReferenciaExportacao(_Contrato):
    sessao_id: StrictStr | None = Field(default=None, min_length=1, max_length=200)
    data_hora: StrictStr | None = Field(default=None, min_length=1, max_length=200,
                                        json_schema_extra={"deprecated": True})

    @model_validator(mode="after")
    def validar_referencia(self):
        if self.sessao_id is not None and self.data_hora is not None:
            raise ValueError("Informe apenas sessao_id ou data_hora legada.")
        if any(valor is not None and not valor.strip() for valor in (self.sessao_id, self.data_hora)):
            raise ValueError("O identificador não pode ser vazio.")
        return self

    @property
    def identificador(self):
        return self.sessao_id if self.sessao_id is not None else self.data_hora


class ReferenciaRegistro(ReferenciaExportacao):
    @model_validator(mode="after")
    def exigir_referencia(self):
        if self.identificador is None:
            raise ValueError("Informe sessao_id ou data_hora legada.")
        return self


class AlteracoesRegistro(_Contrato):
    finalidade: StrictStr | None = Field(default=None, max_length=200)
    contexto: StrictStr | None = Field(default=None, max_length=500)
    observacoes: StrictStr | None = Field(default=None, max_length=4000)

    @field_validator("finalidade", "contexto")
    @classmethod
    def normalizar_metadados(cls, valor, info):
        return validar_metadados_sessao(**{info.field_name: valor})[info.field_name]

    @field_validator("observacoes")
    @classmethod
    def normalizar_observacoes(cls, valor):
        return valor.strip() or None if valor is not None else None

    @model_validator(mode="after")
    def exigir_alteracao(self):
        if not self.model_fields_set:
            raise ValueError("Informe ao menos um campo para corrigir.")
        return self


class CorrecaoRegistroRequest(ReferenciaRegistro):
    alteracoes: AlteracoesRegistro
    motivo: StrictStr | None = Field(default=None, max_length=500)
    revisao_esperada: StrictInt | None = Field(default=None, ge=0)


class ExclusaoTotalQuery(_Contrato):
    confirmar: bool = False


class ExportacaoResponse(_Contrato):
    versao: str
    exportado_em: str
    total: int
    registros: dict[str, dict]
    politica_retencao: dict[str, str]


class CorrecaoRegistroResponse(_Contrato):
    sessao_id: str
    campos_alterados: list[str]
    revisao_registro: int
    registro: dict


class ExclusaoResponse(_Contrato):
    alcance: str
    total_excluido: int
    registros_excluidos: list[str]
    politica_retencao: dict[str, str]


def _executar(funcao, *args, **kwargs):
    try:
        return funcao(*args, **kwargs)
    except ErroTitular as erro:
        raise HTTPException(status_code=erro.status, detail=str(erro)) from erro


@router.get("/api/historico/exportacao", response_model=ExportacaoResponse)
def exportar_historico(response: Response, referencia: Annotated[ReferenciaExportacao, Query()]):
    """Exporta somente os próprios registros; referência opcional restringe a uma sessão."""
    response.headers["Content-Disposition"] = 'attachment; filename="rhythmmind-registros.json"'
    return _executar(exportar_registros, referencia.identificador)


@router.patch("/api/historico/sessao", response_model=CorrecaoRegistroResponse)
def corrigir_sessao(pedido: CorrecaoRegistroRequest):
    """Corrige finalidade, contexto ou observações e registra os valores anterior/novo.

    Relato original, identidade, interpretação e decisões anteriores são preservados.
    revisao_esperada permite recusar uma edição baseada em revisão obsoleta.
    """
    return _executar(
        corrigir_registro, pedido.identificador,
        pedido.alteracoes.model_dump(exclude_unset=True),
        motivo=pedido.motivo, revisao_esperada=pedido.revisao_esperada,
    )


@router.delete("/api/historico/sessao", response_model=ExclusaoResponse)
def excluir_sessao(referencia: Annotated[ReferenciaRegistro, Query()]):
    """Remove uma sessão própria inteira, incluindo suas correções e dados derivados."""
    return _executar(excluir_registros, referencia.identificador)


@router.delete("/api/historico", response_model=ExclusaoResponse)
def excluir_historico(pedido: Annotated[ExclusaoTotalQuery, Query()]):
    """Requer confirmar=true; remove todos os registros próprios, preservando conta e catálogo."""
    if not pedido.confirmar:
        raise HTTPException(status_code=422, detail="Informe confirmar=true para excluir todos os próprios registros.")
    return _executar(excluir_registros)
