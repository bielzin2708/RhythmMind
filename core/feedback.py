"""Leitura do retorno da sessão, sem inferir avaliação a partir de ausência."""

NAO_REGISTRADO = "nao_registrado"
POSITIVO = "positivo"
NEGATIVO = "negativo"

LIMITACAO_POR_FAIXA = (
    "O retorno se refere à sessão. A escolha e a escuta, quando registradas, "
    "descrevem o uso das faixas; não permitem atribuir a avaliação da sessão "
    "a uma faixa individual."
)
INTERPRETACAO_RETORNOS = (
    "Um retorno negativo indica que as recomendações não fizeram sentido para "
    "a pessoa; não permite concluir que houve piora."
)


def classificar_feedback(feedback):
    """Somente booleanos explícitos em 'ajudou' representam avaliação.

    O modelo atual não possui opção explícita de ficar sem avaliação.
    None, {} e ajudou ausente/nulo não demonstram uma decisão do usuário.
    Valores diferentes de bool também não são convertidos em avaliação.
    """
    if isinstance(feedback, dict):
        ajudou = feedback.get("ajudou")
        if ajudou is True:
            return POSITIVO
        if ajudou is False:
            return NEGATIVO
    return NAO_REGISTRADO


def resumir_avaliacoes(historico):
    """Conta resultados por sessão; sessões sem avaliação ficam fora dos resultados."""
    positivos = negativos = 0
    for registro in historico.values():
        estado = classificar_feedback(registro.get("feedback"))
        if estado == POSITIVO:
            positivos += 1
        elif estado == NEGATIVO:
            negativos += 1

    total = len(historico)
    avaliadas = positivos + negativos
    return {
        "sessoes_totais": total,
        "sessoes_avaliadas": avaliadas,
        "retornos_positivos": positivos,
        "retornos_negativos": negativos,
        "retornos_nao_registrados": total - avaliadas,
    }
