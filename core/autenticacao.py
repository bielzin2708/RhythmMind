"""Contas e acessos revogaveis; senhas Argon2id via pwdlib, sem segredos fixos."""

from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
from pathlib import Path
import re
import secrets
import sqlite3
import time
from uuid import uuid4

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError


TTL_ACESSO_SEGUNDOS = 3600
_NOME_USUARIO = re.compile(r"[a-zA-Z0-9_.-]{3,64}\Z")
_TOKEN = re.compile(r"[a-zA-Z0-9_-]{43}\Z")


class ErroCredenciais(Exception):
    """Acesso ausente, incorreto, expirado ou encerrado."""


class ContaExistente(Exception):
    """Nome de usuario ja cadastrado."""


def agora():
    """Relogio do servidor em segundos UTC, substituivel somente nos testes."""
    return time.time()


def normalizar_nome(nome_usuario):
    if not isinstance(nome_usuario, str):
        raise ValueError("Nome de usuario deve ser texto.")
    nome = nome_usuario.strip().casefold()
    if not _NOME_USUARIO.fullmatch(nome):
        raise ValueError("Nome de usuario deve ter 3 a 64 letras ASCII, numeros, ponto, hifen ou sublinhado.")
    return nome


def validar_senha(senha):
    if not isinstance(senha, str) or not 12 <= len(senha) <= 128:
        raise ValueError("Senha deve ter entre 12 e 128 caracteres.")


@lru_cache(maxsize=1)
def _senhas():
    return PasswordHash.recommended()


@lru_cache(maxsize=1)
def _hash_sem_conta():
    # Mantem a verificacao Argon2 tambem quando o nome nao foi cadastrado.
    return _senhas().hash(secrets.token_urlsafe(32))


def _perfil(registro):
    return {
        "usuario_id": registro["usuario_id"],
        "nome_usuario": registro["nome_usuario"],
        "criado_em": registro["criado_em"],
    }


def _data_utc(instante):
    return datetime.fromtimestamp(instante, tz=timezone.utc).isoformat()


def _hash_token(token):
    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        raise ErroCredenciais()
    return hashlib.sha256(token.encode("ascii")).hexdigest()


class RepositorioAcesso:
    """SQLite transacional. O caminho e definido pelo servidor, nunca pelo cliente."""

    def __init__(self, caminho, *, ttl_segundos=None):
        self.caminho = Path(caminho).resolve()
        self.ttl_segundos = TTL_ACESSO_SEGUNDOS if ttl_segundos is None else ttl_segundos
        if type(self.ttl_segundos) is not int or self.ttl_segundos <= 0:
            raise ValueError("Validade de acesso deve ser um inteiro positivo.")
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with self._conexao() as conexao:
            conexao.execute("""
                CREATE TABLE IF NOT EXISTS usuarios (
                    usuario_id TEXT PRIMARY KEY,
                    nome_usuario TEXT NOT NULL UNIQUE,
                    senha_hash TEXT NOT NULL,
                    criado_em TEXT NOT NULL
                )
            """)
            conexao.execute("""
                CREATE TABLE IF NOT EXISTS acessos (
                    token_hash TEXT PRIMARY KEY,
                    usuario_id TEXT NOT NULL REFERENCES usuarios(usuario_id),
                    criado_em REAL NOT NULL,
                    expira_em REAL NOT NULL,
                    revogado_em REAL
                )
            """)
            conexao.execute("CREATE INDEX IF NOT EXISTS acessos_por_usuario ON acessos(usuario_id)")

    @contextmanager
    def _conexao(self):
        conexao = sqlite3.connect(str(self.caminho), timeout=10)
        conexao.row_factory = sqlite3.Row
        conexao.execute("PRAGMA foreign_keys = ON")
        try:
            with conexao:
                yield conexao
        finally:
            conexao.close()

    def cadastrar(self, nome_usuario, senha):
        nome = normalizar_nome(nome_usuario)
        validar_senha(senha)
        perfil = {
            "usuario_id": str(uuid4()),
            "nome_usuario": nome,
            "criado_em": _data_utc(agora()),
        }
        senha_hash = _senhas().hash(senha)
        try:
            with self._conexao() as conexao:
                conexao.execute(
                    "INSERT INTO usuarios(usuario_id, nome_usuario, senha_hash, criado_em) VALUES (?, ?, ?, ?)",
                    (perfil["usuario_id"], nome, senha_hash, perfil["criado_em"]),
                )
        except sqlite3.IntegrityError as erro:
            raise ContaExistente() from erro
        return perfil

    def entrar(self, nome_usuario, senha):
        try:
            nome = normalizar_nome(nome_usuario)
            validar_senha(senha)
        except ValueError as erro:
            raise ErroCredenciais() from erro

        with self._conexao() as conexao:
            registro = conexao.execute(
                "SELECT usuario_id, nome_usuario, senha_hash, criado_em FROM usuarios WHERE nome_usuario = ?",
                (nome,),
            ).fetchone()
        senha_hash = registro["senha_hash"] if registro is not None else _hash_sem_conta()
        try:
            valida, hash_atualizado = _senhas().verify_and_update(senha, senha_hash)
        except (ValueError, UnknownHashError):
            valida, hash_atualizado = False, None
        if not valida or registro is None:
            raise ErroCredenciais()

        token = secrets.token_urlsafe(32)
        instante = agora()
        expira_em = instante + self.ttl_segundos
        with self._conexao() as conexao:
            if hash_atualizado is not None:
                conexao.execute(
                    "UPDATE usuarios SET senha_hash = ? WHERE usuario_id = ? AND senha_hash = ?",
                    (hash_atualizado, registro["usuario_id"], registro["senha_hash"]),
                )
            conexao.execute(
                "INSERT INTO acessos(token_hash, usuario_id, criado_em, expira_em) VALUES (?, ?, ?, ?)",
                (_hash_token(token), registro["usuario_id"], instante, expira_em),
            )
        return {
            "token_acesso": token,
            "tipo_token": "bearer",
            "expires_in": self.ttl_segundos,
            "expira_em": _data_utc(expira_em),
        }

    def identificar(self, token):
        token_hash = _hash_token(token)
        with self._conexao() as conexao:
            registro = conexao.execute(
                """SELECT u.usuario_id, u.nome_usuario, u.criado_em,
                          a.expira_em, a.revogado_em
                   FROM acessos a JOIN usuarios u ON u.usuario_id = a.usuario_id
                   WHERE a.token_hash = ?""",
                (token_hash,),
            ).fetchone()
        if registro is None or registro["revogado_em"] is not None or registro["expira_em"] <= agora():
            raise ErroCredenciais()
        return _perfil(registro)

    def sair(self, token):
        token_hash = _hash_token(token)
        instante = agora()
        with self._conexao() as conexao:
            resultado = conexao.execute(
                """UPDATE acessos SET revogado_em = ?
                   WHERE token_hash = ? AND revogado_em IS NULL AND expira_em > ?""",
                (instante, token_hash, instante),
            )
            if resultado.rowcount != 1:
                raise ErroCredenciais()
