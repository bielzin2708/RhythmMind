"""Preparacao explicita de fixtures ficticias com autenticacao HTTP real.

Nao substitui dependencias nem atribui arquivos legados na aplicacao.
Apenas os dados inventados do diretorio temporario de cada teste sao
copiados para a conta de teste, com titular conhecido na propria fixture.
"""

from contextlib import contextmanager
from contextvars import ContextVar

from fastapi.testclient import TestClient as ClienteHTTPReal

from api import desenvolvimento
from api.main import app
from core import storage
from core.contexto import contexto_usuario


_credencial = ContextVar("credencial_ficticia_de_teste", default=None)


class ClienteAutenticado(ClienteHTTPReal):
    """Usa o token real da fixture; sem fixture continua sem credencial."""

    def __init__(self, *args, **kwargs):
        headers = dict(kwargs.pop("headers", None) or {})
        token = _credencial.get()
        if token is not None:
            headers.setdefault("Authorization", "Bearer " + token)
        super().__init__(*args, headers=headers, **kwargs)


@contextmanager
def autenticacao_ficticia(raiz):
    # Atribuicao deliberada de fixtures inventadas; nao e migracao de dados reais.
    historico_ficticio = storage.carregar_json(storage.ARQ_HISTORICO, {})
    catalogo_ficticio = storage.carregar_json(storage.ARQ_MUSICAS, [])
    credenciais = {
        "nome_usuario": "fixture_ficticia",
        "senha": "senha-ficticia-fixture-123!",
    }
    with ClienteHTTPReal(app, base_url="http://127.0.0.1",
                        client=("127.0.0.1", 50000)) as cliente:
        registro = cliente.post("/api/auth/registrar", json=credenciais)
        if registro.status_code != 201:
            raise RuntimeError("Falha no cadastro da conta ficticia da fixture.")
        entrada = cliente.post("/api/auth/entrar", json=credenciais)
        if entrada.status_code != 200:
            raise RuntimeError("Falha na entrada real da conta ficticia da fixture.")
        usuario_id = registro.json()["usuario_id"]
        token_acesso = entrada.json()["token_acesso"]
    with contexto_usuario(usuario_id, raiz):
        storage.salvar_json(storage.ARQ_HISTORICO, historico_ficticio)
        storage.salvar_json(storage.ARQ_MUSICAS, catalogo_ficticio)
        marcador = _credencial.set(token_acesso)
        try:
            yield
        finally:
            _credencial.reset(marcador)


@contextmanager
def dados_autenticados():
    with desenvolvimento.dados_ficticios_temporarios() as raiz:
        with autenticacao_ficticia(raiz):
            yield raiz
