"""Salvamento progressivo: exemplos fictícios e arquivo temporário compartilhado."""

import copy
import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

import main as cli
from api import main as api
from api.desenvolvimento import dados_ficticios_temporarios
from core import sessoes, storage


TEXTO = "  Relato fictício: estou cansado.\n"


class SalvamentoProgressivoTests(unittest.TestCase):
    def setUp(self):
        self.raiz = self.enterContext(dados_ficticios_temporarios())
        self.arquivo = Path(api.ARQ_HISTORICO).resolve()
        self.client = self.enterContext(TestClient(
            api.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)
        ))

    def ler(self):
        return storage.carregar_json(str(self.arquivo), {})

    def capturar(self, funcao, respostas):
        saida = io.StringIO()
        with redirect_stdout(saida), patch("builtins.input", side_effect=respostas):
            funcao()
        return saida.getvalue()

    def criar_api(self, **campos):
        return self.client.post("/api/registrar-estado", json={"texto_atual": TEXTO, **campos})

    def completa_api(self):
        resposta = self.criar_api(emocoes_confirmadas=["cansado"], texto_desejado="calmo")
        self.assertEqual(resposta.status_code, 200, resposta.text)
        return resposta.json()["sessao_id"]

    def retomar_api(self, identificador, **campos):
        return self.client.post("/api/retomar-sessao", json={"sessao_id": identificador, **campos})

    def unica(self):
        registros = self.ler()
        self.assertEqual(len(registros), 1)
        identificador = next(iter(registros))
        return identificador, registros[identificador]

    def test_cli_preserva_relato_sem_recomendacoes(self):
        with patch.object(cli, "recomendar_musicas", return_value=("descompressao", "Exemplo", [])):
            saida = self.capturar(cli.opcao_registar_estado, [TEXTO, "s", "calmo"])
        identificador, registro = self.unica()
        self.assertEqual(UUID(identificador).version, 4)
        self.assertEqual(registro["texto_usuario"], TEXTO)
        self.assertIsNone(registro["escuta"])
        self.assertIsNone(registro["feedback"])
        self.assertEqual(registro["recomendacoes"], [])
        self.assertTrue(registro["progresso"]["recomendacoes_geradas"])
        self.assertIn("O relato permanece salvo", saida)

    def test_api_preserva_relato_sem_recomendacoes(self):
        with patch.object(api, "recomendar_musicas", return_value=("descompressao", "Exemplo", [])):
            resposta = self.criar_api(emocoes_confirmadas=["cansado"], texto_desejado="calmo")
        self.assertEqual(resposta.status_code, 200)
        identificador, registro = self.unica()
        self.assertEqual(resposta.json()["sessao_id"], identificador)
        self.assertEqual(registro["texto_usuario"], TEXTO)
        self.assertEqual(registro["recomendacoes"], [])
        self.assertIsNone(registro["feedback"])
        self.assertIsNone(registro["escuta"])

    def test_interrupcao_antes_da_analise_ja_encontra_primeiro_salvamento(self):
        def interromper(_texto):
            identificador, registro = self.unica()
            self.assertEqual(registro["texto_usuario"], TEXTO)
            self.assertEqual(registro["sessao_id"], identificador)
            self.assertEqual(registro["analise"]["emocoes"], [])
            self.assertFalse(registro["progresso"]["emocoes_confirmadas"])
            raise KeyboardInterrupt()

        with patch.object(cli, "detectar_emocoes_no_texto", side_effect=interromper):
            saida = self.capturar(cli.opcao_registar_estado, [TEXTO])
        _, registro = self.unica()
        self.assertIsNone(registro["texto_desejado"])
        self.assertIsNone(registro["feedback"])
        self.assertIsNone(registro["escuta"])
        self.assertIn("Fluxo interrompido", saida)

    def test_api_falha_na_analise_informa_id_do_relato_ja_salvo(self):
        with patch.object(api, "detectar_emocoes_no_texto", side_effect=RuntimeError("falha fictícia")):
            resposta = self.criar_api()
        self.assertEqual(resposta.status_code, 500)
        identificador, registro = self.unica()
        self.assertEqual(resposta.json()["detail"]["sessao_id"], identificador)
        self.assertTrue(resposta.json()["detail"]["relato_salvo"])
        self.assertEqual(registro["texto_usuario"], TEXTO)
        self.assertEqual(registro["analise"]["emocoes"], [])

    def test_api_falha_na_recomendacao_preserva_etapas_e_permite_retomar(self):
        with patch.object(api, "recomendar_musicas", side_effect=RuntimeError("falha fictícia")):
            resposta = self.criar_api(emocoes_confirmadas=["cansado"], texto_desejado="calmo")
        self.assertEqual(resposta.status_code, 500)
        identificador, anterior = self.unica()
        self.assertTrue(anterior["progresso"]["emocoes_confirmadas"])
        self.assertFalse(anterior["progresso"]["recomendacoes_geradas"])
        resposta = self.retomar_api(identificador)
        self.assertEqual(resposta.status_code, 200)
        atual = self.ler()[identificador]
        self.assertTrue(atual["progresso"]["recomendacoes_geradas"])
        self.assertEqual(atual["data_hora"], anterior["data_hora"])
        self.assertEqual(atual["texto_usuario"], TEXTO)
        self.assertEqual(len(self.ler()), 1)

    def test_ausencia_de_confirmacao_nao_e_preenchida_pela_deteccao(self):
        resposta = self.criar_api()
        self.assertEqual(resposta.status_code, 200)
        corpo = resposta.json()
        self.assertIn("cansado", corpo["emocoes_detectadas"])
        self.assertEqual(corpo["emocoes_atuais"], [])
        _, registro = self.unica()
        self.assertEqual(registro["analise"]["emocoes"], [])
        self.assertFalse(registro["progresso"]["emocoes_confirmadas"])
        self.assertIsNone(registro["texto_desejado"])
        self.assertFalse(registro["progresso"]["recomendacoes_geradas"])
        saida = self.capturar(cli.opcao_ver_historico, [])
        self.assertIn("Estado desejado: pendente", saida)
        self.assertIn("Músicas recomendadas: pendentes", saida)
        padroes = self.client.get("/api/padroes").json()
        self.assertEqual(padroes["emocoes_frequentes"], [])
        self.assertEqual(padroes["avaliacoes_sessoes"]["sessoes_avaliadas"], 0)

    def test_atualizacao_progressiva_preserva_uuid_criacao_e_texto(self):
        with patch.object(sessoes, "uuid4", wraps=uuid4) as gerador:
            resposta = self.criar_api()
            identificador = resposta.json()["sessao_id"]
            inicial = copy.deepcopy(self.ler()[identificador])
            resposta = self.retomar_api(identificador, emocoes_confirmadas=["cansado"])
            self.assertEqual(resposta.status_code, 200)
            self.assertFalse(resposta.json()["progresso"]["estado_desejado_informado"])
            resposta = self.retomar_api(identificador, texto_desejado="")
            self.assertEqual(resposta.status_code, 200)
            self.assertTrue(resposta.json()["progresso"]["recomendacoes_geradas"])
            self.assertEqual(gerador.call_count, 1)
        atual = self.ler()[identificador]
        for campo in ("sessao_id", "data_hora", "texto_usuario"):
            self.assertEqual(atual[campo], inicial[campo])
        self.assertEqual(atual["analise"]["estado_desejado"], [])
        self.assertEqual(len(self.ler()), 1)

    def test_releitura_em_novo_processo_e_novo_cliente_sobre_mesmo_arquivo(self):
        self.capturar(cli.opcao_registar_estado, [TEXTO, KeyboardInterrupt()])
        identificador, inicial = self.unica()
        programa = (
            "import json,sys; "
            "dados=json.load(open(sys.argv[1],encoding='utf-8')); "
            "print(json.dumps(dados,ensure_ascii=True))"
        )
        processo = subprocess.run(
            [sys.executable, "-B", "-c", programa, str(self.arquivo)],
            capture_output=True, text=True, check=True,
        )
        self.assertEqual(json.loads(processo.stdout)[identificador], inicial)
        with TestClient(api.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50001)) as novo:
            resposta = novo.post("/api/retomar-sessao", json={
                "sessao_id": identificador, "emocoes_confirmadas": ["cansado"],
                "texto_desejado": "calmo",
            })
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json()["sessao_id"], identificador)
        self.assertEqual(len(self.ler()), 1)
        self.assertEqual(self.ler()[identificador]["texto_usuario"], TEXTO)

    def test_retomada_preserva_feedback_e_escuta_sem_recalcular_sugestoes(self):
        identificador = self.completa_api()
        faixas = [{"indice_recomendacao": 1, "ouvida": True}]
        self.assertEqual(self.client.post("/api/escuta", json={
            "sessao_id": identificador, "faixas": faixas,
        }).status_code, 200)
        self.assertEqual(self.client.post("/api/feedback", json={
            "sessao_id": identificador, "ajudou": False, "motivo": "Exemplo fictício",
        }).status_code, 200)
        antes = self.arquivo.read_bytes()
        with patch.object(api, "recomendar_musicas", side_effect=AssertionError("Não recalcular")):
            self.assertEqual(self.retomar_api(identificador).status_code, 200)
        with patch.object(cli, "recomendar_musicas", side_effect=AssertionError("Não recalcular")):
            saida = self.capturar(lambda: cli.continuar_sessao(identificador), [])
        self.assertNotIn("Não foi possível", saida)
        self.assertEqual(self.arquivo.read_bytes(), antes)

    def test_interrupcao_apos_escolha_preserva_faixa_com_escuta_pendente(self):
        self.capturar(cli.opcao_registar_estado, [TEXTO, "s", "calmo", "1", KeyboardInterrupt()])
        identificador, registro = self.unica()
        self.assertEqual(registro["escuta"], {
            "faixas": [{"indice_recomendacao": 1, "ouvida": None}],
        })
        self.assertIsNone(registro["feedback"])
        self.capturar(lambda: cli.continuar_sessao(identificador), ["s", "s", "Motivo fictício", "n"])
        atual = self.ler()[identificador]
        self.assertIs(atual["escuta"]["faixas"][0]["ouvida"], True)
        self.assertIs(atual["feedback"]["ajudou"], True)
        self.assertEqual(len(self.ler()), 1)

    def test_feedback_parcial_retoma_sem_perguntar_novamente_a_avaliacao(self):
        self.capturar(cli.opcao_registar_estado, [
            TEXTO, "s", "calmo", "nenhuma", "n", KeyboardInterrupt(),
        ])
        identificador, registro = self.unica()
        self.assertIs(registro["feedback"]["ajudou"], False)
        self.assertIsNone(registro["feedback"]["existe_melhoria"])
        self.assertFalse(registro["feedback"]["coleta_concluida"])
        self.capturar(lambda: cli.continuar_sessao(identificador), ["Motivo fictício", "n"])
        atual = self.ler()[identificador]
        self.assertIs(atual["feedback"]["ajudou"], False)
        self.assertEqual(atual["feedback"]["motivo"], "Motivo fictício")
        self.assertTrue(atual["feedback"]["coleta_concluida"])
        self.assertEqual(atual["escuta"], {"faixas": []})

    def test_feedback_retoma_detalhe_de_melhoria_preservando_respostas(self):
        self.capturar(cli.opcao_registar_estado, [
            TEXTO, "s", "calmo", "nenhuma", "s", "Motivo fictício", "s", EOFError(),
        ])
        identificador, registro = self.unica()
        self.assertTrue(registro["feedback"]["existe_melhoria"])
        self.capturar(lambda: cli.continuar_sessao(identificador), ["Detalhe fictício"])
        atual = self.ler()[identificador]
        self.assertEqual(atual["feedback"]["motivo"], "Motivo fictício")
        self.assertEqual(atual["feedback"]["melhoria"], "Detalhe fictício")
        self.assertTrue(atual["feedback"]["coleta_concluida"])

    def test_falha_primeira_gravacao_cli_nao_anuncia_sucesso(self):
        antes = self.arquivo.read_bytes()
        with patch.object(storage.os, "replace", side_effect=OSError("falha fictícia")):
            saida = self.capturar(cli.opcao_registar_estado, [TEXTO])
        self.assertIn("Falha ao salvar o relato", saida)
        self.assertNotIn("Relato salvo.", saida)
        self.assertNotIn("Etapas informadas salvas", saida)
        self.assertEqual(self.arquivo.read_bytes(), antes)

    def test_falha_primeira_gravacao_api_retorna_503_sem_sucesso(self):
        antes = self.arquivo.read_bytes()
        with patch.object(storage.os, "replace", side_effect=OSError("falha fictícia")):
            resposta = self.criar_api()
        self.assertEqual(resposta.status_code, 503)
        self.assertFalse(resposta.json()["detail"]["relato_salvo"])
        self.assertEqual(self.arquivo.read_bytes(), antes)

    def test_falha_posterior_cli_preserva_checkpoint_e_nao_anuncia_conclusao(self):
        substituir = storage.os.replace
        chamadas = 0

        def falhar_na_terceira(origem, destino):
            nonlocal chamadas
            chamadas += 1
            if chamadas == 3:
                raise OSError("falha fictícia")
            return substituir(origem, destino)

        with patch.object(storage.os, "replace", side_effect=falhar_na_terceira):
            saida = self.capturar(cli.opcao_registar_estado, [TEXTO, "s", "calmo"])
        _, registro = self.unica()
        self.assertEqual(registro["texto_usuario"], TEXTO)
        self.assertTrue(registro["progresso"]["emocoes_confirmadas"])
        self.assertIsNone(registro["texto_desejado"])
        self.assertIn("Falha ao salvar etapa", saida)
        self.assertNotIn("Etapas informadas salvas", saida)

    def test_falha_na_atualizacao_api_preserva_arquivo_e_retorna_503(self):
        identificador = self.completa_api()
        antes = self.arquivo.read_bytes()
        for rota, campos in (
            ("/api/feedback", {"ajudou": True}),
            ("/api/escuta", {"faixas": []}),
        ):
            with self.subTest(rota=rota):
                with patch.object(storage.os, "replace", side_effect=OSError("falha fictícia")):
                    resposta = self.client.post(rota, json={"sessao_id": identificador, **campos})
                self.assertEqual(resposta.status_code, 503)
                self.assertTrue(resposta.json()["detail"]["relato_salvo"])
                self.assertNotIn("status", resposta.json())
                self.assertEqual(self.arquivo.read_bytes(), antes)

    def test_falha_durante_serializacao_nao_trunca_checkpoint(self):
        identificador = self.completa_api()
        antes = self.arquivo.read_bytes()

        def escrever_e_falhar(dados, arquivo, **opcoes):
            arquivo.write('{"gravacao_incompleta":')
            raise OSError("falha fictícia durante escrita")

        with patch.object(storage.json, "dump", side_effect=escrever_e_falhar):
            resposta = self.client.post("/api/feedback", json={
                "sessao_id": identificador, "ajudou": True,
            })
        self.assertEqual(resposta.status_code, 503)
        self.assertEqual(self.arquivo.read_bytes(), antes)
        self.assertEqual(list(self.arquivo.parent.glob(".rhythmmind-*.tmp")), [])

    def test_historico_invalido_nao_e_substituido_por_arquivo_vazio(self):
        self.arquivo.write_text("{arquivo_ficticio_invalido", encoding="utf-8")
        antes = self.arquivo.read_bytes()
        resposta = self.criar_api()
        self.assertEqual(resposta.status_code, 503)
        self.assertEqual(self.arquivo.read_bytes(), antes)

    def test_relato_vazio_rejeitado_sem_criar_sessao(self):
        antes = self.arquivo.read_bytes()
        resposta = self.client.post("/api/registrar-estado", json={"texto_atual": "  \n "})
        self.assertEqual(resposta.status_code, 422)
        self.assertEqual(self.arquivo.read_bytes(), antes)

    def test_retomada_inexistente_e_mudanca_de_relato_nao_gravam(self):
        identificador = self.completa_api()
        antes = self.arquivo.read_bytes()
        self.assertEqual(self.retomar_api("inexistente").status_code, 404)
        self.assertEqual(self.retomar_api(identificador, texto_atual="Outro relato").status_code, 422)
        self.assertEqual(self.arquivo.read_bytes(), antes)

    def test_legado_retomado_sem_migrar_ou_criar_uuid(self):
        legado = {
            "data_hora": "01/01/2000 10:00:00", "texto_usuario": "Exemplo legado fictício",
            "analise": {"emocoes": ["cansado"], "estado_desejado": []},
            "estrategia": "espelhamento",
            "recomendacoes": [{"nome": "Faixa Inventada A", "artista": "Artista Fictício"}],
            "escuta": {"faixas": []},
            "feedback": {"ajudou": True, "motivo": "Exemplo fictício"},
        }
        chave = legado["data_hora"]
        storage.salvar_json(str(self.arquivo), {chave: legado})
        antes = self.arquivo.read_bytes()
        with patch.object(sessoes, "uuid4", side_effect=AssertionError("Não migrar")):
            resposta = self.retomar_api(chave)
            self.assertEqual(resposta.status_code, 200)
            self.capturar(lambda: cli.continuar_sessao(chave), [])
        self.assertEqual(self.arquivo.read_bytes(), antes)
        self.assertEqual(self.ler()[chave], legado)

    def test_api_feedback_omitido_preserva_detalhes_anteriores(self):
        identificador = self.completa_api()
        self.client.post("/api/feedback", json={
            "sessao_id": identificador, "ajudou": True,
            "motivo": "Motivo fictício", "melhoria": "Melhoria fictícia",
        })
        resposta = self.client.post("/api/feedback", json={
            "sessao_id": identificador, "ajudou": False,
        })
        self.assertEqual(resposta.status_code, 200)
        feedback = self.ler()[identificador]["feedback"]
        self.assertEqual(feedback["motivo"], "Motivo fictício")
        self.assertEqual(feedback["melhoria"], "Melhoria fictícia")
        self.assertIs(feedback["ajudou"], False)

    def test_atualizacao_http_nao_conclui_detalhes_pendentes_do_terminal(self):
        self.capturar(cli.opcao_registar_estado, [
            TEXTO, "s", "calmo", "nenhuma", "n", KeyboardInterrupt(),
        ])
        identificador, _ = self.unica()
        resposta = self.client.post("/api/feedback", json={
            "sessao_id": identificador, "ajudou": True,
        })
        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(self.ler()[identificador]["feedback"]["coleta_concluida"])
        self.capturar(lambda: cli.continuar_sessao(identificador), ["Motivo fictício", "n"])
        feedback = self.ler()[identificador]["feedback"]
        self.assertIs(feedback["ajudou"], True)
        self.assertEqual(feedback["motivo"], "Motivo fictício")
        self.assertTrue(feedback["coleta_concluida"])

    def test_menu_de_retomada_e_protecao_local_da_nova_rota(self):
        with patch.object(cli, "opcao_retomar_sessao") as retomar:
            self.capturar(cli.main, ["10", "7"])
        retomar.assert_called_once_with()
        with patch.object(api.app.state, "diretorio_desenvolvimento", None):
            self.assertEqual(self.retomar_api("ficticio").status_code, 503)


if __name__ == "__main__":
    unittest.main()
