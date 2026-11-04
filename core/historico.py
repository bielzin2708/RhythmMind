"""Filtros de consulta do histórico, sem alterar ou migrar registros salvos."""

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
