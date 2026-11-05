"""Interpretação estruturada e revisável, independente da confirmação da sessão."""

from core.interpretacao.adaptadores import Interpretador, InterpretadorLexical
from core.interpretacao.base import BaseConhecimento, BaseIndisponivel, carregar_base
from core.interpretacao.contratos import Categoria, ParteInterpretacao, PropostaInterpretacao, SugestaoCategoria

__all__ = [
    "BaseConhecimento", "BaseIndisponivel", "Categoria", "Interpretador",
    "InterpretadorLexical", "ParteInterpretacao", "PropostaInterpretacao",
    "SugestaoCategoria", "carregar_base",
]
