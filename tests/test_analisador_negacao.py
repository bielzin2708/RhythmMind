"""Regras locais do analisador: exemplos inventados e dicionario de referencia."""

from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from core import analisador_texto as analisador


DICIONARIO = json.loads((
    Path(__file__).resolve().parents[1] / "data" / "dicionario_emocional.json"
).read_text(encoding="utf-8"))


class AnalisadorNegacaoTests(unittest.TestCase):
    def analisar(self, texto, dicionario=None):
        with patch.object(analisador, "carregar_json",
                          return_value=DICIONARIO if dicionario is None else dicionario):
            return analisador.detectar_emocoes_no_texto(texto)

    def test_casos_essenciais(self):
        casos = [
            ("N\u00e3o estou triste", []),
            ("N\u00e3o estou triste, estou cansado", ["cansado"]),
            ("Estou triste, mas n\u00e3o estou ansioso", ["triste"]),
            ("Estou sem energia", ["cansado"]),
            ("Estou feliz", ["feliz"]),
        ]
        for texto, esperado in casos:
            with self.subTest(texto=texto):
                self.assertEqual(self.analisar(texto), esperado)

    def test_todos_compostos_ja_documentados(self):
        for texto, esperado in [
            ("Estou sem disposi\u00e7\u00e3o", ["cansado"]),
            ("Estou SEM ENERGIA", ["cansado"]),
            ("Estou fora de controle", ["explosivo"]),
            ("Estou no limite", ["explosivo"]),
            ("Estou sem-energia", ["cansado"]),
            ("Estou fora/de/controle", ["explosivo"]),
            ("Estou sem   energia e sem\tdisposicao", ["cansado"]),
        ]:
            with self.subTest(texto=texto):
                self.assertEqual(self.analisar(texto), esperado)

    def test_negacao_externa_suprime_composto_inteiro_sem_sobrar_palavra_positiva(self):
        for composto in ("sem energia", "sem disposi\u00e7\u00e3o", "fora de controle", "no limite"):
            with self.subTest(composto=composto):
                self.assertEqual(self.analisar("N\u00e3o estou " + composto), [])

    def test_nao_inverte_emocao_ou_dupla_negacao(self):
        for texto in ("nao estou triste", "nao estou feliz", "nao nao estou triste",
                      "nao estou sem energia", "nao estou calmo", "nao estou desanimado"):
            with self.subTest(texto=texto):
                self.assertEqual(self.analisar(texto), [])

    def test_marcadores_de_negacao_documentados(self):
        for marcador in ("n\u00e3o", "nao", "nem", "nunca", "jamais", "sem"):
            with self.subTest(marcador=marcador):
                self.assertEqual(self.analisar(marcador + " estou triste e ansioso"), [])

    def test_pontuacao_e_quebra_de_linha_encerram_escopo(self):
        for limite in (",", ";", ":", ".", "!", "?", "\n", "\r\n", "\u2026", "\u2013", "\u2014"):
            with self.subTest(limite=repr(limite)):
                self.assertEqual(self.analisar("nao estou triste" + limite + " estou cansado"),
                                 ["cansado"])

    def test_adversativas_encerram_escopo(self):
        for limite in ("mas", "por\u00e9m", "porem", "contudo", "todavia", "entretanto"):
            with self.subTest(limite=limite):
                self.assertEqual(self.analisar("nao estou triste " + limite + " estou cansado"),
                                 ["cansado"])

    def test_e_ou_nao_encerram_negacao(self):
        for texto in ("nao estou triste e ansioso", "nao estou triste ou ansioso",
                      "nao estou triste nem ansioso"):
            with self.subTest(texto=texto):
                self.assertEqual(self.analisar(texto), [])

    def test_negacao_posterior_nao_apaga_ocorrencia_afirmativa(self):
        self.assertEqual(self.analisar("Estou triste, mas nao estou triste agora"), ["triste"])
        self.assertEqual(self.analisar("Nao estou triste. Depois fiquei triste"), ["triste"])

    def test_expressao_mais_longa_consumida_antes_de_palavras_internas(self):
        dicionario = {
            "isolada": ["controle"], "curta": ["fora de"], "longa": ["fora de controle"],
        }
        self.assertEqual(self.analisar("fora de controle", dicionario), ["longa"])
        self.assertEqual(self.analisar("nao fora de controle", dicionario), [])

    def test_prioridade_esquerda_nao_busca_otimo_global(self):
        dicionario = {
            "esquerda": ["muito cansado"], "direita": ["cansado demais hoje"], "isolada": ["hoje"],
        }
        self.assertEqual(self.analisar("muito cansado demais hoje", dicionario),
                         ["esquerda", "isolada"])

    def test_palavra_interna_pode_ser_reconhecida_em_outra_ocorrencia(self):
        self.assertEqual(self.analisar("sem energia, mas agora energia"), ["animado", "cansado"])

    def test_compostos_nao_atravessam_fronteiras(self):
        self.assertEqual(self.analisar("fora. de controle"), [])
        self.assertEqual(self.analisar("no, limite"), [])
        self.assertEqual(self.analisar("fora mas de controle"), [])

    def test_sinonimos_compartilhados_e_ordem_do_dicionario(self):
        self.assertEqual(self.analisar("tranquilo"), ["calmo", "normal"])
        self.assertEqual(self.analisar("agitado"), ["animado", "ansioso"])
        self.assertEqual(self.analisar("cansado e feliz e cansado"), ["feliz", "cansado"])
        dicionario = {"segunda": ["muito bem"], "primeira": ["muito bem"]}
        self.assertEqual(self.analisar("muito bem", dicionario), ["segunda", "primeira"])

    def test_aliases_simples_positivos_preservados(self):
        for sinonimos in DICIONARIO.values():
            for sinonimo in sinonimos:
                if len(analisador.extrair_palavras(sinonimo)) != 1:
                    continue
                normalizado = analisador.remover_acentos(sinonimo)
                esperado = [
                    categoria for categoria, termos in DICIONARIO.items()
                    if any(analisador.remover_acentos(termo) == normalizado for termo in termos)
                ]
                with self.subTest(sinonimo=sinonimo):
                    self.assertEqual(self.analisar("Estou " + sinonimo), esperado)

    def test_limites_de_palavra_e_normalizacao_preservados(self):
        self.assertEqual(self.analisar("Estou desanimado"), ["triste"])
        self.assertEqual(self.analisar("Estou infeliz e ansiosamente aqui"), [])
        self.assertEqual(self.analisar("semelhante alegre"), ["feliz"])
        self.assertEqual(self.analisar("NAO ESTOU ANSIOSO, ESTOU FELIZ"), ["feliz"])
        self.assertEqual(analisador.extrair_palavras("Ol\u00e1, MUNDO! sem-energia."),
                         ["ola", "mundo", "sem", "energia"])
        self.assertEqual(analisador.remover_acentos("  \u00c1GUA  "), "agua")

    def test_vazio_desconhecido_ou_none_continuam_sem_categoria(self):
        for texto in ("", None, "  ", "Relato ficticio sem termo reconhecido"):
            with self.subTest(texto=texto):
                self.assertEqual(self.analisar(texto), [])

    def test_texto_e_dicionario_preservados_sem_escrita(self):
        texto = "  N\u00e3o estou triste,\nestou cansado.  "
        dicionario = deepcopy(DICIONARIO)
        original = deepcopy(dicionario)
        with patch("core.storage.salvar_json") as gravar:
            self.assertEqual(self.analisar(texto, dicionario), ["cansado"])
        self.assertEqual(texto, "  N\u00e3o estou triste,\nestou cansado.  ")
        self.assertEqual(dicionario, original)
        gravar.assert_not_called()

    def test_dicionario_e_relido_sem_cache_obsoleto(self):
        with patch.object(analisador, "carregar_json", side_effect=[
            {"primeira": ["inventado"]}, {"segunda": ["inventado"]},
        ]):
            self.assertEqual(analisador.detectar_emocoes_no_texto("inventado"), ["primeira"])
            self.assertEqual(analisador.detectar_emocoes_no_texto("inventado"), ["segunda"])

    def test_limites_literais_documentados_sem_interpretacao_sintatica(self):
        casos = [
            ("Nao so triste, mas cansado", ["cansado"]),
            ("Sem duvida feliz", []),
            ("Nao li o livro e estou triste", []),
            ("Deixei de estar triste", ["triste"]),
        ]
        for texto, esperado in casos:
            with self.subTest(texto=texto):
                self.assertEqual(self.analisar(texto), esperado)


if __name__ == "__main__":
    unittest.main()
