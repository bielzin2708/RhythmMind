"""Recortes do diário com sessões fictícias, sem armazenamento pessoal."""

import copy
from datetime import date
import unittest

from core.feedback import NEGATIVO, NAO_REGISTRADO, POSITIVO
from core.historico import filtrar_historico


class HistoricoFiltrosTests(unittest.TestCase):
    def setUp(self):
        self.historico = {
            "anterior": {
                "data_hora": "03/11/2026 23:59:59", "finalidade": "Acolher o momento",
                "contexto": "Em casa", "feedback": {"ajudou": True},
            },
            "inicio": {
                "data_hora": "04/11/2026 00:00:00", "finalidade": "Concentração",
                "contexto": "Estudando em casa", "feedback": {"ajudou": False},
            },
            "fim": {
                "data_hora": "05/11/2026 23:59:59", "finalidade": "CONCENTRAÇÃO musical",
                "contexto": "Depois da aula", "feedback": None,
            },
            "posterior": {
                "data_hora": "06/11/2026 00:00:00", "finalidade": "Acolher o momento",
                "contexto": "Em casa", "feedback": {"ajudou": True},
            },
            "legado": {
                "texto_usuario": "Relato fictício antigo, sem data nem metadados",
            },
        }

    def test_sem_filtros_preserva_ordem_valores_e_legado_em_novo_mapa(self):
        antes = copy.deepcopy(self.historico)
        filtrado = filtrar_historico(self.historico)
        self.assertIsNot(filtrado, self.historico)
        self.assertEqual(list(filtrado), list(self.historico))
        self.assertEqual(filtrado, antes)
        for identificador in self.historico:
            self.assertIs(filtrado[identificador], self.historico[identificador])
        self.assertEqual(self.historico, antes)

    def test_periodo_inclui_os_dias_inicial_e_final_inteiros(self):
        filtrado = filtrar_historico(
            self.historico, data_inicio="2026-11-04", data_fim="2026-11-05",
        )
        self.assertEqual(list(filtrado), ["inicio", "fim"])

    def test_limites_independentes_e_dia_unico(self):
        casos = (
            ({"data_inicio": "2026-11-05"}, ["fim", "posterior"]),
            ({"data_fim": "2026-11-04"}, ["anterior", "inicio"]),
            ({"data_inicio": "2026-11-04", "data_fim": "2026-11-04"}, ["inicio"]),
        )
        for filtros, esperados in casos:
            with self.subTest(filtros=filtros):
                self.assertEqual(list(filtrar_historico(self.historico, **filtros)), esperados)

    def test_intervalo_invertido_e_validado_mesmo_sem_registros(self):
        for historico in ({}, self.historico):
            with self.subTest(vazio=not historico):
                with self.assertRaisesRegex(ValueError, "data inicial"):
                    filtrar_historico(historico, data_inicio="2026-11-06", data_fim="2026-11-04")

    def test_datas_invalidas_ou_fora_do_formato_sao_rejeitadas(self):
        casos = (
            "", " ", "04/11/2026", "2026-11-4", "20261104", "2026-11-04T00:00:00",
            " 2026-11-04", "2026-11-04 ", "2026-02-29", "2026-13-01", "0000-01-01",
            20261104, True, [], {}, date(2026, 11, 4),
        )
        for campo in ("data_inicio", "data_fim"):
            for valor in casos:
                with self.subTest(campo=campo, valor=valor):
                    with self.assertRaises(ValueError):
                        filtrar_historico({}, **{campo: valor})

    def test_datas_bissextas_validas_sao_aceitas(self):
        historico = {"bissexto": {"data_hora": "29/02/2024 12:00:00"}}
        self.assertEqual(
            filtrar_historico(historico, data_inicio="2024-02-29", data_fim="2024-02-29"),
            historico,
        )

    def test_periodo_usa_data_do_registro_e_nunca_a_chave(self):
        historico = {
            "04/11/2026 12:00:00": {"data_hora": "05/11/2026 12:00:00"},
            "uuid-ficticio": {"data_hora": "04/11/2026 12:00:00"},
            "04/11/2026 13:00:00": {},
        }
        self.assertEqual(list(filtrar_historico(
            historico, data_inicio="2026-11-04", data_fim="2026-11-04",
        )), ["uuid-ficticio"])

    def test_datas_legadas_invalidas_so_sao_excluidas_quando_filtradas(self):
        valores = (None, "", "sem data", "31/02/2026 10:00:00", "04/11/2026", 20261104)
        historico = {
            str(indice): {"data_hora": valor, "finalidade": "Reflexão"}
            for indice, valor in enumerate(valores)
        }
        self.assertEqual(filtrar_historico(historico), historico)
        self.assertEqual(filtrar_historico(historico, finalidade="reflexao"), historico)
        self.assertEqual(filtrar_historico(historico, data_inicio="2026-01-01"), {})

    def test_finalidade_e_contexto_usam_substring_literal_sem_caixa_ou_acentos(self):
        self.assertEqual(
            list(filtrar_historico(self.historico, finalidade="  concentracao  ")),
            ["inicio", "fim"],
        )
        self.assertEqual(
            list(filtrar_historico(self.historico, contexto="CASA")),
            ["anterior", "inicio", "posterior"],
        )
        historico = {"literal": {"contexto": "Faixa [A]+; Straße"}}
        self.assertEqual(filtrar_historico(historico, contexto="[a]+"), historico)
        self.assertEqual(filtrar_historico(historico, contexto="STRASSE"), historico)
        self.assertEqual(filtrar_historico(historico, contexto=".*"), {})

    def test_metadados_ausentes_nulos_vazios_ou_nao_textuais_nao_correspondem(self):
        historico = {"ausente": {}}
        for indice, valor in enumerate((None, "", " ", False, ["reflexao"], {"texto": "reflexao"})):
            historico[str(indice)] = {"finalidade": valor, "contexto": valor}
        self.assertEqual(filtrar_historico(historico, finalidade="reflexao"), {})
        self.assertEqual(filtrar_historico(historico, contexto="reflexao"), {})

    def test_filtros_textuais_invalidos_sao_rejeitados_sem_eco(self):
        for campo in ("finalidade", "contexto"):
            for valor in ("", " \n\t ", "\u0301", False, 1, [], {}):
                with self.subTest(campo=campo, valor=valor):
                    with self.assertRaises(ValueError):
                        filtrar_historico({}, **{campo: valor})

    def test_feedback_ausente_nao_e_convertido_em_negativo(self):
        historico = {
            "positivo": {"feedback": {"ajudou": True}},
            "negativo": {"feedback": {"ajudou": False}},
            "ausente": {}, "nulo": {"feedback": None}, "vazio": {"feedback": {}},
            "nulo_interno": {"feedback": {"ajudou": None}},
            "texto": {"feedback": {"ajudou": "false"}},
            "zero": {"feedback": {"ajudou": 0}}, "um": {"feedback": {"ajudou": 1}},
        }
        self.assertEqual(list(filtrar_historico(historico, avaliacao=POSITIVO)), ["positivo"])
        self.assertEqual(list(filtrar_historico(historico, avaliacao=NEGATIVO)), ["negativo"])
        self.assertEqual(
            list(filtrar_historico(historico, avaliacao=NAO_REGISTRADO)),
            ["ausente", "nulo", "vazio", "nulo_interno", "texto", "zero", "um"],
        )

    def test_avaliacoes_invalidas_sao_rejeitadas(self):
        for valor in ("", "sem_avaliacao", "False", False, 0, [], {}, [POSITIVO]):
            with self.subTest(valor=valor):
                with self.assertRaises(ValueError):
                    filtrar_historico({}, avaliacao=valor)

    def test_combina_todos_os_filtros_por_intersecao_sem_mutar_registros(self):
        antes = copy.deepcopy(self.historico)
        filtrado = filtrar_historico(
            self.historico, data_inicio="2026-11-04", data_fim="2026-11-05",
            finalidade="concentracao", contexto="casa", avaliacao=NEGATIVO,
        )
        self.assertEqual(list(filtrado), ["inicio"])
        self.assertIs(filtrado["inicio"], self.historico["inicio"])
        self.assertEqual(self.historico, antes)

    def test_filtros_sem_correspondencia_e_historico_vazio_retornam_mapa_vazio(self):
        self.assertEqual(filtrar_historico(self.historico, finalidade="Não registrado nas sessões"), {})
        self.assertEqual(filtrar_historico({}, contexto="casa", data_inicio="2026-11-04"), {})


if __name__ == "__main__":
    unittest.main()
