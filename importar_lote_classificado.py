"""
importar_lote_classificado.py
-------------------------------
Importa o lote de músicas que vieram com classificação manual já pronta
(BPM, energia, valência, etc). Diferente de cadastrar_em_lote.py, aqui
os campos não são recalculados do zero - apenas validados, e completados
SE estiverem ausentes/inconsistentes, usando as mesmas funções de
inferência do main.py para manter a fórmula de cálculo unificada em
todo o catálogo.
"""
import json

from core.storage import carregar_todas_musicas, salvar_json, ARQ_MUSICAS, ARQ_DICIONARIO, carregar_json
from main import (
    inferir_contextos_para_musica,
    inferir_estrategias_para_musica,
    inferir_energia_para_musica,
    inferir_valencia_para_musica,
    inferir_intensidade_para_musica,
    validar_duracao,
    validar_bpm,
)

CHAVES_VALIDAS = set(carregar_json(ARQ_DICIONARIO).keys())


def validar_e_completar(musica):
    avisos = []

    if not validar_duracao(musica["duracao"]):
        avisos.append(f"duração inválida: {musica['duracao']}")

    bpm = musica.get("bpm")
    if bpm is not None and validar_bpm(str(bpm)) == -1:
        avisos.append(f"BPM fora do intervalo 40-220: {bpm}")

    sentimentos = musica.get("sentimentos_associados", [])
    invalidos = [s for s in sentimentos if s not in CHAVES_VALIDAS]
    if invalidos:
        avisos.append(f"sentimentos fora do dicionário (ignorados): {invalidos}")
        sentimentos = [s for s in sentimentos if s in CHAVES_VALIDAS]
        musica["sentimentos_associados"] = sentimentos

    tags = musica.get("tags", [])

    # Se contextos/estratégias vierem vazios, ou os campos calculados não
    # baterem com a fórmula padrão do projeto, recalcula para manter
    # consistência com o resto do catálogo.
    contextos_calc = inferir_contextos_para_musica(sentimentos, tags)
    estrategias_calc = inferir_estrategias_para_musica(sentimentos, tags, bpm)
    energia_calc = inferir_energia_para_musica(sentimentos, tags, bpm)
    valencia_calc = inferir_valencia_para_musica(sentimentos, tags)
    intensidade_calc = inferir_intensidade_para_musica(sentimentos, tags, bpm)

    if not musica.get("contextos"):
        musica["contextos"] = contextos_calc
        avisos.append("contextos estavam vazios -> recalculados")
    if not musica.get("estrategias"):
        musica["estrategias"] = estrategias_calc
        avisos.append("estratégias estavam vazias -> recalculadas")

    # NÃO sobrescreve energia/valencia/intensidade fornecidas manualmente:
    # a fórmula simples (inferir_*_para_musica) é só keyword-matching e tem
    # limitações conhecidas (ex: trata 'explosivo' sempre como valência baixa,
    # ignorando catarse positiva quando combinado com 'animado'). A classificação
    # manual/curada é tratada como mais confiável. Divergências são só reportadas
    # para você decidir se quer revisar a fórmula no TCC.
    if musica.get("energia") and musica["energia"] != energia_calc:
        avisos.append(f"[divergência, NÃO alterado] energia manual='{musica.get('energia')}' vs fórmula='{energia_calc}'")
    if musica.get("valencia") and musica["valencia"] != valencia_calc:
        avisos.append(f"[divergência, NÃO alterado] valencia manual='{musica.get('valencia')}' vs fórmula='{valencia_calc}'")
    if musica.get("intensidade") and musica["intensidade"] != intensidade_calc:
        avisos.append(f"[divergência, NÃO alterado] intensidade manual='{musica.get('intensidade')}' vs fórmula='{intensidade_calc}'")

    return musica, avisos


def main(caminho_json):
    with open(caminho_json, "r", encoding="utf-8") as f:
        lote = json.load(f)

    existentes = carregar_todas_musicas()
    ids_existentes = {m["id"] for m in existentes}

    importadas, duplicadas = 0, 0
    for musica in lote:
        musica, avisos = validar_e_completar(musica)
        if avisos:
            print(f"ℹ️  {musica['nome']} - {musica['artista']}:")
            for a in avisos:
                print(f"    - {a}")

        if musica["id"] in ids_existentes:
            duplicadas += 1
            continue

        existentes.append(musica)
        ids_existentes.add(musica["id"])
        importadas += 1

    salvar_json(ARQ_MUSICAS, existentes)
    print(f"\nResumo: {importadas} músicas importadas, {duplicadas} já existiam (puladas).")
    print(f"Total no catálogo agora: {len(existentes)} músicas.")


if __name__ == "__main__":
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else "data/lote_recebido.json")
