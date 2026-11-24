"""Filtros de consulta do histórico, sem alterar ou migrar registros salvos."""

from collections import Counter
from datetime import date, datetime
import re
import unicodedata

from core.feedback import NEGATIVO, NAO_REGISTRADO, POSITIVO, classificar_feedback


_DATA_ISO = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_DATA_HORA_REGISTRO = re.compile(r"[0-9]{2}/[0-9]{2}/[0-9]{4} [0-9]{2}:[0-9]{2}:[0-9]{2}")


def _validar_data(valor):
    if valor is None:
        return None
    if not isinstance(valor, str) or _DATA_ISO.fullmatch(valor) is None:
        raise ValueError("Informe as datas dos filtros no formato YYYY-MM-DD.")
    try:
        return date.fromisoformat(valor)
    except ValueError as erro:
        raise ValueError("Informe datas válidas nos filtros do histórico.") from erro


def _normalizar_texto(texto):
    return "".join(
        caractere for caractere in unicodedata.normalize("NFD", texto.casefold())
        if unicodedata.category(caractere) != "Mn"
    ).strip()


def _validar_texto(valor):
    if valor is None:
        return None
    if not isinstance(valor, str) or not _normalizar_texto(valor):
        raise ValueError("Informe texto não vazio nos filtros de finalidade e contexto.")
    return _normalizar_texto(valor)


def _data_do_registro(registro):
    valor = registro.get("data_hora")
    if not isinstance(valor, str) or _DATA_HORA_REGISTRO.fullmatch(valor) is None:
        return None
    try:
        return datetime.strptime(valor, "%d/%m/%Y %H:%M:%S").date()
    except ValueError:
        return None


def _corresponde_texto(valor, filtro):
    return isinstance(valor, str) and filtro in _normalizar_texto(valor)


def filtrar_historico(historico, *, data_inicio=None, data_fim=None,
                     finalidade=None, contexto=None, avaliacao=None):
    """Combina os filtros por AND e devolve um novo mapa na ordem original.

    Datas ISO delimitam dias inclusivos da data/hora salva na sessão. Registros
    sem data válida só são excluídos por esse motivo quando há filtro temporal.
    Finalidade/contexto usam substring literal, ignorando caixa e acentos.
    A avaliação conserva a distinção entre feedback ausente e negativo.
    Chaves e valores dos registros são preservados, sem escrita ou cópia interna.
    """
    inicio = _validar_data(data_inicio)
    fim = _validar_data(data_fim)
    if inicio is not None and fim is not None and inicio > fim:
        raise ValueError("A data inicial não pode ser posterior à data final.")
    finalidade_normalizada = _validar_texto(finalidade)
    contexto_normalizado = _validar_texto(contexto)
    if avaliacao is not None and (
        not isinstance(avaliacao, str)
        or avaliacao not in (POSITIVO, NEGATIVO, NAO_REGISTRADO)
    ):
        raise ValueError("Escolha uma avaliação válida: positivo, negativo ou nao_registrado.")

    filtrado = {}
    for identificador, registro in historico.items():
        if inicio is not None or fim is not None:
            data_registro = _data_do_registro(registro)
            if data_registro is None:
                continue
            if inicio is not None and data_registro < inicio:
                continue
            if fim is not None and data_registro > fim:
                continue
        if finalidade_normalizada is not None and not _corresponde_texto(
            registro.get("finalidade"), finalidade_normalizada,
        ):
            continue
        if contexto_normalizado is not None and not _corresponde_texto(
            registro.get("contexto"), contexto_normalizado,
        ):
            continue
        if avaliacao is not None and classificar_feedback(registro.get("feedback")) != avaliacao:
            continue
        filtrado[identificador] = registro
    return filtrado


def resumir_padroes_historico(historico, rotulos=None):
    """Resume contagens verificáveis com período, denominador e apenas pares observados."""
    total_sessoes = len(historico)
    emocoes_count = Counter()
    desejos_count = Counter()
    estrategias_count = Counter()
    pares_count = Counter()
    datas_validas = []

    for reg in historico.values():
        if not isinstance(reg, dict):
            continue
        data_reg = _data_do_registro(reg)
        if data_reg is not None:
            datas_validas.append(data_reg)
        analise = reg.get("analise") or {}
        emocoes = [e for e in (analise.get("emocoes") or []) if isinstance(e, str) and e]
        desejos = [d for d in (analise.get("estado_desejado") or []) if isinstance(d, str) and d]
        for emocao in emocoes:
            emocoes_count[emocao] += 1
        for desejo in desejos:
            desejos_count[desejo] += 1
        # Coocorrência real na mesma sessão (sem duplicar dentro do mesmo registro).
        for emocao in dict.fromkeys(emocoes):
            for desejo in dict.fromkeys(desejos):
                pares_count[(emocao, desejo)] += 1
        estrategia = reg.get("estrategia")
        if isinstance(estrategia, str) and estrategia:
            estrategias_count[estrategia] += 1

    periodo = None
    if datas_validas:
        inicio = min(datas_validas).strftime("%d/%m/%Y")
        fim = max(datas_validas).strftime("%d/%m/%Y")
        periodo = {
            "inicio": inicio,
            "fim": fim,
            "sessoes_com_data": len(datas_validas),
        }

    combinacoes = [
        {"emocao": emocao, "desejo": desejo, "contagem": contagem}
        for (emocao, desejo), contagem in pares_count.most_common(3)
    ]

    nome = (lambda chave: rotulos.get(chave, chave)) if isinstance(rotulos, dict) else (lambda chave: chave)
    unidade = "sessão registrada" if total_sessoes == 1 else "sessões registradas"
    trecho_periodo = (
        f" Período considerado: {periodo['inicio']}"
        + (f" a {periodo['fim']}." if periodo["inicio"] != periodo["fim"] else ".")
        if periodo else ""
    )

    sintese = None
    if combinacoes:
        topo = combinacoes[0]
        sintese = (
            f"Em {topo['contagem']} de {total_sessoes} {unidade}, "
            f"o estado '{nome(topo['emocao'])}' e o objetivo '{nome(topo['desejo'])}' "
            f"foram registrados na mesma sessão.{trecho_periodo}"
        )
    elif emocoes_count:
        emocao_top, cont_e = emocoes_count.most_common(1)[0]
        if desejos_count:
            desejo_top, cont_d = desejos_count.most_common(1)[0]
            sintese = (
                f"Em {total_sessoes} {unidade}, '{nome(emocao_top)}' apareceu em {cont_e} "
                f"e o objetivo '{nome(desejo_top)}' em {cont_d}, em sessões distintas.{trecho_periodo}"
            )
        else:
            sintese = (
                f"Em {cont_e} de {total_sessoes} {unidade}, "
                f"você confirmou o estado '{nome(emocao_top)}'.{trecho_periodo}"
            )
    elif desejos_count:
        desejo_top, cont_d = desejos_count.most_common(1)[0]
        sintese = (
            f"Em {cont_d} de {total_sessoes} {unidade}, "
            f"você escolheu o objetivo '{nome(desejo_top)}'.{trecho_periodo}"
        )

    return {
        "total_sessoes": total_sessoes,
        "periodo": periodo,
        "emocoes_frequentes": emocoes_count.most_common(3),
        "desejos_frequentes": desejos_count.most_common(3),
        "estrategias_frequentes": estrategias_count.most_common(2),
        "combinacoes_observadas": combinacoes,
        "sintese_reflexiva": sintese,
    }
