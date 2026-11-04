"""Sessões com UUID estável e atualizações progressivas por chave exata."""

from copy import deepcopy
from uuid import uuid4

from core import storage
from core.recomendador import validar_limite_recomendacoes


def validar_metadados_sessao(**campos):
    """Normaliza apenas os metadados fornecidos, sem inferir informações do relato."""
    limites = {"finalidade": 200, "contexto": 500}
    if set(campos) - limites.keys():
        raise ValueError("Informe apenas finalidade e contexto da sessão.")
    normalizados = {}
    for campo, valor in campos.items():
        if valor is not None:
            if not isinstance(valor, str):
                raise ValueError(f"O campo {campo} deve ser um texto ou null.")
            if len(valor) > limites[campo]:
                raise ValueError(f"O campo {campo} deve ter no máximo {limites[campo]} caracteres.")
            valor = valor.strip() or None
        normalizados[campo] = valor
    return normalizados


def criar_sessao(*, data_hora, texto_usuario, analise=None, estrategia=None,
                 recomendacoes=None, escuta=None, feedback=None,
                 finalidade=None, contexto=None, limite_recomendacoes=3):
    if not isinstance(texto_usuario, str) or not texto_usuario.strip():
        raise ValueError("Informe um relato não vazio.")
    return {
        "sessao_id": str(uuid4()),
        "data_hora": data_hora,
        "texto_usuario": texto_usuario,
        **validar_metadados_sessao(finalidade=finalidade, contexto=contexto),
        "analise": analise if analise is not None else {"emocoes": [], "estado_desejado": []},
        "texto_desejado": None,
        "estrategia": estrategia,
        "recomendacoes": recomendacoes if recomendacoes is not None else [],
        "limite_recomendacoes": validar_limite_recomendacoes(limite_recomendacoes),
        "motivos_recomendacoes": [],
        "escuta": escuta,
        "feedback": feedback,
        "progresso": {
            # True com analise.emocoes=[] registra a escolha de seguir sem categoria.
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
        "finalidade", "contexto",
        "limite_recomendacoes", "motivos_recomendacoes",
    }
    if set(campos) - permitidos:
        raise ValueError("A etapa não pode modificar identidade, data ou relato original.")
    if "limite_recomendacoes" in campos:
        campos["limite_recomendacoes"] = validar_limite_recomendacoes(campos["limite_recomendacoes"])
    campos.update(validar_metadados_sessao(**{
        campo: campos[campo] for campo in ("finalidade", "contexto") if campo in campos
    }))
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
