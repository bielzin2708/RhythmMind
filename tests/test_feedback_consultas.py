"""Regressões de consultas: somente sessões e faixas fictícias em diretório temporário."""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import main as cli
from api import main as api
from core import analisador_texto, storage


CASOS = [
    ("nulo", None, "Retorno ainda não registrado.", 0, 0),
    ("vazio", {}, "Retorno ainda não registrado.", 0, 0),
    ("negativo", {"ajudou": False, "motivo": "Exemplo negativo fictício"}, "Não", 0, 1),
    ("positivo", {"ajudou": True, "motivo": "Exemplo positivo fictício"}, "Sim", 1, 0),
]


def registro_ficticio(feedback):
    return {
        "data_hora": "01/01/2000 10:00:00",
        "texto_usuario": "Relato fictício de cansaço",
        "analise": {"emocoes": ["cansado"], "estado_desejado": ["calmo"]},
        "estrategia": "descompressao",
        "recomendacoes": [
            {"nome": "Faixa Inventada A", "artista": "Artista Fictício"},
            {"nome": "Faixa Inventada B", "artista": "Artista Fictício"},
        ],
        "feedback": feedback,
    }


class ConsultasFeedbackTests(unittest.TestCase):
    def setUp(self):
        temporario = tempfile.TemporaryDirectory(prefix="rhythmmind-test-")
        self.addCleanup(temporario.cleanup)
        self.raiz = Path(temporario.name)
        anterior = Path.cwd()
        os.chdir(self.raiz)
        self.addCleanup(os.chdir, anterior)
        self.historico = self.raiz / "data" / "historico.json"

        # Todos os caminhos de dados usados pelos testes apontam ao temporário.
        for modulo, atributo, caminho in (
            (cli, "ARQ_HISTORICO", self.historico),
            (api, "ARQ_HISTORICO", self.historico),
            (storage, "ARQ_HISTORICO", self.historico),
            (storage, "ARQ_MUSICAS", self.raiz / "data" / "musicas_usuario.json"),
            (storage, "ARQ_DICIONARIO", self.raiz / "data" / "dicionario_emocional.json"),
            (analisador_texto, "ARQ_DICIONARIO", self.raiz / "data" / "dicionario_emocional.json"),
        ):
            substituicao = patch.object(modulo, atributo, str(caminho))
            substituicao.start()
            self.addCleanup(substituicao.stop)

        ambiente = patch.object(
            api.app.state, "diretorio_desenvolvimento", str(self.raiz), create=True
        )
        ambiente.start()
        self.addCleanup(ambiente.stop)
        self.client = TestClient(
            api.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)
        )
        self.addCleanup(self.client.close)

    def gravar(self, registros):
        storage.salvar_json(str(self.historico), registros)

    def capturar(self, funcao):
        saida = io.StringIO()
        with redirect_stdout(saida):
            funcao()
        return saida.getvalue()

    def conferir_resumo(self, resumo, total, positivos, negativos):
        self.assertEqual(resumo, {
            "sessoes_totais": total,
            "sessoes_avaliadas": positivos + negativos,
            "retornos_positivos": positivos,
            "retornos_negativos": negativos,
            "retornos_nao_registrados": total - positivos - negativos,
        })

    def test_historico_terminal_matriz_feedback(self):
        for nome, feedback, texto, _, _ in CASOS:
            with self.subTest(caso=nome):
                self.gravar({"sessao-ficticia": registro_ficticio(feedback)})
                antes = self.historico.read_bytes()
                saida = self.capturar(cli.opcao_ver_historico)
                if feedback and "ajudou" in feedback:
                    self.assertIn(f"Fez sentido? {texto}", saida)
                else:
                    self.assertIn(texto, saida)
                    self.assertNotIn("Fez sentido? Não", saida)
                self.assertIn("sessão", saida)
                self.assertEqual(self.historico.read_bytes(), antes)

    def test_historico_api_preserva_feedback_bruto(self):
        for nome, feedback, _, positivos, negativos in CASOS:
            with self.subTest(caso=nome):
                registros = {"sessao-ficticia": registro_ficticio(feedback)}
                self.gravar(registros)
                antes = self.historico.read_bytes()
                resposta = self.client.get("/api/historico")
                self.assertEqual(resposta.status_code, 200)
                corpo = resposta.json()
                self.assertEqual(corpo["registros"], registros)
                self.conferir_resumo(corpo["avaliacoes_sessoes"], 1, positivos, negativos)
                self.assertEqual(self.historico.read_bytes(), antes)

    def test_padroes_terminal_matriz_feedback(self):
        for nome, feedback, _, positivos, negativos in CASOS:
            with self.subTest(caso=nome):
                self.gravar({"sessao-ficticia": registro_ficticio(feedback)})
                antes = self.historico.read_bytes()
                saida = self.capturar(cli.opcao_ver_padroes)
                self.assertIn(f"Sessões avaliadas: {positivos + negativos} de 1.", saida)
                self.assertIn(f"Retornos positivos: {positivos}", saida)
                self.assertIn(f"Retornos negativos: {negativos}", saida)
                self.assertIn(f"Retorno ainda não registrado: {1 - positivos - negativos}", saida)
                self.assertNotIn("Faixa Inventada", saida)
                self.assertNotIn("Músicas que não funcionaram", saida)
                self.assertNotIn("Músicas que mais ajudaram", saida)
                self.assertIn("escolha e a escuta", saida)
                self.assertEqual(self.historico.read_bytes(), antes)

    def test_padroes_api_matriz_feedback(self):
        for nome, feedback, _, positivos, negativos in CASOS:
            with self.subTest(caso=nome):
                self.gravar({"sessao-ficticia": registro_ficticio(feedback)})
                antes = self.historico.read_bytes()
                resposta = self.client.get("/api/padroes")
                self.assertEqual(resposta.status_code, 200)
                corpo = resposta.json()
                self.conferir_resumo(corpo["avaliacoes_sessoes"], 1, positivos, negativos)
                self.assertNotIn("musicas_aprovadas", corpo)
                self.assertNotIn("musicas_reprovadas", corpo)
                self.assertNotIn("Faixa Inventada", json.dumps(corpo, ensure_ascii=False))
                self.assertIn("escolha e a escuta", corpo["limitacao_resultados_por_faixa"])
                self.assertEqual(corpo["emocoes_frequentes"], [["cansado", 1]])
                self.assertEqual(corpo["desejos_frequentes"], [["calmo", 1]])
                self.assertEqual(corpo["estrategias_frequentes"], [["descompressao", 1]])
                self.assertEqual(self.historico.read_bytes(), antes)

    def test_mistura_conta_somente_sessoes_avaliadas(self):
        self.gravar({nome: registro_ficticio(fb) for nome, fb, *_ in CASOS})
        resposta = self.client.get("/api/padroes")
        self.assertEqual(resposta.status_code, 200)
        corpo = resposta.json()
        self.conferir_resumo(corpo["avaliacoes_sessoes"], 4, 1, 1)
        # Frequências descrevem todas as sessões, não somente as avaliadas.
        self.assertEqual(corpo["emocoes_frequentes"], [["cansado", 4]])
        saida = self.capturar(cli.opcao_ver_padroes)
        self.assertIn("Sessões avaliadas: 2 de 4.", saida)
        self.assertIn("Retorno ainda não registrado: 2", saida)

    def test_negativo_nao_significa_piora(self):
        self.gravar({"sessao-ficticia": registro_ficticio({"ajudou": False})})
        for funcao in (cli.opcao_ver_historico, cli.opcao_ver_padroes):
            saida = self.capturar(funcao)
            self.assertIn("não permite concluir que houve piora", saida)
        resposta = self.client.get("/api/padroes")
        self.assertEqual(resposta.status_code, 200)
        self.assertIn(
            "não permite concluir que houve piora",
            resposta.json()["interpretacao_retornos"],
        )

    def test_chave_ausente_ajudou_nulo_e_valores_nao_booleanos_nao_sao_avaliacao(self):
        registros = {"sem-chave": registro_ficticio(None)}
        del registros["sem-chave"]["feedback"]
        for indice, valor in enumerate((None, "false", 0, 1)):
            registros[f"valor-{indice}"] = registro_ficticio({"ajudou": valor})
        self.gravar(registros)
        for funcao in (cli.opcao_ver_historico, cli.opcao_ver_padroes):
            self.capturar(funcao)
        resposta = self.client.get("/api/padroes")
        self.assertEqual(resposta.status_code, 200)
        self.conferir_resumo(resposta.json()["avaliacoes_sessoes"], 5, 0, 0)
        resposta = self.client.get("/api/historico")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json()["registros"], registros)

    def test_historico_vazio(self):
        self.gravar({})
        self.assertIn("ainda não tem registros", self.capturar(cli.opcao_ver_historico))
        self.assertIn("mais registros", self.capturar(cli.opcao_ver_padroes))
        historico = self.client.get("/api/historico")
        padroes = self.client.get("/api/padroes")
        self.assertEqual(historico.status_code, 200)
        self.assertEqual(padroes.status_code, 200)
        self.conferir_resumo(historico.json()["avaliacoes_sessoes"], 0, 0, 0)
        self.conferir_resumo(padroes.json()["avaliacoes_sessoes"], 0, 0, 0)

    def test_api_registrar_consultar_e_avaliar_sessao(self):
        storage.salvar_json(storage.ARQ_MUSICAS, [{
            "nome": "Faixa Inventada A", "artista": "Artista Fictício",
            "sentimentos_associados": ["cansado"], "estrategias": ["descompressao"],
        }])
        storage.salvar_json(storage.ARQ_DICIONARIO, {"calmo": ["calmo"]})
        resposta = self.client.post("/api/registrar-estado", json={
            "texto_atual": "Relato fictício",
            "emocoes_confirmadas": ["cansado"],
            "texto_desejado": "calmo",
        })
        self.assertEqual(resposta.status_code, 200)
        chave = resposta.json()["sessao_id"]
        historico = self.client.get("/api/historico")
        self.assertIsNone(historico.json()["registros"][chave]["feedback"])
        padroes = self.client.get("/api/padroes")
        self.conferir_resumo(padroes.json()["avaliacoes_sessoes"], 1, 0, 0)
        for ajudou in (False, True):
            with self.subTest(ajudou=ajudou):
                resposta = self.client.post("/api/feedback", json={
                    "sessao_id": chave, "ajudou": ajudou, "motivo": "Motivo fictício",
                })
                self.assertEqual(resposta.status_code, 200)
                padroes = self.client.get("/api/padroes")
                self.conferir_resumo(
                    padroes.json()["avaliacoes_sessoes"], 1, int(ajudou), int(not ajudou)
                )
                self.assertNotIn("musicas_aprovadas", padroes.json())
                self.capturar(cli.opcao_ver_historico)
                self.capturar(cli.opcao_ver_padroes)


if __name__ == "__main__":
    unittest.main()
