"""Testes de sessão assinada e persistência multi-instância para Vercel serverless."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Lock
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app
from api.producao import ambiente_producao
from core import armazenamento_nuvem
from core.autenticacao import ContaExistente, ErroCredenciais, RepositorioAcesso


class _FakeBlobStore:
    def __init__(self):
        self.objetos: dict[str, bytes] = {}
        self.lock = Lock()

    def head_blob(self, pathname):
        url = f"https://fake-store.private.blob.vercel-storage.com/{pathname}"
        if url not in self.objetos:
            raise FileNotFoundError(pathname)
        return SimpleNamespace(url=url)

    def put_blob(self, pathname, body, *, access, content_type=None, add_random_suffix=False, allow_overwrite=False, cache_control_max_age=None):
        assert access == "private"
        url = f"https://fake-store.private.blob.vercel-storage.com/{pathname}"
        with self.lock:
            if url in self.objetos and not allow_overwrite:
                from vercel.blob.errors import BlobUnknownError
                raise BlobUnknownError("Blob already exists.")
            self.objetos[url] = bytes(body)
        return SimpleNamespace(url=url, pathname=pathname)

    def query_blobs(self, *, prefix=None, page_size=None, cursor=None):
        prefixo_url = "https://fake-store.private.blob.vercel-storage.com/"
        for url, corpo in list(self.objetos.items()):
            pathname = url[len(prefixo_url):]
            if prefix is None or pathname.startswith(prefix):
                yield SimpleNamespace(url=url, pathname=pathname, size=len(corpo))

    def get_blob(self, url_or_pathname, *, access):
        assert access == "private"
        if url_or_pathname not in self.objetos:
            raise FileNotFoundError(url_or_pathname)
        return SimpleNamespace(body=self.objetos[url_or_pathname], metadata=SimpleNamespace())

    def delete_blob(self, alvos, *, if_match=None):
        lista = [alvos] if isinstance(alvos, str) else list(alvos)
        for item in lista:
            self.objetos.pop(item, None)


class ArmazenamentoNuvemTests(unittest.TestCase):
    def setUp(self):
        self.blob_falso = _FakeBlobStore()
        self.segredo = "segredo_hmac_teste_vercel_com_mais_de_32_caracteres_12345"

    def test_sessao_cadastro_catalogo_e_diario_persistem_entre_instancias_distintas(self):
        dir_instancia_a = self.enterContext(TemporaryDirectory(prefix="rm-inst-a-"))
        dir_instancia_b = self.enterContext(TemporaryDirectory(prefix="rm-inst-b-"))
        env_nuvem = {
            "RHYTHMMIND_AMBIENTE": "producao",
            "RHYTHMMIND_TOKEN_SECRET": self.segredo,
            "BLOB_READ_WRITE_TOKEN": "vercel_blob_rw_fake_token_teste",
        }
        with patch.dict(os.environ, env_nuvem, clear=False), patch.object(
            armazenamento_nuvem, "_cliente_blob", return_value=self.blob_falso
        ):
            # Instância A: cadastro, login, importação do catálogo e sessão salva no diário
            with ambiente_producao(dir_instancia_a):
                with TestClient(app, base_url="https://rhythm-mind-nu.vercel.app", client=("203.0.113.10", 50000)) as cliente_a:
                    reg = cliente_a.post("/api/auth/registrar", json={
                        "nome_usuario": "usuaria_nuvem",
                        "senha": "SenhaFicticia123!",
                    })
                    self.assertEqual(reg.status_code, 201, reg.text)
                    login = cliente_a.post("/api/auth/entrar", json={
                        "nome_usuario": "usuaria_nuvem",
                        "senha": "SenhaFicticia123!",
                    })
                    self.assertEqual(login.status_code, 200, login.text)
                    token = login.json()["token_acesso"]
                    self.assertTrue(token.startswith("rm1."))
                    headers = {"Authorization": f"Bearer {token}"}

                    imp = cliente_a.post("/api/catalogo-referencia/importar", headers=headers)
                    self.assertEqual(imp.status_code, 200, imp.text)

                    diario = cliente_a.post("/api/diario/sessoes", headers=headers, json={
                        "finalidade": "Relaxar",
                        "emocoes_confirmadas": ["cansado"],
                        "estado_desejado_confirmado": ["calmo"],
                        "guardar_relato": False,
                        "limite_recomendacoes": 3,
                    })
                    self.assertEqual(diario.status_code, 201, diario.text)
                    self.assertEqual(len(diario.json()["recomendacoes"]), 3)

            # Instância B (diretório /tmp totalmente vazio, simulando outra Lambda ou cold start!)
            self.assertFalse((Path(dir_instancia_b) / "data" / "acesso.sqlite3").exists())
            with ambiente_producao(dir_instancia_b):
                with TestClient(app, base_url="https://rhythm-mind-nu.vercel.app", client=("203.0.113.11", 50001)) as cliente_b:
                    headers = {"Authorization": f"Bearer {token}"}
                    eu = cliente_b.get("/api/auth/eu", headers=headers)
                    self.assertEqual(eu.status_code, 200, eu.text)
                    self.assertEqual(eu.json()["nome_usuario"], "usuaria_nuvem")

                    musicas = cliente_b.get("/api/musicas", headers=headers)
                    self.assertEqual(musicas.status_code, 200)
                    self.assertEqual(musicas.json()["total"], 500)

                    padroes = cliente_b.get("/api/padroes", headers=headers)
                    self.assertEqual(padroes.status_code, 200)
                    self.assertEqual(padroes.json()["total_sessoes"], 1)

                    # Novo login por senha também funciona na Instância B sem perda da conta
                    novo_login = cliente_b.post("/api/auth/entrar", json={
                        "nome_usuario": "usuaria_nuvem",
                        "senha": "SenhaFicticia123!",
                    })
                    self.assertEqual(novo_login.status_code, 200, novo_login.text)

                    # Logout na Instância B revoga o token também na Instância A!
                    saida = cliente_b.post("/api/auth/sair", headers=headers)
                    self.assertEqual(saida.status_code, 204)

            with ambiente_producao(dir_instancia_a):
                with TestClient(app, base_url="https://rhythm-mind-nu.vercel.app", client=("203.0.113.10", 50000)) as cliente_a2:
                    negado = cliente_a2.get("/api/auth/eu", headers={"Authorization": f"Bearer {token}"})
                    self.assertEqual(negado.status_code, 401)

    def test_google_concorrente_e_reinicio_usam_o_mesmo_perfil(self):
        pasta = Path(self.enterContext(TemporaryDirectory()))
        repos = [RepositorioAcesso(pasta / f"{i}.sqlite3") for i in range(3)]
        issuer, subject = "https://accounts.google.com", "subject-ficticio"
        barreira = Barrier(2)
        gravar = self.blob_falso.put_blob

        def gravar_ao_mesmo_tempo(*args, **kwargs):
            barreira.wait(timeout=5)
            return gravar(*args, **kwargs)

        with patch.dict(os.environ, {
            "RHYTHMMIND_AMBIENTE": "producao", "BLOB_READ_WRITE_TOKEN": "teste",
            "RHYTHMMIND_TOKEN_SECRET": self.segredo,
        }), patch.object(armazenamento_nuvem, "_cliente_blob", return_value=self.blob_falso):
            with patch.object(self.blob_falso, "put_blob", side_effect=gravar_ao_mesmo_tempo):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    perfis = list(executor.map(lambda repo: repo.entrar_google(issuer, subject), repos[:2]))
            self.assertEqual(perfis[0], perfis[1])
            self.assertEqual(len(self.blob_falso.objetos), 1)
            token = repos[0].emitir_acesso(perfis[0]["usuario_id"])["token_acesso"]
            self.assertEqual(repos[2].identificar(token), perfis[0])
            self.assertEqual(repos[2].entrar_google("accounts.google.com", subject), perfis[0])
            self.assertNotEqual(repos[2].entrar_google(issuer, "outra-pessoa"), perfis[0])

    def test_google_preserva_perfil_legado_e_recusa_vinculo_local_conflitante(self):
        pasta = Path(self.enterContext(TemporaryDirectory()))
        repo_a, repo_b = [RepositorioAcesso(pasta / f"{i}.sqlite3") for i in range(2)]
        issuer, subject = "https://accounts.google.com", "subject-legado"
        with patch.dict(os.environ, {"RHYTHMMIND_AMBIENTE": "local"}):
            anterior = repo_a.entrar_google(issuer, subject)
            self.assertNotEqual(repo_b.entrar_google(issuer, subject), anterior)
        with patch.dict(os.environ, {
            "RHYTHMMIND_AMBIENTE": "producao", "BLOB_READ_WRITE_TOKEN": "teste",
        }), patch.object(armazenamento_nuvem, "_cliente_blob", return_value=self.blob_falso):
            self.assertEqual(repo_a.entrar_google(issuer, subject), anterior)
            with self.assertRaises(ErroCredenciais):
                repo_b.entrar_google(issuer, subject)
            novo = RepositorioAcesso(pasta / "nova.sqlite3")
            self.assertEqual(novo.entrar_google(issuer, subject), anterior)

    def test_token_assinado_adulterado_ou_com_outro_segredo_e_rejeitado(self):
        pasta = self.enterContext(TemporaryDirectory(prefix="rm-hmac-"))
        with patch.dict(os.environ, {
            "RHYTHMMIND_AMBIENTE": "producao",
            "RHYTHMMIND_TOKEN_SECRET": self.segredo,
        }, clear=False):
            repo_a = RepositorioAcesso(Path(pasta) / "a.sqlite3")
            repo_a.cadastrar("pessoa_1", "SenhaSegura123")
            token = repo_a.entrar("pessoa_1", "SenhaSegura123")["token_acesso"]
            self.assertNotIn(token.encode("ascii"), (Path(pasta) / "a.sqlite3").read_bytes())

            repo_b = RepositorioAcesso(Path(pasta) / "b.sqlite3")
            self.assertEqual(repo_b.identificar(token)["nome_usuario"], "pessoa_1")

            adulterado = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
            repo_c = RepositorioAcesso(Path(pasta) / "c.sqlite3")
            with self.assertRaises(ErroCredenciais):
                repo_c.identificar(adulterado)

        with patch.dict(os.environ, {
            "RHYTHMMIND_AMBIENTE": "producao",
            "RHYTHMMIND_TOKEN_SECRET": "outro_segredo_diferente_com_mais_de_32_caracteres_99999",
        }, clear=False):
            repo_d = RepositorioAcesso(Path(pasta) / "d.sqlite3")
            with self.assertRaises(ErroCredenciais):
                repo_d.identificar(token)

    def test_conta_duplicada_entre_instancias_retorna_conflito(self):
        pasta = self.enterContext(TemporaryDirectory(prefix="rm-dup-"))
        with patch.dict(os.environ, {
            "RHYTHMMIND_AMBIENTE": "producao",
            "BLOB_READ_WRITE_TOKEN": "vercel_blob_rw_fake_token_teste",
        }, clear=False), patch.object(
            armazenamento_nuvem, "_cliente_blob", return_value=self.blob_falso
        ):
            RepositorioAcesso(Path(pasta) / "1.sqlite3").cadastrar("apelido_unico", "Senha123!")
            with self.assertRaises(ContaExistente):
                RepositorioAcesso(Path(pasta) / "2.sqlite3").cadastrar("APELIDO_UNICO", "OutraSenha123!")


if __name__ == "__main__":
    unittest.main()
