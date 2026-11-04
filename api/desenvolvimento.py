"""API exclusivamente local, com dados fictícios descartados ao encerrar.

Execute da raiz do RhythmMind: python -m api.desenvolvimento
Não habilitar reload/workers: o diretório de trabalho é temporário e do processo.
"""

import json
import os
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

from api.main import app
from core.storage import ARQ_DICIONARIO, ARQ_HISTORICO, ARQ_MUSICAS, salvar_json


_DICIONARIO_REFERENCIA = Path(__file__).resolve().parents[1] / "data" / "dicionario_emocional.json"


@contextmanager
def dados_ficticios_temporarios():
    """Isola os caminhos relativos existentes sem migrar o armazenamento."""
    dicionario = json.loads(_DICIONARIO_REFERENCIA.read_text(encoding="utf-8"))
    anterior = Path.cwd()
    autorizado_anterior = getattr(app.state, "diretorio_desenvolvimento", None)
    with TemporaryDirectory(prefix="rhythmmind-dev-") as temporario:
        try:
            os.chdir(temporario)
            salvar_json(ARQ_HISTORICO, {})
            salvar_json(ARQ_DICIONARIO, dicionario)
            salvar_json(ARQ_MUSICAS, [{
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
            }])
            app.state.diretorio_desenvolvimento = str(Path.cwd().resolve())
            yield Path(temporario)
        finally:
            app.state.diretorio_desenvolvimento = autorizado_anterior
            os.chdir(anterior)


def main():
    with dados_ficticios_temporarios():
        print("Desenvolvimento local: use somente dados fictícios. Dados temporários.")
        uvicorn.run(app, host="127.0.0.1", port=8000, proxy_headers=False)


if __name__ == "__main__":
    main()
