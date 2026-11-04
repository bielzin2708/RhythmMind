"""Contexto de armazenamento pessoal definido somente apos autenticacao no servidor."""

from contextlib import contextmanager
from contextvars import ContextVar
import os
from pathlib import Path
from uuid import UUID


_contexto: ContextVar[tuple[str, Path] | None] = ContextVar(
    "rhythmmind_contexto_usuario", default=None,
)
_ARQUIVOS_PESSOAIS = {"historico.json", "musicas_usuario.json"}


@contextmanager
def contexto_usuario(usuario_id, raiz):
    """Escopa o UUID validado e a raiz absoluta; sempre restaura o contexto anterior."""
    if not isinstance(usuario_id, str):
        raise ValueError("O identificador do usuario deve ser um UUID canonico.")
    try:
        canonico = str(UUID(usuario_id))
    except (ValueError, AttributeError) as erro:
        raise ValueError("O identificador do usuario deve ser um UUID canonico.") from erro
    if usuario_id != canonico:
        raise ValueError("O identificador do usuario deve ser um UUID canonico.")
    raiz_absoluta = Path(os.fspath(raiz)).resolve()
    token = _contexto.set((canonico, raiz_absoluta))
    try:
        yield
    finally:
        _contexto.reset(token)


def usuario_atual():
    """Identidade do contexto validado; ausente no terminal legado."""
    atual = _contexto.get()
    return atual[0] if atual is not None else None


def raiz_atual():
    """Raiz absoluta autorizada para o contexto atual."""
    atual = _contexto.get()
    return atual[1] if atual is not None else None


def _verificar_namespace(caminho, base, usuario_id):
    # Verifica tambem o destino real para recusar links entre namespaces.
    for candidato in (caminho.absolute(), caminho.resolve()):
        try:
            partes = candidato.relative_to(base).parts
        except ValueError:
            continue
        if not partes or partes[0] != usuario_id:
            raise PermissionError("Armazenamento de outro usuario nao autorizado.")


def resolver_caminho(caminho):
    """Isola os arquivos pessoais sem reutilizar os arquivos legados como fallback."""
    original = os.fspath(caminho)
    atual = _contexto.get()
    if atual is None:
        return original
    usuario_id, raiz = atual
    base = raiz / "data" / "usuarios"
    solicitado = Path(original)
    _verificar_namespace(solicitado, base, usuario_id)
    nome = solicitado.name.casefold()
    if nome not in _ARQUIVOS_PESSOAIS:
        return original
    destino = base / usuario_id / nome
    # Um link que escape da pasta autorizada nao deve se tornar destino pessoal.
    resolvido = destino.resolve()
    try:
        partes = resolvido.relative_to(base).parts
    except ValueError as erro:
        raise PermissionError("Destino pessoal fora do namespace autorizado.") from erro
    if not partes or partes[0] != usuario_id:
        raise PermissionError("Armazenamento de outro usuario nao autorizado.")
    return str(destino)
