"""Login Google local: redirecionamento OIDC e entrega de acesso em uso unico."""

import logging
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from api.autenticacao import _executar
from core.google_oidc import (
    ConfiguracaoGoogleInvalida,
    FalhaGoogleIndisponivel,
    FalhaIdentidadeGoogle,
    carregar_config_google,
    validar_codigo_google,
)


router = APIRouter(prefix="/api/auth/google", tags=["acesso Google"])
_COOKIE_FLUXO = "rhythmmind_google_fluxo"
_COOKIE_ENTRADA = "rhythmmind_google_entrada"
_COOKIE_PATH = "/api/auth/google"


class _FiltroCallbackGoogle(logging.Filter):
    def filter(self, record):
        # O codigo de autorizacao chega pela query; nao deve ir ao access log.
        if isinstance(record.args, tuple) and len(record.args) == 5:
            endereco = record.args[2]
            if isinstance(endereco, str) and endereco.split("?", 1)[0] == "/api/auth/google/callback":
                record.args = (*record.args[:2], "/api/auth/google/callback", *record.args[3:])
        return True


def configurar_logs_acesso_google():
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(filtro, _FiltroCallbackGoogle) for filtro in logger.filters):
        logger.addFilter(_FiltroCallbackGoogle())


def _config():
    try:
        config = carregar_config_google()
    except ConfiguracaoGoogleInvalida as erro:
        raise HTTPException(status_code=503, detail="Acesso com Google indisponivel neste ambiente.") from erro
    if config is None:
        raise HTTPException(status_code=503, detail="Acesso com Google indisponivel neste ambiente.")
    return config


def _origem_request(request):
    # O Host ja foi validado pela restricao local, sem confiar em proxies.
    return str(request.base_url).rstrip("/")


def _cookie(resposta, nome, valor, request, *, max_age):
    resposta.set_cookie(
        nome, valor, max_age=max_age, path=_COOKIE_PATH,
        httponly=True, secure=request.url.scheme == "https", samesite="lax",
    )


def _apagar_cookie(resposta, nome, request):
    resposta.delete_cookie(
        nome, path=_COOKIE_PATH, httponly=True,
        secure=request.url.scheme == "https", samesite="lax",
    )


def _retorno(request, estado):
    # Destino fixo. Nenhum codigo, token, email ou erro externo entra na URL.
    resposta = RedirectResponse(f"/?google={estado}", status_code=303)
    resposta.headers["Referrer-Policy"] = "no-referrer"
    _apagar_cookie(resposta, _COOKIE_FLUXO, request)
    _apagar_cookie(resposta, _COOKIE_ENTRADA, request)
    return resposta


def _parametro_unico(request, nome, *, limite):
    valores = request.query_params.getlist(nome)
    if len(valores) != 1 or not valores[0] or len(valores[0]) > limite:
        raise ValueError("Retorno de acesso invalido.")
    valor = valores[0]
    if any(ord(letra) < 32 or ord(letra) == 127 for letra in valor):
        raise ValueError("Retorno de acesso invalido.")
    return valor


@router.get("/config")
def configuracao(request: Request):
    try:
        disponivel = carregar_config_google() is not None
    except ConfiguracaoGoogleInvalida:
        disponivel = False
    return {
        "disponivel": disponivel,
        "inicio_url": "/api/auth/google/iniciar" if disponivel else None,
        "armazenamento": "persistente" if getattr(request.app.state, "armazenamento_persistente", False) else "temporario",
    }


@router.get("/iniciar")
def iniciar(request: Request):
    config = _config()
    if _origem_request(request) != config.origin:
        # Antes de criar cookies, leva localhost/127.0.0.1 a origem cadastrada.
        return RedirectResponse(config.origin + "/api/auth/google/iniciar", status_code=303)
    state, vinculo, nonce = (secrets.token_urlsafe(32) for _ in range(3))
    verifier = secrets.token_urlsafe(48)
    _executar(request, "criar_fluxo_google", state, vinculo, nonce, verifier, config.redirect_uri)
    resposta = RedirectResponse(config.url_autorizacao(state, nonce, verifier), status_code=303)
    resposta.headers["Referrer-Policy"] = "no-referrer"
    _cookie(resposta, _COOKIE_FLUXO, vinculo, request, max_age=600)
    # Reiniciar um fluxo nao conserva uma conclusao anterior pendente.
    _apagar_cookie(resposta, _COOKIE_ENTRADA, request)
    return resposta


@router.get("/callback")
def callback(request: Request):
    try:
        config = _config()
        if _origem_request(request) != config.origin:
            return _retorno(request, "falha")
        state = _parametro_unico(request, "state", limite=43)
        vinculo = request.cookies.get(_COOKIE_FLUXO)
        fluxo = _executar(request, "consumir_fluxo_google", state, vinculo)
        if fluxo["redirect_uri"] != config.redirect_uri:
            return _retorno(request, "falha")
        if "error" in request.query_params:
            erro = _parametro_unico(request, "error", limite=200)
            cancelado = erro == "access_denied" and "code" not in request.query_params
            return _retorno(request, "cancelado" if cancelado else "falha")
        codigo = _parametro_unico(request, "code", limite=4096)
        identidade = validar_codigo_google(config, codigo, fluxo["nonce"], fluxo["verifier"])
        perfil = _executar(request, "entrar_google", identidade["iss"], identidade["sub"])
        entrega = _executar(request, "preparar_entrada_google", perfil["usuario_id"])
        resposta = _retorno(request, "concluir")
        _cookie(resposta, _COOKIE_ENTRADA, entrega, request, max_age=60)
        return resposta
    except (FalhaGoogleIndisponivel, HTTPException) as erro:
        if isinstance(erro, FalhaGoogleIndisponivel) or erro.status_code == 503:
            return _retorno(request, "indisponivel")
        return _retorno(request, "falha")
    except (ValueError, FalhaIdentidadeGoogle):
        return _retorno(request, "falha")


@router.post("/concluir")
def concluir(request: Request):
    config = _config()
    if (
        _origem_request(request) != config.origin
        or request.headers.get("origin") != config.origin
        or request.headers.get("sec-fetch-site") not in {None, "same-origin"}
    ):
        raise HTTPException(status_code=403, detail="Origem de acesso invalida.")
    try:
        acesso = _executar(request, "concluir_entrada_google", request.cookies.get(_COOKIE_ENTRADA))
        resposta = JSONResponse(acesso)
    except HTTPException as erro:
        resposta = JSONResponse({"detail": erro.detail}, status_code=erro.status_code, headers=erro.headers)
    _apagar_cookie(resposta, _COOKIE_ENTRADA, request)
    resposta.headers["Referrer-Policy"] = "no-referrer"
    return resposta
