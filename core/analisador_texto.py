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
    externa suprime a unidade ate pontuacao/adversativa documentada. O texto
    recebido e os dados persistidos nao sao modificados por esta consulta.
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
