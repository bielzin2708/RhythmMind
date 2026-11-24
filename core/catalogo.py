"""Regras de validação e inferência descritiva para o catálogo musical."""

import re

from core.analisador_texto import remover_acentos


def validar_duracao(duracao):
    """Aceita minutos e segundos no formato m:ss ou mm:ss."""
    return isinstance(duracao, str) and bool(re.fullmatch(r"\d{1,2}:[0-5]\d", duracao))


def validar_bpm(bpm_texto):
    """Retorna None quando ausente, o inteiro entre 40 e 220, ou -1 se inválido."""
    if not isinstance(bpm_texto, str) or not bpm_texto.strip():
        return None
    try:
        bpm = int(bpm_texto)
        if 40 <= bpm <= 220:
            return bpm
        return -1
    except ValueError:
        return -1


def inferir_contextos_para_musica(sentimentos, tags):
    contextos = []
    sent_set = set(sentimentos)
    tags_set = set(tags)

    if sent_set.intersection({"animado", "disposto", "explosivo", "raiva"}):
        contextos.append("treinar")
    if sent_set.intersection({"calmo", "normal", "reflexivo", "foco"}):
        contextos.extend(["relaxar", "estudar"])
    if sent_set.intersection({"triste", "sofrendo", "amor", "reflexivo"}):
        contextos.extend(["reflexao", "entender"])
    if tags_set.intersection({"rock", "rap", "trap", "pop"}):
        contextos.append("trabalhar")
    if tags_set.intersection({"bebedeira", "curticao", "curtição", "festa", "dançante", "dancante"}):
        contextos.append("social")

    if not contextos:
        contextos.append("entender")
    return list(dict.fromkeys(contextos))


def inferir_estrategias_para_musica(sentimentos, tags, bpm):
    estrategias = []
    sent_set = set(sentimentos)

    if sent_set.intersection({"triste", "sofrendo", "amor", "reflexivo"}):
        estrategias.append("espelhamento")
    if sent_set.intersection({"triste", "sofrendo", "ansioso", "cansado", "calmo", "reflexivo"}):
        estrategias.append("descompressao")
    if sent_set.intersection({"animado", "disposto", "feliz"}):
        estrategias.append("ativacao")
    if sent_set.intersection({"raiva", "explosivo"}):
        estrategias.append("catarse")
    if sent_set.intersection({"calmo", "normal", "reflexivo", "foco"}):
        estrategias.append("foco_cognitivo")
    if bpm is not None and 95 <= bpm <= 130:
        estrategias.append("ativacao_gradual")

    if not estrategias:
        estrategias.append("espelhamento")
    return list(dict.fromkeys(estrategias))


def inferir_energia_para_musica(sentimentos, tags, bpm):
    sent_set = set(sentimentos)
    tags_set = set(tags)

    if (sent_set.intersection({"animado", "disposto", "explosivo", "raiva"})
            or tags_set.intersection({"energia", "dançante", "dancante", "festa", "curticao", "curtição"})
            or (bpm is not None and bpm >= 135)):
        return "alta"
    if (sent_set.intersection({"calmo", "triste", "sofrendo"})
            or tags_set.intersection({"leve", "suave", "acústico", "acustico"})
            or (bpm is not None and bpm <= 85)):
        return "baixa"
    return "media"


def inferir_valencia_para_musica(sentimentos, tags):
    sent_set = set(sentimentos)
    tags_set = set(tags)

    if (sent_set.intersection({"triste", "sofrendo", "raiva", "explosivo", "ansioso"})
            or tags_set.intersection({"dor", "saudade", "sombria", "triste", "desilusao", "desilusão"})):
        return "baixa"
    if (sent_set.intersection({"feliz", "amor", "animado", "disposto"})
            or tags_set.intersection({"alegria", "feliz", "festa", "energia"})):
        return "alta"
    return "media"


def inferir_intensidade_para_musica(sentimentos, tags, bpm):
    sent_set = set(sentimentos)
    tags_set = set(tags)

    if (sent_set.intersection({"explosivo", "raiva"})
            or tags_set.intersection({"intensa", "intenso", "pesada", "pesado", "rock", "trap", "energia"})
            or (bpm is not None and bpm >= 145)):
        return "alta"
    if (sent_set.intersection({"calmo"})
            or tags_set.intersection({"leve", "suave", "sensivel", "sensível", "acustico", "acústico"})
            or (bpm is not None and bpm <= 85)):
        return "baixa"
    return "media"


def inferir_tags_a_partir_da_percepcao(texto_percepcao, sentimentos, bpm):
    """Gera tags automáticas a partir da percepção livre do usuário."""
    tags = []
    if not texto_percepcao:
        return tags

    texto = remover_acentos(texto_percepcao)

    mapa = {
        "treinar": ["treino", "treinar", "academia", "malhar", "correr", "esporte"],
        "leve": ["leve", "levinha", "suave", "delicada", "delicado"],
        "pesada": ["pesada", "pesado", "forte", "intensa", "intenso"],
        "festa": ["festa", "balada", "dançar", "dancar", "curtir"],
        "pensativo": ["pensativo", "pensar", "refletir", "reflexao", "reflexivo"],
        "energia": ["energia", "agitado", "agitada", "empolgante"],
        "triste": ["triste", "choro", "chorar", "saudade", "melancolia"],
        "foco": ["foco", "concentrar", "estudar", "trabalhar"],
        "calmo": ["calmo", "calma", "relaxar", "descansar", "tranquilo"],
    }

    palavras = texto.split()
    for tag, termos in mapa.items():
        for termo in termos:
            if termo in palavras or termo in texto:
                if tag not in tags:
                    tags.append(tag)
                break

    return tags
