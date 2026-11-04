from pathlib import Path
from core.storage import resolver_caminho
"""Retomada do desejo salvo antes de uma falha de analise, com dados ficticios."""

import copy
import unittest
from unittest.mock import patch

from tests.apoio_autenticacao import ClienteAutenticado as TestClient

from api import main as api
from tests.apoio_autenticacao import dados_autenticados as dados_ficticios_temporarios
from core import storage


class DesejoProgressivoTests(unittest.TestCase):
    def setUp(self):
        self.raiz = self.enterContext(dados_ficticios_temporarios())
        self.arquivo = Path(resolver_caminho(storage.ARQ_HISTORICO)).resolve()
        self.client = self.enterContext(TestClient(
            api.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000),
        ))

    def interromper_analise_do_desejo(self):
        with patch.object(api, "detectar_emocoes_no_texto", side_effect=RuntimeError("Falha ficticia")):
            resposta = self.client.post("/api/registrar-estado", json={
                "texto_atual": "Relato ficticio: estou cansado.",
                "emocoes_confirmadas": ["cansado"],
                "texto_desejado": "calmo",
            })
        self.assertEqual(resposta.status_code, 500)
        identificador = resposta.json()["detail"]["sessao_id"]
        registro = storage.carregar_json(str(self.arquivo))[identificador]
        self.assertEqual(registro["texto_desejado"], "calmo")
        self.assertFalse(registro["progresso"]["estado_desejado_informado"])
        return identificador, copy.deepcopy(registro)

    def test_desejo_ja_salvo_nao_e_substituido_se_analise_ainda_pendente(self):
        identificador, _ = self.interromper_analise_do_desejo()
        antes = self.arquivo.read_bytes()
        resposta = self.client.post("/api/retomar-sessao", json={
            "sessao_id": identificador, "texto_desejado": "animado",
        })
        self.assertEqual(resposta.status_code, 409)
        self.assertEqual(self.arquivo.read_bytes(), antes)

    def test_desejo_salvo_e_reutilizado_apos_falha_sem_gerar_outra_sessao(self):
        for campos in ({}, {"texto_desejado": "calmo"}):
            with self.subTest(campos=campos):
                identificador, inicial = self.interromper_analise_do_desejo()
                resposta = self.client.post("/api/retomar-sessao", json={
                    "sessao_id": identificador, **campos,
                })
                self.assertEqual(resposta.status_code, 200)
                atual = storage.carregar_json(str(self.arquivo))[identificador]
                for campo in ("sessao_id", "data_hora", "texto_usuario", "texto_desejado"):
                    self.assertEqual(atual[campo], inicial[campo])
                self.assertTrue(atual["progresso"]["estado_desejado_informado"])
                self.assertTrue(atual["progresso"]["recomendacoes_geradas"])
                self.assertEqual(atual["analise"]["estado_desejado"], ["calmo"])
                self.assertIsNone(atual["escuta"])
                self.assertIsNone(atual["feedback"])


if __name__ == "__main__":
    unittest.main()
