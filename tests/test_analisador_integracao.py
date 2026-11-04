"""Regressoes do analisador nos fluxos existentes, com dados ficticios temporarios."""

import copy
import csv
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient as ClienteSemCredencial

import cadastrar_em_lote as csv_importador
import importar_lote_classificado as json_importador
import main as cli
from api import main as api
from core import sessoes, storage
from tests.apoio_autenticacao import ClienteAutenticado, dados_autenticados


DICIONARIO = json.loads(
    (Path(__file__).resolve().parents[1] / "data" / "dicionario_emocional.json").read_text(encoding="utf-8")
)


class AnalisadorIntegracaoTests(unittest.TestCase):
    def setUp(self):
        self.raiz = self.enterContext(dados_autenticados())
        storage.salvar_json(storage.ARQ_DICIONARIO, copy.deepcopy(DICIONARIO))
        self.historico = Path(storage.resolver_caminho(storage.ARQ_HISTORICO))
        self.catalogo = Path(storage.resolver_caminho(storage.ARQ_MUSICAS))
        self.client = self.enterContext(ClienteAutenticado(
            api.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000),
        ))

    def capturar_cli(self, funcao, respostas):
        saida = io.StringIO()
        with redirect_stdout(saida), patch("builtins.input", side_effect=respostas):
            resultado = funcao()
        return resultado, saida.getvalue()

    def unica_sessao(self):
        registros = storage.carregar_json(str(self.historico), {})
        self.assertEqual(len(registros), 1)
        identificador, registro = next(iter(registros.items()))
        self.assertEqual(UUID(identificador).version, 4)
        self.assertEqual(registro["sessao_id"], identificador)
        self.assertTrue(registro["data_hora"])
        return identificador, registro

    def test_endpoint_detectar_preserva_contrato_e_aplica_negacao_e_compostos(self):
        casos = [
            ("N\u00e3o estou triste", []),
            ("N\u00e3o estou triste, estou cansado", ["cansado"]),
            ("Estou triste, mas n\u00e3o estou ansioso", ["triste"]),
            ("Estou sem energia", ["cansado"]),
            ("Estou feliz", ["feliz"]),
            ("Estou sem disposi\u00e7\u00e3o", ["cansado"]),
            ("Estou fora de controle", ["explosivo"]),
            ("Estou no limite", ["explosivo"]),
        ]
        for texto, esperado in casos:
            with self.subTest(texto=texto):
                resposta = self.client.post("/api/detectar-emocoes", params={"texto": texto})
                self.assertEqual(resposta.status_code, 200, resposta.text)
                self.assertEqual(resposta.json(), {"emocoes_detectadas": esperado})
        with ClienteSemCredencial(api.app, base_url="http://127.0.0.1",
                                  client=("127.0.0.1", 50001)) as anonimo:
            self.assertEqual(anonimo.post("/api/detectar-emocoes",
                                         params={"texto": "Estou feliz"}).status_code, 401)

    def test_api_preserva_relato_e_revisao_antes_de_recomendar(self):
        texto = "  N\u00e3o estou triste, estou cansado.\n"
        with patch.object(api, "recomendar_musicas", return_value=("espelhamento", "Exemplo ficticio", [])) as recomendar:
            resposta = self.client.post("/api/registrar-estado", json={"texto_atual": texto})
            self.assertEqual(resposta.status_code, 200, resposta.text)
            self.assertEqual(resposta.json()["emocoes_detectadas"], ["cansado"])
            self.assertEqual(resposta.json()["emocoes_atuais"], [])
            recomendar.assert_not_called()
            identificador, inicial = self.unica_sessao()
            self.assertEqual(inicial["texto_usuario"], texto)
            self.assertFalse(inicial["progresso"]["emocoes_confirmadas"])
            self.assertIsNone(inicial["feedback"])
            self.assertIsNone(inicial["escuta"])
            # A revisao explicita pode corrigir a sugestao do analisador.
            resposta = self.client.post("/api/retomar-sessao", json={
                "sessao_id": identificador, "emocoes_confirmadas": ["feliz"],
                "texto_desejado": "N\u00e3o quero estar ansioso, quero ficar calmo",
            })
            self.assertEqual(resposta.status_code, 200, resposta.text)
            recomendar.assert_called_once_with(["feliz"], ["calmo"])
        chave, atual = self.unica_sessao()
        self.assertEqual(chave, identificador)
        self.assertEqual(atual["data_hora"], inicial["data_hora"])
        self.assertEqual(atual["texto_usuario"], texto)
        self.assertEqual(atual["analise"], {"emocoes": ["feliz"], "estado_desejado": ["calmo"]})

    def test_api_negacao_sem_categoria_fica_pendente_sem_inferir_oposto(self):
        texto = "N\u00e3o estou triste"
        with patch.object(api, "recomendar_musicas") as recomendar:
            resposta = self.client.post("/api/registrar-estado", json={"texto_atual": texto})
            self.assertEqual(resposta.status_code, 200, resposta.text)
            self.assertEqual(resposta.json()["emocoes_detectadas"], [])
            identificador, registro = self.unica_sessao()
            self.assertEqual(registro["texto_usuario"], texto)
            self.assertEqual(registro["analise"]["emocoes"], [])
            self.assertFalse(any(registro["progresso"].values()))
            recomendar.assert_not_called()
            # Só a escolha explícita conclui a revisão, sem inferir um estado oposto.
            resposta = self.client.post("/api/retomar-sessao", json={
                "sessao_id": identificador, "emocoes_confirmadas": [],
            })
            self.assertEqual(resposta.status_code, 200, resposta.text)
            atual = self.unica_sessao()[1]
            self.assertEqual(atual["analise"]["emocoes"], [])
            self.assertTrue(atual["progresso"]["emocoes_confirmadas"])
            self.assertFalse(atual["progresso"]["estado_desejado_informado"])
            self.assertEqual(atual["texto_usuario"], texto)
            recomendar.assert_not_called()

    def test_sessao_confirmada_anterior_nao_e_reanalisada_ou_migrada(self):
        registro = sessoes.criar_sessao(
            data_hora="01/01/2000 10:00:00", texto_usuario="N\u00e3o estou triste",
            analise={"emocoes": ["triste"], "estado_desejado": []},
            estrategia="espelhamento", recomendacoes=[], escuta={"faixas": []},
            feedback={"ajudou": False, "motivo": "Retorno ficticio antigo"},
        )
        registro["progresso"] = dict.fromkeys(registro["progresso"], True)
        registro["texto_desejado"] = ""
        sessoes.salvar_nova_sessao(storage.ARQ_HISTORICO, registro)
        antes = self.historico.read_bytes()
        with patch.object(api, "detectar_emocoes_no_texto", side_effect=AssertionError("Nao reanalisar")), \
             patch.object(cli, "detectar_emocoes_no_texto", side_effect=AssertionError("Nao reanalisar")):
            resposta = self.client.post("/api/retomar-sessao", json={"sessao_id": registro["sessao_id"]})
            self.assertEqual(resposta.status_code, 200, resposta.text)
            self.assertEqual(resposta.json()["emocoes_atuais"], ["triste"])
            self.capturar_cli(lambda: cli.continuar_sessao(registro["sessao_id"]), [])
        self.assertEqual(self.historico.read_bytes(), antes)

    def test_cadastro_api_reconhece_composto_sem_rotular_animacao(self):
        anteriores = storage.carregar_todas_musicas()
        resposta = self.client.post("/api/musicas", json={
            "nome": "Faixa Nova Ficticia", "artista": "Artista Inventado", "duracao": "3:00",
            "sentimentos_texto": "Sem energia, n\u00e3o ansioso",
        })
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertEqual(resposta.json()["sentimentos_associados"], ["cansado"])
        atuais = storage.carregar_todas_musicas()
        self.assertEqual(atuais[:-1], anteriores)
        self.assertEqual(atuais[-1]["sentimentos_associados"], ["cansado"])

    def test_cadastro_api_so_negado_continua_recusando_ausencia_de_categoria(self):
        antes = self.catalogo.read_bytes()
        resposta = self.client.post("/api/musicas", json={
            "nome": "Faixa Nova Ficticia", "artista": "Artista Inventado", "duracao": "3:00",
            "sentimentos_texto": "N\u00e3o estou triste",
        })
        self.assertEqual(resposta.status_code, 422)
        self.assertEqual(self.catalogo.read_bytes(), antes)

    def test_csv_processamento_e_importacao_usam_mesmas_regras_sem_migrar_catalogo(self):
        linha = {
            "nome": "Faixa CSV Ficticia", "artista": "Artista Inventado", "duracao": "3:00",
            "bpm": "", "sentimentos_texto": "N\u00e3o estou triste, estou cansado", "tags": "",
        }
        musica, aviso = csv_importador.processar_linha(linha)
        self.assertIsNone(aviso)
        self.assertEqual(musica["sentimentos_associados"], ["cansado"])
        so_negada = {**linha, "nome": "Faixa Negada Ficticia", "sentimentos_texto": "N\u00e3o estou triste"}
        musica, aviso = csv_importador.processar_linha(so_negada)
        self.assertIsNone(musica)
        self.assertIsNotNone(aviso)
        anteriores = storage.carregar_todas_musicas()
        caminho = self.raiz / "lote_ficticio.csv"
        with caminho.open("w", encoding="utf-8", newline="") as arquivo:
            escritor = csv.DictWriter(arquivo, fieldnames=list(linha))
            escritor.writeheader()
            escritor.writerows([linha, so_negada])
        with redirect_stdout(io.StringIO()):
            csv_importador.main(str(caminho))
        atuais = storage.carregar_todas_musicas()
        self.assertEqual(atuais[:-1], anteriores)
        self.assertEqual(len(atuais), len(anteriores) + 1)
        self.assertEqual(atuais[-1]["sentimentos_associados"], ["cansado"])

    def test_json_classificado_preserva_rotulos_explicitos_e_percepcao_original(self):
        original = {
            "id": "classificada_ficticia", "nome": "Faixa Classificada Ficticia",
            "artista": "Artista Inventado", "duracao": "3:00", "bpm": None,
            "sentimentos_associados": ["triste"], "contextos": ["reflexao"],
            "estrategias": ["espelhamento"], "tags": [], "energia": "baixa",
            "valencia": "baixa", "intensidade": "baixa",
            "percepcao_usuario": "N\u00e3o estou triste",
        }
        antes = copy.deepcopy(original)
        completa, _avisos = json_importador.validar_e_completar(original)
        self.assertEqual(original, antes)
        self.assertEqual(completa["sentimentos_associados"], ["triste"])
        self.assertEqual(completa["percepcao_usuario"], original["percepcao_usuario"])

    def test_cli_cadastro_de_sensacoes_nao_aceita_so_emocao_negada(self):
        resultado, _saida = self.capturar_cli(cli.ler_sensacoes_musica, [
            "N\u00e3o estou triste", "Estou feliz",
        ])
        self.assertEqual(resultado, ["feliz"])

    def test_cli_relato_so_negado_ja_esta_salvo_antes_do_refinamento_interrompido(self):
        texto = "  N\u00e3o estou triste.\n"
        with patch.object(cli, "recomendar_musicas") as recomendar:
            _resultado, saida = self.capturar_cli(cli.opcao_registar_estado, [texto, EOFError()])
            recomendar.assert_not_called()
        _identificador, registro = self.unica_sessao()
        self.assertEqual(registro["texto_usuario"], texto)
        self.assertEqual(registro["analise"]["emocoes"], [])
        self.assertFalse(any(registro["progresso"].values()))
        self.assertIsNone(registro["escuta"])
        self.assertIsNone(registro["feedback"])
        self.assertIn("Vamos refinar", saida)
        self.assertIn("Fluxo interrompido", saida)

    def test_cli_revisao_manual_corrige_detectadas_sem_substituir_relato(self):
        texto = "N\u00e3o estou triste, estou cansado"
        with patch.object(cli, "recomendar_musicas", return_value=("espelhamento", "Exemplo ficticio", [])) as recomendar:
            self.capturar_cli(cli.opcao_registar_estado, [texto, "n", "feliz", "calmo"])
            recomendar.assert_called_once_with(["feliz"], ["calmo"])
        _identificador, registro = self.unica_sessao()
        self.assertEqual(registro["texto_usuario"], texto)
        self.assertEqual(registro["analise"]["emocoes"], ["feliz"])
        self.assertEqual(registro["texto_desejado"], "calmo")



class InicializadorDicionarioTests(unittest.TestCase):
    def test_inicializador_copia_referencia_com_compostos_sem_mudar_original(self):
        from api.desenvolvimento import dados_ficticios_temporarios
        from core.analisador_texto import detectar_emocoes_no_texto

        referencia = Path(__file__).resolve().parents[1] / "data" / "dicionario_emocional.json"
        antes = referencia.read_bytes()
        with dados_ficticios_temporarios():
            self.assertEqual(storage.carregar_json(storage.ARQ_DICIONARIO), DICIONARIO)
            self.assertEqual(detectar_emocoes_no_texto("Estou sem energia"), ["cansado"])
            self.assertEqual(detectar_emocoes_no_texto("Estou feliz"), ["feliz"])
            self.assertEqual(detectar_emocoes_no_texto("N\u00e3o estou triste"), [])
        self.assertEqual(referencia.read_bytes(), antes)



if __name__ == "__main__":
    unittest.main()
