import json
import os
from pathlib import Path
import tempfile
from threading import RLock

from core.armazenamento_nuvem import (
    blob_ativo,
    ler_arquivo_pessoal_blob,
    salvar_arquivo_pessoal_blob,
)
from core.caracterizacao import preparar_musica
from core.contexto import resolver_caminho, usuario_atual

LOCK_MUSICAS = RLock()
_RAIZ_PROJETO = Path(__file__).resolve().parents[1]
_NOMES_PESSOAIS = frozenset({"historico.json", "musicas_usuario.json"})

# Definição das constantes
ARQ_MUSICAS = 'data/musicas_usuario.json'
ARQ_HISTORICO = 'data/historico.json'
ARQ_DICIONARIO = 'data/dicionario_emocional.json'  # <-- estava faltando (causa do seu erro original)
LOCK_MUSICAS = RLock()


def _padrao_json(caminho, default):
    if default is not None:
        return default
    return [] if "musicas" in str(caminho) else {}


def _resolver_leitura_estatica(caminho: str) -> str:
    if os.path.exists(caminho) or os.path.isabs(caminho):
        return caminho
    candidato = _RAIZ_PROJETO / caminho
    return str(candidato) if candidato.exists() else caminho


def carregar_json(caminho, default=None, *, estrito=False):
    """Lê um arquivo JSON e retorna seu conteúdo.
    'default' permite chamadas como carregar_json(ARQ_HISTORICO, {})."""
    original = os.fspath(caminho)
    nome = Path(original).name.casefold()
    uid = usuario_atual()
    caminho_resolvido = resolver_caminho(original)

    if uid is not None and nome in _NOMES_PESSOAIS and blob_ativo():
        remoto = ler_arquivo_pessoal_blob(uid, nome, default=None)
        if remoto is not None:
            return remoto
        return _padrao_json(caminho_resolvido, default)

    if uid is None:
        caminho_resolvido = _resolver_leitura_estatica(caminho_resolvido)
    elif nome not in _NOMES_PESSOAIS:
        caminho_resolvido = _resolver_leitura_estatica(caminho_resolvido)

    if not os.path.exists(caminho_resolvido):
        return _padrao_json(caminho_resolvido, default)

    with open(caminho_resolvido, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            if estrito:
                raise
            return _padrao_json(caminho_resolvido, default)


def salvar_json(caminho, dados):
    """Conclui a escrita em temporário antes de substituir o arquivo anterior."""
    original = os.fspath(caminho)
    nome = Path(original).name.casefold()
    uid = usuario_atual()
    caminho = resolver_caminho(original)
    pasta = os.path.dirname(os.path.abspath(caminho))
    os.makedirs(pasta, exist_ok=True)
    temporario = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=pasta,
            prefix=".rhythmmind-", suffix=".tmp", delete=False,
        ) as arquivo:
            temporario = arquivo.name
            json.dump(dados, arquivo, indent=4, ensure_ascii=False)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.replace(temporario, caminho)
    finally:
        if temporario is not None and os.path.exists(temporario):
            os.unlink(temporario)
    if uid is not None and nome in _NOMES_PESSOAIS and blob_ativo():
        salvar_arquivo_pessoal_blob(uid, nome, dados)

def carregar_todas_musicas():
    """Carrega a lista de músicas do usuário."""
    dados = carregar_json(ARQ_MUSICAS)
    if not isinstance(dados, list):
        return []
    return dados

def carregar_musicas_usuario():
    """Alias usado por core/recomendador.py."""
    return carregar_todas_musicas()

def salvar_musica_usuario(nova_musica):
    """Adiciona uma nova música à lista e salva no arquivo."""
    preparada = preparar_musica(nova_musica)
    with LOCK_MUSICAS:
        musicas = carregar_todas_musicas()
        musicas.append(preparada)
        salvar_json(ARQ_MUSICAS, musicas)
    return preparada
