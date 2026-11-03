"""Edição interrompida: respostas fictícias e histórico exclusivamente temporário."""

import copy
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import main as cli
from core import sessoes, storage


class EdicaoProgressivaTests(unittest.TestCase):
    def setUp(self):
        temporario = self.enterContext(tempfile.TemporaryDirectory(prefix="rhythmmind-edicao-"))
        self.arquivo = Path(temporario) / "historico.json"
        self.enterContext(patch.object(cli, "ARQ_HISTORICO", str(self.arquivo)))
        self.registro = sessoes.criar_sessao(
            data_hora="01/01/2000 10:00:00", texto_usuario="Relato fictício",
            analise={"emocoes": ["cansado"], "estado_desejado": ["calmo"]},
            recomendacoes=[
                {"nome": f"Faixa Inventada {indice}", "artista": "Artista Fictício"}
                for indice in range(1, 4)
            ],
            escuta={"faixas": [
                {"indice_recomendacao": 1, "ouvida": True},
                {"indice_recomendacao": 2, "ouvida": False},
            ]},
            feedback={
                "ajudou": True, "motivo": "Motivo fictício anterior",
                "existe_melhoria": True, "melhoria": "Detalhe fictício anterior",
                "coleta_concluida": True, "campo_legado": "preservar",
            },
        )
        self.registro["progresso"] = dict.fromkeys(self.registro["progresso"], True)
        self.chave = self.registro["sessao_id"]
        storage.salvar_json(str(self.arquivo), {self.chave: self.registro})

    def ler(self):
        return storage.carregar_json(str(self.arquivo), {})[self.chave]

    def capturar(self, funcao, respostas):
        saida = io.StringIO()
        with redirect_stdout(saida), patch("builtins.input", side_effect=respostas):
            funcao()
        return saida.getvalue()

    def verificar_demais_campos(self, campo_alterado):
        esperado = copy.deepcopy(self.registro)
        atual = self.ler()
        esperado.pop(campo_alterado)
        atual.pop(campo_alterado)
        self.assertEqual(atual, esperado)
        self.assertEqual(len(storage.carregar_json(str(self.arquivo), {})), 1)

    def test_edicao_feedback_interrompida_preserva_detalhes_anteriores(self):
        saida = self.capturar(cli.opcao_registrar_feedback, [self.chave, "não", KeyboardInterrupt()])
        feedback = self.ler()["feedback"]
        esperado = {**self.registro["feedback"], "ajudou": False, "coleta_concluida": False}
        self.assertEqual(feedback, esperado)
        self.assertIn("interrompido", saida)
        self.verificar_demais_campos("feedback")

    def test_edicao_feedback_salva_motivo_sem_apagar_melhoria_pendente(self):
        self.capturar(cli.opcao_registrar_feedback, [self.chave, "s", "Novo motivo fictício", EOFError()])
        esperado = {
            **self.registro["feedback"], "motivo": "Novo motivo fictício",
            "coleta_concluida": False,
        }
        self.assertEqual(self.ler()["feedback"], esperado)
        self.verificar_demais_campos("feedback")

    def test_enter_na_edicao_feedback_mantem_valores_anteriores(self):
        self.capturar(cli.opcao_registrar_feedback, [self.chave, "", "", "", ""])
        self.assertEqual(self.ler(), self.registro)

    def test_resposta_explicita_sem_melhoria_substitui_detalhe_anterior(self):
        self.capturar(cli.opcao_registrar_feedback, [self.chave, "n", "Novo motivo fictício", "n"])
        esperado = {
            **self.registro["feedback"], "ajudou": False, "motivo": "Novo motivo fictício",
            "existe_melhoria": False, "melhoria": "", "coleta_concluida": True,
        }
        self.assertEqual(self.ler()["feedback"], esperado)

    def test_edicao_escolha_interrompida_preserva_escuta_das_faixas_mantidas(self):
        self.capturar(cli.opcao_registrar_escuta, [self.chave, "1,3", KeyboardInterrupt()])
        self.assertEqual(self.ler()["escuta"], {"faixas": [
            {"indice_recomendacao": 1, "ouvida": True},
            {"indice_recomendacao": 3, "ouvida": None},
        ]})
        self.verificar_demais_campos("escuta")

    def test_enter_mantem_escuta_anterior_e_resposta_explicita_corrige(self):
        self.capturar(cli.opcao_registrar_escuta, [self.chave, "1,2", "", "s"])
        self.assertEqual(self.ler()["escuta"], {"faixas": [
            {"indice_recomendacao": 1, "ouvida": True},
            {"indice_recomendacao": 2, "ouvida": True},
        ]})
        self.verificar_demais_campos("escuta")

    def test_edicao_escuta_aceita_nao_com_acento(self):
        self.capturar(cli.opcao_registrar_escuta, [self.chave, "1,2", "não", ""])
        self.assertEqual(self.ler()["escuta"], {"faixas": [
            {"indice_recomendacao": 1, "ouvida": False},
            {"indice_recomendacao": 2, "ouvida": False},
        ]})
        self.verificar_demais_campos("escuta")

    def test_edicao_escolha_nenhuma_remove_lista_explicitamente(self):
        self.capturar(cli.opcao_registrar_escuta, [self.chave, "nenhuma"])
        self.assertEqual(self.ler()["escuta"], {"faixas": []})
        self.verificar_demais_campos("escuta")

    def test_retomada_pula_respostas_ja_conhecidas_apos_edicao_interrompida(self):
        self.capturar(cli.opcao_registrar_feedback, [self.chave, "n", KeyboardInterrupt()])
        self.capturar(lambda: cli.continuar_sessao(self.chave), [])
        esperado = {**self.registro["feedback"], "ajudou": False}
        self.assertEqual(self.ler()["feedback"], esperado)
        self.verificar_demais_campos("feedback")

    def test_edicao_legada_interrompida_preserva_chave_e_dados(self):
        legado = copy.deepcopy(self.registro)
        del legado["sessao_id"]
        del legado["progresso"]
        self.chave = legado["data_hora"]
        storage.salvar_json(str(self.arquivo), {self.chave: legado})
        self.capturar(cli.opcao_registrar_feedback, [self.chave, "n", EOFError()])
        self.capturar(cli.opcao_registrar_escuta, [self.chave, "1,2", KeyboardInterrupt()])
        esperado = copy.deepcopy(legado)
        esperado["feedback"].update(ajudou=False, coleta_concluida=False)
        self.assertEqual(self.ler(), esperado)
        self.assertEqual(list(storage.carregar_json(str(self.arquivo), {})), [self.chave])


if __name__ == "__main__":
    unittest.main()
