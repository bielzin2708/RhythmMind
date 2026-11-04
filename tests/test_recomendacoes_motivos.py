"""Sugestões ampliadas e motivos calculados sobre catálogos fictícios."""

from copy import deepcopy
import unittest
from unittest.mock import patch

from core import recomendador


def faixa(identificador, *, sentimentos=(), estrategias=()):
    return {
        "id": identificador, "nome": f"Faixa Inventada {identificador}",
        "artista": "Artista Fictício", "sentimentos_associados": list(sentimentos),
        "estrategias": list(estrategias),
    }


class RecomendacoesMotivosTests(unittest.TestCase):
    def setUp(self):
        self.catalogo = [
            faixa(str(indice), sentimentos=["cansado"], estrategias=["descompressao"])
            for indice in range(12)
        ]

    def recomendar(self, emocoes, desejo=None, ajuste=None, **opcoes):
        with patch.object(recomendador, "carregar_musicas_usuario", return_value=self.catalogo):
            return recomendador.recomendar_musicas(emocoes, desejo, ajuste, **opcoes)

    def test_padrao_preserva_tupla_tres_musicas_brutas_e_ordem_dos_empates(self):
        resultado = self.recomendar(["cansado"], ["calmo"])
        self.assertEqual(len(resultado), 3)
        estrategia, explicacao, musicas = resultado
        self.assertEqual(estrategia, "descompressao")
        self.assertTrue(explicacao)
        self.assertEqual(musicas, self.catalogo[:3])
        for indice, musica in enumerate(musicas):
            self.assertIs(musica, self.catalogo[indice])

    def test_limites_ampliam_apenas_o_prefixo_e_mantem_ordem_de_empate(self):
        padrao = self.recomendar(["cansado"], ["calmo"])
        for limite in range(1, 11):
            with self.subTest(limite=limite):
                resultado = self.recomendar(["cansado"], ["calmo"], limite=limite)
                self.assertEqual(resultado[:2], padrao[:2])
                self.assertEqual(resultado[2], self.catalogo[:limite])

    def test_limite_invalido_e_rejeitado_antes_de_consultar_catalogo(self):
        for valor in (None, False, True, 0, -1, 11, 3.0, "3", [], {}):
            with self.subTest(valor=valor), \
                 patch.object(recomendador, "carregar_musicas_usuario") as carregar:
                with self.assertRaisesRegex(ValueError, "inteiro de 1 a 10"):
                    recomendador.recomendar_musicas([], [], limite=valor)
                carregar.assert_not_called()

    def test_validador_retorna_o_inteiro_estrito(self):
        for limite in (1, 3, 10):
            self.assertEqual(recomendador.validar_limite_recomendacoes(limite), limite)

    def test_motivos_preservam_pontuacao_base_e_indice_da_lista_recebida(self):
        selecionadas = self.catalogo[:2]
        motivos = recomendador.explicar_recomendacoes(["cansado"], "descompressao", selecionadas)
        self.assertEqual([motivo["indice_recomendacao"] for motivo in motivos], [1, 2])
        self.assertEqual([motivo["pontuacao"] for motivo in motivos], [5, 5])
        self.assertEqual(motivos[0]["criterios"], [
            {"tipo": "estrategia", "valor": "descompressao", "pontos": 3},
            {"tipo": "emocao_confirmada", "valor": "cansado", "pontos": 2},
        ])
        self.assertIn("cadastro", motivos[0]["explicacao"])
        self.assertIn("confirmada por você", motivos[0]["explicacao"])

    def test_multiplicidade_das_emocoes_confirmadas_preserva_pesos_anteriores(self):
        motivos = recomendador.explicar_recomendacoes(
            ["cansado", "cansado"], "descompressao", self.catalogo[:1],
        )
        self.assertEqual(motivos[0]["pontuacao"], 7)
        self.assertEqual([c["tipo"] for c in motivos[0]["criterios"]],
                         ["estrategia", "emocao_confirmada", "emocao_confirmada"])

    def test_transicao_expoe_categorias_em_ordem_fixa_e_soma_todos_criterios(self):
        ponte = faixa("ponte", sentimentos=["normal", "foco", "reflexivo", "calmo", "cansado"],
                      estrategias=["transicao_emocional", "ativacao_gradual"])
        motivos = recomendador.explicar_recomendacoes(
            ["cansado"], "transicao_emocional", [ponte],
        )
        self.assertEqual(motivos[0]["pontuacao"], 15)
        criterios = motivos[0]["criterios"]
        self.assertEqual([c["valor"] for c in criterios if c["tipo"] == "categoria_ponte"],
                         ["calmo", "reflexivo", "foco", "normal"])
        self.assertEqual(criterios[-1], {
            "tipo": "estrategia_ponte", "valor": "ativacao_gradual", "pontos": 2,
        })
        self.assertEqual(sum(c["pontos"] for c in criterios), motivos[0]["pontuacao"])

    def test_ajustes_positivos_e_negativos_entram_na_mesma_soma_e_ordenacao(self):
        self.catalogo = [
            faixa("base", sentimentos=["cansado"], estrategias=["descompressao"]),
            faixa("ajustada", estrategias=["descompressao"]),
            faixa("reduzida", sentimentos=["cansado"], estrategias=["descompressao"]),
        ]
        ajuste = {"Faixa Inventada ajustada - Artista Fictício": 4,
                  "Faixa Inventada reduzida - Artista Fictício": -2.5}
        estrategia, _, selecionadas = self.recomendar(["cansado"], ["calmo"], ajuste)
        self.assertEqual([f["id"] for f in selecionadas], ["ajustada", "base", "reduzida"])
        motivos = recomendador.explicar_recomendacoes(["cansado"], estrategia, selecionadas, ajuste)
        self.assertEqual([m["pontuacao"] for m in motivos], [7, 5, 2.5])
        self.assertEqual(motivos[0]["criterios"][-1], {"tipo": "ajuste_informado", "pontos": 4})
        self.assertEqual(motivos[-1]["criterios"][-1], {"tipo": "ajuste_informado", "pontos": -2.5})
        for motivo in motivos:
            self.assertEqual(sum(c["pontos"] for c in motivo["criterios"]), motivo["pontuacao"])

    def test_ajuste_zero_nao_cria_criterio_e_pontuacao_nao_positiva_nao_recomenda(self):
        ajuste = {f"Faixa Inventada {indice} - Artista Fictício": -5 for indice in range(12)}
        self.assertEqual(self.recomendar(["cansado"], ["calmo"], ajuste)[2], [])
        motivos = recomendador.explicar_recomendacoes(
            ["cansado"], "descompressao", self.catalogo[:1],
            {"Faixa Inventada 0 - Artista Fictício": 0},
        )
        self.assertNotIn("ajuste_informado", [c["tipo"] for c in motivos[0]["criterios"]])

    def test_explicacao_nao_consulta_ou_reordena_catalogo_nem_modifica_entradas(self):
        selecionadas = [self.catalogo[4], self.catalogo[1]]
        emocoes, ajuste = ["cansado"], {"Faixa Inventada 4 - Artista Fictício": -1}
        antes = deepcopy((selecionadas, emocoes, ajuste))
        with patch.object(recomendador, "carregar_musicas_usuario", side_effect=AssertionError("Sem leitura")), \
             patch.object(recomendador, "carregar_json", side_effect=AssertionError("Sem histórico")):
            motivos = recomendador.explicar_recomendacoes(emocoes, "descompressao", selecionadas, ajuste)
        self.assertEqual([m["pontuacao"] for m in motivos], [4, 5])
        self.assertEqual((selecionadas, emocoes, ajuste), antes)

    def test_desejo_sem_categoria_atual_explana_so_estrategia_cadastrada(self):
        estrategia, _, musicas = self.recomendar([], ["calmo"])
        motivos = recomendador.explicar_recomendacoes([], estrategia, musicas)
        self.assertEqual([m["pontuacao"] for m in motivos], [3, 3, 3])
        for motivo in motivos:
            self.assertEqual(motivo["criterios"], [
                {"tipo": "estrategia", "valor": "descompressao", "pontos": 3},
            ])
            self.assertNotIn("confirmada por você", motivo["explicacao"])

    def test_sem_estrategia_nao_carrega_catalogo_nem_produz_sugestoes_artificiais(self):
        with patch.object(recomendador, "carregar_musicas_usuario") as carregar:
            estrategia, explicacao, musicas = recomendador.recomendar_musicas([], [], limite=10)
        carregar.assert_not_called()
        self.assertIsNone(estrategia)
        self.assertTrue(explicacao)
        self.assertEqual(musicas, [])
        self.assertEqual(recomendador.explicar_recomendacoes([], estrategia, musicas), [])

    def test_sem_criterios_nao_inventa_atributos_a_partir_do_titulo_bpm_ou_bloco_opcional(self):
        musica = {"nome": "Calmo Triste Foco", "artista": "Fictício", "bpm": 70,
                  "caracterizacao": {"estimativas_sistema": [{"atributo": "valencia", "valor": 1}]}}
        motivos = recomendador.explicar_recomendacoes(["calmo"], "descompressao", [musica])
        self.assertEqual(motivos[0]["criterios"], [])
        self.assertEqual(motivos[0]["pontuacao"], 0)
        self.assertIn("suficientes", motivos[0]["explicacao"])

    def test_recomendacao_e_explicacao_preservam_catalogo_e_ajustes_originais(self):
        ajuste = {"Faixa Inventada 0 - Artista Fictício": 7}
        antes = deepcopy((self.catalogo, ajuste))
        estrategia, _, musicas = self.recomendar(["cansado"], ["calmo"], ajuste, limite=10)
        recomendador.explicar_recomendacoes(["cansado"], estrategia, musicas, ajuste)
        self.assertEqual((self.catalogo, ajuste), antes)


if __name__ == "__main__":
    unittest.main()
