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

def detectar_emocoes_no_texto(texto):
    """Cruza as palavras do texto do utilizador com o dicionário emocional."""
    dicionario = carregar_json(ARQ_DICIONARIO, {})
    palavras_usuario = extrair_palavras(texto)
    
    emocoes_encontradas = []
    
    for emocao_principal, sinonimos in dicionario.items():
        for sinonimo in sinonimos:
            sinonimo_limpo = remover_acentos(sinonimo)
            # Se o sinónimo (ex: "tristinho") estiver na frase do utilizador
            if sinonimo_limpo in palavras_usuario:
                # Adiciona a emoção principal (ex: "triste") se ainda não estiver na lista
                if emocao_principal not in emocoes_encontradas:
                    emocoes_encontradas.append(emocao_principal)
    
    return emocoes_encontradas