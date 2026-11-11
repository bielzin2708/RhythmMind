"""Referência pública e importação explícita, sem análise de áudio ou inferências."""

from datetime import date
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlsplit

from core import storage
from core.caracterizacao import preparar_musica, validar_caracterizacao
from core.contexto import usuario_atual
from core.interpretacao.base import ESTRATEGIAS
from core.interpretacao.contratos import CATEGORIAS


ARQ_CATALOGO_REFERENCIA = Path(__file__).resolve().parents[1] / "data/catalogo_referencia.json"
_HOSTS_FONTES = {"music.apple.com", "itunes.apple.com", "open.spotify.com"}


class CatalogoIndisponivel(RuntimeError):
    """O artefato público não pôde ser lido e validado integralmente."""


def _exigir(condicao, mensagem):
    if not condicao:
        raise ValueError(mensagem)


def _texto(valor):
    return isinstance(valor, str) and bool(valor.strip())


def _lista_textos(valor, permitidos=None):
    return (isinstance(valor, list) and all(_texto(item) for item in valor)
            and len(set(valor)) == len(valor)
            and (permitidos is None or set(valor).issubset(permitidos)))


def _url_publica(valor):
    if not _texto(valor):
        return False
    try:
        url = urlsplit(valor)
        return (url.scheme == "https" and url.hostname in _HOSTS_FONTES
                and url.username is None and url.password is None
                and url.port in {None, 443} and bool(url.path))
    except ValueError:
        return False


def _chave_musica(musica):
    def normalizar(valor):
        return " ".join("".join(
            letra for letra in unicodedata.normalize("NFKD", valor.casefold())
            if not unicodedata.combining(letra)
        ).split())
    nome, artista = musica.get("nome"), musica.get("artista")
    if not _texto(nome) or not _texto(artista):
        return None
    return normalizar(nome), normalizar(artista)


def validar_catalogo(catalogo):
    """Valida todo o lote antes de permitir qualquer gravação pessoal."""
    _exigir(isinstance(catalogo, dict), "Catálogo deve ser um objeto.")
    _exigir(_texto(catalogo.get("versao")), "Versão do catálogo ausente.")
    _exigir(_texto(catalogo.get("descricao")), "Descrição do catálogo ausente.")
    musicas = catalogo.get("musicas")
    _exigir(isinstance(musicas, list) and len(musicas) <= 300,
            "Catálogo deve conter uma lista de até 300 faixas.")
    ids, chaves = set(), set()
    for musica in musicas:
        _exigir(isinstance(musica, dict), "Faixa deve ser um objeto.")
        for campo in ("id", "nome", "artista", "duracao"):
            _exigir(_texto(musica.get(campo)), f"Campo obrigatório inválido: {campo}.")
        _exigir(len(musica["id"]) <= 200, "Identificador de faixa muito longo.")
        _exigir(re.fullmatch(r"\d{1,2}:[0-5]\d", musica["duracao"]) is not None,
                "Duração inválida na referência.")
        _exigir(musica.get("bpm") is None, "Referência sem análise de áudio deve manter BPM desconhecido.")
        _exigir(all(musica.get(campo) is None for campo in ("energia", "valencia", "intensidade")),
                "Curadoria editorial não comprova energia, valência ou intensidade.")
        _exigir(_lista_textos(musica.get("sentimentos_associados"), CATEGORIAS),
                "Categorias editoriais inválidas.")
        _exigir(_lista_textos(musica.get("estrategias"), ESTRATEGIAS), "Estratégias editoriais inválidas.")
        for campo in ("contextos", "tags"):
            _exigir(_lista_textos(musica.get(campo, [])), f"Lista inválida: {campo}.")
        chave = _chave_musica(musica)
        _exigir(musica["id"] not in ids and chave not in chaves, "Faixa duplicada na referência.")
        ids.add(musica["id"])
        chaves.add(chave)

        fonte = musica.get("proveniencia")
        _exigir(isinstance(fonte, dict), "Proveniência ausente.")
        _exigir(_texto(fonte.get("fonte")) and _url_publica(fonte.get("url")), "Fonte pública inválida.")
        _exigir(_texto(fonte.get("id_fonte")) or type(fonte.get("id_fonte")) is int,
                "Identificador da fonte ausente.")
        _exigir(_texto(fonte.get("album")), "Álbum da gravação ausente.")
        consultado = fonte.get("consultado_em")
        _exigir(_texto(consultado), "Data de consulta ausente.")
        date.fromisoformat(consultado)
        duracao_ms = fonte.get("duracao_ms")
        _exigir(type(duracao_ms) is int and duracao_ms > 0, "Duração da fonte inválida.")
        minutos, segundos = map(int, musica["duracao"].split(":"))
        _exigir(abs((minutos * 60 + segundos) * 1000 - duracao_ms) <= 1000,
                "Duração diverge da gravação identificada pela fonte.")

        curadoria = musica.get("curadoria")
        _exigir(isinstance(curadoria, dict), "Curadoria editorial ausente.")
        _exigir(curadoria.get("status") == "provisoria"
                and curadoria.get("metodo") == "associacao_editorial_sem_analise_de_audio"
                and _texto(curadoria.get("versao")) and _texto(curadoria.get("justificativa")),
                "Método editorial precisa ser explícito e provisório.")
        bloco = musica.get("caracterizacao")
        _exigir(isinstance(bloco, dict), "Caracterização da referência ausente.")
        validar_caracterizacao(bloco)
        _exigir(not bloco.get("anotacoes_emocionais") and not bloco.get("estimativas_sistema"),
                "Indicação editorial não é anotação emocional nem estimativa de áudio.")
        for observacao in bloco.get("caracteristicas_acusticas", []):
            _exigir(observacao["atributo"] == "duracao"
                    and observacao.get("valor") is not None
                    and abs(observacao["valor"] * 1000 - duracao_ms) <= 1000
                    and all(_texto(observacao.get(campo)) for campo in ("fonte", "metodo", "versao")),
                    "Somente duração documentada pela fonte é admitida nesta referência.")
    return catalogo


def carregar_catalogo_referencia():
    """Lê sempre o recurso distribuído com o código, independente do cwd pessoal."""
    try:
        with ARQ_CATALOGO_REFERENCIA.open(encoding="utf-8") as arquivo:
            catalogo = json.load(arquivo)
        return validar_catalogo(catalogo)
    except (OSError, ValueError, TypeError, KeyError) as erro:
        raise CatalogoIndisponivel("Catálogo de referência indisponível ou inválido.") from erro


def importar_catalogo_referencia(ids=None):
    """Acrescenta uma cópia à conta atual, preservando todos os registros anteriores."""
    if usuario_atual() is None:
        raise PermissionError("Importação exige um contexto de conta autenticada.")
    catalogo = carregar_catalogo_referencia()
    disponiveis = {musica["id"] for musica in catalogo["musicas"]}
    if ids is not None:
        if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
            raise ValueError("Informe uma lista de identificadores de faixas.")
        if len(ids) > 300 or set(ids) - disponiveis:
            raise ValueError("A seleção contém identificador desconhecido ou excede 300 faixas.")
    selecionados = disponiveis if ids is None else set(ids)
    preparadas = [preparar_musica(musica) for musica in catalogo["musicas"]
                  if musica["id"] in selecionados]
    with storage.LOCK_MUSICAS:
        existentes = storage.carregar_json(storage.ARQ_MUSICAS, [], estrito=True)
        if not isinstance(existentes, list) or not all(isinstance(musica, dict) for musica in existentes):
            raise ValueError("Catálogo pessoal inválido; importação não realizada.")
        ids_existentes = {musica["id"] for musica in existentes if isinstance(musica.get("id"), str)}
        chaves_existentes = {_chave_musica(musica) for musica in existentes}
        novas = []
        for musica in preparadas:
            chave = _chave_musica(musica)
            if musica["id"] in ids_existentes or chave in chaves_existentes:
                continue
            novas.append(musica)
            ids_existentes.add(musica["id"])
            chaves_existentes.add(chave)
        if novas:
            storage.salvar_json(storage.ARQ_MUSICAS, existentes + novas)
        return {"versao": catalogo["versao"], "importadas": len(novas),
                "ja_existentes": len(preparadas) - len(novas), "total": len(existentes) + len(novas)}
