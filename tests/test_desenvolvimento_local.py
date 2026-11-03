"""Proteções operacionais da API local; não equivalem a autenticação."""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import desenvolvimento
from api.main import app
from core.storage import ARQ_HISTORICO, carregar_json, salvar_json


class DesenvolvimentoLocalTests(unittest.TestCase):
    def cliente(self, host="127.0.0.1", peer="127.0.0.1"):
        client = TestClient(app, base_url=f"http://{host}", client=(peer, 50000))
        self.addCleanup(client.close)
        return client

    def test_bloqueia_sem_ambiente_temporario(self):
        with patch.object(app.state, "diretorio_desenvolvimento", None, create=True):
            for rota in ("/api/historico", "/api/padroes", "/docs"):
                self.assertEqual(self.cliente().get(rota).status_code, 503)
            self.assertEqual(
                self.cliente().post("/api/feedback", json={}).status_code, 503
            )

    def test_bloqueia_cliente_e_host_externos_mesmo_com_cabecalho_encaminhado(self):
        with desenvolvimento.dados_ficticios_temporarios():
            self.assertEqual(self.cliente().get("/api/historico").status_code, 200)
            self.assertEqual(
                self.cliente(peer="203.0.113.10").get(
                    "/api/historico", headers={"X-Forwarded-For": "127.0.0.1"}
                ).status_code,
                403,
            )
            self.assertEqual(
                self.cliente(host="exemplo.invalid").get("/api/historico").status_code,
                403,
            )

    def test_bloqueia_se_diretorio_de_trabalho_mudar(self):
        with desenvolvimento.dados_ficticios_temporarios() as temporario:
            subdiretorio = temporario / "outro"
            subdiretorio.mkdir()
            os.chdir(subdiretorio)
            try:
                self.assertEqual(self.cliente().get("/api/historico").status_code, 503)
            finally:
                os.chdir(temporario)

    def test_inicializador_usa_loopback_e_desativa_proxy(self):
        with patch.object(desenvolvimento.uvicorn, "run") as servidor:
            desenvolvimento.main()
        servidor.assert_called_once_with(
            app, host="127.0.0.1", port=8000, proxy_headers=False
        )

    def test_temporario_e_restauracao_mesmo_apos_erro(self):
        anterior = Path.cwd()
        autorizado_anterior = getattr(app.state, "diretorio_desenvolvimento", None)
        with self.assertRaisesRegex(RuntimeError, "falha fictícia"):
            with desenvolvimento.dados_ficticios_temporarios() as temporario:
                self.assertNotEqual(Path.cwd(), anterior)
                self.assertEqual(carregar_json(ARQ_HISTORICO), {})
                salvar_json(ARQ_HISTORICO, {"sessao-ficticia": {"feedback": None}})
                resposta = self.cliente().get("/api/historico")
                self.assertEqual(resposta.status_code, 200)
                self.assertEqual(resposta.json()["total"], 1)
                raise RuntimeError("falha fictícia")
        self.assertEqual(Path.cwd(), anterior)
        self.assertFalse(temporario.exists())
        self.assertEqual(
            getattr(app.state, "diretorio_desenvolvimento", None), autorizado_anterior
        )


if __name__ == "__main__":
    unittest.main()
