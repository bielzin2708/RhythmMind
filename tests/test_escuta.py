"""Escolha/escuta por sessão: somente exemplos fictícios e armazenamento temporário."""

import copy
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import main as cli
from api import main as api
from api.desenvolvimento import dados_ficticios_temporarios
from core.escuta import preparar_escuta
from core.storage import carregar_json, salvar_json


def sessao_ficticia():
    return {
        "data_hora": "01/01/2000 10:00:00",
        "texto_usuario": "Relato fictício",
        "analise": {"emocoes": ["cansado"], "estado_desejado": ["calmo"]},
        "estrategia": "descompressao",
        "recomendacoes": [
            {"nome": f"Faixa Inventada {letra}", "artista": "Artista Fictício"}
            for letra in ("A", "B", "C")
        ],
        "feedback": {"ajudou": True, "motivo": "Motivo fictício"},
    }


class PrepararEscutaTests(unittest.TestCase):
    def test_estados_explicitos_e_ausencia_sem_alterar_entradas(self):
        recomendacoes = sessao_ficticia()["recomendacoes"]
        faixas = [
            {"indice_recomendacao": 1, "ouvida": True},
            {"indice_recomendacao": 3, "ouvida": False},
            {"indice_recomendacao": 2},
        ]
        antes = copy.deepcopy((recomendacoes, faixas))
        resultado = preparar_escuta(recomendacoes, faixas)
        self.assertEqual(resultado["faixas"], [
            {"indice_recomendacao": 1, "ouvida": True},
            {"indice_recomendacao": 3, "ouvida": False},
            {"indice_recomendacao": 2, "ouvida": None},
        ])
        self.assertEqual((recomendacoes, faixas), antes)

    def test_nenhuma_escolha_exige_lista_vazia_explicita(self):
        self.assertEqual(preparar_escuta([], []), {"faixas": []})
        with self.assertRaises(ValueError):
            preparar_escuta([], None)
        with self.assertRaises(ValueError):
            preparar_escuta([], [{"indice_recomendacao": 1}])

    def test_rejeita_indices_e_estados_ambiguos(self):
        invalidos = [
            [{"indice_recomendacao": indice}]
            for indice in (True, False, 0, -1, 4, 1.0, "1", None)
        ]
        invalidos += [
            [{"indice_recomendacao": 1}, {"indice_recomendacao": 1}],
            *[[{"indice_recomendacao": 1, "ouvida": valor}] for valor in (0, 1, "sim")],
            [{}],
            [{"indice_recomendacao": 1, "nome": "Faixa arbitrária"}],
            [None],
        ]
        for faixas in invalidos:
            with self.subTest(faixas=faixas), self.assertRaises(ValueError):
                preparar_escuta(sessao_ficticia()["recomendacoes"], faixas)


class HistoricoTemporarioTests(unittest.TestCase):
    def setUp(self):
        self.raiz = self.enterContext(dados_ficticios_temporarios())
        self.arquivo = Path(api.ARQ_HISTORICO).resolve()
        self.chave = "01/01/2000 10:00:00"
        self.registro = sessao_ficticia()
        self.gravar({self.chave: self.registro})
        self.client = self.enterContext(TestClient(
            api.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)
        ))

    def gravar(self, registros):
        salvar_json(str(self.arquivo), registros)

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

    def enviar(self, faixas):
        return self.client.post("/api/escuta", json={
            "data_hora": self.chave, "faixas": faixas,
        })


class EscutaApiTests(HistoricoTemporarioTests):
    def test_nova_sessao_nao_presume_escolha_ou_escuta(self):
        resposta = self.client.post("/api/registrar-estado", json={
            "texto_atual": "Exemplo fictício",
            "emocoes_confirmadas": ["cansado"],
            "texto_desejado": "calmo",
        })
        self.assertEqual(resposta.status_code, 200)
        self.assertIsNone(resposta.json()["escuta"])
        chave = resposta.json()["sessao_id"]
        self.assertIsNone(self.ler()[chave]["escuta"])
        self.assertIsNone(self.ler()[chave]["feedback"])
        resposta = self.client.post("/api/feedback", json={
            "sessao_id": chave, "ajudou": True, "motivo": "Exemplo fictício",
        })
        self.assertEqual(resposta.status_code, 200)
        self.assertIsNone(self.ler()[chave]["escuta"])

    def test_legado_ausente_e_nulo_continuam_intactos(self):
        registros = {
            "legado": self.registro,
            "nulo": {**self.registro, "escuta": None},
        }
        self.gravar(registros)
        antes = self.arquivo.read_bytes()
        resposta = self.client.get("/api/historico")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json()["registros"], registros)
        self.assertEqual(self.client.get("/api/padroes").status_code, 200)
        saida = self.capturar(cli.opcao_ver_historico)
        self.assertEqual(saida.count("Escolha e escuta ainda não informadas."), 2)
        self.assertEqual(self.arquivo.read_bytes(), antes)

    def test_escolha_multipla_preserva_feedback_e_demais_sessoes(self):
        original = {self.chave: self.registro, "outra": sessao_ficticia()}
        self.gravar(original)
        faixas = [
            {"indice_recomendacao": 1, "ouvida": True},
            {"indice_recomendacao": 2, "ouvida": False},
            {"indice_recomendacao": 3, "ouvida": None},
        ]
        resposta = self.enviar(faixas)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json()["escuta"], {"faixas": faixas})
        esperado = copy.deepcopy(original)
        esperado[self.chave]["escuta"] = {"faixas": faixas}
        self.assertEqual(self.ler(), esperado)
        self.assertEqual(
            self.client.get("/api/historico").json()["registros"], esperado
        )

    def test_substituicao_completa_e_nenhuma_explicita(self):
        casos = [
            ([{"indice_recomendacao": 1, "ouvida": True}],
             [{"indice_recomendacao": 1, "ouvida": True}]),
            ([{"indice_recomendacao": 3}],
             [{"indice_recomendacao": 3, "ouvida": None}]),
            ([], []),
        ]
        for entrada, esperado in casos:
            with self.subTest(entrada=entrada):
                resposta = self.enviar(entrada)
                self.assertEqual(resposta.status_code, 200)
                self.assertEqual(self.ler()[self.chave]["escuta"], {"faixas": esperado})
                self.assertEqual(self.ler()[self.chave]["feedback"], self.registro["feedback"])

    def test_rejeita_requisicoes_invalidas_sem_gravar(self):
        faixas_invalidas = [
            None, {}, ["1"], [{}], [None],
            [{"indice_recomendacao": 1}, {"indice_recomendacao": 1}],
            [{"indice_recomendacao": 1, "nome": "Faixa externa"}],
            *[[{"indice_recomendacao": indice}] for indice in (0, -1, 4, True, "1", 1.0)],
            *[[{"indice_recomendacao": 1, "ouvida": valor}] for valor in (0, 1, "false", "sim")],
        ]
        corpos = [
            {},
            {"data_hora": self.chave},
            {"data_hora": self.chave, "faixas": [], "campo_desconhecido": True},
            *[{"data_hora": self.chave, "faixas": faixas} for faixas in faixas_invalidas],
        ]
        antes = self.arquivo.read_bytes()
        for corpo in corpos:
            with self.subTest(corpo=corpo):
                resposta = self.client.post("/api/escuta", json=corpo)
                self.assertEqual(resposta.status_code, 422, resposta.text)
                self.assertEqual(self.arquivo.read_bytes(), antes)

    def test_sessao_inexistente_retorna_404_sem_gravar(self):
        antes = self.arquivo.read_bytes()
        resposta = self.client.post("/api/escuta", json={
            "data_hora": "sessao-ficticia-inexistente", "faixas": [],
        })
        self.assertEqual(resposta.status_code, 404)
        self.assertEqual(self.arquivo.read_bytes(), antes)

    def test_feedback_independente_e_padroes_continuam_por_sessao(self):
        antes = self.client.get("/api/padroes").json()
        faixas = [{"indice_recomendacao": 1, "ouvida": True}]
        self.assertEqual(self.enviar(faixas).status_code, 200)
        self.assertEqual(self.client.get("/api/padroes").json(), antes)
        for ajudou in (False, True):
            with self.subTest(ajudou=ajudou):
                resposta = self.client.post("/api/feedback", json={
                    "data_hora": self.chave, "ajudou": ajudou,
                })
                self.assertEqual(resposta.status_code, 200)
                self.assertEqual(self.ler()[self.chave]["escuta"], {"faixas": faixas})
                corpo = self.client.get("/api/padroes").json()
                self.assertEqual(corpo["avaliacoes_sessoes"]["sessoes_avaliadas"], 1)
                self.assertNotIn("musicas_aprovadas", corpo)
                self.assertNotIn("musicas_reprovadas", corpo)
                self.assertNotIn("Faixa Inventada", str(corpo))

    def test_nova_rota_tambem_exige_ambiente_ficticio_e_cliente_local(self):
        antes = self.arquivo.read_bytes()
        with patch.object(api.app.state, "diretorio_desenvolvimento", None):
            self.assertEqual(self.enviar([]).status_code, 503)
        for peer, host in (("203.0.113.10", "127.0.0.1"), ("127.0.0.1", "exemplo.invalid")):
            with TestClient(api.app, base_url=f"http://{host}", client=(peer, 50000)) as client:
                resposta = client.post("/api/escuta", json={
                    "data_hora": self.chave, "faixas": [],
                }, headers={"X-Forwarded-For": "127.0.0.1"})
                self.assertEqual(resposta.status_code, 403)
        self.assertEqual(self.arquivo.read_bytes(), antes)


class EscutaTerminalTests(HistoricoTemporarioTests):
    def coletar(self, respostas):
        with patch("builtins.input", side_effect=respostas), redirect_stdout(io.StringIO()):
            return cli.coletar_escuta(self.registro["recomendacoes"])

    def test_adiar_nao_e_escolher_nenhuma(self):
        self.assertIsNone(self.coletar([""]))
        self.assertEqual(self.coletar(["nenhuma"]), {"faixas": []})

    def test_coleta_estados_de_escuta_sem_presumir(self):
        self.assertEqual(self.coletar(["1,3,2", "sim", "não", ""]), {"faixas": [
            {"indice_recomendacao": 1, "ouvida": True},
            {"indice_recomendacao": 3, "ouvida": False},
            {"indice_recomendacao": 2, "ouvida": None},
        ]})

    def test_entrada_invalida_pede_nova_resposta(self):
        self.assertEqual(
            self.coletar(["1,1", "4", "0", "1,,2", "texto", "2", "talvez", "n"]),
            {"faixas": [{"indice_recomendacao": 2, "ouvida": False}]},
        )

    def test_atualiza_sessao_existente_preservando_feedback(self):
        self.capturar(cli.opcao_registrar_escuta, [self.chave, "2", "n"])
        esperado = copy.deepcopy(self.registro)
        esperado["escuta"] = {"faixas": [{"indice_recomendacao": 2, "ouvida": False}]}
        self.assertEqual(self.ler(), {self.chave: esperado})

    def test_adiar_atualizacao_preserva_registro_anterior(self):
        self.enviar([{"indice_recomendacao": 1, "ouvida": True}])
        antes = self.arquivo.read_bytes()
        saida = self.capturar(cli.opcao_registrar_escuta, [self.chave, ""])
        self.assertIn("Nenhuma alteração", saida)
        self.assertEqual(self.arquivo.read_bytes(), antes)

    def test_nova_sessao_terminal_grava_ausencia_ou_escolha_explicita(self):
        casos = [
            ([""], None),
            (["nenhuma"], {"faixas": []}),
            (["1", "s"], {"faixas": [{"indice_recomendacao": 1, "ouvida": True}]}),
        ]
        for respostas_escuta, esperado in casos:
            with self.subTest(escuta=esperado):
                self.gravar({})
                respostas = [
                    "cansado", "s", "calmo",
                    *respostas_escuta,
                    "s", "Motivo fictício", "n",
                ]
                self.capturar(cli.opcao_registar_estado, respostas)
                registros = self.ler()
                self.assertEqual(len(registros), 1)
                registro = next(iter(registros.values()))
                self.assertEqual(registro["escuta"], esperado)
                self.assertIs(registro["feedback"]["ajudou"], True)

    def test_historico_mostra_todos_os_estados_sem_alterar_arquivo(self):
        registros = {
            "sem-escolha": self.registro,
            "nenhuma": {**self.registro, "escuta": {"faixas": []}},
            "mista": {**self.registro, "escuta": {"faixas": [
                {"indice_recomendacao": 1, "ouvida": True},
                {"indice_recomendacao": 2, "ouvida": False},
                {"indice_recomendacao": 3, "ouvida": None},
            ]}},
        }
        self.gravar(registros)
        antes = self.arquivo.read_bytes()
        saida = self.capturar(cli.opcao_ver_historico)
        self.assertIn("Escolha e escuta ainda não informadas.", saida)
        self.assertIn("Escolha registrada: nenhuma faixa.", saida)
        self.assertIn("Escuta informada: sim", saida)
        self.assertIn("Escuta informada: não", saida)
        self.assertIn("Escuta informada: ainda não informada", saida)
        self.assertEqual(self.arquivo.read_bytes(), antes)

    def test_opcao_oito_e_saida_sete(self):
        with patch.object(cli, "opcao_registrar_escuta") as atualizar:
            self.capturar(cli.main, ["8", "7"])
        atualizar.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
