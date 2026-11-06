"""Armazenamento local opcional; dados e credenciais dos testes são fictícios."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import desenvolvimento
from api.main import app
from core.storage import ARQ_DICIONARIO, ARQ_HISTORICO, ARQ_MUSICAS


class DesenvolvimentoPersistenteTests(unittest.TestCase):
    def setUp(self):
        self.temporario = Path(self.enterContext(TemporaryDirectory(prefix="rhythmmind-persistencia-teste-")))
        self.raiz = self.temporario / "dados-locais"

    def cliente(self):
        return TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))

    def test_conta_e_sessao_continuam_disponiveis_apos_reabrir(self):
        credenciais = {"nome_usuario": "conta_persistente_ficticia", "senha": "senha-ficticia-123!"}
        with desenvolvimento.dados_locais_persistentes(self.raiz):
            with self.cliente() as cliente:
                cadastro = cliente.post("/api/auth/registrar", json=credenciais)
                self.assertEqual(cadastro.status_code, 201, cadastro.text)
                perfil = cadastro.json()
                entrada = cliente.post("/api/auth/entrar", json=credenciais)
                self.assertEqual(entrada.status_code, 200, entrada.text)
                cabecalhos = {"Authorization": "Bearer " + entrada.json()["token_acesso"]}
                sessao = cliente.post("/api/registrar-estado", headers=cabecalhos, json={
                    "texto_atual": "Relato fictício: estou cansado após o treino.",
                })
                self.assertEqual(sessao.status_code, 200, sessao.text)
                sessao_id = sessao.json()["sessao_id"]
        self.assertTrue((self.raiz / "data" / "acesso.sqlite3").is_file())
        with desenvolvimento.dados_locais_persistentes(self.raiz):
            with self.cliente() as cliente:
                entrada = cliente.post("/api/auth/entrar", json=credenciais)
                self.assertEqual(entrada.status_code, 200, entrada.text)
                cabecalhos = {"Authorization": "Bearer " + entrada.json()["token_acesso"]}
                self.assertEqual(cliente.get("/api/auth/eu", headers=cabecalhos).json(), perfil)
                sessao = cliente.get("/api/historico/sessao", headers=cabecalhos,
                                     params={"sessao_id": sessao_id})
                self.assertEqual(sessao.status_code, 200, sessao.text)
                self.assertIn("Relato fictício", sessao.text)

    def test_sementes_nao_substituem_catalogo_dicionario_ou_historico_existentes(self):
        with desenvolvimento.dados_locais_persistentes(self.raiz):
            for arquivo in (ARQ_DICIONARIO, ARQ_HISTORICO, ARQ_MUSICAS):
                destino = self.raiz / arquivo
                destino.write_text(json.dumps({"conteudo_ficticio_preservar": arquivo}), encoding="utf-8")
            anteriores = {arquivo: (self.raiz / arquivo).read_bytes()
                          for arquivo in (ARQ_DICIONARIO, ARQ_HISTORICO, ARQ_MUSICAS)}
        with desenvolvimento.dados_locais_persistentes(self.raiz):
            for arquivo, esperado in anteriores.items():
                self.assertEqual((self.raiz / arquivo).read_bytes(), esperado)

    def test_recria_apenas_semente_ausente(self):
        with desenvolvimento.dados_locais_persistentes(self.raiz):
            anterior = (self.raiz / ARQ_DICIONARIO).read_bytes()
            (self.raiz / ARQ_MUSICAS).unlink()
        with desenvolvimento.dados_locais_persistentes(self.raiz):
            self.assertEqual((self.raiz / ARQ_DICIONARIO).read_bytes(), anterior)
            catalogo = json.loads((self.raiz / ARQ_MUSICAS).read_text(encoding="utf-8"))
            self.assertEqual(catalogo[0]["id"], "faixa_ficticia_a")

    def test_restaura_diretorio_e_estado_apos_erro_sem_apagar_dados(self):
        anterior = Path.cwd()
        autorizado_anterior = getattr(app.state, "diretorio_desenvolvimento", None)
        persistente_anterior = getattr(app.state, "armazenamento_persistente", False)
        with self.assertRaisesRegex(RuntimeError, "falha ficticia"):
            with desenvolvimento.dados_locais_persistentes(self.raiz):
                self.assertEqual(Path.cwd(), self.raiz)
                self.assertEqual(app.state.diretorio_desenvolvimento, str(self.raiz))
                self.assertTrue(app.state.armazenamento_persistente)
                with desenvolvimento.dados_ficticios_temporarios():
                    self.assertFalse(app.state.armazenamento_persistente)
                self.assertTrue(app.state.armazenamento_persistente)
                raise RuntimeError("falha ficticia")
        self.assertEqual(Path.cwd(), anterior)
        self.assertEqual(app.state.diretorio_desenvolvimento, autorizado_anterior)
        self.assertEqual(app.state.armazenamento_persistente, persistente_anterior)
        self.assertTrue((self.raiz / ARQ_HISTORICO).is_file())

    def test_recusa_raiz_do_projeto_e_diretorios_pessoais_genericos(self):
        for caminho in (desenvolvimento._RAIZ_PROJETO, Path.home(), Path("/")):
            with self.subTest(caminho=str(caminho)):
                with self.assertRaisesRegex(ValueError, "pasta dedicada"):
                    with desenvolvimento.dados_locais_persistentes(caminho):
                        self.fail("Diretorio generico foi autorizado.")

    def test_flag_persistente_mantem_servidor_local_e_diretorio(self):
        contexto = desenvolvimento.dados_locais_persistentes
        with patch.object(desenvolvimento, "dados_locais_persistentes",
                          side_effect=lambda: contexto(self.raiz)) as persistente:
            with patch.object(desenvolvimento.uvicorn, "run") as servidor:
                desenvolvimento.main(["--persistente"])
        persistente.assert_called_once_with()
        servidor.assert_called_once_with(app, host="127.0.0.1", port=8000, proxy_headers=False)
        self.assertTrue((self.raiz / ARQ_HISTORICO).is_file())


if __name__ == "__main__":
    unittest.main()
