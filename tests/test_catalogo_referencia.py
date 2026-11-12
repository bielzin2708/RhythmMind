"""Referência pública e importação testadas só com contas e arquivos temporários."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import main as api
from api.desenvolvimento import dados_ficticios_temporarios
from core import catalogo_referencia as referencia, storage
from core.contexto import contexto_usuario
from core.recomendador import recomendar_musicas


def catalogo_ficticio():
    musicas = []
    for numero, nome in enumerate(("Canção Fictícia", "Outra Faixa Fictícia"), 1):
        musicas.append({
            "id": f"referencia_ficticia_{numero}", "nome": nome,
            "artista": "Artista Inventado", "duracao": "3:00", "bpm": None,
            "sentimentos_associados": ["calmo"], "estrategias": ["descompressao"],
            "contextos": [], "tags": [],
            "proveniencia": {"fonte": "Fonte de teste fictícia",
                "url": f"https://music.apple.com/br/album/fixture/{numero}",
                "id_fonte": str(numero), "consultado_em": "2026-11-11",
                "album": "Álbum Inventado", "duracao_ms": 180123},
            "curadoria": {"status": "provisoria",
                "metodo": "associacao_editorial_sem_analise_de_audio", "versao": "ficticia-1",
                "justificativa": "Associação editorial fictícia, sem garantia de resposta individual."},
            "caracterizacao": {"versao_estrutura": 1,
                "caracteristicas_acusticas": [{"atributo": "duracao", "valor": 180.123,
                    "unidade": "s", "fonte": "Fonte de teste fictícia",
                    "metodo": "metadado_da_gravacao", "versao": "ficticia-1"}],
                "anotacoes_emocionais": [], "estimativas_sistema": [],
                "procedencia_legado": {"nome": {"fonte": "Fonte de teste fictícia",
                    "metodo": "metadado_da_gravacao", "versao": "ficticia-1"}}},
        })
    return {"versao": "ficticia-1", "descricao": "Referência fictícia para teste.", "musicas": musicas}


def catalogo_ficticio_grande(total=512):
    catalogo = catalogo_ficticio()
    modelo = catalogo["musicas"][0]
    catalogo["musicas"] = []
    for numero in range(total):
        musica = deepcopy(modelo)
        musica.update(id=f"referencia_grande_{numero}", nome=f"Canção fictícia {numero}",
                      sentimentos_associados=[], estrategias=[])
        musica["proveniencia"].update(album=None, id_fonte=str(numero))
        musica["curadoria"].update(status="pendente", metodo="metadados_publicos_sem_classificacao")
        catalogo["musicas"].append(musica)
    return catalogo


class ValidacaoReferenciaTests(unittest.TestCase):
    def test_referencia_publicada_valida_independente_do_diretorio_pessoal(self):
        with dados_ficticios_temporarios():
            catalogo = referencia.carregar_catalogo_referencia()
            self.assertTrue(catalogo["musicas"])
            self.assertTrue(referencia.ARQ_CATALOGO_REFERENCIA.is_absolute())

    def test_valida_lote_inteiro_sem_mutacao(self):
        catalogo = catalogo_ficticio()
        original = deepcopy(catalogo)
        self.assertEqual(referencia.validar_catalogo(catalogo), original)
        self.assertEqual(catalogo, original)

    def test_recusa_fontes_inseguras_e_metadados_sem_suporte(self):
        for url in ("http://music.apple.com/faixa", "https://music.apple.com.evil.invalid/faixa",
                    "https://senha@music.apple.com/faixa", "https://open.spotify.com:444/faixa"):
            with self.subTest(url=url):
                catalogo = catalogo_ficticio()
                catalogo["musicas"][0]["proveniencia"]["url"] = url
                with self.assertRaises(ValueError):
                    referencia.validar_catalogo(catalogo)
        for campo, valor in (("bpm", 120), ("valencia", "alta"), ("energia", "baixa"),
                             ("sentimentos_associados", ["categoria_inventada"]),
                             ("estrategias", ["estrategia_inventada"])):
            with self.subTest(campo=campo):
                catalogo = catalogo_ficticio()
                catalogo["musicas"][0][campo] = valor
                with self.assertRaises(ValueError):
                    referencia.validar_catalogo(catalogo)

    def test_recusa_duplicatas_e_duracao_de_outra_gravacao(self):
        catalogo = catalogo_ficticio()
        catalogo["musicas"].append(deepcopy(catalogo["musicas"][0]))
        with self.assertRaises(ValueError):
            referencia.validar_catalogo(catalogo)
        catalogo = catalogo_ficticio()
        catalogo["musicas"][1]["proveniencia"]["duracao_ms"] = 420000
        with self.assertRaises(ValueError):
            referencia.validar_catalogo(catalogo)

    def test_album_desconhecido_pode_ser_nulo_ou_omitido(self):
        for omitido in (False, True):
            with self.subTest(omitido=omitido):
                catalogo = catalogo_ficticio()
                fonte = catalogo["musicas"][0]["proveniencia"]
                if omitido:
                    del fonte["album"]
                else:
                    fonte["album"] = None
                referencia.validar_catalogo(catalogo)
        for invalido in ("", "  ", 123, False, []):
            with self.subTest(album=invalido):
                catalogo = catalogo_ficticio()
                catalogo["musicas"][0]["proveniencia"]["album"] = invalido
                with self.assertRaises(ValueError):
                    referencia.validar_catalogo(catalogo)

    def test_curadoria_pendente_exige_listas_vazias_e_metodo_documentado(self):
        for campo, valor in (("sentimentos_associados", ["calmo"]),
                             ("estrategias", ["descompressao"]),
                             ("curadoria", {"status": "pendente", "metodo": "outro", "versao": "1",
                                            "justificativa": "Fictícia"}),
                             ("curadoria", {"status": "pendente", "metodo": "metadados_publicos_sem_classificacao",
                                            "versao": "", "justificativa": "Fictícia"}),
                             ("curadoria", {"status": "pendente", "metodo": "metadados_publicos_sem_classificacao",
                                            "versao": "1", "justificativa": " "})):
            with self.subTest(campo=campo, valor=valor):
                catalogo = catalogo_ficticio_grande(1)
                catalogo["musicas"][0][campo] = valor
                with self.assertRaises(ValueError):
                    referencia.validar_catalogo(catalogo)


class ImportacaoReferenciaTests(unittest.TestCase):
    def setUp(self):
        self.raiz = self.enterContext(dados_ficticios_temporarios())
        self.artefato = self.raiz / "referencia-ficticia.json"
        self.catalogo = catalogo_ficticio()
        self.gravar_referencia()
        self.enterContext(patch.object(referencia, "ARQ_CATALOGO_REFERENCIA", self.artefato))
        self.anonimo = self.cliente()
        self.perfil, self.a = self.cadastrar("conta_a_referencia")
        self.arquivo = self.raiz / "data/usuarios" / self.perfil["usuario_id"] / "musicas_usuario.json"

    def gravar_referencia(self):
        self.artefato.write_text(json.dumps(self.catalogo), encoding="utf-8")

    def cliente(self, token=None):
        headers = {"Authorization": "Bearer " + token} if token else {}
        return self.enterContext(TestClient(api.app, base_url="http://127.0.0.1",
            client=("127.0.0.1", 50000), headers=headers))

    def cadastrar(self, nome):
        credenciais = {"nome_usuario": nome, "senha": "senha-ficticia-referencia-123!"}
        cadastro = self.anonimo.post("/api/auth/registrar", json=credenciais)
        self.assertEqual(cadastro.status_code, 201, cadastro.text)
        entrada = self.anonimo.post("/api/auth/entrar", json=credenciais)
        self.assertEqual(entrada.status_code, 200, entrada.text)
        return cadastro.json(), self.cliente(entrada.json()["token_acesso"])

    def importar(self, **corpo):
        return self.a.post("/api/catalogo-referencia/importar", json=corpo)

    def cadastrar_pessoal(self):
        resposta = self.a.post("/api/musicas", json={
            "nome": "Canção Pessoal Fictícia", "artista": "Artista Pessoal Inventado",
            "duracao": "2:00", "sentimentos_texto": "reflexivo",
        })
        self.assertEqual(resposta.status_code, 200, resposta.text)
        return resposta.json()

    def test_exige_autenticacao_e_nova_conta_permanece_vazia(self):
        self.assertEqual(self.anonimo.get("/api/catalogo-referencia").status_code, 401)
        self.assertEqual(self.anonimo.post("/api/catalogo-referencia/importar", json={}).status_code, 401)
        self.assertEqual(self.a.get("/api/musicas").json()["total"], 0)
        self.assertFalse(self.arquivo.exists())
        with self.assertRaises(PermissionError):
            referencia.importar_catalogo_referencia()

    def test_consulta_nao_grava_catalogo_pessoal(self):
        antes = self.artefato.read_bytes()
        resposta = self.a.get("/api/catalogo-referencia")
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertEqual(resposta.json()["total"], 2)
        self.assertEqual(resposta.json()["pronta_para_recomendar"], 2)
        self.assertEqual(resposta.json()["pendentes_associacao"], 0)
        self.assertEqual(resposta.json()["musicas"], self.catalogo["musicas"])
        self.assertFalse(self.arquivo.exists())
        self.assertEqual(self.artefato.read_bytes(), antes)

    def test_importacao_preserva_proveniencia_sem_inferir_valencia_ou_energia(self):
        with patch.object(api, "inferir_valencia_para_musica", side_effect=AssertionError("Não inferir")), \
             patch.object(api, "inferir_energia_para_musica", side_effect=AssertionError("Não inferir")):
            resposta = self.importar()
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertEqual(resposta.json(), {"versao": "ficticia-1", "importadas": 2,
            "ja_existentes": 0, "total": 2})
        salvas = json.loads(self.arquivo.read_text(encoding="utf-8"))
        for salva, original in zip(salvas, self.catalogo["musicas"]):
            self.assertEqual(salva["proveniencia"], original["proveniencia"])
            self.assertEqual(salva["curadoria"], original["curadoria"])
            self.assertIsNone(salva["bpm"])
            self.assertNotIn("valencia", salva)
            self.assertNotIn("energia", salva)
            self.assertEqual(salva["caracterizacao"]["anotacoes_emocionais"], [])
            self.assertEqual(salva["caracterizacao"]["estimativas_sistema"], [])
        with contexto_usuario(self.perfil["usuario_id"], self.raiz):
            _estrategia, _explicacao, recomendacoes = recomendar_musicas(["calmo"], ["calmo"])
        self.assertEqual(len(recomendacoes), 2)

    def test_isolamento_e_preservacao_de_musica_pessoal_e_arquivos_legados(self):
        pessoal = self.cadastrar_pessoal()
        perfil_b, b = self.cadastrar("conta_b_referencia")
        legado = self.raiz / storage.ARQ_MUSICAS
        historico_legado = self.raiz / storage.ARQ_HISTORICO
        antes = {caminho: caminho.read_bytes() for caminho in (legado, historico_legado)}
        fonte = self.artefato.read_bytes()
        resposta = self.importar()
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertEqual(self.a.get("/api/musicas").json()["musicas"][0], pessoal)
        self.assertEqual(b.get("/api/musicas").json()["total"], 0)
        self.assertFalse((self.raiz / "data/usuarios" / perfil_b["usuario_id"] / "musicas_usuario.json").exists())
        self.assertEqual(self.artefato.read_bytes(), fonte)
        for caminho, conteudo in antes.items():
            self.assertEqual(caminho.read_bytes(), conteudo)

    def test_repeticao_preserva_bytes_e_nao_regrava(self):
        self.assertEqual(self.importar().status_code, 200)
        antes = self.arquivo.read_bytes()
        with patch.object(storage, "salvar_json", side_effect=AssertionError("Não regravar")):
            resposta = self.importar()
        self.assertEqual(resposta.json()["importadas"], 0)
        self.assertEqual(resposta.json()["ja_existentes"], 2)
        self.assertEqual(self.arquivo.read_bytes(), antes)

    def test_selecao_vazia_parcial_e_duplicata_manual_normalizada(self):
        self.assertEqual(self.importar(ids=[]).json()["importadas"], 0)
        self.assertFalse(self.arquivo.exists())
        pessoal = {"id": "meu_identificador", "nome": "  CANCAO  FICTICIA ",
            "artista": "ARTISTA INVENTADO", "minha_nota": "Preservar edição pessoal."}
        with contexto_usuario(self.perfil["usuario_id"], self.raiz):
            storage.salvar_json(storage.ARQ_MUSICAS, [pessoal])
        resposta = self.importar(ids=["referencia_ficticia_1"])
        self.assertEqual(resposta.json()["ja_existentes"], 1)
        self.assertEqual(json.loads(self.arquivo.read_text()), [pessoal])
        resposta = self.importar(ids=["referencia_ficticia_2"])
        self.assertEqual(resposta.json()["importadas"], 1)
        self.assertEqual(resposta.json()["total"], 2)

    def test_recusa_ids_desconhecidos_e_campos_de_outro_usuario_antes_de_gravar(self):
        for corpo in ({"ids": ["referencia_ficticia_1", "ausente"]},
                      {"usuario_id": "outro"}, {"caminho": "data/outro.json"},
                      {"ids": ["referencia_ficticia_1"] * (referencia.MAX_IDS_IMPORTACAO + 1)},
                      {"ids": [1]}, {"ids": [""]}):
            with self.subTest(corpo=corpo):
                resposta = self.importar(**corpo)
                self.assertEqual(resposta.status_code, 422, resposta.text)
                self.assertFalse(self.arquivo.exists())

    def test_importa_faixas_pendentes_sem_recomenda_las(self):
        self.catalogo = catalogo_ficticio_grande(30)
        self.gravar_referencia()
        consulta = self.a.get("/api/catalogo-referencia")
        self.assertEqual(consulta.status_code, 200, consulta.text)
        self.assertEqual(consulta.json()["pronta_para_recomendar"], 0)
        self.assertEqual(consulta.json()["pendentes_associacao"], 30)
        ids = [musica["id"] for musica in self.catalogo["musicas"]]
        resposta = self.importar(ids=ids)
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertEqual(resposta.json()["importadas"], 30)
        self.assertEqual(len(json.loads(self.arquivo.read_text())), 30)
        with contexto_usuario(self.perfil["usuario_id"], self.raiz):
            self.assertEqual(recomendar_musicas(["calmo"], ["calmo"])[2], [])
        antes = self.arquivo.read_bytes()
        self.assertEqual(self.importar().json()["importadas"], 0)
        self.assertEqual(self.arquivo.read_bytes(), antes)

    def test_lote_invalido_e_falha_de_substituicao_preservam_arquivo_anterior(self):
        self.cadastrar_pessoal()
        antes = self.arquivo.read_bytes()
        self.catalogo["musicas"][1]["bpm"] = 120
        self.gravar_referencia()
        resposta = self.importar(ids=["referencia_ficticia_1"])
        self.assertEqual(resposta.status_code, 503, resposta.text)
        self.assertEqual(self.arquivo.read_bytes(), antes)
        self.catalogo = catalogo_ficticio()
        self.gravar_referencia()
        with patch.object(storage.os, "replace", side_effect=OSError("Falha fictícia")):
            resposta = self.importar()
        self.assertEqual(resposta.status_code, 503, resposta.text)
        self.assertEqual(self.arquivo.read_bytes(), antes)
        self.assertFalse(list(self.arquivo.parent.glob(".rhythmmind-*.tmp")))

    def test_importacoes_e_cadastro_concorrentes_nao_perdem_nem_duplicam_faixas(self):
        def executar(indice):
            with contexto_usuario(self.perfil["usuario_id"], self.raiz):
                if indice == 0:
                    storage.salvar_musica_usuario({"id": "pessoal_concorrente", "nome": "Faixa Pessoal",
                        "artista": "Artista Fictício"})
                else:
                    referencia.importar_catalogo_referencia()
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(executar, range(4)))
        salvas = json.loads(self.arquivo.read_text())
        self.assertEqual(len(salvas), 3)
        self.assertEqual({musica["id"] for musica in salvas},
            {"pessoal_concorrente", "referencia_ficticia_1", "referencia_ficticia_2"})


if __name__ == "__main__":
    unittest.main()
