"""Caracterizacao opcional e ranking: somente musicas e fontes ficticias."""

import copy
import math
import unittest
from unittest.mock import patch

from core import recomendador
from core.caracterizacao import (
    obter_caracterizacao,
    preparar_musica,
    validar_caracterizacao,
    validar_musica,
)


GRUPOS = (
    "caracteristicas_acusticas", "anotacoes_emocionais", "estimativas_sistema",
)


def legado_ficticio():
    return {
        "id": "faixa_ficticia", "nome": "Faixa Inventada", "artista": "Artista Ficticio",
        "duracao": "3:00", "bpm": 120, "energia": "media", "valencia": "baixa",
        "intensidade": "media", "sentimentos_associados": ["cansado"],
        "contextos": ["relaxar"], "estrategias": ["descompressao"], "tags": ["ficticia"],
        "percepcao_usuario": "Percepcao ficticia", "campo_extra_legado": {"inventado": True},
    }


def bloco(**campos):
    return {"versao_estrutura": 1, **campos}


def escala_numerica(minimo=-1, maximo=1):
    return {"minimo": minimo, "maximo": maximo, "descricao": "Escala ficticia declarada"}


class CaracterizacaoTests(unittest.TestCase):
    def test_catalogo_antigo_valido_nao_e_reescrito_ou_reinterpretado(self):
        musica = legado_ficticio()
        original = copy.deepcopy(musica)
        with patch("core.storage.salvar_json") as gravar:
            validar_musica(musica)
            vista = obter_caracterizacao(musica)
        gravar.assert_not_called()
        self.assertEqual(musica, original)
        self.assertNotIn("caracterizacao", musica)
        self.assertEqual(vista["versao_estrutura"], 1)
        for grupo in GRUPOS:
            self.assertEqual(vista[grupo], [])
        for campo in ("bpm", "energia", "valencia", "sentimentos_associados", "percepcao_usuario"):
            self.assertEqual(vista["procedencia_legado"][campo], {
                "fonte": "desconhecida", "metodo": None, "versao": None,
            })

    def test_preparar_preserva_todos_campos_legados_e_faz_copia_independente(self):
        musica = legado_ficticio()
        preparada = preparar_musica(musica)
        self.assertEqual({k: v for k, v in preparada.items() if k != "caracterizacao"}, musica)
        self.assertEqual(preparar_musica(preparada), preparada)
        preparada["sentimentos_associados"].append("animado")
        preparada["campo_extra_legado"]["inventado"] = False
        self.assertEqual(musica["sentimentos_associados"], ["cansado"])
        self.assertIs(musica["campo_extra_legado"]["inventado"], True)

    def test_atributos_ausentes_e_bloco_nulo_continuam_desconhecidos(self):
        for musica in ({"id": "ficticia"}, {"id": "ficticia", "bpm": None, "caracterizacao": None}):
            with self.subTest(musica=musica):
                antes = copy.deepcopy(musica)
                validar_musica(musica)
                preparada = preparar_musica(musica)
                self.assertEqual(musica, antes)
                self.assertNotIn("energia", preparada)
                self.assertNotIn("valencia", preparada)
                if "bpm" in musica:
                    self.assertIsNone(preparada["bpm"])
                else:
                    self.assertNotIn("bpm", preparada)
                for grupo in GRUPOS:
                    self.assertEqual(preparada["caracterizacao"][grupo], [])

    def test_observacoes_sem_valor_nao_recebem_zero_ou_escala_inventada(self):
        observacoes = [{"atributo": "bpm"}, {"atributo": "bpm", "valor": None}]
        musica = {"caracterizacao": bloco(estimativas_sistema=observacoes)}
        vista = obter_caracterizacao(musica)
        self.assertEqual(musica["caracterizacao"]["estimativas_sistema"], observacoes)
        for observacao in vista["estimativas_sistema"]:
            self.assertIsNone(observacao.get("valor"))
            self.assertIsNone(observacao.get("unidade"))
            self.assertIsNone(observacao.get("escala"))
            self.assertEqual(observacao["fonte"], "desconhecida")
            self.assertIsNone(observacao["metodo"])
            self.assertIsNone(observacao["versao"])

    def test_metadata_documentada_e_procedencia_legada_sao_preservadas(self):
        observacao = {
            "atributo": "bpm", "valor": 123.5, "unidade": "bpm",
            "fonte": "estimador_ficticio", "metodo": "exemplo_sem_audio", "versao": "demo-1",
        }
        musica = legado_ficticio()
        musica["caracterizacao"] = bloco(
            estimativas_sistema=[observacao],
            procedencia_legado={"bpm": {
                "fonte": "documento_ficticio", "metodo": "declaracao_ficticia", "versao": "demo-2",
            }},
        )
        antes = copy.deepcopy(musica)
        preparada = preparar_musica(musica)
        self.assertEqual(preparada["caracterizacao"]["estimativas_sistema"][0], observacao)
        self.assertEqual(preparada["caracterizacao"]["procedencia_legado"]["bpm"],
                         musica["caracterizacao"]["procedencia_legado"]["bpm"])
        preparada["caracterizacao"]["estimativas_sistema"][0]["fonte"] = "outra_fonte_ficticia"
        preparada["caracterizacao"]["procedencia_legado"]["bpm"]["metodo"] = "outro_metodo_ficticio"
        self.assertEqual(musica, antes)

    def test_escala_declarada_nao_e_normalizada_e_zero_real_e_valido(self):
        for valor, escala in ((0, escala_numerica()), (1, escala_numerica(1, 9)),
                              (9, escala_numerica(1, 9)), (5.5, escala_numerica(1, 9))):
            with self.subTest(valor=valor, escala=escala):
                observacao = {"atributo": "valencia", "valor": valor, "escala": escala}
                vista = obter_caracterizacao({"caracterizacao": bloco(anotacoes_emocionais=[observacao])})
                self.assertEqual(vista["anotacoes_emocionais"][0]["valor"], valor)
                self.assertEqual(vista["anotacoes_emocionais"][0]["escala"], escala)

    def test_escala_categorica_explicita_preserva_rotulos(self):
        observacao = {
            "atributo": "ativacao", "valor": "moderada",
            "escala": {"categorias": ["baixa", "moderada", "alta"], "descricao": "Exemplo ficticio"},
        }
        validar_caracterizacao(bloco(anotacoes_emocionais=[observacao]))
        vista = obter_caracterizacao({"caracterizacao": bloco(anotacoes_emocionais=[observacao])})
        self.assertEqual(vista["anotacoes_emocionais"][0]["escala"], observacao["escala"])
        self.assertEqual(vista["anotacoes_emocionais"][0]["valor"], "moderada")

    def test_duas_anotacoes_mesmo_atributo_preservam_fontes_e_escalas(self):
        anotacoes = [
            {"atributo": "valencia", "valor": -0.5, "escala": escala_numerica(), "fonte": "anotador_ficticio_a"},
            {"atributo": "valencia", "valor": 2, "escala": escala_numerica(1, 9), "fonte": "anotador_ficticio_b"},
        ]
        vista = obter_caracterizacao({"caracterizacao": bloco(anotacoes_emocionais=anotacoes)})
        self.assertEqual(len(vista["anotacoes_emocionais"]), 2)
        for original, preservada in zip(anotacoes, vista["anotacoes_emocionais"]):
            for campo in ("atributo", "valor", "escala", "fonte"):
                self.assertEqual(preservada[campo], original[campo])

    def test_bpm_alto_e_anotacao_negativa_nao_geram_emocao_automatica(self):
        musica = legado_ficticio()
        musica["caracterizacao"] = bloco(
            estimativas_sistema=[{"atributo": "bpm", "valor": 195, "unidade": "bpm"}],
            anotacoes_emocionais=[{"atributo": "valencia", "valor": -0.9, "escala": escala_numerica()}],
        )
        preparada = preparar_musica(musica)
        self.assertEqual(preparada["bpm"], 120)
        self.assertEqual(preparada["valencia"], "baixa")
        self.assertEqual(preparada["sentimentos_associados"], ["cansado"])
        self.assertEqual(preparada["caracterizacao"]["caracteristicas_acusticas"], [])
        self.assertNotIn("feedback", preparada)

    def test_campos_legados_sem_escala_nao_recebem_validacao_nova(self):
        musica = legado_ficticio()
        musica.update(bpm=-123, energia="rotulo_legado", valencia=None)
        validar_musica(musica)
        preparada = preparar_musica(musica)
        self.assertEqual(preparada["bpm"], -123)
        self.assertEqual(preparada["energia"], "rotulo_legado")
        self.assertIsNone(preparada["valencia"])

    def test_valores_numericos_invalidos_rejeitados(self):
        casos = [
            ("estimativas_sistema", {"atributo": "bpm", "valor": valor, "unidade": "bpm"})
            for valor in (True, False, 0, -1, "120", math.nan, math.inf, -math.inf)
        ]
        casos += [
            ("anotacoes_emocionais", {"atributo": "valencia", "valor": valor, "escala": escala_numerica()})
            for valor in (True, False, -1.1, 1.1, math.nan, math.inf, "0")
        ]
        for grupo, observacao in casos:
            with self.subTest(grupo=grupo, observacao=observacao):
                with self.assertRaises(ValueError):
                    validar_caracterizacao(bloco(**{grupo: [observacao]}))

    def test_unidades_ausentes_erradas_e_ambiguidade_rejeitadas(self):
        casos = [
            ("caracteristicas_acusticas", {"atributo": "bpm", "valor": 120}),
            ("caracteristicas_acusticas", {"atributo": "bpm", "valor": 120, "unidade": "Hz"}),
            ("caracteristicas_acusticas", {"atributo": "duracao", "valor": 180, "unidade": "min"}),
            ("caracteristicas_acusticas", {"atributo": "duracao", "valor": 0, "unidade": "s"}),
            ("estimativas_sistema", {"atributo": "bpm", "valor": 120, "unidade": "bpm", "escala": escala_numerica(0, 220)}),
            ("anotacoes_emocionais", {"atributo": "valencia", "valor": 0}),
            ("anotacoes_emocionais", {"atributo": "valencia", "valor": 0, "unidade": "pontos", "escala": escala_numerica()}),
        ]
        for grupo, observacao in casos:
            with self.subTest(grupo=grupo, observacao=observacao):
                with self.assertRaises(ValueError):
                    validar_caracterizacao(bloco(**{grupo: [observacao]}))

    def test_escalas_malformadas_e_rotulos_fora_da_escala_rejeitados(self):
        escalas = [
            {}, {"minimo": 0}, {"maximo": 1}, {"minimo": 1, "maximo": 1},
            {"minimo": 2, "maximo": 1}, {"minimo": False, "maximo": 1},
            {"minimo": 0, "maximo": math.inf}, {"minimo": math.nan, "maximo": 1},
            {"minimo": "0", "maximo": 1}, {"minimo": 0, "maximo": 1, "extra": 1},
            {"categorias": []}, {"categorias": ["baixa", "baixa"]},
            {"categorias": ["", "alta"]}, {"categorias": [1, 2]},
            {"categorias": ["baixa"], "minimo": 0, "maximo": 1},
        ]
        for escala in escalas:
            with self.subTest(escala=escala):
                with self.assertRaises(ValueError):
                    validar_caracterizacao(bloco(anotacoes_emocionais=[{
                        "atributo": "valencia", "valor": 0, "escala": escala,
                    }]))
        with self.assertRaises(ValueError):
            validar_caracterizacao(bloco(anotacoes_emocionais=[{
                "atributo": "valencia", "valor": "desconhecido", "escala": {"categorias": ["baixa", "alta"]},
            }]))

    def test_estrutura_versao_e_atributos_invalidos_rejeitados(self):
        casos = [None, [], "bloco", {}, {"versao_estrutura": True},
                 {"versao_estrutura": "1"}, {"versao_estrutura": 2}, bloco(campo_desconhecido=[])]
        for grupo in GRUPOS:
            casos += [bloco(**{grupo: None}), bloco(**{grupo: {}}), bloco(**{grupo: [None]})]
        casos += [
            bloco(caracteristicas_acusticas=[{"atributo": "valencia", "valor": 0, "escala": escala_numerica()}]),
            bloco(anotacoes_emocionais=[{"atributo": "bpm", "valor": 120, "unidade": "bpm"}]),
            bloco(estimativas_sistema=[{"atributo": "danceability", "valor": 0.5, "escala": escala_numerica(0, 1)}]),
            bloco(estimativas_sistema=[{"valor": 120, "unidade": "bpm"}]),
            bloco(estimativas_sistema=[{"atributo": "bpm", "valor": 120, "unidade": "bpm", "campo_extra": True}]),
        ]
        for invalido in casos:
            with self.subTest(bloco=invalido):
                with self.assertRaises(ValueError):
                    validar_caracterizacao(invalido)

    def test_metadata_invalida_rejeitada_sem_adivinhar_procedencia(self):
        for campo in ("fonte", "metodo", "versao"):
            for valor in ("", " ", 1, True, [], {}):
                with self.subTest(campo=campo, valor=valor):
                    with self.assertRaises(ValueError):
                        validar_caracterizacao(bloco(estimativas_sistema=[{
                            "atributo": "bpm", "valor": 120, "unidade": "bpm", campo: valor,
                        }]))
        for procedencia in ([], {"campo_inexistente": {"fonte": "ficticia"}}, {"bpm": None},
                            {"bpm": {"fonte": "ficticia", "extra": 1}}):
            with self.subTest(procedencia=procedencia):
                with self.assertRaises(ValueError):
                    validar_caracterizacao(bloco(procedencia_legado=procedencia))


class RecomendadorCompativelTests(unittest.TestCase):
    def setUp(self):
        self.catalogo = [
            {"id": "a", "nome": "Faixa A", "artista": "Ficticio", "sentimentos_associados": ["cansado"], "estrategias": ["descompressao"]},
            {"id": "b", "nome": "Faixa B", "artista": "Ficticio", "sentimentos_associados": ["cansado"], "estrategias": ["descompressao"]},
            {"id": "c", "nome": "Faixa C", "artista": "Ficticio", "sentimentos_associados": ["calmo"], "estrategias": ["descompressao"]},
            {"id": "d", "nome": "Faixa D", "artista": "Ficticio", "sentimentos_associados": ["cansado"], "estrategias": []},
            {"id": "zero", "nome": "Faixa Zero", "artista": "Ficticio", "sentimentos_associados": [], "estrategias": []},
        ]
        self.enriquecido = []
        for indice, musica in enumerate(self.catalogo):
            nova = copy.deepcopy(musica)
            nova["caracterizacao"] = bloco(
                caracteristicas_acusticas=[{"atributo": "duracao", "valor": 180 + indice, "unidade": "s"}],
                estimativas_sistema=[{"atributo": "bpm", "valor": 190 - 30 * indice, "unidade": "bpm"}],
                anotacoes_emocionais=[{"atributo": "valencia", "valor": -1 + 0.5 * indice, "escala": escala_numerica()}],
            )
            self.enriquecido.append(preparar_musica(nova))

    def executar(self, catalogo, emocoes, desejo=None, ajuste=None):
        with patch.object(recomendador, "carregar_musicas_usuario", return_value=catalogo):
            return recomendador.recomendar_musicas(emocoes, desejo, ajuste)

    def sem_bloco(self, resultado):
        estrategia, explicacao, musicas = resultado
        return estrategia, explicacao, [
            {chave: valor for chave, valor in musica.items() if chave != "caracterizacao"}
            for musica in musicas
        ]

    def test_resultado_conhecido_top_tres_e_ordem_de_empate_preservados(self):
        antigo = self.executar(self.catalogo, ["cansado"], ["calmo"])
        novo = self.executar(self.enriquecido, ["cansado"], ["calmo"])
        self.assertEqual(antigo[0], "descompressao")
        self.assertEqual([musica["id"] for musica in antigo[2]], ["a", "b", "c"])
        self.assertEqual(self.sem_bloco(novo), antigo)
        self.assertEqual(len(novo[2]), 3)

    def test_ajuste_existente_e_estrategias_continuam_com_mesmo_resultado(self):
        casos = [
            (["cansado"], ["calmo"], {"Faixa D - Ficticio": 9}),
            (["cansado"], ["calmo"], {"Faixa A - Ficticio": -20}),
            (["cansado"], ["animado"], None),
            (["raiva"], [], None),
            (["calmo"], ["foco"], None),
        ]
        for emocoes, desejo, ajuste in casos:
            with self.subTest(emocoes=emocoes, desejo=desejo, ajuste=ajuste):
                antigo = self.executar(self.catalogo, emocoes, desejo, ajuste)
                novo = self.executar(self.enriquecido, emocoes, desejo, ajuste)
                self.assertEqual(self.sem_bloco(novo), antigo)
        ajustado = self.executar(self.enriquecido, ["cansado"], ["calmo"], {"Faixa D - Ficticio": 9})
        self.assertEqual([musica["id"] for musica in ajustado[2]], ["d", "a", "b"])

    def test_atributos_novos_nao_criam_pontuacao_nem_leem_feedback_da_sessao(self):
        antes = copy.deepcopy(self.enriquecido)
        with patch.object(recomendador, "carregar_json", side_effect=AssertionError("Nao ler historico")):
            resultado = self.executar(self.enriquecido, ["categoria_ficticia_sem_correspondencia"], [])
        self.assertEqual(resultado[2], [])
        self.assertEqual(self.enriquecido, antes)
        self.assertTrue(all("feedback" not in musica for musica in self.enriquecido))


if __name__ == "__main__":
    unittest.main()
