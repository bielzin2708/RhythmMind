"""UUIDs estáveis: exemplos fictícios, relógio congelado e arquivos temporários."""

import copy
import io
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

import main as cli
from api import main as api
from api.desenvolvimento import dados_ficticios_temporarios
from core import sessoes
from core.storage import carregar_json, salvar_json


MOMENTO = datetime(2000, 1, 1, 10, 0, 0)
DATA_HORA = "01/01/2000 10:00:00"


def legado_ficticio():
    return {
        "data_hora": DATA_HORA,
        "texto_usuario": "Sessão legada fictícia",
        "analise": {"emocoes": ["cansado"], "estado_desejado": ["calmo"]},
        "estrategia": "descompressao",
        "recomendacoes": [{"nome": "Faixa Inventada A", "artista": "Artista Fictício"}],
        "escuta": None,
        "feedback": None,
    }


class SessoesUuidTests(unittest.TestCase):
    def setUp(self):
        self.raiz = self.enterContext(dados_ficticios_temporarios())
        self.arquivo = Path(api.ARQ_HISTORICO).resolve()
        self.client = self.enterContext(TestClient(
            api.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)
        ))

    def ler(self):
        return carregar_json(str(self.arquivo), {})

    def capturar(self, funcao, respostas=None):
        saida = io.StringIO()
        with redirect_stdout(saida):
            if respostas is None:
                funcao()
            else:
                with patch("builtins.input", side_effect=respostas):
                    funcao()
        return saida.getvalue()

    def criar_api(self, texto="Sessão fictícia"):
        resposta = self.client.post("/api/registrar-estado", json={
            "texto_atual": texto, "emocoes_confirmadas": ["cansado"],
            "texto_desejado": "calmo",
        })
        self.assertEqual(resposta.status_code, 200, resposta.text)
        return resposta.json()

    def duas_api(self):
        with patch.object(api, "datetime") as relogio:
            relogio.now.return_value = MOMENTO
            return self.criar_api("Sessão fictícia A"), self.criar_api("Sessão fictícia B")

    def criar_terminal(self, motivo="Motivo fictício"):
        return self.capturar(cli.opcao_registar_estado, [
            "cansado", "s", "calmo", "", "s", motivo, "n",
        ])

    def duas_terminal(self):
        with patch.object(cli, "datetime") as relogio:
            relogio.now.return_value = MOMENTO
            saidas = [self.criar_terminal("Motivo fictício A"), self.criar_terminal("Motivo fictício B")]
        return list(self.ler()), saidas

    def consultar(self, identificador):
        return self.client.get("/api/historico/sessao", params={"sessao_id": identificador})

    def conferir_uuid(self, identificador):
        valor = UUID(identificador)
        self.assertEqual(valor.version, 4)
        self.assertEqual(str(valor), identificador)

    def test_duas_sessoes_api_mesmo_segundo_permanecem_distintas(self):
        with patch.object(sessoes, "uuid4", wraps=uuid4) as gerador:
            primeira, segunda = self.duas_api()
        self.assertEqual(gerador.call_count, 2)
        ids = [primeira["sessao_id"], segunda["sessao_id"]]
        self.assertNotEqual(*ids)
        registros = self.ler()
        self.assertEqual(set(registros), set(ids))
        self.assertEqual(primeira["data_hora"], DATA_HORA)
        self.assertEqual(segunda["data_hora"], DATA_HORA)
        for identificador in ids:
            self.conferir_uuid(identificador)
            self.assertEqual(registros[identificador]["sessao_id"], identificador)
            self.assertEqual(registros[identificador]["data_hora"], DATA_HORA)

    def test_atualizacoes_api_atingem_somente_a_sessao_indicada(self):
        primeira, segunda = self.duas_api()
        id_a, id_b = primeira["sessao_id"], segunda["sessao_id"]
        original = copy.deepcopy(self.ler())
        resposta = self.client.post("/api/feedback", json={
            "sessao_id": id_a, "ajudou": False, "motivo": "Motivo fictício negativo",
        })
        self.assertEqual(resposta.status_code, 200)
        apos_feedback = self.ler()
        self.assertEqual(apos_feedback[id_b], original[id_b])
        self.assertIs(apos_feedback[id_a]["feedback"]["ajudou"], False)
        self.assertIsNone(apos_feedback[id_a]["escuta"])
        faixas = [{"indice_recomendacao": 1, "ouvida": True}]
        resposta = self.client.post("/api/escuta", json={"sessao_id": id_b, "faixas": faixas})
        self.assertEqual(resposta.status_code, 200)
        registros = self.ler()
        self.assertEqual(registros[id_a], apos_feedback[id_a])
        self.assertIsNone(registros[id_b]["feedback"])
        self.assertEqual(registros[id_b]["escuta"], {"faixas": faixas})
        for identificador in (id_a, id_b):
            resposta = self.consultar(identificador)
            self.assertEqual(resposta.status_code, 200)
            self.assertEqual(resposta.json(), {
                "sessao_id": identificador, "registro": registros[identificador],
            })

    def test_releitura_consultas_e_atualizacoes_nao_geram_outros_uuids(self):
        primeira, segunda = self.duas_api()
        ids = [primeira["sessao_id"], segunda["sessao_id"]]
        antes = self.arquivo.read_bytes()
        with patch.object(sessoes, "uuid4", side_effect=AssertionError("Não gerar UUID na leitura/atualização")):
            self.assertEqual(set(self.ler()), set(ids))
            self.assertEqual(set(self.ler()), set(ids))
            self.assertEqual(set(self.client.get("/api/historico").json()["registros"]), set(ids))
            self.assertEqual(self.client.get("/api/padroes").status_code, 200)
            for identificador in ids:
                resposta = self.consultar(identificador)
                self.assertEqual(resposta.json()["registro"]["sessao_id"], identificador)
                saida = self.capturar(lambda: cli.opcao_ver_historico(identificador))
                self.assertIn(identificador, saida)
                self.assertIn(DATA_HORA, saida)
            self.assertEqual(self.arquivo.read_bytes(), antes)
            self.assertEqual(self.client.post("/api/feedback", json={
                "sessao_id": ids[0], "ajudou": True,
            }).status_code, 200)
            self.assertEqual(self.client.post("/api/escuta", json={
                "sessao_id": ids[1], "faixas": [],
            }).status_code, 200)
        self.assertEqual(set(self.ler()), set(ids))
        self.assertEqual([self.ler()[identificador]["sessao_id"] for identificador in ids], ids)

    def test_identificadores_inexistentes_nao_gravam(self):
        self.duas_api()
        antes = self.arquivo.read_bytes()
        for identificador in ("00000000-0000-4000-8000-000000000000", "chave-legada-inexistente"):
            with self.subTest(identificador=identificador):
                self.assertEqual(self.consultar(identificador).status_code, 404)
                self.assertEqual(self.client.post("/api/feedback", json={
                    "sessao_id": identificador, "ajudou": False,
                }).status_code, 404)
                self.assertEqual(self.client.post("/api/escuta", json={
                    "sessao_id": identificador, "faixas": [],
                }).status_code, 404)
                self.assertEqual(self.arquivo.read_bytes(), antes)

    def test_legado_e_novas_sessoes_com_mesma_data_coexistem(self):
        original = legado_ficticio()
        salvar_json(str(self.arquivo), {DATA_HORA: original})
        primeira, segunda = self.duas_api()
        ids = [primeira["sessao_id"], segunda["sessao_id"]]
        self.assertEqual(len(self.ler()), 3)
        antes = self.arquivo.read_bytes()
        with patch.object(sessoes, "uuid4", side_effect=AssertionError("Não migrar legado na leitura")):
            resposta = self.consultar(DATA_HORA)
            self.assertEqual(resposta.status_code, 200)
            self.assertEqual(resposta.json(), {"sessao_id": DATA_HORA, "registro": original})
            self.assertNotIn("sessao_id", resposta.json()["registro"])
            self.capturar(lambda: cli.opcao_ver_historico(DATA_HORA))
            self.assertEqual(self.arquivo.read_bytes(), antes)
            resposta = self.client.post("/api/feedback", json={
                "data_hora": DATA_HORA, "ajudou": True,
            })
            self.assertEqual(resposta.status_code, 200)
            resposta = self.client.post("/api/escuta", json={
                "sessao_id": DATA_HORA, "faixas": [{"indice_recomendacao": 1, "ouvida": False}],
            })
            self.assertEqual(resposta.status_code, 200)
        registros = self.ler()
        self.assertNotIn("sessao_id", registros[DATA_HORA])
        self.assertIs(registros[DATA_HORA]["feedback"]["ajudou"], True)
        for identificador in ids:
            self.assertIsNone(registros[identificador]["feedback"])
            self.assertIsNone(registros[identificador]["escuta"])

    def test_data_descritiva_nao_resolve_nova_sessao(self):
        self.duas_api()
        antes = self.arquivo.read_bytes()
        self.assertEqual(self.consultar(DATA_HORA).status_code, 404)
        for campo in ("sessao_id", "data_hora"):
            self.assertEqual(self.client.post("/api/feedback", json={
                campo: DATA_HORA, "ajudou": False,
            }).status_code, 404)
            self.assertEqual(self.client.post("/api/escuta", json={
                campo: DATA_HORA, "faixas": [],
            }).status_code, 404)
        self.assertEqual(self.arquivo.read_bytes(), antes)

    def test_referencia_ausente_vazia_ou_concorrente_retorna_422(self):
        primeira, _ = self.duas_api()
        antes = self.arquivo.read_bytes()
        referencias = [
            {}, {"sessao_id": None}, {"data_hora": None},
            {"sessao_id": primeira["sessao_id"], "data_hora": DATA_HORA},
            {"sessao_id": ""}, {"sessao_id": "  "}, {"data_hora": ""},
            {"sessao_id": 123},
        ]
        for referencia in referencias:
            for rota, campos in (("/api/feedback", {"ajudou": True}), ("/api/escuta", {"faixas": []})):
                with self.subTest(referencia=referencia, rota=rota):
                    resposta = self.client.post(rota, json={**referencia, **campos})
                    self.assertEqual(resposta.status_code, 422, resposta.text)
                    self.assertEqual(self.arquivo.read_bytes(), antes)
        self.assertEqual(self.client.post("/api/feedback", json={
            "sessao_id": primeira["sessao_id"], "data_hora": None, "ajudou": True,
        }).status_code, 200)

    def test_nova_consulta_continua_restrita_ao_ambiente_local(self):
        primeira, _ = self.duas_api()
        with patch.object(api.app.state, "diretorio_desenvolvimento", None):
            self.assertEqual(self.consultar(primeira["sessao_id"]).status_code, 503)
        with TestClient(api.app, base_url="http://127.0.0.1", client=("203.0.113.10", 50000)) as client:
            self.assertEqual(client.get("/api/historico/sessao", params={
                "sessao_id": primeira["sessao_id"],
            }).status_code, 403)

    def test_duas_sessoes_terminal_mesmo_segundo_preservam_identidades(self):
        with patch.object(sessoes, "uuid4", wraps=uuid4) as gerador:
            ids, saidas = self.duas_terminal()
        self.assertEqual(gerador.call_count, 2)
        self.assertEqual(len(ids), 2)
        self.assertNotEqual(*ids)
        for identificador, saida in zip(ids, saidas):
            self.conferir_uuid(identificador)
            self.assertIn(identificador, saida)
            self.assertEqual(self.ler()[identificador]["sessao_id"], identificador)
            self.assertEqual(self.ler()[identificador]["data_hora"], DATA_HORA)

    def test_terminal_atualiza_escuta_e_feedback_de_sessoes_distintas(self):
        ids, _ = self.duas_terminal()
        original = copy.deepcopy(self.ler())
        self.capturar(cli.opcao_registrar_escuta, [ids[0], "1", "s"])
        apos_escuta = self.ler()
        self.assertEqual(apos_escuta[ids[1]], original[ids[1]])
        self.assertEqual(apos_escuta[ids[0]]["feedback"], original[ids[0]]["feedback"])
        self.capturar(cli.opcao_registrar_feedback, [ids[1], "n", "Motivo fictício", "n"])
        registros = self.ler()
        self.assertEqual(registros[ids[0]], apos_escuta[ids[0]])
        self.assertIs(registros[ids[1]]["feedback"]["ajudou"], False)
        self.assertEqual(registros[ids[1]]["escuta"], original[ids[1]]["escuta"])
        saida = self.capturar(lambda: cli.opcao_ver_historico(ids[0]))
        self.assertIn(ids[0], saida)
        self.assertNotIn(ids[1], saida)

    def test_terminal_legado_e_identificador_inexistente(self):
        salvar_json(str(self.arquivo), {DATA_HORA: legado_ficticio()})
        with patch.object(sessoes, "uuid4", side_effect=AssertionError("Não gerar UUID em atualização")):
            self.capturar(cli.opcao_registrar_escuta, [DATA_HORA, "1", "s"])
            self.capturar(cli.opcao_registrar_feedback, [DATA_HORA, "n", "Motivo fictício", "n"])
        legado = self.ler()[DATA_HORA]
        self.assertNotIn("sessao_id", legado)
        self.assertIs(legado["feedback"]["ajudou"], False)
        self.assertIs(legado["escuta"]["faixas"][0]["ouvida"], True)
        antes = self.arquivo.read_bytes()
        for funcao in (cli.opcao_registrar_escuta, cli.opcao_registrar_feedback):
            self.assertIn("Sessão não encontrada.", self.capturar(funcao, ["inexistente"]))
        self.assertIn("Sessão não encontrada.", self.capturar(lambda: cli.opcao_ver_historico("inexistente")))
        self.assertEqual(self.arquivo.read_bytes(), antes)

    def test_menu_encaminha_consulta_por_id_e_feedback(self):
        with patch.object(cli, "opcao_ver_historico") as consultar:
            with patch.object(cli, "opcao_registrar_feedback") as avaliar:
                self.capturar(cli.main, ["4", "id-ficticio", "9", "7"])
        consultar.assert_called_once_with("id-ficticio")
        avaliar.assert_called_once_with()

    def test_terminal_e_api_criam_sessoes_distintas_no_mesmo_segundo(self):
        with patch.object(cli, "datetime") as relogio_cli, patch.object(api, "datetime") as relogio_api:
            relogio_cli.now.return_value = MOMENTO
            relogio_api.now.return_value = MOMENTO
            self.criar_terminal()
            resposta = self.criar_api()
        registros = self.ler()
        self.assertEqual(len(registros), 2)
        self.assertIn(resposta["sessao_id"], registros)
        for identificador, registro in registros.items():
            self.conferir_uuid(identificador)
            self.assertEqual(registro["sessao_id"], identificador)
            self.assertEqual(registro["data_hora"], DATA_HORA)


if __name__ == "__main__":
    unittest.main()
