"""Escolha ampliada e motivos persistidos no terminal, com dados fictícios."""

from copy import deepcopy
import io
from contextlib import redirect_stdout
from pathlib import Path
import unittest
from unittest.mock import patch

import main as cli
from core import sessoes, storage
from tests.apoio_autenticacao import dados_autenticados


RELATO = "  Relato fictício: estou cansado.\n"
CATALOGO = [
    {"id": f"ficticia_{indice}", "nome": f"Faixa Inventada {indice}",
     "artista": "Artista Fictício", "estrategias": ["descompressao"],
     "sentimentos_associados": ["cansado"]}
    for indice in range(1, 7)
]


class EscolhaMusicalCliTests(unittest.TestCase):
    def setUp(self):
        self.raiz = self.enterContext(dados_autenticados())
        self.historico = Path(storage.resolver_caminho(storage.ARQ_HISTORICO))
        storage.salvar_json(storage.ARQ_MUSICAS, CATALOGO)

    def capturar(self, funcao, respostas=()):
        saida = io.StringIO()
        with redirect_stdout(saida), patch("builtins.input", side_effect=respostas):
            funcao()
        return saida.getvalue()

    def ler(self):
        return storage.carregar_json(str(self.historico), {})

    def unica(self):
        registros = self.ler()
        self.assertEqual(len(registros), 1)
        return next(iter(registros.items()))

    def pendente(self, *, limite=3):
        registro = sessoes.criar_sessao(
            data_hora="04/11/2026 10:00:00", texto_usuario=RELATO,
            limite_recomendacoes=limite,
        )
        sessoes.salvar_nova_sessao(storage.ARQ_HISTORICO, registro)
        return registro["sessao_id"], deepcopy(registro)

    def concluir(self, *, limite=3):
        self.capturar(
            lambda: cli.opcao_registar_estado(limite_recomendacoes=limite),
            [RELATO, "s", "calmo", "nenhuma", "s", "Exemplo fictício", "n"],
        )
        return self.unica()

    def test_chamada_direta_padrao_preserva_tres_faixas_e_registra_motivos(self):
        with patch.object(cli, "recomendar_musicas", wraps=cli.recomendar_musicas) as recomendar:
            _identificador, registro = self.concluir()
        recomendar.assert_called_once_with(["cansado"], ["calmo"])
        self.assertEqual(registro["limite_recomendacoes"], 3)
        self.assertEqual(registro["recomendacoes"], CATALOGO[:3])
        self.assertEqual(len(registro["motivos_recomendacoes"]), 3)
        self.assertEqual([m["indice_recomendacao"] for m in registro["motivos_recomendacoes"]], [1, 2, 3])

    def test_cinco_sugestoes_permite_escolher_escutar_e_avaliar_indice_cinco(self):
        self.capturar(
            lambda: cli.opcao_registar_estado(limite_recomendacoes=5),
            [RELATO, "s", "calmo", "5", "s", "n", "Exemplo fictício", "n"],
        )
        _identificador, registro = self.unica()
        self.assertEqual(registro["recomendacoes"], CATALOGO[:5])
        self.assertEqual(registro["escuta"], {"faixas": [{"indice_recomendacao": 5, "ouvida": True}]})
        self.assertIs(registro["feedback"]["ajudou"], False)
        self.assertEqual(len(registro["motivos_recomendacoes"]), 5)

    def test_menu_um_coleta_quantidade_depois_do_contexto_antes_da_revisao(self):
        self.capturar(cli.main, [
            "1", RELATO, "Relaxar", "Em casa", "5", "sem categoria", "calmo",
            "nenhuma", "s", "Exemplo fictício", "n", "7",
        ])
        _identificador, registro = self.unica()
        self.assertEqual(registro["texto_usuario"], RELATO)
        self.assertEqual(registro["finalidade"], "Relaxar")
        self.assertEqual(registro["contexto"], "Em casa")
        self.assertEqual(registro["limite_recomendacoes"], 5)
        self.assertEqual(registro["analise"]["emocoes"], [])
        self.assertEqual(registro["recomendacoes"], CATALOGO[:5])

    def test_menu_treze_altera_apenas_quantidade_em_sessao_pendente(self):
        identificador, inicial = self.pendente()
        self.capturar(cli.main, ["13", identificador, "5", "7"])
        self.assertEqual(self.ler()[identificador], {**inicial, "limite_recomendacoes": 5})

    def test_quantidade_invalida_pede_nova_resposta_sem_aceitar_coercao(self):
        identificador, _inicial = self.pendente()
        saida = self.capturar(cli.opcao_quantidade_sugestoes, [
            identificador, "0", "11", "3.0", "true", "+3", "5",
        ])
        self.assertEqual(self.ler()[identificador]["limite_recomendacoes"], 5)
        self.assertFalse(self.ler()[identificador]["progresso"]["recomendacoes_geradas"])
        self.assertIn("inteiro", saida)

    def test_enter_na_quantidade_mantem_valor_anterior_sem_escrever(self):
        identificador, _inicial = self.pendente(limite=5)
        antes = self.historico.read_bytes()
        self.capturar(cli.opcao_quantidade_sugestoes, [identificador, ""])
        self.assertEqual(self.historico.read_bytes(), antes)

    def test_sessao_concluida_recusa_alteracao_sem_recalcular_nem_reexplicar(self):
        identificador, _registro = self.concluir(limite=5)
        antes = self.historico.read_bytes()
        with patch.object(cli, "recomendar_musicas", side_effect=AssertionError("Não recalcular")), \
             patch.object(cli, "explicar_recomendacoes", side_effect=AssertionError("Não reexplicar")):
            saida = self.capturar(cli.opcao_quantidade_sugestoes, [identificador])
        self.assertIn("não pode ser alterada", saida)
        self.assertEqual(self.historico.read_bytes(), antes)

    def test_interrupcao_apos_quantidade_conserva_metadados_e_retomada_usa_limite(self):
        saida = self.capturar(
            lambda: cli.opcao_registar_estado(coletar_contexto=True),
            [RELATO, "Relaxar", "Em casa", "5", EOFError()],
        )
        identificador, inicial = self.unica()
        self.assertIn("Fluxo interrompido", saida)
        self.assertEqual(inicial["limite_recomendacoes"], 5)
        self.assertEqual(inicial["finalidade"], "Relaxar")
        self.assertEqual(inicial["contexto"], "Em casa")
        self.assertFalse(inicial["progresso"]["recomendacoes_geradas"])
        self.capturar(lambda: cli.continuar_sessao(identificador), [
            "s", "calmo", "nenhuma", "s", "Exemplo fictício", "n",
        ])
        _identificador, atual = self.unica()
        self.assertEqual(atual["sessao_id"], inicial["sessao_id"])
        self.assertEqual(atual["data_hora"], inicial["data_hora"])
        self.assertEqual(atual["texto_usuario"], RELATO)
        self.assertEqual(atual["recomendacoes"], CATALOGO[:5])

    def test_lista_motivos_limite_e_progresso_sao_salvos_na_mesma_etapa(self):
        gravacoes = []
        gravar = cli._gravar_etapa_cli

        def acompanhar(identificador, **campos):
            if "recomendacoes" in campos:
                gravacoes.append(deepcopy(campos))
            return gravar(identificador, **campos)

        with patch.object(cli, "_gravar_etapa_cli", side_effect=acompanhar):
            self.capturar(
                lambda: cli.opcao_registar_estado(limite_recomendacoes=5),
                [RELATO, "s", "calmo", EOFError()],
            )
        self.assertEqual(len(gravacoes), 1)
        etapa = gravacoes[0]
        self.assertEqual(etapa["recomendacoes"], CATALOGO[:5])
        self.assertEqual(etapa["limite_recomendacoes"], 5)
        self.assertEqual(len(etapa["motivos_recomendacoes"]), 5)
        self.assertTrue(etapa["progresso"]["recomendacoes_geradas"])

    def test_retomada_conserva_motivos_mesmo_depois_de_alterar_catalogo(self):
        identificador, inicial = self.concluir(limite=5)
        storage.salvar_json(storage.ARQ_MUSICAS, [])
        antes = self.historico.read_bytes()
        with patch.object(cli, "recomendar_musicas", side_effect=AssertionError("Não recalcular")), \
             patch.object(cli, "explicar_recomendacoes", side_effect=AssertionError("Não reexplicar")):
            saida = self.capturar(lambda: cli.continuar_sessao(identificador))
        for motivo in inicial["motivos_recomendacoes"]:
            self.assertIn(motivo["explicacao"], saida)
        self.assertEqual(self.historico.read_bytes(), antes)

    def test_legado_exibe_ausencia_de_motivos_sem_recalcular_ou_migrar(self):
        legado = {
            "data_hora": "01/01/2000 10:00:00", "texto_usuario": "Relato fictício antigo",
            "analise": {"emocoes": ["cansado"], "estado_desejado": ["calmo"]},
            "recomendacoes": CATALOGO[:1], "escuta": {"faixas": []},
            "feedback": {"ajudou": True, "motivo": "Exemplo fictício", "coleta_concluida": True},
        }
        storage.salvar_json(str(self.historico), {"legado": legado})
        antes = self.historico.read_bytes()
        with patch.object(cli, "explicar_recomendacoes", side_effect=AssertionError("Não reexplicar")), \
             patch.object(cli, "recomendar_musicas", side_effect=AssertionError("Não recalcular")):
            for funcao, respostas in (
                (lambda: cli.continuar_sessao("legado"), ()),
                (lambda: cli.opcao_ver_historico("legado"), ()),
                (cli.opcao_registrar_escuta, ("legado", "")),
            ):
                with self.subTest(funcao=funcao):
                    saida = self.capturar(funcao, respostas)
                    self.assertIn("Motivos por faixa não registrados", saida)
                    self.assertEqual(self.historico.read_bytes(), antes)

    def test_historico_e_edicao_de_escuta_exibem_motivos_salvos(self):
        identificador, registro = self.concluir(limite=5)
        antes = self.historico.read_bytes()
        for funcao, respostas in (
            (lambda: cli.opcao_ver_historico(identificador), ()),
            (cli.opcao_registrar_escuta, (identificador, "")),
        ):
            with self.subTest(funcao=funcao):
                saida = self.capturar(funcao, respostas)
                for motivo in registro["motivos_recomendacoes"]:
                    self.assertIn(motivo["explicacao"], saida)
                self.assertNotIn("pontuacao", saida)
                self.assertEqual(self.historico.read_bytes(), antes)

    def test_cancelamento_ou_interrupcao_da_configuracao_nao_altera_quantidade(self):
        identificador, _inicial = self.pendente(limite=5)
        antes = self.historico.read_bytes()
        for respostas in ([""], [identificador, EOFError()]):
            with self.subTest(respostas=respostas):
                self.capturar(cli.opcao_quantidade_sugestoes, respostas)
                self.assertEqual(self.historico.read_bytes(), antes)


if __name__ == "__main__":
    unittest.main()
