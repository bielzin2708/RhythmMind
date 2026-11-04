"""Integracao da caracterizacao opcional, sempre com catalogos ficticios temporarios."""

import copy
import csv
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import unittest

from fastapi.testclient import TestClient

import cadastrar_em_lote as csv_importador
import importar_lote_classificado as json_importador
from api import main as api
from api.desenvolvimento import dados_ficticios_temporarios
from core import storage
from core.caracterizacao import obter_caracterizacao, preparar_musica, validar_musica


def bloco_ficticio():
    return {
        "versao_estrutura": 1,
        "caracteristicas_acusticas": [{
            "atributo": "duracao", "valor": 180, "unidade": "s",
            "fonte": "exemplo_ficticio", "metodo": "dado_sintetico", "versao": "demo-1",
        }],
        "anotacoes_emocionais": [{
            "atributo": "valencia", "valor": -0.5,
            "escala": {"minimo": -1, "maximo": 1, "descricao": "Exemplo ficticio: desagradavel a agradavel"},
            "fonte": "anotador_ficticio", "metodo": "anotacao_sintetica", "versao": "demo-1",
        }],
        "estimativas_sistema": [{
            "atributo": "bpm", "valor": 155.5, "unidade": "bpm",
            "fonte": "estimador_ficticio", "metodo": "exemplo_sem_audio", "versao": "demo-1",
        }],
    }


def musica_ficticia():
    return {
        "id": "nova_ficticia", "nome": "Nova Faixa Ficticia", "artista": "Artista Inventado",
        "duracao": "3:00", "bpm": 70, "energia": "baixa", "valencia": "media",
        "intensidade": "baixa", "sentimentos_associados": ["cansado"],
        "contextos": ["reflexao"], "estrategias": ["espelhamento"], "tags": [],
    }


class IntegracaoCaracterizacaoTests(unittest.TestCase):
    def setUp(self):
        self.raiz = self.enterContext(dados_ficticios_temporarios())
        self.catalogo = self.raiz / storage.ARQ_MUSICAS
        self.client = self.enterContext(TestClient(
            api.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000),
        ))

    def criar_api(self, **campos):
        return self.client.post("/api/musicas", json={
            "nome": "Faixa API Ficticia", "artista": "Artista Inventado",
            "duracao": "3:00", "sentimentos_texto": "calmo", **campos,
        })

    def test_leitura_legada_nao_migra_catalogo_nem_altera_arquivo(self):
        antes = self.catalogo.read_bytes()
        musicas = storage.carregar_todas_musicas()
        self.assertEqual(musicas, json.loads(antes))
        for musica in musicas:
            self.assertNotIn("caracterizacao", musica)
            vista = obter_caracterizacao(musica)
            self.assertEqual(vista["anotacoes_emocionais"], [])
            self.assertEqual(vista["procedencia_legado"]["nome"]["fonte"], "desconhecida")
        self.assertEqual(self.catalogo.read_bytes(), antes)

    def test_escrita_nova_acrescenta_procedencia_sem_migrar_anteriores(self):
        antigas = storage.carregar_todas_musicas()
        nova = musica_ficticia()
        original = copy.deepcopy(nova)
        persistida = storage.salvar_musica_usuario(nova)
        atuais = storage.carregar_todas_musicas()
        self.assertEqual(atuais[:-1], antigas)
        self.assertEqual(nova, original)
        self.assertEqual(atuais[-1], persistida)
        self.assertEqual({k: v for k, v in persistida.items() if k != "caracterizacao"}, original)
        for secao in ("caracteristicas_acusticas", "anotacoes_emocionais", "estimativas_sistema"):
            self.assertEqual(persistida["caracterizacao"][secao], [])
        self.assertEqual(persistida["caracterizacao"]["procedencia_legado"]["bpm"], {
            "fonte": "desconhecida", "metodo": None, "versao": None,
        })

    def test_escrita_invalida_nao_altera_catalogo(self):
        musica = musica_ficticia()
        musica["caracterizacao"] = bloco_ficticio()
        musica["caracterizacao"]["estimativas_sistema"][0]["valor"] = -10
        antes = self.catalogo.read_bytes()
        with self.assertRaises(ValueError):
            storage.salvar_musica_usuario(musica)
        self.assertEqual(self.catalogo.read_bytes(), antes)

    def test_json_preserva_valores_antigos_e_novos_sem_reinterpretar(self):
        musica = musica_ficticia()
        musica["caracterizacao"] = bloco_ficticio()
        original = copy.deepcopy(musica)
        completa, _avisos = json_importador.validar_e_completar(musica)
        self.assertEqual(musica, original)
        self.assertEqual({k: v for k, v in completa.items() if k != "caracterizacao"},
                         {k: v for k, v in original.items() if k != "caracterizacao"})
        for secao in ("caracteristicas_acusticas", "anotacoes_emocionais", "estimativas_sistema"):
            self.assertEqual(completa["caracterizacao"][secao], original["caracterizacao"][secao])
        self.assertEqual(completa["bpm"], 70)
        self.assertEqual(completa["caracterizacao"]["estimativas_sistema"][0]["valor"], 155.5)
        self.assertEqual(completa["valencia"], "media")
        self.assertEqual(completa["caracterizacao"]["procedencia_legado"]["valencia"]["fonte"], "desconhecida")

    def test_json_lote_invalido_nao_grava_nem_parcialmente(self):
        invalida = musica_ficticia()
        invalida["id"] = "invalida_ficticia"
        invalida["caracterizacao"] = {"versao_estrutura": 99}
        lote = self.raiz / "lote_ficticio.json"
        lote.write_text(json.dumps([musica_ficticia(), invalida]), encoding="utf-8")
        antes = self.catalogo.read_bytes()
        with redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
            json_importador.main(str(lote))
        self.assertEqual(self.catalogo.read_bytes(), antes)

    def test_json_lote_preserva_registros_anteriores_e_nova_caracterizacao(self):
        anteriores = storage.carregar_todas_musicas()
        nova = musica_ficticia()
        nova["caracterizacao"] = bloco_ficticio()
        lote = self.raiz / "lote_ficticio.json"
        lote.write_text(json.dumps([nova]), encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            json_importador.main(str(lote))
        atuais = storage.carregar_todas_musicas()
        self.assertEqual(atuais[:-1], anteriores)
        self.assertEqual(atuais[-1]["caracterizacao"]["estimativas_sistema"],
                         nova["caracterizacao"]["estimativas_sistema"])

    def test_csv_antigo_sem_bpm_nao_inventa_atributos_novos(self):
        musica, aviso = csv_importador.processar_linha({
            "nome": "Faixa CSV Ficticia", "artista": "Artista Inventado",
            "duracao": "2:30", "bpm": "", "sentimentos_texto": "calmo", "tags": "",
        })
        self.assertIsNone(aviso)
        self.assertIsNone(musica["bpm"])
        self.assertEqual(musica["caracterizacao"]["caracteristicas_acusticas"], [])
        self.assertEqual(musica["caracterizacao"]["anotacoes_emocionais"], [])
        self.assertEqual(musica["caracterizacao"]["estimativas_sistema"], [])
        self.assertEqual(musica["caracterizacao"]["procedencia_legado"]["bpm"]["fonte"], "desconhecida")

    def test_csv_fluxo_completo_permanece_compativel(self):
        caminho = self.raiz / "lote_ficticio.csv"
        with caminho.open("w", encoding="utf-8", newline="") as arquivo:
            escritor = csv.DictWriter(arquivo, fieldnames=[
                "nome", "artista", "duracao", "bpm", "sentimentos_texto", "tags",
            ])
            escritor.writeheader()
            escritor.writerow({
                "nome": "Faixa CSV Ficticia", "artista": "Artista Inventado",
                "duracao": "2:30", "bpm": "", "sentimentos_texto": "calmo", "tags": "",
            })
        anteriores = storage.carregar_todas_musicas()
        with redirect_stdout(io.StringIO()):
            csv_importador.main(str(caminho))
        atuais = storage.carregar_todas_musicas()
        self.assertEqual(atuais[:-1], anteriores)
        self.assertEqual(atuais[-1]["sentimentos_associados"], ["calmo"])
        self.assertIsNone(atuais[-1]["bpm"])
        self.assertEqual(atuais[-1]["caracterizacao"]["estimativas_sistema"], [])

    def test_api_aceita_bloco_opcional_sem_sincronizar_bpm_e_emocao(self):
        bloco = bloco_ficticio()
        resposta = self.criar_api(bpm="70", caracterizacao=bloco)
        self.assertEqual(resposta.status_code, 200, resposta.text)
        persistida = storage.carregar_todas_musicas()[-1]
        self.assertEqual(resposta.json(), persistida)
        self.assertEqual(persistida["bpm"], 70)
        self.assertEqual(persistida["sentimentos_associados"], ["calmo"])
        self.assertEqual(persistida["valencia"], "media")
        self.assertEqual(persistida["caracterizacao"]["estimativas_sistema"], bloco["estimativas_sistema"])

    def test_api_sem_caracterizacao_continua_aceitando_cadastro(self):
        resposta = self.criar_api()
        self.assertEqual(resposta.status_code, 200, resposta.text)
        musica = resposta.json()
        self.assertIsNone(musica["bpm"])
        self.assertEqual(musica["caracterizacao"]["estimativas_sistema"], [])
        self.assertEqual(musica["caracterizacao"]["procedencia_legado"]["bpm"]["fonte"], "desconhecida")

    def test_api_rejeita_unidade_escala_e_versao_invalidas_sem_gravar(self):
        invalidos = [
            {"versao_estrutura": 2},
            {"versao_estrutura": 1, "estimativas_sistema": [
                {"atributo": "bpm", "valor": 120, "unidade": "Hz"},
            ]},
            {"versao_estrutura": 1, "anotacoes_emocionais": [
                {"atributo": "valencia", "valor": 7, "escala": {"minimo": 0, "maximo": 1}},
            ]},
        ]
        for bloco in invalidos:
            with self.subTest(bloco=bloco):
                antes = self.catalogo.read_bytes()
                resposta = self.criar_api(caracterizacao=bloco)
                self.assertEqual(resposta.status_code, 422, resposta.text)
                self.assertEqual(self.catalogo.read_bytes(), antes)

    def test_feedback_de_sessao_nao_vira_anotacao_global_da_faixa(self):
        antes = self.catalogo.read_bytes()
        criacao = self.client.post("/api/registrar-estado", json={
            "texto_atual": "Relato ficticio: estou cansado.",
            "emocoes_confirmadas": ["cansado"], "texto_desejado": "calmo",
        })
        self.assertEqual(criacao.status_code, 200)
        resposta = self.client.post("/api/feedback", json={
            "sessao_id": criacao.json()["sessao_id"], "ajudou": True,
            "motivo": "Experiencia ficticia desta sessao",
        })
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(self.catalogo.read_bytes(), antes)

    def test_exemplos_publicaveis_validos_e_ao_menos_um_legado(self):
        caminho = Path(__file__).resolve().parents[1] / "data" / "musicas_exemplo.json"
        exemplos = json.loads(caminho.read_text(encoding="utf-8"))
        self.assertTrue(any("caracterizacao" in m for m in exemplos))
        self.assertTrue(any("caracterizacao" not in m for m in exemplos))
        for musica in exemplos:
            validar_musica(musica)
            preparada = preparar_musica(musica)
            self.assertEqual({k: v for k, v in preparada.items() if k != "caracterizacao"},
                             {k: v for k, v in musica.items() if k != "caracterizacao"})

    def test_api_numeros_nao_finitos_no_json_bruto_retornam_422(self):
        from fastapi.testclient import TestClient
        invalidos = [
            '{"versao_estrutura":1,"estimativas_sistema":[{"atributo":"bpm","valor":'
            + literal + ',"unidade":"bpm"}]}'
            for literal in ("1e309", "-1e309", "NaN", "Infinity")
        ] + ["[1e309]"]
        with TestClient(api.app, base_url="http://127.0.0.1",
                        client=("127.0.0.1", 50001), raise_server_exceptions=False) as client:
            for bloco_bruto in invalidos:
                with self.subTest(bloco=bloco_bruto):
                    antes = self.catalogo.read_bytes()
                    corpo = json.dumps({
                        "nome": "Faixa Ficticia", "artista": "Artista Inventado",
                        "duracao": "3:00", "sentimentos_texto": "calmo",
                        "caracterizacao": "BLOCO_FICTICIO",
                    }).replace('"BLOCO_FICTICIO"', bloco_bruto)
                    resposta = client.post("/api/musicas", content=corpo,
                                           headers={"content-type": "application/json"})
                    self.assertEqual(resposta.status_code, 422, resposta.text)
                    self.assertEqual(self.catalogo.read_bytes(), antes)


if __name__ == "__main__":
    unittest.main()
