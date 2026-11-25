"""Entrada ASGI de producao usada pela Vercel."""

from api.main import app
from api.producao import ativar_producao, preparar_producao

ativar_producao()
preparar_producao()

__all__ = ["app"]
