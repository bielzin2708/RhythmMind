"""Entrada ASGI de producao usada pela Vercel."""

from api import main
from api.producao import ativar_producao, preparar_producao

ativar_producao()
preparar_producao()
app = main.app
