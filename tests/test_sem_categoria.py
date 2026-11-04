"""Revisão explícita sem categoria, com relatos e contas fictícios temporários."""

import io
from contextlib import redirect_stdout
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient

import main as cli
from api import main as api
from core import recomendador, sessoes, storage
from tests.apoio_autenticacao import ClienteAutenticado, dados_autenticados


TEXTO = "  Relato fictício: não estou triste.\n"
TEXTO_RECONHECIDO = "  Relato fictício: estou cansado.\n"
CATALOGO = [
    {"id": "espelho", "nome": "Espelho Inventado", "artista": "Artista Fictício",
     "sentimentos_associados": ["triste"], "estrategias": ["espelhamento"]},
    {"id": "calma", "nome": "Calma Inventada", "artista": "Artista Fictício",
     "sentimentos_associados": ["calmo"], "estrategias": ["descompressao"]},
    {"id": "foco", "nome": "Foco Inventado", "artista": "Artista Fictício",
     "sentimentos_associados": ["foco"], "estrategias": ["foco_cognitivo"]},
    {"id": "energia", "nome": "Energia Inventada", "artista": "Artista Fictício",
     "sentimentos_associados": ["animado"], "estrategias": ["ativacao"]},
]


class SemCategoriaFluxosTests(unittest.TestCase):
    def setUp(self):
        self.raiz = self.enterContext(dados_autenticados())
        storage.salvar_json(storage.ARQ_MUSICAS, CATALOGO)
        self.historico = Path(storage.resolver_caminho(storage.ARQ_HISTORICO))
        self.client = self.enterContext(ClienteAutenticado(
            api.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000),
        ))

    def ler(self):
        return storage.carregar_json(str(self.historico), {})

    def criar(self, texto=TEXTO, **campos):
        resposta = self.client.post("/api/registrar-estado", json={"texto_atual": texto, **campos})
        self.assertEqual(resposta.status_code, 200, resposta.text)
        return resposta.json()

    def retomar(self, identificador, **campos):
        return self.client.post("/api/retomar-sessao", json={"sessao_id": identificador, **campos})

    def capturar_cli(self, funcao, respostas=()):
        saida = io.StringIO()
        with redirect_stdout(saida), patch("builtins.input", side_effect=respostas):
            funcao()
        return saida.getvalue()

    def unica_sessao(self):
        registros = self.ler()
        self.assertEqual(len(registros), 1)
        identificador, registro = next(iter(registros.items()))
        self.assertEqual(UUID(identificador).version, 4)
        self.assertEqual(registro["sessao_id"], identificador)
        return identificador, registro

    def test_api_ausencia_ou_null_continua_pendente_sem_inferir_categoria(self):
        with patch.object(api, "recomendar_musicas") as recomendar:
            for campos in ({}, {"emocoes_confirmadas": None}):
                with self.subTest(campos=campos):
                    resposta = self.criar(texto_desejado="", **campos)
                    registro = self.ler()[resposta["sessao_id"]]
                    self.assertEqual(resposta["emocoes_detectadas"], [])
                    self.assertEqual(registro["analise"]["emocoes"], [])
                    self.assertFalse(registro["progresso"]["emocoes_confirmadas"])
                    self.assertFalse(registro["progresso"]["recomendacoes_geradas"])
                    self.assertIn("emocoes_confirmadas", resposta["pendencias"])
                    self.assertEqual(registro["texto_usuario"], TEXTO)
            recomendar.assert_not_called()

    def test_api_escolha_explicita_sem_desejo_conclui_sem_espelhamento(self):
        resposta = self.criar(emocoes_confirmadas=[], texto_desejado="")
        identificador, registro = self.unica_sessao()
        self.assertEqual(resposta["sessao_id"], identificador)
        self.assertEqual(registro["texto_usuario"], TEXTO)
        self.assertEqual(registro["analise"], {"emocoes": [], "estado_desejado": []})
        self.assertTrue(all(registro["progresso"].values()))
        self.assertEqual(resposta["pendencias"], [])
        self.assertIsNone(registro["estrategia"])
        self.assertTrue(registro["explicacao"].strip())
        self.assertEqual(registro["recomendacoes"], [])
        self.assertIsNone(registro["escuta"])
        self.assertIsNone(registro["feedback"])

    def test_api_escolha_explicita_recusa_rotulos_detectados_sem_completar_desejo(self):
        with patch.object(api, "recomendar_musicas") as recomendar:
            resposta = self.criar(texto=TEXTO_RECONHECIDO, emocoes_confirmadas=[])
            recomendar.assert_not_called()
        registro = self.ler()[resposta["sessao_id"]]
        self.assertEqual(registro["analise"]["emocoes"], [])
        self.assertTrue(registro["progresso"]["emocoes_confirmadas"])
        self.assertFalse(registro["progresso"]["estado_desejado_informado"])
        self.assertFalse(registro["progresso"]["recomendacoes_geradas"])
        self.assertIsNone(registro["texto_desejado"])
        self.assertEqual(registro["texto_usuario"], TEXTO_RECONHECIDO)

    def test_api_retomada_sem_categoria_usa_desejo_calmo_real_e_preserva_identidade(self):
        identificador = self.criar()["sessao_id"]
        anterior = self.ler()[identificador]
        resposta = self.retomar(identificador, emocoes_confirmadas=[], texto_desejado="calmo")
        self.assertEqual(resposta.status_code, 200, resposta.text)
        atual = self.ler()[identificador]
        self.assertEqual(len(self.ler()), 1)
        for campo in ("sessao_id", "data_hora", "texto_usuario"):
            self.assertEqual(atual[campo], anterior[campo])
        self.assertEqual(atual["analise"], {"emocoes": [], "estado_desejado": ["calmo"]})
        self.assertEqual(atual["estrategia"], "descompressao")
        self.assertEqual([m["id"] for m in atual["recomendacoes"]], ["calma"])
        self.assertTrue(all(atual["progresso"].values()))
        self.assertIsNone(atual["escuta"])
        self.assertIsNone(atual["feedback"])

    def test_api_confirmacao_sem_categoria_e_idempotente_antes_do_desejo(self):
        identificador = self.criar(emocoes_confirmadas=[])["sessao_id"]
        antes = self.historico.read_bytes()
        with patch.object(api, "detectar_emocoes_no_texto", side_effect=AssertionError("Não reanalisar")):
            resposta = self.retomar(identificador, emocoes_confirmadas=[])
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertEqual(self.historico.read_bytes(), antes)
        conflito = self.retomar(identificador, emocoes_confirmadas=["triste"])
        self.assertEqual(conflito.status_code, 409)
        self.assertEqual(self.historico.read_bytes(), antes)

    def test_api_retomada_concluida_nao_recalcula_nem_substitui_escolha(self):
        identificador = self.criar(emocoes_confirmadas=[], texto_desejado="")["sessao_id"]
        antes = self.historico.read_bytes()
        with patch.object(api, "recomendar_musicas", side_effect=AssertionError("Não recalcular")):
            for campos in ({}, {"emocoes_confirmadas": None}, {"emocoes_confirmadas": []},
                           {"emocoes_confirmadas": [], "texto_desejado": ""}):
                with self.subTest(campos=campos):
                    resposta = self.retomar(identificador, **campos)
                    self.assertEqual(resposta.status_code, 200, resposta.text)
                    self.assertEqual(self.historico.read_bytes(), antes)
            for campos in ({"emocoes_confirmadas": ["triste"]}, {"texto_desejado": "calmo"}):
                with self.subTest(campos=campos):
                    self.assertEqual(self.retomar(identificador, **campos).status_code, 409)
                    self.assertEqual(self.historico.read_bytes(), antes)

    def test_api_categoria_confirmada_nao_pode_ser_trocada_por_escolha_vazia(self):
        for desejo in (None, "calmo"):
            with self.subTest(desejo=desejo):
                identificador = self.criar(
                    texto=TEXTO_RECONHECIDO,
                    emocoes_confirmadas=["cansado"], texto_desejado=desejo,
                )["sessao_id"]
                antes = self.historico.read_bytes()
                resposta = self.retomar(identificador, emocoes_confirmadas=[])
                self.assertEqual(resposta.status_code, 409)
                self.assertEqual(self.historico.read_bytes(), antes)

    def test_api_itens_vazios_nao_sao_escolha_de_seguir_sem_categoria(self):
        identificador = self.criar()["sessao_id"]
        antes = self.historico.read_bytes()
        for emocoes in ([""], [" "], ["calmo", ""]):
            with self.subTest(emocoes=emocoes):
                self.assertEqual(self.retomar(identificador, emocoes_confirmadas=emocoes).status_code, 422)
                self.assertEqual(self.historico.read_bytes(), antes)

    def test_api_falha_de_recomendacao_conserva_escolha_vazia_para_retomada(self):
        with patch.object(api, "recomendar_musicas", side_effect=RuntimeError("Falha fictícia")):
            resposta = self.client.post("/api/registrar-estado", json={
                "texto_atual": TEXTO, "emocoes_confirmadas": [], "texto_desejado": "",
            })
        self.assertEqual(resposta.status_code, 500)
        identificador, inicial = self.unica_sessao()
        self.assertEqual(resposta.json()["detail"]["sessao_id"], identificador)
        self.assertEqual(inicial["analise"]["emocoes"], [])
        self.assertTrue(inicial["progresso"]["emocoes_confirmadas"])
        self.assertFalse(inicial["progresso"]["recomendacoes_geradas"])
        with patch.object(api, "detectar_emocoes_no_texto", side_effect=AssertionError("Não reanalisar")):
            retomada = self.retomar(identificador)
        self.assertEqual(retomada.status_code, 200, retomada.text)
        atual = self.ler()[identificador]
        self.assertTrue(atual["progresso"]["recomendacoes_geradas"])
        self.assertEqual(atual["sessao_id"], inicial["sessao_id"])
        self.assertEqual(atual["texto_usuario"], TEXTO)
        self.assertIsNone(atual["estrategia"])

    def test_cli_comando_explicito_na_confirmacao_recusa_categorias_detectadas(self):
        self.capturar_cli(cli.opcao_registar_estado, [TEXTO_RECONHECIDO, "  SEM CATEGORIA  ", ""])
        _, registro = self.unica_sessao()
        self.assertEqual(registro["texto_usuario"], TEXTO_RECONHECIDO)
        self.assertEqual(registro["analise"]["emocoes"], [])
        self.assertTrue(all(registro["progresso"].values()))
        self.assertIsNone(registro["estrategia"])
        self.assertEqual(registro["recomendacoes"], [])

    def test_cli_comando_explicito_no_refinamento_nao_exige_categoria_reconhecida(self):
        self.capturar_cli(cli.opcao_registar_estado, [TEXTO, "  sem categoria  ", ""])
        _, registro = self.unica_sessao()
        self.assertEqual(registro["texto_usuario"], TEXTO)
        self.assertEqual(registro["analise"]["emocoes"], [])
        self.assertTrue(all(registro["progresso"].values()))

    def test_cli_pode_seguir_sem_categoria_depois_de_rejeitar_sugestoes(self):
        self.capturar_cli(cli.opcao_registar_estado, [TEXTO_RECONHECIDO, "n", "sem categoria", ""])
        _, registro = self.unica_sessao()
        self.assertEqual(registro["analise"]["emocoes"], [])
        self.assertTrue(registro["progresso"]["emocoes_confirmadas"])

    def test_cli_enter_nao_e_confirmacao_nem_escolha_sem_categoria(self):
        for texto in (TEXTO, TEXTO_RECONHECIDO):
            with self.subTest(texto=texto):
                storage.salvar_json(str(self.historico), {})
                saida = self.capturar_cli(cli.opcao_registar_estado, [texto, "", EOFError()])
                _, registro = self.unica_sessao()
                self.assertFalse(registro["progresso"]["emocoes_confirmadas"])
                self.assertFalse(registro["progresso"]["recomendacoes_geradas"])
                self.assertIn("Fluxo interrompido", saida)

    def test_cli_interrupcao_apos_escolha_vazia_retoma_sem_reanalisar_relato(self):
        saida = self.capturar_cli(cli.opcao_registar_estado, [TEXTO, "sem categoria", EOFError()])
        identificador, inicial = self.unica_sessao()
        self.assertIn("Fluxo interrompido", saida)
        self.assertTrue(inicial["progresso"]["emocoes_confirmadas"])
        self.assertFalse(inicial["progresso"]["estado_desejado_informado"])
        with patch.object(cli, "detectar_emocoes_no_texto", side_effect=AssertionError("Não reanalisar")):
            saida = self.capturar_cli(lambda: cli.continuar_sessao(identificador), [""])
        _, atual = self.unica_sessao()
        for campo in ("sessao_id", "data_hora", "texto_usuario"):
            self.assertEqual(atual[campo], inicial[campo])
        self.assertEqual(atual["analise"]["emocoes"], [])
        self.assertTrue(all(atual["progresso"].values()))
        self.assertIsNone(atual["escuta"])
        self.assertIsNone(atual["feedback"])
        self.assertIn("O relato permanece salvo", saida)

    def test_historico_distingue_pendencia_escolha_e_legado_sem_inventar_padroes(self):
        pendente = sessoes.criar_sessao(data_hora="01/01/2000 10:00:00", texto_usuario=TEXTO)
        explicito = sessoes.criar_sessao(data_hora="01/01/2000 10:00:01", texto_usuario=TEXTO)
        explicito["progresso"] = dict.fromkeys(explicito["progresso"], True)
        conhecido = sessoes.criar_sessao(
            data_hora="01/01/2000 10:00:02", texto_usuario=TEXTO_RECONHECIDO,
            analise={"emocoes": ["cansado"], "estado_desejado": ["calmo"]},
            estrategia="descompressao",
        )
        conhecido["progresso"] = dict.fromkeys(conhecido["progresso"], True)
        legado = {"data_hora": "01/01/2000 09:00:00", "texto_usuario": "Relato fictício antigo",
                  "analise": {"emocoes": [], "estado_desejado": []}, "recomendacoes": []}
        registros = {"pendente": pendente, "explicito": explicito, "conhecido": conhecido, "legado": legado}
        storage.salvar_json(str(self.historico), registros)
        antes = self.historico.read_bytes()
        saida = self.capturar_cli(lambda: cli.opcao_ver_historico("explicito"))
        self.assertIn("Emoções confirmadas: sem categoria (escolha explícita)", saida)
        saida = self.capturar_cli(lambda: cli.opcao_ver_historico("pendente"))
        self.assertIn("Emoções confirmadas: pendentes", saida)
        saida = self.capturar_cli(lambda: cli.opcao_ver_historico("legado"))
        self.assertNotIn("sem categoria (escolha explícita)", saida)
        historico = self.client.get("/api/historico")
        self.assertEqual(historico.status_code, 200)
        self.assertEqual(historico.json()["registros"], registros)
        padroes = self.client.get("/api/padroes")
        self.assertEqual(padroes.status_code, 200)
        self.assertEqual(padroes.json()["emocoes_frequentes"], [["cansado", 1]])
        self.assertEqual(padroes.json()["desejos_frequentes"], [["calmo", 1]])
        self.assertEqual(padroes.json()["estrategias_frequentes"], [["descompressao", 1]])
        self.assertEqual(padroes.json()["avaliacoes_sessoes"]["retornos_nao_registrados"], 4)
        self.assertEqual(self.historico.read_bytes(), antes)

    def test_api_retomada_legada_nao_migra_vazio_para_escolha_explicita(self):
        legado = {"data_hora": "01/01/2000 09:00:00", "texto_usuario": TEXTO,
                  "analise": {"emocoes": [], "estado_desejado": []}, "recomendacoes": []}
        storage.salvar_json(str(self.historico), {"legado": legado})
        antes = self.historico.read_bytes()
        with patch.object(api, "detectar_emocoes_no_texto", side_effect=AssertionError("Não reanalisar")), \
             patch.object(api, "recomendar_musicas", side_effect=AssertionError("Não recalcular")):
            for campos in ({}, {"emocoes_confirmadas": []}):
                with self.subTest(campos=campos):
                    resposta = self.retomar("legado", **campos)
                    self.assertEqual(resposta.status_code, 200, resposta.text)
                    self.assertIsNone(resposta.json()["progresso"])
        self.assertEqual(self.historico.read_bytes(), antes)

    def test_escolha_vazia_exige_autenticacao_e_continua_isolada_por_conta(self):
        identificador = self.criar(emocoes_confirmadas=[])["sessao_id"]
        antes = self.historico.read_bytes()
        anonimo = self.enterContext(TestClient(
            api.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50001),
        ))
        dados = {"sessao_id": identificador, "emocoes_confirmadas": []}
        self.assertEqual(anonimo.post("/api/retomar-sessao", json=dados).status_code, 401)
        credenciais = {"nome_usuario": "outra_conta_ficticia", "senha": "senha-ficticia-outra-123!"}
        self.assertEqual(anonimo.post("/api/auth/registrar", json=credenciais).status_code, 201)
        entrada = anonimo.post("/api/auth/entrar", json=credenciais)
        self.assertEqual(entrada.status_code, 200)
        headers = {"Authorization": "Bearer " + entrada.json()["token_acesso"]}
        self.assertEqual(anonimo.post("/api/retomar-sessao", json=dados, headers=headers).status_code, 404)
        self.assertEqual(anonimo.get("/api/historico", headers=headers).json()["total"], 0)
        self.assertEqual(self.historico.read_bytes(), antes)


class SemCategoriaRecomendadorTests(unittest.TestCase):
    def test_sem_categoria_e_sem_regra_de_desejo_nao_usa_espelhamento(self):
        with patch.object(recomendador, "carregar_musicas_usuario", return_value=CATALOGO):
            for desejo in (None, [], ["feliz"], ["triste"], ["reflexivo"]):
                with self.subTest(desejo=desejo):
                    estrategia, explicacao, musicas = recomendador.recomendar_musicas([], desejo)
                    self.assertIsNone(estrategia)
                    self.assertTrue(explicacao.strip())
                    self.assertEqual(musicas, [])

    def test_sem_categoria_preserva_estrategias_suportadas_pelo_desejo(self):
        with patch.object(recomendador, "carregar_musicas_usuario", return_value=CATALOGO):
            for desejo, esperada, faixa in (
                (["calmo"], "descompressao", "calma"),
                (["foco"], "foco_cognitivo", "foco"),
                (["animado"], "ativacao", "energia"),
            ):
                with self.subTest(desejo=desejo):
                    estrategia, explicacao, musicas = recomendador.recomendar_musicas([], desejo)
                    self.assertEqual(estrategia, esperada)
                    self.assertTrue(explicacao.strip())
                    self.assertEqual([m["id"] for m in musicas], [faixa])

    def test_categoria_atual_preserva_espelhamento_existente(self):
        with patch.object(recomendador, "carregar_musicas_usuario", return_value=CATALOGO):
            estrategia, _explicacao, musicas = recomendador.recomendar_musicas(["triste"], [])
        self.assertEqual(estrategia, "espelhamento")
        self.assertEqual([m["id"] for m in musicas], ["espelho"])


if __name__ == "__main__":
    unittest.main()
