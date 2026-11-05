"""Estado e intenção nos fluxos existentes, com HTTP e armazenamento fictícios."""

from contextlib import redirect_stdout
import io
from pathlib import Path
import unittest
from unittest.mock import patch

import main as cli
from api import main as api
from core import storage
from tests.apoio_autenticacao import ClienteAutenticado, dados_autenticados


class AnalisadorPapeisIntegracaoTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(dados_autenticados())
        self.historico = Path(storage.resolver_caminho(storage.ARQ_HISTORICO))
        self.client = self.enterContext(ClienteAutenticado(
            api.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000),
        ))

    def registros(self):
        return storage.carregar_json(str(self.historico), {}, estrito=True)

    def capturar_cli(self, funcao, respostas):
        saida = io.StringIO()
        with redirect_stdout(saida), patch("builtins.input", side_effect=respostas):
            resultado = funcao()
        return resultado, saida.getvalue()

    def criar(self, texto, **campos):
        resposta = self.client.post("/api/registrar-estado", json={"texto_atual": texto, **campos})
        self.assertEqual(resposta.status_code, 200, resposta.text)
        return resposta.json()

    def interpretar(self, sessao_id):
        resposta = self.client.post("/api/interpretacoes", json={"sessao_id": sessao_id})
        self.assertEqual(resposta.status_code, 200, resposta.text)
        return resposta.json()["proposta"]

    def test_preview_http_mantem_contrato_e_remove_intencao_do_estado_atual(self):
        antes = self.historico.read_bytes()
        casos = (
            ("Estou cansado e queria ficar calmo", ["cansado"]),
            ("Preciso de foco e estou cansado", ["cansado"]),
            ("Preciso de foco", []),
            ("Não estou tristinha, só cansadão", ["cansado"]),
        )
        for relato, esperado in casos:
            with self.subTest(relato=relato):
                resposta = self.client.post("/api/detectar-emocoes", params={"texto": relato})
                self.assertEqual(resposta.status_code, 200, resposta.text)
                self.assertEqual(resposta.json(), {"emocoes_detectadas": esperado})
        self.assertEqual(self.historico.read_bytes(), antes)

    def test_registro_e_interpretacao_separam_papeis_sem_confirmar_ou_recomendar(self):
        relato = "  Estou cansado e queria ficar calmo\n"
        with patch.object(api, "recomendar_musicas") as recomendar:
            resposta = self.criar(relato)
            self.assertEqual(resposta["emocoes_detectadas"], ["cansado"])
            sessao_id = resposta["sessao_id"]
            original = self.registros()[sessao_id]
            proposta = self.interpretar(sessao_id)
            recomendar.assert_not_called()
        self.assertEqual([s["categoria"] for s in proposta["estado_atual"]["sugestoes"]], ["cansado"])
        self.assertEqual([s["categoria"] for s in proposta["estado_desejado"]["sugestoes"]], ["calmo"])
        self.assertEqual(proposta["texto_intencao"], "queria ficar calmo")
        salvo = self.registros()[sessao_id]
        self.assertEqual({k: v for k, v in salvo.items() if k != "interpretacao"}, original)
        self.assertEqual(salvo["texto_usuario"], relato)
        self.assertEqual(salvo["analise"], {"emocoes": [], "estado_desejado": []})
        self.assertFalse(any(salvo["progresso"].values()))
        self.assertEqual(salvo["recomendacoes"], [])

    def test_intencao_sozinha_nao_preenche_estado_atual_nem_confirma_decisao(self):
        resposta = self.criar("Preciso de foco")
        self.assertEqual(resposta["emocoes_detectadas"], [])
        sessao_id = resposta["sessao_id"]
        proposta = self.interpretar(sessao_id)
        self.assertEqual(proposta["estado_atual"]["sugestoes"], [])
        self.assertEqual([s["categoria"] for s in proposta["estado_desejado"]["sugestoes"]], ["foco"])
        self.assertTrue(proposta["precisa_esclarecimento"])
        salvo = self.registros()[sessao_id]
        self.assertIsNone(salvo["texto_desejado"])
        self.assertFalse(any(salvo["progresso"].values()))

    def test_desejo_informado_em_campo_separado_continua_sendo_analisado(self):
        texto_desejado = "queria ficar calmo"
        with patch.object(api, "recomendar_musicas", return_value=("descompressao", "Exemplo fictício", [])) as recomendar:
            resposta = self.criar("Estou cansado", emocoes_confirmadas=["cansado"],
                                  texto_desejado=texto_desejado)
            recomendar.assert_called_once_with(["cansado"], ["calmo"])
        registro = self.registros()[resposta["sessao_id"]]
        self.assertEqual(registro["texto_desejado"], texto_desejado)
        self.assertEqual(registro["analise"], {"emocoes": ["cansado"], "estado_desejado": ["calmo"]})

    def test_termo_pilhado_preserva_ambiguidade_para_revisao_humana(self):
        resposta = self.criar("Estou pilhado")
        proposta = self.interpretar(resposta["sessao_id"])
        self.assertEqual({s["categoria"] for s in proposta["estado_atual"]["sugestoes"]},
                         {"animado", "ansioso"})
        self.assertEqual(proposta["estado_atual"]["estado"], "ambigua")
        self.assertTrue(proposta["precisa_esclarecimento"])
        self.assertFalse(self.registros()[resposta["sessao_id"]]["progresso"]["emocoes_confirmadas"])

    def test_cli_apresenta_so_estado_atual_e_preserva_relato_ao_interromper(self):
        relato = "Estou cansado e queria ficar calmo"
        with patch.object(cli, "recomendar_musicas") as recomendar:
            _, saida = self.capturar_cli(cli.opcao_registar_estado, [relato, EOFError()])
            recomendar.assert_not_called()
        self.assertIn("  - cansado", saida)
        self.assertNotIn("  - calmo", saida)
        self.assertIn("Fluxo interrompido", saida)
        registros = self.registros()
        self.assertEqual(len(registros), 1)
        registro = next(iter(registros.values()))
        self.assertEqual(registro["texto_usuario"], relato)
        self.assertEqual(registro["analise"], {"emocoes": [], "estado_desejado": []})
        self.assertFalse(any(registro["progresso"].values()))

    def test_refinamento_cli_nao_confirma_uma_intencao_como_estado_atual(self):
        antes = self.historico.read_bytes()
        resultado, saida = self.capturar_cli(
            lambda: cli.solicitar_refinamento_estado("Relato fictício"),
            ["queria ficar calmo", "Estou esgotada e preciso de foco"],
        )
        self.assertEqual(resultado, ["cansado"])
        self.assertIn("Ainda não consegui reconhecer", saida)
        self.assertEqual(self.historico.read_bytes(), antes)

    def test_cadastro_musical_preserva_reconhecedor_generico_de_sensacoes(self):
        resposta = self.client.post("/api/musicas", json={
            "nome": "Faixa Fictícia de Teste", "artista": "Artista Inventado", "duracao": "3:00",
            "sentimentos_texto": "queria ficar calmo",
        })
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertEqual(resposta.json()["sentimentos_associados"], ["calmo"])


if __name__ == "__main__":
    unittest.main()
