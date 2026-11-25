"""Persistência privada em Vercel Blob e tokens assinados para instâncias serverless."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import time
from uuid import UUID


_PREFIXO_TOKEN_ASSINADO = "rm1."
_PADRAO_TOKEN_ASSINADO = re.compile(r"rm1\.[a-zA-Z0-9_-]{20,512}\.[a-zA-Z0-9_-]{43}\Z")
_PADRAO_ARQUIVO_PESSOAL = frozenset({"historico.json", "musicas_usuario.json"})


def segredo_token_producao(environ=None) -> bytes | None:
    """Retorna o segredo HMAC configurado em produção, ou None fora desse modo."""
    env = os.environ if environ is None else environ
    if env.get("RHYTHMMIND_AMBIENTE", "").strip() != "producao":
        return None
    valor = env.get("RHYTHMMIND_TOKEN_SECRET", "").strip()
    if len(valor) < 32:
        return None
    return valor.encode("utf-8")


def blob_ativo(environ=None) -> bool:
    """Ativa o Vercel Blob privado apenas em produção quando credenciais existem."""
    env = os.environ if environ is None else environ
    if env.get("RHYTHMMIND_AMBIENTE", "").strip() != "producao":
        return False
    if env.get("BLOB_READ_WRITE_TOKEN", "").strip():
        return True
    return bool(
        env.get("VERCEL_OIDC_TOKEN", "").strip()
        and env.get("BLOB_STORE_ID", "").strip()
    )


def formato_token_assinado_valido(token: str) -> bool:
    return isinstance(token, str) and _PADRAO_TOKEN_ASSINADO.fullmatch(token) is not None


def emitir_token_assinado(
    *,
    usuario_id: str,
    nome_usuario: str,
    criado_em: str,
    emitido_em: float,
    expira_em: float,
    segredo: bytes,
) -> str:
    corpo = {
        "u": str(UUID(usuario_id)),
        "n": nome_usuario,
        "c": criado_em,
        "i": round(float(emitido_em), 3),
        "e": round(float(expira_em), 3),
        "j": secrets.token_urlsafe(12),
    }
    compacto = json.dumps(corpo, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    payload_b64 = base64.urlsafe_b64encode(compacto).rstrip(b"=").decode("ascii")
    assinatura = hmac.new(segredo, payload_b64.encode("ascii"), hashlib.sha256).digest()
    assinatura_b64 = base64.urlsafe_b64encode(assinatura).rstrip(b"=").decode("ascii")
    return f"{_PREFIXO_TOKEN_ASSINADO}{payload_b64}.{assinatura_b64}"


def verificar_token_assinado(token: str, *, segredo: bytes, instante_atual: float) -> dict | None:
    if not formato_token_assinado_valido(token):
        return None
    sem_prefixo = token[len(_PREFIXO_TOKEN_ASSINADO):]
    payload_b64, assinatura_recebida = sem_prefixo.split(".", 1)
    assinatura_esperada = base64.urlsafe_b64encode(
        hmac.new(segredo, payload_b64.encode("ascii"), hashlib.sha256).digest()
    ).rstrip(b"=").decode("ascii")
    if not hmac.compare_digest(assinatura_recebida, assinatura_esperada):
        return None
    try:
        padding = "=" * (-len(payload_b64) % 4)
        dados = json.loads(base64.urlsafe_b64decode(payload_b64 + padding).decode("utf-8"))
        usuario_id = str(UUID(dados["u"]))
        if dados["u"] != usuario_id:
            return None
        nome_usuario = dados["n"]
        criado_em = dados["c"]
        emitido_em = float(dados["i"])
        expira_em = float(dados["e"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(nome_usuario, str) or not nome_usuario or not isinstance(criado_em, str) or not criado_em:
        return None
    if expira_em <= float(instante_atual):
        return None
    return {
        "usuario_id": usuario_id,
        "nome_usuario": nome_usuario,
        "criado_em": criado_em,
        "criado_em_ts": emitido_em,
        "expira_em": expira_em,
    }


def _cliente_blob():
    from vercel.blob import sync as blob
    return blob


def _ler_ultimo_json_prefixo(prefixo: str, default=None):
    """Busca a versão imutável mais recente sob `prefixo/v-` sem depender de cache CDN."""
    blob = _cliente_blob()
    try:
        itens = list(blob.query_blobs(prefix=f"{prefixo}/v-"))
        if not itens:
            return default
        mais_recente = max(itens, key=lambda item: item.pathname)
        resposta = blob.get_blob(mais_recente.url, access="private")
        return json.loads(resposta.body.decode("utf-8"))
    except FileNotFoundError:
        return default
    except Exception as erro:
        raise OSError("Falha ao consultar armazenamento em nuvem.") from erro


def _gravar_versao_json_prefixo(prefixo: str, dados) -> None:
    """Grava uma nova versão imutável em Blob privado e remove versões anteriores."""
    blob = _cliente_blob()
    try:
        anteriores = [item.url for item in blob.query_blobs(prefix=f"{prefixo}/v-")]
        versao = f"{prefixo}/v-{time.time_ns():020d}-{secrets.token_hex(6)}.json"
        corpo = json.dumps(dados, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        blob.put_blob(
            versao,
            corpo,
            access="private",
            content_type="application/json",
            add_random_suffix=False,
            allow_overwrite=False,
        )
        if anteriores:
            try:
                blob.delete_blob(anteriores[:900])
            except Exception:
                pass
    except Exception as erro:
        raise OSError("Falha ao persistir dados no armazenamento em nuvem.") from erro


def _prefixo_conta(nome_normalizado: str) -> str:
    resumo = hashlib.sha256(nome_normalizado.encode("utf-8")).hexdigest()
    return f"rhythmmind/v1/contas/{resumo}"


def ler_conta_blob(nome_normalizado: str) -> dict | None:
    dados = _ler_ultimo_json_prefixo(_prefixo_conta(nome_normalizado), default=None)
    return dados if isinstance(dados, dict) else None


def salvar_conta_blob(nome_normalizado: str, registro: dict) -> None:
    _gravar_versao_json_prefixo(_prefixo_conta(nome_normalizado), {
        "usuario_id": registro["usuario_id"],
        "nome_usuario": registro["nome_usuario"],
        "senha_hash": registro.get("senha_hash"),
        "criado_em": registro["criado_em"],
    })


def registrar_revogacao_blob(token_hash: str, revogado_em: float, expira_em: float) -> None:
    _gravar_versao_json_prefixo(f"rhythmmind/v1/revogacoes/{token_hash}", {
        "revogado_em": float(revogado_em),
        "expira_em": float(expira_em),
    })


def token_revogado_blob(token_hash: str) -> bool:
    dados = _ler_ultimo_json_prefixo(f"rhythmmind/v1/revogacoes/{token_hash}", default=None)
    return isinstance(dados, dict) and dados.get("revogado_em") is not None


def _prefixo_arquivo_usuario(usuario_id: str, nome_arquivo: str) -> str:
    canonico = str(UUID(usuario_id))
    limpo = Path(nome_arquivo).name.casefold()
    if limpo not in _PADRAO_ARQUIVO_PESSOAL:
        raise ValueError("Arquivo pessoal inválido para persistência em nuvem.")
    return f"rhythmmind/v1/usuarios/{canonico}/{limpo}"


def ler_arquivo_pessoal_blob(usuario_id: str, nome_arquivo: str, default=None):
    return _ler_ultimo_json_prefixo(_prefixo_arquivo_usuario(usuario_id, nome_arquivo), default=default)


def salvar_arquivo_pessoal_blob(usuario_id: str, nome_arquivo: str, dados) -> None:
    _gravar_versao_json_prefixo(_prefixo_arquivo_usuario(usuario_id, nome_arquivo), dados)
