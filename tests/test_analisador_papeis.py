"""Negação e papéis explícitos, sem rede ou alteração de relatos/dicionários."""

from copy import deepcopy
import json
from pathlib import Path
import unittest
import unicodedata
from unittest.mock import patch

from core.analisador_texto import detectar_emocoes_com_dicionario, separar_papeis_texto
from core.interpretacao.adaptadores import InterpretadorLexical
from core.interpretacao.base import carregar_base


RAIZ = Path(__file__).resolve().parents[1]
DICIONARIO = json.loads((RAIZ / "data/dicionario_emocional.json").read_text(encoding="utf-8"))


class AnalisadorPapeisTests(unittest.TestCase):
    def analisar(self, relato, desejo=None):
        atual, intencoes, literal = separar_papeis_texto(relato)
        desejado = desejo if desejo is not None else "\n".join(intencoes)
        return (detectar_emocoes_com_dicionario(atual, DICIONARIO),
                detectar_emocoes_com_dicionario(desejado, DICIONARIO), literal)

    def test_v02_e_contraste_preservam_apenas_categorias_afirmadas(self):
        for relato, esperado in (
            ("Não estou triste", []),
            ("Não estou triste, só cansado", ["cansado"]),
            ("Nunca estou ansiosa; hoje estou feliz", ["feliz"]),
            ("Não estou tristinha, só esgotada", ["cansado"]),
            ("NÃO ESTOU CANSADÃO, ESTOU DISPOSTA", ["disposto"]),
        ):
            with self.subTest(relato=relato):
                self.assertEqual(self.analisar(relato)[0], esperado)

    def test_negacao_compartilhada_nao_e_encerrada_por_coordenacao_de_adjetivos(self):
        for relato in ("Não estou triste e ansiosa", "Não estou triste ou ansiosa", "Nunca estou triste nem cansada"):
            with self.subTest(relato=relato):
                self.assertEqual(self.analisar(relato)[:2], ([], []))

    def test_nova_oracao_afirmativa_encerra_negacao_anterior(self):
        for trecho in ("estou", "tô", "tou", "eu estou", "me sinto", "ando",
                       "agora estou", "hoje me sinto", "agora eu estou", "eu atualmente estou"):
            relato = f"Não estou triste e {trecho} cansada"
            with self.subTest(relato=relato):
                self.assertEqual(self.analisar(relato)[0], ["cansado"])

    def test_nova_oracao_negada_permanece_suprimida(self):
        for trecho in ("não estou", "nunca estou", "eu não estou", "hoje não estou"):
            with self.subTest(trecho=trecho):
                self.assertEqual(self.analisar(f"Não estou triste e {trecho} cansada")[0], [])

    def test_composto_nao_se_torna_emocao_interna_quando_negado(self):
        self.assertEqual(self.analisar("Não estou sem energia e estou tristinha")[0], ["triste"])
        self.assertEqual(self.analisar("Estou sem energia e queria ficar disposta")[:2], (["cansado"], ["disposto"]))

    def test_queria_separa_intencao_do_estado_atual(self):
        for relato, literal in (
            ("Estou cansado e queria ficar calmo", "queria ficar calmo"),
            ("Queria ficar calmo e estou cansado", "Queria ficar calmo"),
            ("Tô cansada, queria ficar calma", "queria ficar calma"),
        ):
            with self.subTest(relato=relato):
                self.assertEqual(self.analisar(relato), (["cansado"], ["calmo"], literal))

    def test_necessidade_explicita_define_desejo_sem_atribuir_foco_atual(self):
        for intencao in ("preciso de foco", "preciso ter foco", "preciso ficar focado",
                         "preciso estar focada", "preciso me sentir focado"):
            with self.subTest(intencao=intencao):
                self.assertEqual(self.analisar(f"Estou cansado e {intencao}"),
                                 (["cansado"], ["foco"], intencao))
        self.assertEqual(self.analisar("Preciso de foco e tô cansada")[:2], (["cansado"], ["foco"]))

    def test_intencao_isolada_nao_vira_categoria_atual(self):
        for relato, desejado in (("Queria ficar calmo", ["calmo"]), ("Preciso de foco", ["foco"])):
            with self.subTest(relato=relato):
                self.assertEqual(self.analisar(relato)[:2], ([], desejado))

    def test_nega_intencao_sem_inventar_seu_oposto(self):
        for intencao in ("Não queria ficar triste", "Nunca queria ficar triste",
                         "Eu não preciso ficar triste", "Não preciso de foco", "Queria não estar triste"):
            with self.subTest(intencao=intencao):
                self.assertEqual(self.analisar(intencao)[:2], ([], []))
        self.assertEqual(self.analisar("Estou cansado e não queria ficar triste")[:2], (["cansado"], []))

    def test_negacao_preservada_com_unicode_decomposto(self):
        relato = unicodedata.normalize("NFD", "Não queria ficar triste e tô cansada")
        self.assertEqual(self.analisar(relato)[:2], (["cansado"], []))
        self.assertIn(self.analisar(relato)[2], relato)

    def test_palavra_preciso_sem_complemento_de_estado_nao_cria_intencao(self):
        relato = "Preciso saber se estou triste"
        self.assertEqual(self.analisar(relato), (["triste"], [], None))

    def test_desejo_separado_inclusive_vazio_tem_precedencia(self):
        relato = "Estou cansado e queria ficar calmo"
        self.assertEqual(self.analisar(relato, "Preciso de foco")[:2], (["cansado"], ["foco"]))
        self.assertEqual(self.analisar(relato, "")[:2], (["cansado"], []))

    def test_dois_papeis_podem_conter_mesma_categoria_sem_compartilhar_negacao(self):
        self.assertEqual(self.analisar("Não estou triste e queria ficar feliz")[:2], ([], ["feliz"]))
        self.assertEqual(self.analisar("Estou cansado e não preciso ficar cansado")[:2], (["cansado"], []))

    def test_recorte_preserva_literal_e_nao_escreve_nem_muta_dicionario(self):
        relato = "  Tô esgotada e queria ficar calmo!\n"
        original = deepcopy(DICIONARIO)
        with patch("core.storage.salvar_json") as salvar:
            atual, intencoes, literal = separar_papeis_texto(relato)
            self.assertEqual(literal, "queria ficar calmo")
            self.assertEqual(intencoes, [literal])
            self.assertIn(literal, relato)
            self.assertEqual(detectar_emocoes_com_dicionario(atual, DICIONARIO), ["cansado"])
        self.assertEqual(DICIONARIO, original)
        self.assertEqual(relato, "  Tô esgotada e queria ficar calmo!\n")
        salvar.assert_not_called()

    def test_adaptador_utiliza_mesmo_recorte_e_preserva_texto_intencao(self):
        base = carregar_base(caminho_dicionario=RAIZ / "data/dicionario_emocional.json")
        relato = "Estou esgotada e preciso de foco"
        proposta = InterpretadorLexical().interpretar(relato, None, base)
        self.assertEqual([s.categoria for s in proposta.estado_atual.sugestoes], ["cansado"])
        self.assertEqual([s.categoria for s in proposta.estado_desejado.sugestoes], ["foco"])
        self.assertEqual(proposta.texto_intencao, "preciso de foco")


if __name__ == "__main__":
    unittest.main()
