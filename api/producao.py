"""Inicializador de producao para container (Cloud Run) com armazenamento temporario.

Execute na raiz do repositorio:
    RHYTHMMIND_AMBIENTE=producao python -m api.producao
"""

from contextlib import contextmanager
import os
from pathlib import Path
import tempfile

import uvicorn

from api.google_auth import configurar_logs_acesso_google
from api.main import app
from core.google_oidc import ConfiguracaoGoogleInvalida, carregar_config_google


_AUSENTE = object()


def resolver_diretorio_dados(diretorio=None, environ=None):
    """Define e garante o diretorio gravavel separado dos arquivos estaticos."""
    env = os.environ if environ is None else environ
    if diretorio is not None:
        destino = Path(os.fspath(diretorio))
    else:
        configurado = env.get("RHYTHMMIND_DIRETORIO_DADOS", "").strip()
        destino = Path(configurado) if configurado else Path(tempfile.gettempdir()) / "rhythmmind-dados"
    destino.mkdir(parents=True, exist_ok=True)
    return destino.resolve()


def resolver_porta(environ=None):
    """Le e valida a porta HTTP informada pela plataforma ($PORT, padrao 8080)."""
    env = os.environ if environ is None else environ
    bruto = env.get("PORT", "8080").strip()
    try:
        porta = int(bruto)
    except ValueError as erro:
        raise ValueError("Variavel PORT invalida.") from erro
    if not 1 <= porta <= 65535:
        raise ValueError("Variavel PORT deve estar entre 1 e 65535.")
    return porta


def ativar_producao(diretorio_dados=None):
    """Inicializa o armazenamento temporario de uma instancia de producao."""
    raiz = resolver_diretorio_dados(diretorio_dados)
    os.environ["RHYTHMMIND_AMBIENTE"] = "producao"
    app.state.modo_producao = True
    app.state.diretorio_dados = str(raiz)
    app.state.armazenamento_persistente = False
    return raiz


@contextmanager
def ambiente_producao(diretorio_dados=None):
    """Ativa o modo de producao no app durante a execucao e restaura o estado ao sair."""
    ambiente_anterior = os.environ.get("RHYTHMMIND_AMBIENTE", _AUSENTE)
    modo_anterior = getattr(app.state, "modo_producao", _AUSENTE)
    dados_anterior = getattr(app.state, "diretorio_dados", _AUSENTE)
    persistente_anterior = getattr(app.state, "armazenamento_persistente", _AUSENTE)

    try:
        yield ativar_producao(diretorio_dados)
    finally:
        if ambiente_anterior is _AUSENTE:
            os.environ.pop("RHYTHMMIND_AMBIENTE", None)
        else:
            os.environ["RHYTHMMIND_AMBIENTE"] = ambiente_anterior

        for atributo, anterior in (
            ("modo_producao", modo_anterior),
            ("diretorio_dados", dados_anterior),
            ("armazenamento_persistente", persistente_anterior),
        ):
            if anterior is _AUSENTE:
                if hasattr(app.state, atributo):
                    delattr(app.state, atributo)
            else:
                setattr(app.state, atributo, anterior)


def preparar_producao():
    """Configura sanitizacao de logs OAuth e valida a configuracao Google sem expor segredos."""
    configurar_logs_acesso_google()
    try:
        config = carregar_config_google()
    except ConfiguracaoGoogleInvalida:
        return "invalido"
    return "habilitado" if config is not None else "desabilitado"


def main():
    porta = resolver_porta()
    with ambiente_producao() as raiz:
        estado_google = preparar_producao()
        print(
            "RhythmMind producao ativo.",
            f"Porta: {porta} | Dados: {raiz} (temporario)",
            f"Google OAuth: {estado_google}",
            sep="\n",
            flush=True,
        )
        if estado_google == "invalido":
            print(
                "Aviso: verifique RHYTHMMIND_GOOGLE_CLIENT_ID, RHYTHMMIND_GOOGLE_CLIENT_SECRET "
                "e RHYTHMMIND_GOOGLE_REDIRECT_URI (https://.../api/auth/google/callback).",
                flush=True,
            )
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=porta,
            proxy_headers=True,
            forwarded_allow_ips="*",
        )


if __name__ == "__main__":
    main()
