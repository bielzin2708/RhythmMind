"""Integridade da bateria sintética fixa, independente do desempenho dos motores."""

from collections import Counter
import json
from pathlib import Path
import unittest

from core.interpretacao.contratos import CATEGORIAS, CONTEXTOS, OBJETIVOS


ARQUIVO = Path(__file__).resolve().parents[1] / "data/casos_avaliacao_interpretacao.json"
GRUPOS = {
    "escrita_direta": "DIR",
    "variacao_escrita": "TYP",
    "negacao": "NEG",
    "estado_intencao": "INT",
    "coexistencia": "COE",
    "ambiguidade": "AMB",
}


class CasosAvaliacaoInterpretacaoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = json.loads(ARQUIVO.read_text(encoding="utf-8"))
        cls.casos = cls.base["casos"]

    def test_bateria_versionada_identifica_anotacoes_sinteticas_e_limites_do_mock(self):
        self.assertEqual(set(self.base), {"versao", "natureza", "nota", "casos"})
        self.assertEqual(self.base["versao"], "rhythmmind.casos-interpretacao.v1")
        self.assertEqual(self.base["natureza"], "sintetico")
        self.assertIn("anotações editoriais provisórias", self.base["nota"])
        self.assertIn("não devem ser ajustados aos resultados do motor lexical", self.base["nota"])
        self.assertIn("mock", self.base["nota"])

    def test_24_casos_unicos_distribuidos_em_seis_grupos_balanceados(self):
        self.assertEqual(len(self.casos), 24)
        self.assertEqual(len({caso["id"] for caso in self.casos}), 24)
        self.assertEqual(len({caso["texto_original"] for caso in self.casos}), 24)
        self.assertEqual(Counter(caso["grupo"] for caso in self.casos),
                         Counter({grupo: 4 for grupo in GRUPOS}))
        for grupo, prefixo in GRUPOS.items():
            with self.subTest(grupo=grupo):
                self.assertEqual({caso["id"] for caso in self.casos if caso["grupo"] == grupo},
                                 {f"{prefixo}{indice:02}" for indice in range(1, 5)})

    def test_entradas_e_notas_tem_formato_compativel_com_adaptadores(self):
        for caso in self.casos:
            with self.subTest(caso=caso["id"]):
                self.assertEqual(set(caso), {
                    "id", "grupo", "texto_original", "texto_desejado", "esperado", "nota",
                })
                for campo in ("texto_original", "nota"):
                    self.assertIsInstance(caso[campo], str)
                    self.assertTrue(caso[campo].strip())
                self.assertLessEqual(len(caso["texto_original"]), 4000)
                desejo = caso["texto_desejado"]
                self.assertTrue(desejo is None or isinstance(desejo, str))
                if desejo is not None:
                    self.assertLessEqual(len(desejo), 4000)

    def test_anotacoes_usam_vocabulario_fechado_sem_categorias_ou_musicas_inventadas(self):
        for caso in self.casos:
            esperado = caso["esperado"]
            with self.subTest(caso=caso["id"]):
                self.assertEqual(set(esperado), {
                    "estado_atual", "estado_desejado", "objetivos", "contextos", "precisa_esclarecimento",
                })
                for campo, permitidos in (
                    ("estado_atual", CATEGORIAS), ("estado_desejado", CATEGORIAS),
                    ("objetivos", OBJETIVOS), ("contextos", CONTEXTOS),
                ):
                    valores = esperado[campo]
                    self.assertIsInstance(valores, list)
                    self.assertTrue(all(isinstance(valor, str) for valor in valores))
                    self.assertEqual(len(valores), len(set(valores)))
                    self.assertLessEqual(len(valores), len(permitidos))
                    self.assertLessEqual(set(valores), set(permitidos))
                self.assertIs(type(esperado["precisa_esclarecimento"]), bool)

    def test_ambiguidades_nao_transformam_estado_passado_ou_de_outro_em_estado_atual(self):
        ambiguos = [caso for caso in self.casos if caso["grupo"] == "ambiguidade"]
        for caso in ambiguos:
            with self.subTest(caso=caso["id"]):
                self.assertTrue(caso["esperado"]["precisa_esclarecimento"])
                self.assertEqual(caso["esperado"]["estado_atual"], [])
                self.assertEqual(caso["esperado"]["estado_desejado"], [])
        texto = " ".join(caso["texto_original"] for caso in ambiguos)
        self.assertIn("Meu amigo", texto)
        self.assertIn("Ontem", texto)

    def test_distincao_de_papeis_tem_desejo_no_relato_e_no_campo_separado(self):
        intencoes = [caso for caso in self.casos if caso["grupo"] == "estado_intencao"]
        self.assertTrue(any(caso["texto_desejado"] is not None for caso in intencoes))
        self.assertTrue(any(caso["texto_desejado"] is None for caso in intencoes))
        for caso in intencoes:
            with self.subTest(caso=caso["id"]):
                esperado = caso["esperado"]
                self.assertTrue(esperado["estado_atual"])
                self.assertTrue(esperado["estado_desejado"])
                self.assertFalse(set(esperado["estado_atual"]) & set(esperado["estado_desejado"]))


if __name__ == "__main__":
    unittest.main()
