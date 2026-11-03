"""Escolha e escuta autodeclaradas, independentes da avaliação da sessão."""


def preparar_escuta(recomendacoes, faixas):
    """Valida uma substituição completa da escolha/escuta, sem alterar entradas.

    Os índices começam em 1 e referem-se às sugestões salvas nesta sessão.
    Lista vazia é a decisão explícita de não escolher nenhuma sugestão.
    ouvida=None indica escuta ainda não informada, diferente de False.
    """
    if not isinstance(recomendacoes, list):
        raise ValueError("A sessão não possui uma lista válida de sugestões.")
    if not isinstance(faixas, list):
        raise ValueError("Informe uma lista de faixas escolhidas.")

    resultado = []
    indices = set()
    for faixa in faixas:
        if not isinstance(faixa, dict) or set(faixa) - {"indice_recomendacao", "ouvida"}:
            raise ValueError("Cada escolha deve conter somente o índice e a escuta.")
        indice = faixa.get("indice_recomendacao")
        if type(indice) is not int or not 1 <= indice <= len(recomendacoes):
            raise ValueError("Use números inteiros de sugestões desta sessão, a partir de 1.")
        if indice in indices:
            raise ValueError("Uma sugestão não pode ser escolhida duas vezes.")
        ouvida = faixa.get("ouvida")
        if ouvida is not None and type(ouvida) is not bool:
            raise ValueError("A escuta deve ser informada como sim, não ou ainda não informada.")
        indices.add(indice)
        resultado.append({"indice_recomendacao": indice, "ouvida": ouvida})

    return {"faixas": resultado}
