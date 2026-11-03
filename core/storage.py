import json
import os
import tempfile

# Definição das constantes
ARQ_MUSICAS = 'data/musicas_usuario.json'
ARQ_HISTORICO = 'data/historico.json'
ARQ_DICIONARIO = 'data/dicionario_emocional.json'  # <-- estava faltando (causa do seu erro original)

def carregar_json(caminho, default=None, *, estrito=False):
    """Lê um arquivo JSON e retorna seu conteúdo.
    'default' permite chamadas como carregar_json(ARQ_HISTORICO, {})."""
    if not os.path.exists(caminho):
        if default is not None:
            return default
        return [] if "musicas" in caminho else {}

    with open(caminho, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            if estrito:
                raise
            if default is not None:
                return default
            return [] if "musicas" in caminho else {}

def salvar_json(caminho, dados):
    """Conclui a escrita em temporário antes de substituir o arquivo anterior."""
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
    musicas = carregar_todas_musicas()
    musicas.append(nova_musica)
    salvar_json(ARQ_MUSICAS, musicas)
