"""Variações curadas preservam palavras inteiras, negação e revisão humana."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from core.analisador_texto import detectar_emocoes_com_dicionario
from core.interpretacao.adaptadores import InterpretadorLexical
from core.interpretacao.base import BaseConhecimento
from core.interpretacao.contratos import CATEGORIAS


DICIONARIO = json.loads((Path(__file__).resolve().parents[1]
                         / "data/dicionario_emocional.json").read_text(encoding="utf-8"))


class VariacoesLexicaisTests(unittest.TestCase):
    def analisar(self, texto):
        return detectar_emocoes_com_dicionario(texto, DICIONARIO)

    def test_flexoes_curadas_mantem_as_14_categorias_e_sua_ordem(self):
        self.assertEqual(list(DICIONARIO), list(CATEGORIAS))
        casos = {
            "satisfeita": "feliz", "empolgada": "animado", "focadinha": "foco",
            "calminho": "calmo", "disposta": "disposto", "reflexiva": "reflexivo",
            "tristinha": "triste", "esgotada": "cansado", "angustiada": "sofrendo",
            "aflita": "ansioso", "furiosa": "raiva", "explosiva": "explosivo",
            "apaixonadinha": "amor", "normalzinha": "normal",
        }
        for termo, categoria in casos.items():
            with self.subTest(termo=termo):
                self.assertEqual(self.analisar("Estou " + termo), [categoria])

    def test_diminutivos_aumentativos_e_variacao_de_acentos(self):
        casos = (
            ("Tô tristinho", ["triste"]),
            ("Tô tristinha", ["triste"]),
            ("Estou tristonha", ["triste"]),
            ("TÔ CANSADÃO", ["cansado"]),
            ("to cansadao", ["cansado"]),
            ("Estou cansadona", ["cansado"]),
            ("Estou esgotadinha e exausta", ["cansado"]),
            ("Tô animadinha e concentrada", ["animado", "foco"]),
        )
        for texto, esperado in casos:
            with self.subTest(texto=texto):
                self.assertEqual(self.analisar(texto), esperado)

    def test_girias_e_flexoes_compartilhadas_preservam_ambiguidade(self):
        for texto, esperado in (
            ("Estou pilhado", ["animado", "ansioso"]),
            ("Estou pilhada", ["animado", "ansioso"]),
            ("Estou agitada", ["animado", "ansioso"]),
            ("Estou tranquila", ["calmo", "normal"]),
            ("Tô de boa", ["calmo", "normal"]),
        ):
            with self.subTest(texto=texto):
                self.assertEqual(self.analisar(texto), esperado)

    def test_negar_variacao_nao_inverte_categoria_e_respeita_compostos(self):
        for texto, esperado in (
            ("Não estou tristinha, só esgotada", ["cansado"]),
            ("Nunca estou pilhada", []),
            ("Não estou de boa; estou cansadona", ["cansado"]),
            ("Não estou cansadão, mas estou focada", ["foco"]),
            ("Estou sem energia, não estou animadinha", ["cansado"]),
            ("Não estou sem energia", []),
        ):
            with self.subTest(texto=texto):
                self.assertEqual(self.analisar(texto), esperado)

    def test_variacoes_exigem_palavras_inteiras_sem_aproximacao_indiscriminada(self):
        for texto in ("infeliz", "ansiosamente", "esgotadamente", "cansadaozinho",
                      "esgotamentoindustrial", "pilhadouro", "trsite", "ancioso"):
            with self.subTest(texto=texto):
                self.assertEqual(self.analisar(texto), [])

    def test_dicionario_e_texto_original_nao_sao_modificados(self):
        dicionario = deepcopy(DICIONARIO)
        original = deepcopy(dicionario)
        texto = "  Não estou tristinha, só esgotada.\n"
        self.assertEqual(detectar_emocoes_com_dicionario(texto, dicionario), ["cansado"])
        self.assertEqual(dicionario, original)
        self.assertEqual(texto, "  Não estou tristinha, só esgotada.\n")

    def test_pilhado_e_de_boa_continuam_sugestoes_ambiguas_para_revisao(self):
        # Snapshot independente do diretório atual e sem leitura de dados pessoais.
        base = BaseConhecimento("0" * 64, json.dumps({
            "taxonomia": DICIONARIO, "ordem_categorias": list(DICIONARIO),
        }))
        motor = InterpretadorLexical()
        for texto in ("Estou pilhado", "Estou de boa"):
            with self.subTest(texto=texto):
                proposta = motor.interpretar(texto, None, base)
                self.assertEqual(proposta.estado_atual.estado, "ambigua")
                self.assertTrue(proposta.precisa_esclarecimento)
                self.assertEqual(len(proposta.estado_atual.sugestoes), 2)
                self.assertTrue(proposta.estado_atual.ambiguidades)


if __name__ == "__main__":
    unittest.main()
