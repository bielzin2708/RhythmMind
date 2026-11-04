"""Finalidade, contexto e consultas pelo terminal, com dados fictícios temporários."""

from copy import deepcopy
import io
from contextlib import redirect_stdout
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import UUID

import main as cli
from core import sessoes, storage
from tests.apoio_autenticacao import dados_autenticados


RELATO = "  Relato fictício: estou cansado.\n"


class ContextoCliTests(unittest.TestCase):
    def setUp(self):
        self.raiz = self.enterContext(dados_autenticados())
        self.historico = Path(storage.resolver_caminho(storage.ARQ_HISTORICO))

    def capturar(self, funcao, respostas=()):
        saida = io.StringIO()
        with redirect_stdout(saida), patch("builtins.input", side_effect=respostas):
            resultado = funcao()
        return resultado, saida.getvalue()

    def ler(self):
        return storage.carregar_json(str(self.historico), {})

    def unica(self):
        registros = self.ler()
        self.assertEqual(len(registros), 1)
        identificador, registro = next(iter(registros.items()))
        self.assertEqual(UUID(identificador).version, 4)
        return identificador, registro

    def criar(self, *, finalidade=None, contexto=None, data_hora="04/11/2026 10:00:00", feedback=None):
        registro = sessoes.criar_sessao(
            data_hora=data_hora, texto_usuario=RELATO,
            finalidade=finalidade, contexto=contexto,
            analise={"emocoes": ["cansado"], "estado_desejado": ["calmo"]},
            estrategia="descompressao",
            recomendacoes=[{"nome": "Faixa inventada", "artista": "Artista fictício"}],
            feedback=feedback,
        )
        registro["progresso"] = dict.fromkeys(registro["progresso"], True)
        sessoes.salvar_nova_sessao(storage.ARQ_HISTORICO, registro)
        return registro["sessao_id"], deepcopy(registro)

    def test_criacao_coleta_metadados_antes_da_revisao_e_preserva_relato(self):
        _resultado, saida = self.capturar(
            lambda: cli.opcao_registar_estado(coletar_contexto=True),
            [RELATO, "  Desacelerar  ", "  Após estudar  ", "sem categoria", ""],
        )
        identificador, registro = self.unica()
        self.assertEqual(registro["sessao_id"], identificador)
        self.assertEqual(registro["texto_usuario"], RELATO)
        self.assertEqual(registro["finalidade"], "Desacelerar")
        self.assertEqual(registro["contexto"], "Após estudar")
        self.assertEqual(registro["analise"]["emocoes"], [])
        self.assertTrue(all(registro["progresso"].values()))
        self.assertIn("Relato salvo", saida)

    def test_interrupcao_apos_finalidade_permite_completar_sem_perder_primeiro_salvamento(self):
        _resultado, saida = self.capturar(
            lambda: cli.opcao_registar_estado(coletar_contexto=True),
            [RELATO, "Relaxar", EOFError()],
        )
        identificador, inicial = self.unica()
        self.assertIn("Fluxo interrompido", saida)
        self.assertEqual(inicial["finalidade"], "Relaxar")
        self.assertIsNone(inicial["contexto"])
        self.assertFalse(any(inicial["progresso"].values()))
        self.capturar(cli.opcao_registrar_contexto, [identificador, "", "Em casa"])
        _chave, parcial = self.unica()
        self.assertEqual(parcial["finalidade"], "Relaxar")
        self.assertEqual(parcial["contexto"], "Em casa")
        self.assertFalse(any(parcial["progresso"].values()))
        self.capturar(lambda: cli.continuar_sessao(identificador), ["sem categoria", ""])
        _chave, atual = self.unica()
        for campo in ("sessao_id", "data_hora", "texto_usuario"):
            self.assertEqual(atual[campo], inicial[campo])
        self.assertEqual(atual["finalidade"], "Relaxar")
        self.assertEqual(atual["contexto"], "Em casa")
        self.assertTrue(all(atual["progresso"].values()))

    def test_enter_na_criacao_continua_sem_inferir_finalidade_ou_contexto(self):
        self.capturar(
            lambda: cli.opcao_registar_estado(coletar_contexto=True),
            [RELATO, "", "", "sem categoria", ""],
        )
        _identificador, registro = self.unica()
        self.assertIsNone(registro["finalidade"])
        self.assertIsNone(registro["contexto"])
        self.assertTrue(all(registro["progresso"].values()))

    def test_enter_na_edicao_mantem_inclusive_recomendacoes_ja_salvas(self):
        identificador, anterior = self.criar(finalidade="Foco", contexto="Estudando")
        antes = self.historico.read_bytes()
        self.capturar(cli.opcao_registrar_contexto, [identificador, "", ""])
        self.assertEqual(self.historico.read_bytes(), antes)
        self.assertEqual(self.ler()[identificador], anterior)

    def test_apagar_uma_informacao_e_editar_outra_preserva_demais_campos(self):
        identificador, anterior = self.criar(finalidade="Foco", contexto="Estudando")
        self.capturar(cli.opcao_registrar_contexto, [identificador, "-", "Após estudar"])
        esperado = {**anterior, "finalidade": None, "contexto": "Após estudar"}
        self.assertEqual(self.ler()[identificador], esperado)

    def test_limites_invalidos_pedem_nova_resposta_sem_gravar_valores_invalidos(self):
        identificador, _anterior = self.criar()
        _resultado, saida = self.capturar(
            cli.opcao_registrar_contexto,
            [identificador, "x" * 201, "Concentrar", "x" * 501, "Estudando"],
        )
        atual = self.ler()[identificador]
        self.assertEqual(atual["finalidade"], "Concentrar")
        self.assertEqual(atual["contexto"], "Estudando")
        self.assertNotIn("x" * 201, self.historico.read_text(encoding="utf-8"))
        self.assertIn("200", saida)
        self.assertIn("500", saida)

    def test_limites_contam_espacos_antes_de_normalizar_como_na_api(self):
        identificador, _anterior = self.criar()
        _resultado, saida = self.capturar(
            cli.opcao_registrar_contexto,
            [identificador, " " + "x" * 200 + " ", "  Foco  ",
             " " + "y" * 500 + " ", "  Estudando  "],
        )
        atual = self.ler()[identificador]
        self.assertEqual(atual["finalidade"], "Foco")
        self.assertEqual(atual["contexto"], "Estudando")
        self.assertIn("200", saida)
        self.assertIn("500", saida)

    def test_interromper_edicao_conserva_primeira_resposta_e_contexto_anterior(self):
        identificador, anterior = self.criar(finalidade="Foco", contexto="Estudando")
        _resultado, saida = self.capturar(
            cli.opcao_registrar_contexto, [identificador, "Acolher o momento", KeyboardInterrupt()],
        )
        esperado = {**anterior, "finalidade": "Acolher o momento"}
        self.assertEqual(self.ler()[identificador], esperado)
        self.assertIn("informações já salvas", saida)

    def test_cancelar_selecao_ou_interromper_nao_modifica_sessao(self):
        self.criar(finalidade="Foco", contexto="Estudando")
        antes = self.historico.read_bytes()
        for respostas in ([""], [EOFError()]):
            with self.subTest(respostas=respostas):
                self.capturar(cli.opcao_registrar_contexto, respostas)
                self.assertEqual(self.historico.read_bytes(), antes)

    def test_historico_mostra_metadados_e_legado_ausente_sem_escrever(self):
        identificador, _registro = self.criar(finalidade="Descompressão", contexto="Em casa")
        legado = {"texto_usuario": "Relato fictício antigo", "analise": {}, "recomendacoes": []}
        registros = self.ler()
        registros["legado"] = legado
        storage.salvar_json(str(self.historico), registros)
        antes = self.historico.read_bytes()
        _resultado, saida = self.capturar(lambda: cli.opcao_ver_historico(identificador))
        self.assertIn("Finalidade: Descompressão", saida)
        self.assertIn("Contexto: Em casa", saida)
        _resultado, saida = self.capturar(lambda: cli.opcao_ver_historico("legado"))
        self.assertIn("Finalidade: não informada", saida)
        self.assertIn("Contexto: não informado", saida)
        self.assertEqual(self.historico.read_bytes(), antes)

    def test_filtros_combinados_recortam_historico_sem_modificar_arquivo(self):
        esperado, _registro = self.criar(
            finalidade="Descompressão", contexto="Após estudar", feedback={"ajudou": False},
        )
        outro, _registro = self.criar(
            finalidade="Concentrar", contexto="Estudando", feedback={"ajudou": True},
        )
        antes = self.historico.read_bytes()
        _resultado, saida = self.capturar(lambda: cli.opcao_ver_historico(
            data_inicio="2026-11-04", data_fim="2026-11-04",
            finalidade="DESCOMPRESSAO", contexto="APOS", avaliacao="negativo",
        ))
        self.assertIn(esperado, saida)
        self.assertNotIn(outro, saida)
        self.assertEqual(self.historico.read_bytes(), antes)

    def test_filtro_invalido_e_ausencia_de_resultados_sao_distintos_de_historico_vazio(self):
        self.criar(finalidade="Relaxar")
        antes = self.historico.read_bytes()
        _resultado, saida = self.capturar(lambda: cli.opcao_ver_historico(data_inicio="04/11/2026"))
        self.assertIn("Filtro inválido", saida)
        _resultado, saida = self.capturar(lambda: cli.opcao_ver_historico(finalidade="Exemplo sem resultado"))
        self.assertIn("Nenhuma sessão corresponde aos filtros", saida)
        self.assertNotIn("ainda não tem registros", saida)
        self.assertEqual(self.historico.read_bytes(), antes)
        storage.salvar_json(str(self.historico), {})
        _resultado, saida = self.capturar(cli.opcao_ver_historico)
        self.assertIn("ainda não tem registros", saida)

    def test_menu_12_coleta_filtros_e_exibe_sessao_correspondente(self):
        identificador, _registro = self.criar(finalidade="Foco", contexto="Estudando")
        _resultado, saida = self.capturar(cli.main, ["12", "2026-11-04", "", "foco", "", "nao_registrado", "7"])
        self.assertIn(identificador, saida)
        self.assertIn("A encerrar", saida)

    def test_menu_11_registra_metadados_e_menu_1_coleta_antes_da_revisao(self):
        identificador, _registro = self.criar()
        self.capturar(cli.main, ["11", identificador, "Relaxar", "Em casa", "7"])
        self.assertEqual(self.ler()[identificador]["finalidade"], "Relaxar")
        storage.salvar_json(str(self.historico), {})
        self.capturar(cli.main, ["1", RELATO, "Foco", "Estudando", "sem categoria", "", "7"])
        _identificador, registro = self.unica()
        self.assertEqual(registro["finalidade"], "Foco")
        self.assertEqual(registro["contexto"], "Estudando")
        self.assertTrue(all(registro["progresso"].values()))

    def test_interrupcao_ao_informar_filtros_nao_modifica_historico(self):
        self.criar()
        antes = self.historico.read_bytes()
        _resultado, saida = self.capturar(cli.opcao_filtrar_historico, [EOFError()])
        self.assertIn("Consulta interrompida", saida)
        self.assertEqual(self.historico.read_bytes(), antes)


if __name__ == "__main__":
    unittest.main()
