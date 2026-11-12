"""Consulta da referência pública e cópia voluntária para a própria conta."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from api.autenticacao import usuario_autenticado
from core.catalogo_referencia import (
    AssociacaoAmbigua, CatalogoIndisponivel, MAX_IDS_IMPORTACAO, MusicaNaoEncontrada,
    atualizar_associacoes_musica, carregar_catalogo_referencia, importar_catalogo_referencia,
)
from core.interpretacao.contratos import CATEGORIAS, Categoria


router = APIRouter(dependencies=[Depends(usuario_autenticado)], tags=["catálogo"])
IdentificadorFaixa = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=200)]


class ImportarCatalogoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[IdentificadorFaixa] | None = Field(default=None, max_length=MAX_IDS_IMPORTACAO)


class AssociacoesMusicaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    sentimentos_associados: list[Categoria] = Field(max_length=len(CATEGORIAS))

    @field_validator("sentimentos_associados")
    @classmethod
    def categorias_sem_repeticoes(cls, categorias):
        if len(categorias) != len(set(categorias)):
            raise ValueError("Categorias não podem se repetir.")
        return categorias


@router.get("/api/catalogo-referencia")
def consultar_catalogo_referencia():
    try:
        catalogo = carregar_catalogo_referencia()
    except CatalogoIndisponivel as erro:
        raise HTTPException(status_code=503, detail=str(erro)) from erro
    prontas = sum(bool(musica["sentimentos_associados"] or musica["estrategias"])
                  for musica in catalogo["musicas"])
    return {"versao": catalogo["versao"], "total": len(catalogo["musicas"]),
            "pronta_para_recomendar": prontas,
            "pendentes_associacao": len(catalogo["musicas"]) - prontas,
            "descricao": catalogo["descricao"], "musicas": catalogo["musicas"]}


@router.post("/api/catalogo-referencia/importar")
def importar_referencia(req: ImportarCatalogoRequest | None = None):
    try:
        return importar_catalogo_referencia(req.ids if req is not None else None)
    except CatalogoIndisponivel as erro:
        raise HTTPException(status_code=503, detail=str(erro)) from erro
    except ValueError as erro:
        raise HTTPException(status_code=422, detail=str(erro)) from erro
    except OSError as erro:
        raise HTTPException(status_code=503, detail="Não foi possível salvar a importação; o catálogo anterior foi preservado.") from erro


@router.patch("/api/musicas/{musica_id}/associacoes")
def atualizar_associacoes(musica_id: IdentificadorFaixa, req: AssociacoesMusicaRequest):
    try:
        return {"musica": atualizar_associacoes_musica(musica_id, req.sentimentos_associados)}
    except MusicaNaoEncontrada as erro:
        raise HTTPException(status_code=404, detail=str(erro)) from erro
    except AssociacaoAmbigua as erro:
        raise HTTPException(status_code=409, detail=str(erro)) from erro
    except ValueError as erro:
        raise HTTPException(status_code=422, detail=str(erro)) from erro
    except OSError as erro:
        raise HTTPException(status_code=503, detail="Não foi possível salvar as associações; o catálogo anterior foi preservado.") from erro
