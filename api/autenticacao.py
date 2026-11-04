"""Autenticacao da API local: credencial validada e contexto pessoal por requisicao."""

from pathlib import Path
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from starlette.concurrency import run_in_threadpool

from core.autenticacao import (
    ContaExistente,
    ErroCredenciais,
    RepositorioAcesso,
    validar_senha,
)
from core.contexto import contexto_usuario


router = APIRouter(prefix="/api/auth", tags=["acesso"])
seguranca = HTTPBearer(auto_error=False)


class CredenciaisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome_usuario: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    senha: SecretStr

    @field_validator("senha")
    @classmethod
    def validar_tamanho_senha(cls, senha):
        validar_senha(senha.get_secret_value())
        return senha


def _nao_autorizado():
    return HTTPException(
        status_code=401,
        detail="Credencial ausente, invalida, expirada ou encerrada.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _raiz_autorizada(request):
    diretorio = getattr(request.app.state, "diretorio_desenvolvimento", None)
    if diretorio is None or Path.cwd().resolve() != Path(diretorio).resolve():
        raise HTTPException(status_code=503, detail="Ambiente de desenvolvimento local nao autorizado.")
    return Path(diretorio).resolve()


def _executar(request, metodo, *argumentos):
    try:
        repositorio = RepositorioAcesso(_raiz_autorizada(request) / "data" / "acesso.sqlite3")
        return getattr(repositorio, metodo)(*argumentos)
    except ErroCredenciais as erro:
        raise _nao_autorizado() from erro
    except ContaExistente as erro:
        raise HTTPException(status_code=409, detail="Nome de usuario indisponivel.") from erro
    except ValueError as erro:
        raise HTTPException(status_code=422, detail=str(erro)) from erro
    except (OSError, sqlite3.Error) as erro:
        raise HTTPException(status_code=503, detail="Armazenamento de acesso indisponivel.") from erro


async def usuario_autenticado(
    request: Request,
    credenciais: HTTPAuthorizationCredentials | None = Depends(seguranca),
):
    """A identidade vem somente da credencial, com reset de contexto no encerramento."""
    if credenciais is None:
        raise _nao_autorizado()
    perfil = await run_in_threadpool(_executar, request, "identificar", credenciais.credentials)
    with contexto_usuario(perfil["usuario_id"], _raiz_autorizada(request)):
        yield perfil


@router.post("/registrar", status_code=201)
def registrar(req: CredenciaisRequest, request: Request, response: Response):
    perfil = _executar(request, "cadastrar", req.nome_usuario, req.senha.get_secret_value())
    response.headers["Cache-Control"] = "no-store"
    return perfil


@router.post("/entrar")
def entrar(req: CredenciaisRequest, request: Request, response: Response):
    acesso = _executar(request, "entrar", req.nome_usuario, req.senha.get_secret_value())
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return acesso


@router.post("/sair", status_code=204)
def sair(
    request: Request,
    perfil: dict = Depends(usuario_autenticado),
    credenciais: HTTPAuthorizationCredentials = Depends(seguranca),
):
    _executar(request, "sair", credenciais.credentials)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.get("/eu")
def eu(response: Response, perfil: dict = Depends(usuario_autenticado)):
    response.headers["Cache-Control"] = "no-store"
    return perfil
