"""Identidades Google e transações locais com dados exclusivamente fictícios."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import UUID

from pwdlib import PasswordHash

from core import autenticacao


ISSUER = "https://accounts.google.com"
STATE = "s" * 43
VINCULO = "v" * 43
NONCE = "n" * 43
VERIFIER = "r" * 64
RETORNO = "http://127.0.0.1:8000/api/auth/google/callback"


class GoogleRepositorioTests(unittest.TestCase):
    def setUp(self):
        raiz = self.enterContext(TemporaryDirectory(prefix="rm-google-repo-test-"))
        self.caminho = Path(raiz) / "acesso.sqlite3"
        self.repo = autenticacao.RepositorioAcesso(self.caminho)

    def fluxo(self):
        self.repo.criar_fluxo_google(STATE, VINCULO, NONCE, VERIFIER, RETORNO)

    def test_identidade_estavel_sem_senha_e_sem_vinculo_com_nome_local(self):
        local = self.repo.cadastrar("subject_ficticio", "senha-ficticia-123!")
        perfil = self.repo.entrar_google(ISSUER, "subject_ficticio")
        self.assertNotEqual(perfil["usuario_id"], local["usuario_id"])
        self.assertTrue(perfil["nome_usuario"].startswith("google_"))
        self.assertEqual(UUID(perfil["usuario_id"]).version, 4)
        self.assertEqual(self.repo.entrar_google("accounts.google.com", "subject_ficticio"), perfil)
        self.assertEqual(autenticacao.RepositorioAcesso(self.caminho).entrar_google(ISSUER, "subject_ficticio"), perfil)
        with closing(sqlite3.connect(self.caminho)) as conexao:
            senha_hash = conexao.execute("SELECT senha_hash FROM usuarios WHERE usuario_id = ?",
                                         (perfil["usuario_id"],)).fetchone()[0]
            self.assertIsNone(senha_hash)
        outro = self.repo.entrar_google(ISSUER, "outro_subject_ficticio")
        self.assertNotEqual(perfil["usuario_id"], outro["usuario_id"])

    def test_login_por_senha_recusa_conta_google_com_verificacao_dummy(self):
        perfil = self.repo.entrar_google(ISSUER, "subject_ficticio")
        hasher = PasswordHash.recommended()
        dummy = hasher.hash("segredo-dummy-ficticio")
        with patch.object(autenticacao, "_hash_sem_conta", return_value=dummy), \
                patch.object(hasher, "verify_and_update", wraps=hasher.verify_and_update) as verificar, \
                patch.object(autenticacao, "_senhas", return_value=hasher):
            with self.assertRaises(autenticacao.ErroCredenciais):
                self.repo.entrar(perfil["nome_usuario"], "segredo-dummy-ficticio")
            verificar.assert_called_once_with("segredo-dummy-ficticio", dummy)

    def test_issuer_e_subject_invalidos_recusados(self):
        for issuer, subject in (("https://outro.invalid", "subject"), (ISSUER, ""),
                                (ISSUER, "subject com espaco"), (ISSUER, "subject\0"),
                                (ISSUER, "s" * 256), (ISSUER, None)):
            with self.subTest(issuer=issuer, subject=subject):
                with self.assertRaises(autenticacao.ErroCredenciais):
                    self.repo.entrar_google(issuer, subject)

    def test_concorrencia_cria_apenas_uma_identidade(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            perfis = list(executor.map(lambda _: self.repo.entrar_google(ISSUER, "subject_concorrente"), range(8)))
        self.assertTrue(all(perfil == perfis[0] for perfil in perfis))
        with closing(sqlite3.connect(self.caminho)) as conexao:
            self.assertEqual(conexao.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0], 1)
            self.assertEqual(conexao.execute("SELECT COUNT(*) FROM identidades_google").fetchone()[0], 1)

    def test_sessao_google_reutiliza_expiracao_revogacao_e_so_hashes(self):
        perfil = self.repo.entrar_google(ISSUER, "subject_ficticio")
        acesso = self.repo.emitir_acesso(perfil["usuario_id"])
        self.assertEqual(acesso["tipo_token"], "bearer")
        self.assertEqual(acesso["expires_in"], autenticacao.TTL_ACESSO_SEGUNDOS)
        self.assertEqual(self.repo.identificar(acesso["token_acesso"]), perfil)
        self.assertNotIn(acesso["token_acesso"].encode(), self.caminho.read_bytes())
        self.repo.sair(acesso["token_acesso"])
        with self.assertRaises(autenticacao.ErroCredenciais):
            self.repo.identificar(acesso["token_acesso"])
        with self.assertRaises(autenticacao.ErroCredenciais):
            self.repo.emitir_acesso("uuid_inexistente")

    def test_fluxo_vinculado_ao_navegador_uso_unico_e_hashes(self):
        self.fluxo()
        with self.assertRaises(autenticacao.ErroCredenciais):
            self.repo.consumir_fluxo_google(STATE, "b" * 43)
        self.assertEqual(self.repo.consumir_fluxo_google(STATE, VINCULO), {
            "nonce": NONCE, "verifier": VERIFIER, "redirect_uri": RETORNO,
        })
        with self.assertRaises(autenticacao.ErroCredenciais):
            self.repo.consumir_fluxo_google(STATE, VINCULO)
        bruto = self.caminho.read_bytes()
        self.assertNotIn(STATE.encode(), bruto)
        self.assertNotIn(VINCULO.encode(), bruto)

    def test_expiracao_fluxo_no_limite_e_limpeza_ao_iniciar(self):
        with patch.object(autenticacao, "agora", return_value=100):
            self.fluxo()
        with patch.object(autenticacao, "agora", return_value=100 + autenticacao.TTL_FLUXO_GOOGLE_SEGUNDOS):
            with self.assertRaises(autenticacao.ErroCredenciais):
                self.repo.consumir_fluxo_google(STATE, VINCULO)
            self.fluxo()
        with closing(sqlite3.connect(self.caminho)) as conexao:
            self.assertEqual(conexao.execute("SELECT COUNT(*) FROM fluxos_google").fetchone()[0], 1)

    def test_fluxo_recusa_segredos_malformados_sem_criar_registro(self):
        base = [STATE, VINCULO, NONCE, VERIFIER, RETORNO]
        for indice, valor in ((0, "state-curto"), (1, None), (2, "nonce\n"),
                              (3, "v" * 42), (3, "v" * 129), (3, "v" * 63 + "\n"),
                              (4, "http://localhost/\r\nretorno")):
            with self.subTest(indice=indice, valor=valor):
                argumentos = base.copy()
                argumentos[indice] = valor
                with self.assertRaises((ValueError, autenticacao.ErroCredenciais)):
                    self.repo.criar_fluxo_google(*argumentos)
        with closing(sqlite3.connect(self.caminho)) as conexao:
            self.assertEqual(conexao.execute("SELECT COUNT(*) FROM fluxos_google").fetchone()[0], 0)

    def test_fluxo_consumido_atomicamente_sob_concorrencia(self):
        self.fluxo()

        def consumir(_):
            try:
                return self.repo.consumir_fluxo_google(STATE, VINCULO)
            except autenticacao.ErroCredenciais:
                return None

        with ThreadPoolExecutor(max_workers=4) as executor:
            resultados = list(executor.map(consumir, range(4)))
        self.assertEqual(sum(resultado is not None for resultado in resultados), 1)

    def test_handoff_uso_unico_limite_expiracao_e_so_hash_no_banco(self):
        perfil = self.repo.entrar_google(ISSUER, "subject_ficticio")
        with patch.object(autenticacao, "agora", return_value=100):
            expirado = self.repo.preparar_entrada_google(perfil["usuario_id"])
        self.assertNotIn(expirado.encode(), self.caminho.read_bytes())
        with patch.object(autenticacao, "agora", return_value=100 + autenticacao.TTL_ENTRADA_GOOGLE_SEGUNDOS):
            with self.assertRaises(autenticacao.ErroCredenciais):
                self.repo.concluir_entrada_google(expirado)
            segredo = self.repo.preparar_entrada_google(perfil["usuario_id"])
        with self.assertRaises(autenticacao.ErroCredenciais):
            self.repo.concluir_entrada_google("f" * 43)
        with patch.object(autenticacao, "agora", return_value=161):
            acesso = self.repo.concluir_entrada_google(segredo)
            self.assertEqual(self.repo.identificar(acesso["token_acesso"]), perfil)
        with self.assertRaises(autenticacao.ErroCredenciais):
            self.repo.concluir_entrada_google(segredo)
        self.assertNotIn(segredo.encode(), self.caminho.read_bytes())
        self.assertNotIn(acesso["token_acesso"].encode(), self.caminho.read_bytes())

    def test_handoff_concorrente_emite_apenas_uma_sessao(self):
        perfil = self.repo.entrar_google(ISSUER, "subject_ficticio")
        segredo = self.repo.preparar_entrada_google(perfil["usuario_id"])

        def concluir(_):
            try:
                return self.repo.concluir_entrada_google(segredo)
            except autenticacao.ErroCredenciais:
                return None

        with ThreadPoolExecutor(max_workers=4) as executor:
            resultados = list(executor.map(concluir, range(4)))
        self.assertEqual(sum(resultado is not None for resultado in resultados), 1)
        with closing(sqlite3.connect(self.caminho)) as conexao:
            self.assertEqual(conexao.execute("SELECT COUNT(*) FROM acessos").fetchone()[0], 1)


class MigracaoGoogleTests(unittest.TestCase):
    def setUp(self):
        raiz = self.enterContext(TemporaryDirectory(prefix="rm-google-migracao-test-"))
        self.caminho = Path(raiz) / "acesso.sqlite3"
        self.usuario_id = "ff65c4a2-a983-4e82-85ea-69b2c88b281b"
        self.senha = "senha-legada-ficticia-123!"
        self.token = "t" * 43
        self.hash_senha = PasswordHash.recommended().hash(self.senha)
        with closing(sqlite3.connect(self.caminho)) as conexao, conexao:
            conexao.execute("""CREATE TABLE usuarios (
                usuario_id TEXT PRIMARY KEY, nome_usuario TEXT NOT NULL UNIQUE,
                senha_hash TEXT NOT NULL, criado_em TEXT NOT NULL
            )""")
            conexao.execute("""CREATE TABLE acessos (
                token_hash TEXT PRIMARY KEY, usuario_id TEXT NOT NULL REFERENCES usuarios(usuario_id),
                criado_em REAL NOT NULL, expira_em REAL NOT NULL, revogado_em REAL
            )""")
            conexao.execute("INSERT INTO usuarios VALUES (?, ?, ?, ?)",
                             (self.usuario_id, "conta_legada", self.hash_senha, "2026-11-06T00:00:00+00:00"))
            conexao.execute("INSERT INTO acessos VALUES (?, ?, ?, ?, NULL)",
                             (hashlib.sha256(self.token.encode()).hexdigest(), self.usuario_id, 100, 10 ** 12))

    def test_migracao_preserva_usuario_hash_token_e_chaves_estrangeiras(self):
        repo = autenticacao.RepositorioAcesso(self.caminho)
        self.assertEqual(repo.identificar(self.token)["usuario_id"], self.usuario_id)
        self.assertEqual(repo.identificar(repo.entrar("conta_legada", self.senha)["token_acesso"])["usuario_id"],
                         self.usuario_id)
        with closing(sqlite3.connect(self.caminho)) as conexao:
            self.assertEqual(conexao.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(conexao.execute("SELECT senha_hash FROM usuarios WHERE usuario_id = ?",
                                             (self.usuario_id,)).fetchone()[0], self.hash_senha)
            colunas = conexao.execute("PRAGMA table_info(usuarios)").fetchall()
            self.assertEqual(next(coluna[3] for coluna in colunas if coluna[1] == "senha_hash"), 0)
        google = repo.entrar_google(ISSUER, "subject_legado_ficticio")
        self.assertNotEqual(google["usuario_id"], self.usuario_id)
        self.assertEqual(autenticacao.RepositorioAcesso(self.caminho).identificar(self.token)["usuario_id"],
                         self.usuario_id)

    def test_migracao_inconsistente_faz_rollback_sem_perder_dados(self):
        with closing(sqlite3.connect(self.caminho)) as conexao, conexao:
            conexao.execute("UPDATE acessos SET usuario_id = 'inexistente'")
        with self.assertRaises(sqlite3.IntegrityError):
            autenticacao.RepositorioAcesso(self.caminho)
        with closing(sqlite3.connect(self.caminho)) as conexao:
            self.assertEqual(conexao.execute("SELECT usuario_id FROM usuarios").fetchone()[0], self.usuario_id)
            self.assertEqual(conexao.execute("SELECT usuario_id FROM acessos").fetchone()[0], "inexistente")
            colunas = conexao.execute("PRAGMA table_info(usuarios)").fetchall()
            self.assertEqual(next(coluna[3] for coluna in colunas if coluna[1] == "senha_hash"), 1)


if __name__ == "__main__":
    unittest.main()
