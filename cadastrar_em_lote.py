"""
cadastrar_em_lote.py
---------------------
Cadastra músicas em massa a partir de um CSV (ex: extraído de playlists do Spotify),
reaproveitando 100% da lógica de inferência e validação já existente no main.py
(BLOCO A e B) e em core/storage.py — sem duplicar regras de negócio.

Uso:
    python cadastrar_em_lote.py data/cadastro_em_lote.csv

Formato esperado do CSV (cabeçalho exato):
    nome,artista,duracao,bpm,sentimentos_texto,tags

- nome, artista, duracao: obrigatórios (duracao no formato m:ss ou mm:ss)
- bpm: opcional, vazio = sem BPM
- sentimentos_texto: texto livre (ex: "calmo reflexivo") — processado pelo
  mesmo analisador_texto.detectar_emocoes_no_texto usado no cadastro manual.
  Linhas SEM sentimento reconhecido são puladas e reportadas no final,
  porque sentimentos_associados é campo obrigatório no modelo de dados.
- tags: opcional, separadas por espaço ou vírgula
"""
import csv
import re
import sys

from core.analisador_texto import detectar_emocoes_no_texto
from core.caracterizacao import preparar_musica
from core.storage import salvar_musica_usuario, carregar_todas_musicas
from main import (
    validar_duracao,
    validar_bpm,
    inferir_contextos_para_musica,
    inferir_estrategias_para_musica,
    inferir_energia_para_musica,
    inferir_valencia_para_musica,
    inferir_intensidade_para_musica,
)


def processar_linha(linha):
    nome = linha["nome"].strip()
    artista = linha["artista"].strip()
    duracao = linha["duracao"].strip()
    bpm_texto = (linha.get("bpm") or "").strip()
    sentimentos_texto = (linha.get("sentimentos_texto") or "").strip()
    tags_texto = (linha.get("tags") or "").strip()

    if not nome or not artista:
        return None, f"⚠️  Linha ignorada: nome ou artista vazio ({linha})"

    if not validar_duracao(duracao):
        return None, f"⚠️  '{nome}' ignorada: duração inválida ('{duracao}'). Use m:ss ou mm:ss."

    bpm = validar_bpm(bpm_texto)
    if bpm == -1:
        return None, f"⚠️  '{nome}' ignorada: BPM inválido ('{bpm_texto}')."

    if not sentimentos_texto:
        return None, f"⚠️  '{nome}' ignorada: sem sentimentos preenchidos no CSV."

    sentimentos = detectar_emocoes_no_texto(sentimentos_texto)
    if not sentimentos:
        return None, (f"⚠️  '{nome}' ignorada: '{sentimentos_texto}' não bateu com nenhum "
                       f"termo do dicionário emocional (data/dicionario_emocional.json).")

    tags = [t.strip().lower() for t in re.split(r"[,\s]+", tags_texto) if t.strip()]

    id_musica = f"{re.sub(r'[^a-z0-9]', '', nome.lower())}_{re.sub(r'[^a-z0-9]', '', artista.lower())}"

    contextos = inferir_contextos_para_musica(sentimentos, tags)
    estrategias = inferir_estrategias_para_musica(sentimentos, tags, bpm)
    energia = inferir_energia_para_musica(sentimentos, tags, bpm)
    valencia = inferir_valencia_para_musica(sentimentos, tags)
    intensidade = inferir_intensidade_para_musica(sentimentos, tags, bpm)

    musica = {
        "id": id_musica,
        "nome": nome,
        "artista": artista,
        "bpm": bpm,
        "duracao": duracao,
        "energia": energia,
        "valencia": valencia,
        "intensidade": intensidade,
        "sentimentos_associados": sentimentos,
        "contextos": contextos,
        "estrategias": estrategias,
        "tags": tags,
    }
    return preparar_musica(musica), None


def main(caminho_csv):
    existentes = {m["id"] for m in carregar_todas_musicas()}
    importadas, avisos, duplicadas = 0, [], 0

    with open(caminho_csv, "r", encoding="utf-8") as f:
        leitor = csv.DictReader(f)
        for linha in leitor:
            musica, aviso = processar_linha(linha)
            if aviso:
                avisos.append(aviso)
                continue
            if musica["id"] in existentes:
                duplicadas += 1
                continue
            salvar_musica_usuario(musica)
            existentes.add(musica["id"])
            importadas += 1
            print(f"✅ {musica['nome']} - {musica['artista']}  "
                  f"[{musica['sentimentos_associados']}] -> {musica['estrategias']}")

    print(f"\nResumo: {importadas} importadas, {duplicadas} já existiam, {len(avisos)} ignoradas.")
    if avisos:
        print("\n--- Avisos (revise e preencha sentimentos_texto no CSV) ---")
        for a in avisos:
            print(a)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python cadastrar_em_lote.py caminho/para/arquivo.csv")
        sys.exit(1)
    main(sys.argv[1])
