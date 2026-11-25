"""Login Google com PKCE e entrega de acesso vinculada ao navegador."""

import base64
import hmac
import logging
import secrets

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from api.autenticacao import _executar
from core.armazenamento_nuvem import blob_ativo
from core.autenticacao import TTL_ENTRADA_GOOGLE_SEGUNDOS, TTL_FLUXO_GOOGLE_SEGUNDOS
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
_TAMANHO_PARTE_COOKIE = 3200


def _cifra_cookie(config, etapa):
    # Chaves distintas por cliente, callback e etapa impedem a troca de cookies.
    contexto = "\0".join(("rhythmmind-oidc-v1", config.client_id, config.redirect_uri, etapa))
    chave = hmac.digest(config.client_secret.encode("ascii"), contexto.encode("ascii"), "sha256")
    return Fernet(base64.urlsafe_b64encode(chave))


def _selar(config, etapa, primeiro, nonce, verifier):
    corpo = "\n".join((primeiro, nonce, verifier)).encode("ascii")
    return _cifra_cookie(config, etapa).encrypt(corpo).decode("ascii")


def _abrir(config, etapa, cookie, validade):
    try:
        corpo = _cifra_cookie(config, etapa).decrypt(cookie or "", ttl=validade)
        primeiro, nonce, verifier = corpo.decode("ascii").split("\n")
    except (InvalidToken, ValueError) as erro:
        raise FalhaIdentidadeGoogle() from erro
    return primeiro, nonce, verifier


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


def _eh_https(request):
    if request.url.scheme == "https":
        return True
    if getattr(request.app.state, "modo_producao", False):
        proto = request.headers.get("x-forwarded-proto", "")
        primeiro = proto.split(",", 1)[0].strip().lower()
        return primeiro == "https"
    return False


def _origem_request(request):
    # Em desenvolvimento local, o Host ja foi validado sem confiar em proxies.
    base = str(request.base_url).rstrip("/")
    if (
        getattr(request.app.state, "modo_producao", False)
        and base.startswith("http://")
        and _eh_https(request)
    ):
        return "https://" + base[len("http://"):]
    return base


def _cookie(resposta, nome, valor, request, *, max_age):
    resposta.set_cookie(
        nome, valor, max_age=max_age, path=_COOKIE_PATH,
        httponly=True, secure=_eh_https(request), samesite="lax",
    )


def _apagar_cookie(resposta, nome, request):
    resposta.delete_cookie(
        nome, path=_COOKIE_PATH, httponly=True,
        secure=_eh_https(request), samesite="lax",
    )


def _retorno(request, estado):
    # Destino fixo. Nenhum codigo, token, email ou erro externo entra na URL.
    resposta = RedirectResponse(f"/?google={estado}", status_code=303)
    resposta.headers["Referrer-Policy"] = "no-referrer"
    if estado != "concluir":
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
    state, nonce = (secrets.token_urlsafe(32) for _ in range(2))
    verifier = secrets.token_urlsafe(48)
    if blob_ativo():
        vinculo = _selar(config, "fluxo", state, nonce, verifier)
    else:
        vinculo = secrets.token_urlsafe(32)
        _executar(request, "criar_fluxo_google", state, vinculo, nonce, verifier, config.redirect_uri)
    resposta = RedirectResponse(config.url_autorizacao(state, nonce, verifier), status_code=303)
    resposta.headers["Referrer-Policy"] = "no-referrer"
    _cookie(resposta, _COOKIE_FLUXO, vinculo, request, max_age=TTL_FLUXO_GOOGLE_SEGUNDOS)
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
        compartilhado = blob_ativo()
        if compartilhado:
            esperado, nonce, verifier = _abrir(config, "fluxo", vinculo, TTL_FLUXO_GOOGLE_SEGUNDOS)
            if not state.isascii() or not secrets.compare_digest(esperado, state):
                return _retorno(request, "falha")
        else:
            fluxo = _executar(request, "consumir_fluxo_google", state, vinculo)
            if fluxo["redirect_uri"] != config.redirect_uri:
                return _retorno(request, "falha")
            nonce, verifier = fluxo["nonce"], fluxo["verifier"]
        if "error" in request.query_params:
            erro = _parametro_unico(request, "error", limite=200)
            cancelado = erro == "access_denied" and "code" not in request.query_params
            return _retorno(request, "cancelado" if cancelado else "falha")
        codigo = _parametro_unico(request, "code", limite=4096)
        resposta = _retorno(request, "concluir")
        restante = ""
        if compartilhado:
            if not codigo.isascii():
                return _retorno(request, "falha")
            # O Google consome o código uma única vez no POST, mesmo em outra instância.
            entrega = _selar(config, "entrada", codigo, nonce, verifier)
            # Códigos longos podem ultrapassar o limite de um cookie após a cifragem.
            restante = entrega[_TAMANHO_PARTE_COOKIE:]
            entrega = entrega[:_TAMANHO_PARTE_COOKIE]
        else:
            identidade = validar_codigo_google(config, codigo, nonce, verifier)
            perfil = _executar(request, "entrar_google", identidade["iss"], identidade["sub"])
            entrega = _executar(request, "preparar_entrada_google", perfil["usuario_id"])
        if restante:
            _cookie(resposta, _COOKIE_FLUXO, restante, request, max_age=TTL_ENTRADA_GOOGLE_SEGUNDOS)
        else:
            _apagar_cookie(resposta, _COOKIE_FLUXO, request)
        _cookie(resposta, _COOKIE_ENTRADA, entrega, request, max_age=TTL_ENTRADA_GOOGLE_SEGUNDOS)
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
        entrega = request.cookies.get(_COOKIE_ENTRADA, "")
        if blob_ativo():
            dados = entrega + request.cookies.get(_COOKIE_FLUXO, "")
            codigo, nonce, verifier = _abrir(config, "entrada", dados, TTL_ENTRADA_GOOGLE_SEGUNDOS)
            identidade = validar_codigo_google(config, codigo, nonce, verifier)
            perfil = _executar(request, "entrar_google", identidade["iss"], identidade["sub"])
            acesso = _executar(request, "emitir_acesso", perfil["usuario_id"])
        else:
            acesso = _executar(request, "concluir_entrada_google", entrega)
        resposta = JSONResponse(acesso)
    except FalhaIdentidadeGoogle:
        resposta = JSONResponse({"detail": "Acesso Google inválido ou expirado."}, status_code=401)
    except FalhaGoogleIndisponivel:
        resposta = JSONResponse({"detail": "Acesso Google indisponível."}, status_code=503)
    except HTTPException as erro:
        resposta = JSONResponse({"detail": erro.detail}, status_code=erro.status_code, headers=erro.headers)
    _apagar_cookie(resposta, _COOKIE_ENTRADA, request)
    if blob_ativo():
        _apagar_cookie(resposta, _COOKIE_FLUXO, request)
    resposta.headers["Referrer-Policy"] = "no-referrer"
    return resposta
