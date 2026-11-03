"""Sessões com UUID estável e atualizações progressivas por chave exata."""

from copy import deepcopy
from uuid import uuid4

from core import storage


def criar_sessao(*, data_hora, texto_usuario, analise=None, estrategia=None,
                 recomendacoes=None, escuta=None, feedback=None):
    if not isinstance(texto_usuario, str) or not texto_usuario.strip():
        raise ValueError("Informe um relato não vazio.")
    return {
        "sessao_id": str(uuid4()),
        "data_hora": data_hora,
        "texto_usuario": texto_usuario,
        "analise": analise if analise is not None else {"emocoes": [], "estado_desejado": []},
        "texto_desejado": None,
        "estrategia": estrategia,
        "recomendacoes": recomendacoes if recomendacoes is not None else [],
        "escuta": escuta,
        "feedback": feedback,
        "progresso": {
            "emocoes_confirmadas": False,
            "estado_desejado_informado": False,
            "recomendacoes_geradas": False,
        },
    }


def _historico_para_gravar(caminho):
    try:
        historico = storage.carregar_json(caminho, {}, estrito=True)
        if not isinstance(historico, dict):
            raise ValueError("Formato de histórico inválido.")
        return historico
    except (OSError, ValueError) as erro:
        raise OSError("Não foi possível ler o histórico para gravar.") from erro


def salvar_nova_sessao(caminho, registro):
    historico = _historico_para_gravar(caminho)
    identificador = registro["sessao_id"]
    if identificador in historico:
        raise ValueError("Identificador de sessão já existente.")
    historico[identificador] = deepcopy(registro)
    storage.salvar_json(caminho, historico)
    return registro


def atualizar_sessao(caminho, identificador, **campos):
    """Altera só os campos da etapa; identidade, criação e relato são imutáveis."""
    permitidos = {
        "analise", "texto_desejado", "estrategia", "explicacao", "recomendacoes",
        "escuta", "feedback", "progresso",
    }
    if set(campos) - permitidos:
        raise ValueError("A etapa não pode modificar identidade, data ou relato original.")
    historico = _historico_para_gravar(caminho)
    registro = deepcopy(historico[identificador])
    registro.update(deepcopy(campos))
    historico[identificador] = registro
    storage.salvar_json(caminho, historico)
    return registro


def recomendacoes_registradas(registro):
    """Legado não é reprocessado nem migrado ao ser retomado."""
    progresso = registro.get("progresso")
    return progresso is None or progresso.get("recomendacoes_geradas", False)
