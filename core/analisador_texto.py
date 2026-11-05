import unicodedata
import re
from core.storage import carregar_json, ARQ_DICIONARIO

def remover_acentos(texto):
    """Remove acentos e converte para letras minúsculas."""
    if not texto:
        return ""
    texto = texto.lower()
    # Transforma caracteres com acento nos seus equivalentes sem acento
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    return texto.strip()

def extrair_palavras(texto):
    """Remove pontuação e extrai as palavras como uma lista."""
    texto_limpo = remover_acentos(texto)
    # Substitui tudo o que não for letra, número ou espaço vazio por um espaço
    texto_limpo = re.sub(r'[^\w\s]', ' ', texto_limpo)
    return texto_limpo.split()

# Regras lexicais locais; alcance e limitacoes em docs/negacao_expressoes.md.
_NEGADORES = frozenset({"nao", "nem", "nunca", "jamais", "sem"})
_FRONTEIRAS_PALAVRA = frozenset({"mas", "porem", "contudo", "todavia", "entretanto"})
_FRONTEIRAS_PONTUACAO = frozenset(",;:.!?\n\r\u2026\u2013\u2014")
_TOKENS_COM_FRONTEIRAS = re.compile(r"\w+|[,;:.!?\n\r\u2026\u2013\u2014]")

# Os intervalos são recortados no texto original, preservando trechos literais.
_INTENCAO = re.compile(
    r"\b(?:(?:eu\s+)?(?:não|na\u0303o|nao|nem|nunca|jamais)\s+)?"
    r"(?:quero|queria|gostaria(?:\s+de)?|pretendo|busco|desejo|almejo|"
    r"preciso\s+(?:de|ficar|estar|ter|me\s+sentir)|meu\s+objetivo\s+[eé])\b",
    re.IGNORECASE,
)
_FRONTEIRA_ORACAO = re.compile(
    r"[,;:.!?\n\r…–—]+|\b(?:mas|por[eé]m|contudo|todavia|entretanto)\b",
    re.IGNORECASE,
)
_ESTADO_EXPLICITO = re.compile(
    r"\b(?:(?:e|agora|hoje|atualmente)\s+)?(?:eu\s+)?"
    r"(?:(?:não|na\u0303o|nao|nem|nunca|jamais)\s+)?"
    r"(?:estou|t[oô]|tou|me\s+sinto|sinto-me|ando)\b",
    re.IGNORECASE,
)


def separar_papeis_texto(texto):
    """Separa estado atual e intenções explícitas sem interpretar emoções.

    Retorna texto atual, lista de trechos de intenção e seu intervalo literal.
    Não atribui intenções implícitas, não altera o relato e não decide por quem
    fala. Marcadores negados acompanham a intenção para não virar desejo positivo.
    """
    texto = texto or ""
    intervalos = []
    inicio = 0
    segmentos = [(fronteira.start(), fronteira.end())
                 for fronteira in _FRONTEIRA_ORACAO.finditer(texto)]
    segmentos.append((len(texto), len(texto)))
    for fim, proximo_inicio in segmentos:
        marcadores = list(_INTENCAO.finditer(texto, inicio, fim))
        for indice, marcador in enumerate(marcadores):
            final = marcadores[indice + 1].start() if indice + 1 < len(marcadores) else fim
            novo_estado = _ESTADO_EXPLICITO.search(texto, marcador.end(), final)
            if novo_estado:
                final = novo_estado.start()
            while final > marcador.start() and texto[final - 1].isspace():
                final -= 1
            if final > marcador.start():
                intervalos.append((marcador.start(), final))
        inicio = proximo_inicio
    atual = []
    inicio = 0
    for primeiro, ultimo in intervalos:
        atual.append(texto[inicio:primeiro])
        inicio = ultimo
    atual.append(texto[inicio:])
    intencoes = [texto[primeiro:ultimo] for primeiro, ultimo in intervalos]
    trecho_literal = texto[intervalos[0][0]:intervalos[-1][1]] if intervalos else None
    # Impede que uma negação do presente atravesse um trecho de intenção retirado.
    return "\n".join(atual), intencoes, trecho_literal


def _nova_afirmacao(tokens, indice):
    """Reconhece só novas orações explícitas; 'e ansioso' mantém a negação."""
    if tokens[indice] != "e":
        return False
    seguintes = tokens[indice + 1:indice + 5]
    while seguintes and seguintes[0] in {"eu", "agora", "hoje", "atualmente"}:
        seguintes = seguintes[1:]
    return bool(seguintes) and (
        seguintes[0] in {"estou", "to", "tou", "ando"}
        or seguintes[:2] == ["me", "sinto"]
        or seguintes[:2] == ["sinto", "me"]
    )


def _unidades_por_inicio(dicionario):
    """Une sinonimos iguais e prioriza o mais longo em cada posicao do texto."""
    unidades = {}
    for categoria, sinonimos in dicionario.items():
        for sinonimo in sinonimos:
            palavras = tuple(extrair_palavras(sinonimo))
            if not palavras or any(palavra in _FRONTEIRAS_PALAVRA for palavra in palavras):
                continue
            categorias = unidades.setdefault(palavras, [])
            if categoria not in categorias:
                categorias.append(categoria)

    por_inicio = {}
    for palavras, categorias in sorted(unidades.items(), key=lambda item: -len(item[0])):
        por_inicio.setdefault(palavras[0], []).append((palavras, categorias))
    return por_inicio


def detectar_emocoes_no_texto(texto):
    """Retorna categorias deduplicadas na ordem do dicionario, sem inferir opostos.

    Expressao mais longa na posicao atual vence palavras internas. Negacao
    externa suprime a unidade até uma fronteira ou nova oração afirmativa. O texto
    recebido e os dados persistidos nao sao modificados por esta consulta.
    Reconhecedor genérico também usado em desejo e cadastro musical. Para
    interpretar o estado atual, recorte antes com separar_papeis_texto.
    """
    dicionario = carregar_json(ARQ_DICIONARIO, {})
    return detectar_emocoes_com_dicionario(texto, dicionario)


def detectar_emocoes_com_dicionario(texto, dicionario):
    """Aplica as mesmas regras a um snapshot explícito, sem reler arquivos."""
    por_inicio = _unidades_por_inicio(dicionario)
    tokens = _TOKENS_COM_FRONTEIRAS.findall(remover_acentos(texto))
    encontradas = set()
    negado = False
    indice = 0

    while indice < len(tokens):
        token = tokens[indice]
        if token in _FRONTEIRAS_PONTUACAO or token in _FRONTEIRAS_PALAVRA:
            negado = False
            indice += 1
            continue
        if negado and _nova_afirmacao(tokens, indice):
            negado = False

        for palavras, categorias in por_inicio.get(token, []):
            # Negadores internos de compostos (ex.: sem energia) pertencem
            # a unidade do dicionario, antes da regra de negacao isolada.
            if token in _NEGADORES and len(palavras) == 1:
                continue
            if tuple(tokens[indice:indice + len(palavras)]) == palavras:
                if not negado:
                    encontradas.update(categorias)
                indice += len(palavras)
                break
        else:
            if token in _NEGADORES:
                negado = True
            indice += 1

    return [categoria for categoria in dicionario if categoria in encontradas]
