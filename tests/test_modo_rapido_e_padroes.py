"""Testes do modo rápido sem persistência padrão, privacidade no corpo JSON e padrões verificáveis."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import main as cli
from api import main as api
from core import recomendador, storage
from tests.apoio_autenticacao import ClienteAutenticado, dados_autenticados


DICIONARIO = json.loads(
    (Path(__file__).resolve().parents[1] / "data" / "dicionario_emocional.json").read_text(encoding="utf-8")
)


class ModoRapidoEPadroesTests(unittest.TestCase):
    def setUp(self):
        self.raiz = self.enterContext(dados_autenticados())
        storage.salvar_json(storage.ARQ_DICIONARIO, DICIONARIO)
        self.historico = Path(storage.resolver_caminho(storage.ARQ_HISTORICO))
        self.client = self.enterContext(ClienteAutenticado(
            api.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000),
        ))

    def registros(self):
        return storage.carregar_json(str(self.historico), {}, estrito=True)

    def test_detectar_emocoes_aceita_json_no_corpo_e_impoe_limite(self):
        resposta = self.client.post(
            "/api/detectar-emocoes",
            json={"texto": "Estou cansado e queria ficar calmo"},
        )
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertEqual(resposta.json(), {"emocoes_detectadas": ["cansado"]})

        excesso = self.client.post("/api/detectar-emocoes", json={"texto": "a" * 4001})
        self.assertEqual(excesso.status_code, 422)
        self.assertNotIn("aaaa", excesso.text)

        sem_dados = self.client.post("/api/detectar-emocoes")
        self.assertEqual(sem_dados.status_code, 422)

    def test_cansado_para_disposto_alcanca_ativacao_gradual_em_pt_br(self):
        estrategia, explicacao = recomendador.definir_estrategia(["cansado"], ["disposto"])
        self.assertEqual(estrategia, "ativacao_gradual")
        self.assertNotIn("tirar-te", explicacao)
        self.assertNotIn("sentes", explicacao)

        ponte, exp_ponte = recomendador.definir_estrategia(["ansioso"], ["disposto"])
        self.assertEqual(ponte, "transicao_emocional")
        self.assertNotIn("sentes", exp_ponte)

    def test_explorar_interpretacao_e_escuta_deixam_zero_relatos_gravados(self):
        storage.salvar_json(storage.ARQ_MUSICAS, [])
        previa = self.client.post("/api/explorar-interpretacao", json={
            "texto_atual": "Estou cansado depois das aulas e queria desacelerar",
            "texto_desejado": "calmo",
            "motor": "dicionario",
        })
        self.assertEqual(previa.status_code, 200, previa.text)
        corpo_previa = previa.json()
        self.assertFalse(corpo_previa["persistido"])
        self.assertEqual(self.registros(), {})

        vazio = self.client.post("/api/explorar-escuta", json={
            "emocoes_atuais": [],
            "estado_desejado": ["calmo"],
            "limite_recomendacoes": 3,
        })
        self.assertEqual(vazio.status_code, 200, vazio.text)
        self.assertEqual(vazio.json()["catalogo"]["estado"], "vazio")
        self.assertEqual(vazio.json()["recomendacoes"], [])
        self.assertEqual(self.registros(), {})

        importacao = self.client.post("/api/catalogo-referencia/importar", json={})
        self.assertEqual(importacao.status_code, 200, importacao.text)

        com_catalogo = self.client.post("/api/explorar-escuta", json={
            "emocoes_atuais": [],
            "estado_desejado": ["calmo"],
            "limite_recomendacoes": 3,
        })
        self.assertEqual(com_catalogo.status_code, 200, com_catalogo.text)
        dados = com_catalogo.json()
        self.assertFalse(dados["persistido"])
        self.assertEqual(dados["catalogo"]["estado"], "pronto")
        self.assertEqual(len(dados["recomendacoes"]), 3)
        self.assertEqual(len(dados["motivos_recomendacoes"]), 3)
        self.assertEqual(self.registros(), {})

    def test_guardar_no_diario_persiste_so_quando_solicitado_e_respeita_opcao_sem_relato(self):
        self.client.post("/api/musicas", json={
            "nome": "Calmaria Fictícia", "artista": "Artista Teste",
            "duracao": "3:10", "sentimentos_texto": "calmo",
        })
        sem_nota = self.client.post("/api/diario/sessoes", json={
            "texto_atual": "Nota íntima que decidi não guardar",
            "guardar_relato": False,
            "finalidade": "Relaxar",
            "emocoes_confirmadas": ["cansado"],
            "estado_desejado_confirmado": ["calmo"],
            "limite_recomendacoes": 3,
            "faixas_escuta": [{"indice_recomendacao": 1, "ouvida": True}],
            "feedback_ajudou": True,
            "feedback_motivo": "Combinou com o descanso.",
        })
        self.assertEqual(sem_nota.status_code, 201, sem_nota.text)
        sessao_id = sem_nota.json()["sessao_id"]
        salvo = self.registros()[sessao_id]
        self.assertEqual(salvo["texto_usuario"], "")
        self.assertEqual(salvo["finalidade"], "Relaxar")
        self.assertEqual(salvo["escuta"], {"faixas": [{"indice_recomendacao": 1, "ouvida": True}]})
        self.assertEqual(salvo["feedback"]["ajudou"], True)

    def test_padroes_nao_inventam_coocorrencia_inexistente_e_mostram_periodo_e_denominador(self):
        sessoes_ficticias = {
            "s1": {"data_hora": "01/11/2026 10:00:00", "analise": {"emocoes": ["triste"], "estado_desejado": ["disposto"]}, "estrategia": "transicao_emocional"},
            "s2": {"data_hora": "02/11/2026 10:00:00", "analise": {"emocoes": ["triste"], "estado_desejado": ["foco"]}, "estrategia": "foco_cognitivo"},
            "s3": {"data_hora": "03/11/2026 10:00:00", "analise": {"emocoes": ["triste"], "estado_desejado": []}, "estrategia": "espelhamento"},
            "s4": {"data_hora": "04/11/2026 10:00:00", "analise": {"emocoes": [], "estado_desejado": ["calmo"]}, "estrategia": "descompressao"},
            "s5": {"data_hora": "05/11/2026 10:00:00", "analise": {"emocoes": [], "estado_desejado": ["calmo"]}, "estrategia": "descompressao"},
            "s6": {"data_hora": "06/11/2026 10:00:00", "analise": {"emocoes": [], "estado_desejado": ["calmo"]}, "estrategia": "descompressao"},
        }
        storage.salvar_json(str(self.historico), sessoes_ficticias)
        resposta = self.client.get("/api/padroes")
        self.assertEqual(resposta.status_code, 200, resposta.text)
        corpo = resposta.json()
        self.assertEqual(corpo["total_sessoes"], 6)
        self.assertEqual(corpo["periodo"], {"inicio": "01/11/2026", "fim": "06/11/2026", "sessoes_com_data": 6})
        pares = {(item["emocao"], item["desejo"]) for item in corpo["combinacoes_observadas"]}
        self.assertNotIn(("triste", "calmo"), pares)
        self.assertNotIn("calmo", corpo["sintese_reflexiva"])
        self.assertIn("de 6 sessões registradas", corpo["sintese_reflexiva"])

        saida = io.StringIO()
        with patch.object(cli, "ARQ_HISTORICO", str(self.historico)), redirect_stdout(saida):
            cli.opcao_ver_padroes()
        texto_cli = saida.getvalue()
        self.assertNotIn("muito pesados", texto_cli)
        self.assertIn("01/11/2026 a 06/11/2026", texto_cli)
        self.assertIn("de 6", texto_cli)

    def test_cli_permite_pular_feedback_sem_gravar_avaliacao(self):
        chamadas = []
        saida = io.StringIO()
        with redirect_stdout(saida), patch("builtins.input", side_effect=["pular"]):
            resultado = cli.coletar_feedback(ao_atualizar=chamadas.append)
        self.assertEqual(resultado, (None, "", None, ""))
        self.assertEqual(chamadas, [])


if __name__ == "__main__":
    unittest.main()
