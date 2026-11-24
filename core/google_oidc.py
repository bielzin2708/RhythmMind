"""OpenID Connect Google: contexto fixo, PKCE e identidade verificada no servidor.

Nao conserva tokens Google nem deriva identidades locais de email/nome.
O navegador nunca recebe o segredo do cliente OAuth.
"""

import base64
from dataclasses import dataclass, field
import hashlib
import math
import os
import re
import secrets
from urllib.parse import urlencode, urlsplit

from google.auth import exceptions as google_exceptions, jwt as google_jwt
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
import requests


_AUTORIZACAO = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN = "https://oauth2.googleapis.com/token"
_ISSUER = "https://accounts.google.com"
_CALLBACK = "/api/auth/google/callback"
_REDIRECT_PADRAO = "http://127.0.0.1:8000" + _CALLBACK
_HOSTS_LOCAIS = frozenset({"localhost", "127.0.0.1", "::1"})
_ROTULO_HOST = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_TIMEOUT = 10
_CLIENT_ID = re.compile(r"[a-zA-Z0-9_-]+\.apps\.googleusercontent\.com\Z")
_ALEATORIO = re.compile(r"[a-zA-Z0-9_-]{43}\Z")
_VERIFIER = re.compile(r"[a-zA-Z0-9._~-]{43,128}\Z")


def ambiente_producao(environ=None):
    env = os.environ if environ is None else environ
    return env.get("RHYTHMMIND_AMBIENTE", "").strip().lower() == "producao"


def _host_externo_valido(host):
    if not isinstance(host, str) or not 1 <= len(host) <= 253 or "." not in host:
        return False
    rotulos = host.split(".")
    if any(not _ROTULO_HOST.fullmatch(rotulo) for rotulo in rotulos):
        return False
    tld = rotulos[-1]
    return tld != "invalid" and not tld.isdigit() and len(tld) >= 2


class ConfiguracaoGoogleInvalida(Exception):
    def __init__(self):
        super().__init__("Configuracao de acesso Google incompleta ou invalida.")


class FalhaGoogleIndisponivel(Exception):
    def __init__(self):
        super().__init__("O acesso com Google esta temporariamente indisponivel.")


class FalhaIdentidadeGoogle(Exception):
    def __init__(self):
        super().__init__("Nao foi possivel confirmar a identidade com Google.")


def _texto_seguro(valor, maximo):
    return (isinstance(valor, str) and 0 < len(valor) <= maximo
            and valor.isascii() and all(33 <= ord(c) <= 126 for c in valor))


@dataclass(frozen=True)
class GoogleConfig:
    client_id: str
    client_secret: str = field(repr=False)
    redirect_uri: str = _REDIRECT_PADRAO
    permitir_host_externo: bool = False

    def __post_init__(self):
        if (not _texto_seguro(self.client_id, 1024) or not _CLIENT_ID.fullmatch(self.client_id)
                or not _texto_seguro(self.client_secret, 1024)
                or not _texto_seguro(self.redirect_uri, 2048)):
            raise ConfiguracaoGoogleInvalida()
        try:
            url = urlsplit(self.redirect_uri)
            porta = url.port
            local = url.hostname in _HOSTS_LOCAIS
            esquema_valido = url.scheme in {"http", "https"} if local else url.scheme == "https"
            host_valido = local or (self.permitir_host_externo and _host_externo_valido(url.hostname))
            if (not esquema_valido
                    or not host_valido
                    or url.username is not None or url.password is not None
                    or (porta is not None and not 1 <= porta <= 65535)
                    or url.path != _CALLBACK or url.query or url.fragment
                    or "?" in self.redirect_uri or "#" in self.redirect_uri):
                raise ConfiguracaoGoogleInvalida()
            host = "[::1]" if url.hostname == "::1" else url.hostname
            autoridade = host + (f":{porta}" if porta is not None else "")
            object.__setattr__(self, "redirect_uri", f"{url.scheme}://{autoridade}{_CALLBACK}")
        except ValueError:
            raise ConfiguracaoGoogleInvalida() from None

    @property
    def origin(self):
        return self.redirect_uri[:-len(_CALLBACK)]

    def url_autorizacao(self, state, nonce, verifier):
        if (not isinstance(state, str) or not _ALEATORIO.fullmatch(state)
                or not isinstance(nonce, str) or not _ALEATORIO.fullmatch(nonce)
                or not isinstance(verifier, str) or not _VERIFIER.fullmatch(verifier)):
            raise FalhaIdentidadeGoogle()
        desafio = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        return _AUTORIZACAO + "?" + urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid profile email",
            "state": state,
            "nonce": nonce,
            "code_challenge": desafio.decode("ascii").rstrip("="),
            "code_challenge_method": "S256",
            "prompt": "select_account",
        })


def carregar_config_google():
    client_id = os.environ.get("RHYTHMMIND_GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("RHYTHMMIND_GOOGLE_CLIENT_SECRET", "")
    if not client_id and not client_secret:
        return None
    producao = ambiente_producao()
    redirect_uri = (
        os.environ.get("RHYTHMMIND_GOOGLE_REDIRECT_URI", "")
        if producao
        else os.environ.get("RHYTHMMIND_GOOGLE_REDIRECT_URI", _REDIRECT_PADRAO)
    )
    config = GoogleConfig(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        permitir_host_externo=producao,
    )
    if producao:
        url = urlsplit(config.redirect_uri)
        if url.scheme != "https" or url.hostname in _HOSTS_LOCAIS:
            raise ConfiguracaoGoogleInvalida()
    return config


class _RequestComTimeout:
    """Limita tambem a consulta de certificados feita pelo google-auth."""

    def __init__(self, session):
        self.request = GoogleRequest(session=session)

    def __call__(self, url, method="GET", body=None, headers=None, **kwargs):
        return self.request(url=url, method=method, body=body, headers=headers, timeout=_TIMEOUT)


def _identidade(claims, config, nonce):
    if not isinstance(claims, dict):
        raise FalhaIdentidadeGoogle()
    issuer = claims.get("iss")
    subject = claims.get("sub")
    nonce_recebido = claims.get("nonce")
    if (issuer not in {_ISSUER, "accounts.google.com"}
            or claims.get("aud") != config.client_id
            or ("azp" in claims and claims["azp"] != config.client_id)
            or not _texto_seguro(subject, 255)
            or not isinstance(nonce_recebido, str) or not nonce_recebido.isascii()
            or not secrets.compare_digest(nonce_recebido, nonce)):
        raise FalhaIdentidadeGoogle()
    # verify_oauth2_token valida assinatura, emissor, audiencia, iat e exp.
    # Exigimos explicitamente a presenca e o tipo dos tempos, sem aceitar bool.
    for campo in ("exp", "iat"):
        valor = claims.get(campo)
        if type(valor) not in (int, float) or (type(valor) is float and not math.isfinite(valor)):
            raise FalhaIdentidadeGoogle()
    return {"iss": _ISSUER, "sub": subject}


def validar_codigo_google(config, code, nonce, verifier):
    if (not _texto_seguro(code, 4096)
            or not isinstance(nonce, str) or not _ALEATORIO.fullmatch(nonce)
            or not isinstance(verifier, str) or not _VERIFIER.fullmatch(verifier)):
        raise FalhaIdentidadeGoogle()
    try:
        with requests.Session() as session:
            resposta = session.post(
                _TOKEN,
                data={
                    "grant_type": "authorization_code", "code": code,
                    "client_id": config.client_id, "client_secret": config.client_secret,
                    "redirect_uri": config.redirect_uri, "code_verifier": verifier,
                },
                headers={"Accept": "application/json"},
                timeout=_TIMEOUT, allow_redirects=False,
            )
            if resposta.status_code >= 500 or resposta.status_code == 429:
                raise FalhaGoogleIndisponivel()
            if resposta.status_code != 200:
                raise FalhaIdentidadeGoogle()
            try:
                dados = resposta.json()
            except ValueError:
                raise FalhaIdentidadeGoogle() from None
            token = dados.get("id_token") if isinstance(dados, dict) else None
            if not _texto_seguro(token, 16384):
                raise FalhaIdentidadeGoogle()
            if google_jwt.decode_header(token).get("alg") != "RS256":
                raise FalhaIdentidadeGoogle()
            claims = id_token.verify_oauth2_token(
                token, _RequestComTimeout(session), audience=config.client_id,
            )
            return _identidade(claims, config, nonce)
    except (requests.RequestException, google_exceptions.TransportError, OSError):
        raise FalhaGoogleIndisponivel() from None
    except (ValueError, TypeError, KeyError, google_exceptions.GoogleAuthError):
        raise FalhaIdentidadeGoogle() from None
