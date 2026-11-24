"""API exclusivamente local; dados temporários por padrão.

Execute da raiz do RhythmMind: python -m api.desenvolvimento
Use --persistente para manter as contas e registros em .rhythmmind-local/.
Não habilitar reload/workers: o diretório de trabalho pertence ao processo.
"""

import argparse
import json
import os
import re
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

from api.main import app
from core.storage import ARQ_DICIONARIO, ARQ_HISTORICO, ARQ_MUSICAS, salvar_json


_RAIZ_PROJETO = Path(__file__).resolve().parents[1]
_DICIONARIO_REFERENCIA = _RAIZ_PROJETO / "data" / "dicionario_emocional.json"
_DIRETORIO_PERSISTENTE = _RAIZ_PROJETO / ".rhythmmind-local"
_ENV_LOCAL = _RAIZ_PROJETO / ".env.local"
_CHAVE_ENV = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_AUSENTE = object()


def _sementes_ficticias():
    return {
        ARQ_HISTORICO: {},
        ARQ_DICIONARIO: json.loads(_DICIONARIO_REFERENCIA.read_text(encoding="utf-8")),
        ARQ_MUSICAS: [{
            "id": "faixa_ficticia_a",
            "nome": "Faixa Inventada A",
            "artista": "Artista Fictício",
            "duracao": "3:00",
            "sentimentos_associados": ["calmo", "cansado"],
            "estrategias": ["descompressao", "espelhamento"],
        }, {
            "id": "faixa_ficticia_b",
            "nome": "Faixa Inventada B",
            "artista": "Artista Fictício",
            "duracao": "2:30",
            "sentimentos_associados": ["animado"],
            "estrategias": ["ativacao"],
        }],
    }


@contextmanager
def dados_ficticios_temporarios():
    """Isola os caminhos relativos existentes sem migrar o armazenamento."""
    anterior = Path.cwd()
    autorizado_anterior = getattr(app.state, "diretorio_desenvolvimento", None)
    persistente_anterior = getattr(app.state, "armazenamento_persistente", False)
    with TemporaryDirectory(prefix="rhythmmind-dev-") as temporario:
        try:
            os.chdir(temporario)
            for arquivo, dados in _sementes_ficticias().items():
                salvar_json(arquivo, dados)
            app.state.diretorio_desenvolvimento = str(Path.cwd().resolve())
            app.state.armazenamento_persistente = False
            yield Path(temporario)
        finally:
            app.state.diretorio_desenvolvimento = autorizado_anterior
            app.state.armazenamento_persistente = persistente_anterior
            os.chdir(anterior)


@contextmanager
def dados_locais_persistentes(caminho=None):
    """Mantém dados locais entre execuções, sem sobrescrever arquivos existentes.

    O parâmetro de caminho destina-se aos testes; a CLI usa somente a pasta
    dedicada do projeto, sem aceitar caminhos enviados pelo navegador.
    """
    raiz = Path(caminho if caminho is not None else _DIRETORIO_PERSISTENTE).resolve()
    if raiz == Path.home().resolve() or raiz == _RAIZ_PROJETO or raiz in _RAIZ_PROJETO.parents:
        raise ValueError("Use uma pasta dedicada para os dados locais persistentes.")
    anterior = Path.cwd()
    autorizado_anterior = getattr(app.state, "diretorio_desenvolvimento", None)
    persistente_anterior = getattr(app.state, "armazenamento_persistente", False)
    raiz.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        # Escrita exclusiva: outro processo ou uma inicialização anterior nunca
        # tem seus arquivos substituídos pelas sementes da demonstração.
        for arquivo, dados in _sementes_ficticias().items():
            destino = raiz / arquivo
            destino.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                with destino.open("x", encoding="utf-8") as saida:
                    json.dump(dados, saida, ensure_ascii=False, indent=4)
            except FileExistsError:
                pass
        os.chdir(raiz)
        app.state.diretorio_desenvolvimento = str(raiz)
        app.state.armazenamento_persistente = True
        yield raiz
    finally:
        app.state.diretorio_desenvolvimento = autorizado_anterior
        app.state.armazenamento_persistente = persistente_anterior
        os.chdir(anterior)


def _ler_env_local(caminho):
    """Lê pares CHAVE=VALOR de um arquivo local ignorado pelo Git."""
    pares = {}
    for bruta in Path(caminho).read_text(encoding="utf-8-sig").splitlines():
        linha = bruta.strip()
        if not linha or linha.startswith("#"):
            continue
        if linha.startswith("export "):
            linha = linha[7:].lstrip()
        if "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        chave = chave.strip()
        valor = valor.strip()
        if not _CHAVE_ENV.fullmatch(chave):
            continue
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in {"'", '"'}:
            valor = valor[1:-1]
        pares[chave] = valor
    return pares


@contextmanager
def carregar_env_local(caminho=None):
    """Aplica variáveis ausentes de .env.local apenas durante a execução local."""
    alvo = Path(caminho if caminho is not None else _ENV_LOCAL)
    if not alvo.is_file():
        yield False
        return
    anteriores = {}
    try:
        for chave, valor in _ler_env_local(alvo).items():
            atual = os.environ.get(chave, _AUSENTE)
            if atual is _AUSENTE or atual == "":
                anteriores[chave] = atual
                os.environ[chave] = valor
        yield bool(anteriores)
    finally:
        for chave, anterior in anteriores.items():
            if anterior is _AUSENTE:
                os.environ.pop(chave, None)
            else:
                os.environ[chave] = anterior


def main(argv=()):
    from api.google_auth import configurar_logs_acesso_google

    argumentos = argparse.ArgumentParser(description="RhythmMind em desenvolvimento local.")
    argumentos.add_argument(
        "--persistente", action="store_true",
        help="Mantém contas e registros na pasta local .rhythmmind-local/.",
    )
    # Os argumentos do processo são encaminhados apenas no ponto de entrada;
    # importar/chamar main em testes não consome argumentos do unittest.
    opcoes = argumentos.parse_args(argv)
    ambiente = dados_locais_persistentes if opcoes.persistente else dados_ficticios_temporarios
    with carregar_env_local() as env_carregado, ambiente():
        if opcoes.persistente:
            print("Desenvolvimento local: use somente dados fictícios. Dados persistentes nesta máquina.")
        else:
            print("Desenvolvimento local: use somente dados fictícios. Dados temporários.")
        if env_carregado and os.environ.get("RHYTHMMIND_GOOGLE_CLIENT_ID"):
            print("Variáveis locais carregadas de .env.local.")
        configurar_logs_acesso_google()
        uvicorn.run(app, host="127.0.0.1", port=8000, proxy_headers=False)


if __name__ == "__main__":
    main(sys.argv[1:])
