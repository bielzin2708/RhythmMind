"""Prepara um piloto de anotações DEAM; não baixa áudio nem executa modelos."""

import argparse
import csv
from hashlib import sha256
import io
import json
from math import isfinite
from pathlib import Path
import zipfile

from core.caracterizacao import validar_musica


COLUNAS = ("song_id", "valence_mean", "valence_std", "arousal_mean", "arousal_std")
MEMBRO_CSV = (
    "annotations/annotations averaged per song/song_level/"
    "static_annotations_averaged_songs_1_2000.csv"
)
SHA256_ZIP = "8aef028d6b3d8592b755ae6aefc61c0f9962dce8af9c6bd231d4dc59d59670fd"
SHA256_CSV = "b07312724c1add58c09849eeee90c5b53cc54b5e4a97ff3e4f9505d5aa2a1b94"
SEMENTE = "rhythmmind-deam-piloto-v1"
URL_ESPELHO = "https://zenodo.org/records/11400122"
URL_ZIP = "https://zenodo.org/api/records/11400122/files/DEAM_Annotations.zip/content"
URL_ORIGINAL = "https://cvml.unige.ch/databases/DEAM/"
URL_MANUAL = URL_ORIGINAL + "manual.pdf"
DOI_ARTIGO = "https://doi.org/10.1371/journal.pone.0173392"


def _numero(texto, coluna, linha):
    try:
        numero = float(texto)
    except (ValueError, TypeError):
        raise ValueError(f"Linha {linha}: {coluna} exige número finito.") from None
    if not isfinite(numero):
        raise ValueError(f"Linha {linha}: {coluna} exige número finito.")
    if coluna.endswith("_mean") and not 1 <= numero <= 9:
        raise ValueError(f"Linha {linha}: {coluna} deve estar na escala 1 a 9.")
    if coluna.endswith("_std") and numero < 0:
        raise ValueError(f"Linha {linha}: {coluna} não pode ser negativo.")
    return numero


def ler_anotacoes(conteudo):
    """Lê as cinco colunas agregadas; os textos de origem ficam preservados."""
    if not isinstance(conteudo, bytes):
        raise ValueError("Forneça o conteúdo CSV como bytes UTF-8.")
    try:
        texto = conteudo.decode("utf-8-sig")
    except UnicodeDecodeError as erro:
        raise ValueError("O CSV deve estar em UTF-8.") from erro
    leitor = csv.reader(io.StringIO(texto, newline=""), strict=True)
    try:
        cabecalho = next(leitor, [])
        if tuple(campo.strip() for campo in cabecalho) != COLUNAS:
            raise ValueError("Cabeçalho DEAM agregado ausente, alterado ou ambíguo.")
        registros, identificadores = [], set()
        for campos in leitor:
            linha = leitor.line_num
            if not campos:
                continue
            if len(campos) != len(COLUNAS):
                raise ValueError(f"Linha {linha}: quantidade inesperada de colunas.")
            origem = dict(zip(COLUNAS, campos))
            identificador = origem["song_id"].strip()
            if not identificador.isascii() or not identificador.isdecimal() or int(identificador) <= 0:
                raise ValueError(f"Linha {linha}: song_id deve ser inteiro positivo.")
            identificador = int(identificador)
            if identificador in identificadores:
                raise ValueError(f"Linha {linha}: song_id repetido.")
            identificadores.add(identificador)
            numeros = {coluna: _numero(origem[coluna], coluna, linha) for coluna in COLUNAS[1:]}
            registros.append({"id_fonte": identificador, "colunas_originais": origem, **numeros})
    except csv.Error as erro:
        raise ValueError("CSV malformado.") from erro
    if not registros:
        raise ValueError("O CSV não contém anotações.")
    return registros


def selecionar_registros(registros, quantidade=24):
    """Seleciona por hash do ID, sem usar as notas ou o estado global do sorteio."""
    if type(quantidade) is not int or not 1 <= quantidade <= len(registros):
        raise ValueError("Quantidade deve ser inteiro positivo e caber no conjunto.")
    def chave(registro):
        identificador = registro["id_fonte"]
        return sha256(f"{SEMENTE}:{identificador}".encode("ascii")).hexdigest(), identificador
    selecionados = sorted(registros, key=chave)[:quantidade]
    return sorted(selecionados, key=lambda registro: registro["id_fonte"])


def construir_registro(registro, *, fonte, versao_fonte):
    """Adapta médias publicadas sem tratá-las como estimativas ou retorno pessoal."""
    observacoes = []
    for atributo, coluna in (("valencia", "valence_mean"), ("ativacao", "arousal_mean")):
        observacoes.append({
            "atributo": atributo,
            "valor": registro[coluna],
            "escala": {
                "minimo": 1, "maximo": 9,
                "descricao": "Média da anotação global DEAM em nove pontos, sem normalização.",
            },
            "fonte": fonte,
            "metodo": "media_estatica_publicada_de_anotacoes",
            "versao": versao_fonte,
        })
    resultado = {
        "id": f"deam:{registro['id_fonte']}",
        "id_fonte": registro["id_fonte"],
        "colunas_originais": dict(registro["colunas_originais"]),
        "dispersao_publicada": {
            "valencia_desvio_padrao": registro["valence_std"],
            "ativacao_desvio_padrao": registro["arousal_std"],
        },
        "caracterizacao": {
            "versao_estrutura": 1,
            "caracteristicas_acusticas": [],
            "anotacoes_emocionais": observacoes,
            "estimativas_sistema": [],
        },
    }
    validar_musica(resultado)
    return resultado


def preparar_piloto(caminho_zip, quantidade=24):
    """Aceita somente os bytes auditados do espelho; não presume equivalência ao original."""
    caminho_zip = Path(caminho_zip)
    if caminho_zip.stat().st_size > 8_000_000:
        raise ValueError("O arquivo excede o limite do arquivo DEAM auditado.")
    arquivo = caminho_zip.read_bytes()
    if sha256(arquivo).hexdigest() != SHA256_ZIP:
        raise ValueError("SHA-256 do ZIP difere da versão auditada; revise a fonte antes de usar.")
    with zipfile.ZipFile(io.BytesIO(arquivo)) as pacote:
        info = pacote.getinfo(MEMBRO_CSV)
        if info.file_size > 1_000_000:
            raise ValueError("CSV excede o limite esperado.")
        conteudo = pacote.read(info)
    if sha256(conteudo).hexdigest() != SHA256_CSV:
        raise ValueError("SHA-256 do CSV difere da versão auditada.")
    registros = ler_anotacoes(conteudo)
    if len(registros) != 1744:
        raise ValueError("Quantidade de registros difere do arquivo auditado.")
    selecionados = selecionar_registros(registros, quantidade)
    fonte = f"DEAM / {MEMBRO_CSV}"
    return {
        "versao_conjunto": 1,
        "finalidade": "piloto_de_ingestao_e_planejamento_de_avaliacao",
        "fonte": {
            "dataset": "DEAM",
            "pagina_original": URL_ORIGINAL,
            "manual_original": URL_MANUAL,
            "artigo": {
                "autores": ["Anna Aljanaki", "Yi-Hsuan Yang", "Mohammad Soleymani"],
                "titulo": "Developing a benchmark for emotional analysis of music",
                "ano": 2017, "doi": DOI_ARTIGO,
            },
            "espelho": URL_ESPELHO,
            "download": URL_ZIP,
            "bytes_zip": len(arquivo),
            "md5_publicado_espelho": "31731747c2a52a3332c17f9dc9a4b1e8",
            "sha256_zip": SHA256_ZIP,
            "membro_csv": MEMBRO_CSV,
            "sha256_csv": SHA256_CSV,
            "equivalencia_com_original_por_checksum": "nao_verificada_servidor_original_http_503",
            "licenca": {
                "declaracao_manual_original": "Creative Commons BY-NC",
                "versao_declarada_manual": None,
                "declaracao_api_espelho": "CC BY 4.0",
                "divergencia_documentada": True,
                "restricao_adotada_no_piloto": "pesquisa_nao_comercial_com_atribuicao",
                "acesso_manual": "secao_3_recuperada_em_indice_de_busca_download_http_503",
            },
        },
        "selecao": {
            "metodo": "menores_hashes_sha256_da_semente_e_song_id",
            "semente": SEMENTE,
            "elegiveis": len(registros), "selecionados": len(selecionados),
            "ordenacao_apresentacao": "song_id_crescente",
            "usa_notas_na_selecao": False,
            "normaliza_escalas": False,
        },
        "registros": [construir_registro(registro, fonte=fonte, versao_fonte=f"sha256:{SHA256_CSV}")
                      for registro in selecionados],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arquivo_zip", type=Path, help="ZIP DEAM já baixado da versão documentada")
    parser.add_argument("--saida", type=Path, required=True, help="Novo arquivo JSON do piloto")
    parser.add_argument("--quantidade", type=int, default=24)
    argumentos = parser.parse_args(argv)
    try:
        piloto = preparar_piloto(argumentos.arquivo_zip, argumentos.quantidade)
        argumentos.saida.parent.mkdir(parents=True, exist_ok=True)
        # 'x' impede sobrescrever catálogo, histórico ou outro arquivo existente.
        with argumentos.saida.open("x", encoding="utf-8", newline="\n") as arquivo:
            json.dump(piloto, arquivo, indent=2, ensure_ascii=False, allow_nan=False)
            arquivo.write("\n")
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as erro:
        parser.exit(2, f"Não foi possível preparar o piloto: {erro}\n")
    print(f"Piloto salvo: {argumentos.saida} ({len(piloto['registros'])} registros).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
