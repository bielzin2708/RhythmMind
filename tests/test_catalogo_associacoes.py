"""Associações pessoais explícitas, sem preencher metadados ou analisar áudio."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
import json
from threading import Barrier
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import main as api
from api.desenvolvimento import dados_ficticios_temporarios
from core import catalogo_referencia as referencia, storage
from core.contexto import contexto_usuario
from core.recomendador import recomendar_musicas
from tests.test_catalogo_referencia import catalogo_ficticio


CURADORIA_PESSOAL = {
    "status": "informada_pelo_usuario",
    "metodo": "categorias_confirmadas_sem_analise_de_audio",
    "versao": "1",
    "justificativa": "Associações informadas pelo titular; sem análise de áudio.",
}


def faixa_pendente():
    faixa = catalogo_ficticio()["musicas"][0]
    faixa["sentimentos_associados"] = []
    faixa["estrategias"] = []
    faixa["curadoria"] = {
        "status": "pendente", "metodo": "metadados_publicos_sem_classificacao",
        "versao": "ficticia-1", "justificativa": "Somente metadados públicos.",
    }
    return faixa


class AssociacoesPessoaisTests(unittest.TestCase):
    def setUp(self):
        self.raiz = self.enterContext(dados_ficticios_temporarios())
        self.anonimo = self.cliente()
        self.perfil_a, self.a = self.cadastrar("associacoes_a")
        self.perfil_b, self.b = self.cadastrar("associacoes_b")
        self.faixa = faixa_pendente()
        self.gravar(self.perfil_a, [self.faixa])
        self.arquivo = self.caminho(self.perfil_a, "musicas_usuario.json")

    def cliente(self, token=None):
        headers = {"Authorization": "Bearer " + token} if token else {}
        return self.enterContext(TestClient(api.app, base_url="http://127.0.0.1",
            client=("127.0.0.1", 50000), headers=headers))

    def cadastrar(self, nome):
        credenciais = {"nome_usuario": nome, "senha": "senha-ficticia-associacoes-123!"}
        registro = self.anonimo.post("/api/auth/registrar", json=credenciais)
        self.assertEqual(registro.status_code, 201, registro.text)
        entrada = self.anonimo.post("/api/auth/entrar", json=credenciais)
        self.assertEqual(entrada.status_code, 200, entrada.text)
        return registro.json(), self.cliente(entrada.json()["token_acesso"])

    def caminho(self, perfil, nome):
        return self.raiz / "data/usuarios" / perfil["usuario_id"] / nome

    def gravar(self, perfil, musicas):
        with contexto_usuario(perfil["usuario_id"], self.raiz):
            storage.salvar_json(storage.ARQ_MUSICAS, musicas)

    def associar(self, categorias, *, cliente=None, musica_id=None, **extras):
        return (cliente or self.a).patch(
            f"/api/musicas/{musica_id or self.faixa['id']}/associacoes",
            json={"sentimentos_associados": categorias, **extras},
        )

    def test_exige_autenticacao_e_procura_apenas_na_propria_conta(self):
        antes = self.arquivo.read_bytes()
        self.assertEqual(self.associar(["calmo"], cliente=self.anonimo).status_code, 401)
        self.assertEqual(self.associar(["calmo"], cliente=self.b).status_code, 404)
        self.assertEqual(self.associar(["calmo"], musica_id="inexistente").status_code, 404)
        self.assertEqual(self.arquivo.read_bytes(), antes)
        self.assertFalse(self.caminho(self.perfil_b, "musicas_usuario.json").exists())

    def test_contas_com_mesmo_id_mantem_associacoes_independentes(self):
        self.gravar(self.perfil_b, [self.faixa])
        antes_b = self.caminho(self.perfil_b, "musicas_usuario.json").read_bytes()
        resposta = self.associar(["calmo"])
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertEqual(resposta.json()["musica"]["sentimentos_associados"], ["calmo"])
        self.assertEqual(self.caminho(self.perfil_b, "musicas_usuario.json").read_bytes(), antes_b)
        self.assertEqual(self.associar(["animado"], cliente=self.b).status_code, 200)
        self.assertEqual(json.loads(self.arquivo.read_text())[0]["sentimentos_associados"], ["calmo"])

    def test_preserva_metadados_observacoes_e_historico_sem_inferencias_numericas(self):
        original = deepcopy(self.faixa)
        original.update({"bpm": 120, "energia": "baixa", "valencia": "media",
            "intensidade": "alta", "tags": ["festa", "energia"],
            "contextos": ["social"], "nota_pessoal": "Preservar literalmente."})
        bloco = original["caracterizacao"]
        bloco["caracteristicas_acusticas"].append({"atributo": "bpm", "valor": 120,
            "unidade": "bpm", "fonte": "Titular anterior", "metodo": "medicao_manual", "versao": "1"})
        bloco["anotacoes_emocionais"] = [{"atributo": "valencia", "valor": 0.4,
            "escala": {"minimo": 0, "maximo": 1}, "fonte": "Titular anterior"}]
        self.gravar(self.perfil_a, [original])
        with contexto_usuario(self.perfil_a["usuario_id"], self.raiz):
            storage.salvar_json(storage.ARQ_HISTORICO, {"sessao_antiga": {"musicas": [original]}})
        historico = self.caminho(self.perfil_a, "historico.json")
        antes_historico = historico.read_bytes()
        legado = {nome: (self.raiz / nome).read_bytes()
                  for nome in (storage.ARQ_MUSICAS, storage.ARQ_HISTORICO)}
        with patch.object(api, "inferir_valencia_para_musica", side_effect=AssertionError("Não inferir")), \
             patch.object(api, "inferir_energia_para_musica", side_effect=AssertionError("Não inferir")), \
             patch.object(api, "inferir_intensidade_para_musica", side_effect=AssertionError("Não inferir")):
            resposta = self.associar(["calmo"])
        self.assertEqual(resposta.status_code, 200, resposta.text)
        salva = resposta.json()["musica"]
        self.assertEqual(salva["estrategias"], ["descompressao", "foco_cognitivo"])
        self.assertEqual(salva["curadoria"], CURADORIA_PESSOAL)
        for campo in set(original) - {"sentimentos_associados", "estrategias", "curadoria", "caracterizacao"}:
            self.assertEqual(salva[campo], original[campo], campo)
        for grupo in ("caracteristicas_acusticas", "anotacoes_emocionais", "estimativas_sistema"):
            self.assertEqual(salva["caracterizacao"][grupo], original["caracterizacao"][grupo])
        procedencia = salva["caracterizacao"]["procedencia_legado"]
        self.assertEqual(procedencia["nome"], original["caracterizacao"]["procedencia_legado"]["nome"])
        for campo in ("sentimentos_associados", "estrategias"):
            self.assertEqual(procedencia[campo], {"fonte": "Titular",
                "metodo": CURADORIA_PESSOAL["metodo"], "versao": "1"})
        revisao = salva["revisoes_associacoes"][0]
        datetime.fromisoformat(revisao["timestamp"].replace("Z", "+00:00"))
        self.assertEqual(revisao["categorias_anteriores"], original["sentimentos_associados"])
        self.assertEqual(revisao["estrategias_anteriores"], original["estrategias"])
        self.assertEqual(revisao["curadoria_anterior"], original["curadoria"])
        self.assertEqual(historico.read_bytes(), antes_historico)
        for nome, conteudo in legado.items():
            self.assertEqual((self.raiz / nome).read_bytes(), conteudo)

    def test_pendente_sem_criterio_so_entra_na_recomendacao_apos_associacao(self):
        ajuste = {f"{self.faixa['nome']} - {self.faixa['artista']}": 10}
        with contexto_usuario(self.perfil_a["usuario_id"], self.raiz):
            self.assertEqual(recomendar_musicas(["calmo"], ["calmo"])[2], [])
            self.assertEqual(recomendar_musicas(["calmo"], ["calmo"], ajuste)[2], [])
        resposta = self.associar(["calmo"])
        self.assertEqual(resposta.status_code, 200, resposta.text)
        salva = resposta.json()["musica"]
        self.assertIsNone(salva["bpm"])
        for campo in ("energia", "valencia", "intensidade"):
            self.assertNotIn(campo, salva)
        with contexto_usuario(self.perfil_a["usuario_id"], self.raiz):
            recomendacoes = recomendar_musicas(["calmo"], ["calmo"], ajuste)[2]
        self.assertEqual([musica["id"] for musica in recomendacoes], [self.faixa["id"]])
        retirada = self.associar([])
        self.assertEqual(retirada.status_code, 200, retirada.text)
        with contexto_usuario(self.perfil_a["usuario_id"], self.raiz):
            self.assertEqual(recomendar_musicas(["calmo"], ["calmo"], ajuste)[2], [])

    def test_retirar_associacoes_e_repetir_nao_regrava_nem_cria_revisao(self):
        primeira = self.associar(["calmo"])
        self.assertEqual(primeira.status_code, 200, primeira.text)
        segunda = self.associar([])
        self.assertEqual(segunda.status_code, 200, segunda.text)
        salva = segunda.json()["musica"]
        self.assertEqual(salva["sentimentos_associados"], [])
        self.assertEqual(salva["estrategias"], [])
        self.assertEqual(len(salva["revisoes_associacoes"]), 2)
        self.assertEqual(salva["revisoes_associacoes"][1]["categorias_anteriores"], ["calmo"])
        antes = self.arquivo.read_bytes()
        with patch.object(storage, "salvar_json", side_effect=AssertionError("Não regravar")):
            repetida = self.associar([])
        self.assertEqual(repetida.status_code, 200, repetida.text)
        self.assertEqual(repetida.json()["musica"], salva)
        self.assertEqual(self.arquivo.read_bytes(), antes)
        with contexto_usuario(self.perfil_a["usuario_id"], self.raiz):
            self.assertEqual(recomendar_musicas(["calmo"], ["calmo"])[2], [])

    def test_recusa_categorias_invalidas_duplicatas_coercao_e_campos_extras(self):
        antes = self.arquivo.read_bytes()
        for corpo in ({"sentimentos_associados": ["inventada"]},
                      {"sentimentos_associados": ["calmo", "calmo"]},
                      {"sentimentos_associados": [1]},
                      {"sentimentos_associados": "calmo"},
                      {"sentimentos_associados": ["calmo"], "usuario_id": self.perfil_b["usuario_id"]},
                      {"sentimentos_associados": ["calmo"], "bpm": 123},
                      {"sentimentos_associados": ["calmo"], "estrategias": ["ativacao"]},
                      {}):
            with self.subTest(corpo=corpo):
                resposta = self.a.patch(f"/api/musicas/{self.faixa['id']}/associacoes", json=corpo)
                self.assertEqual(resposta.status_code, 422, resposta.text)
                self.assertEqual(self.arquivo.read_bytes(), antes)

    def test_id_pessoal_ambiguo_recusa_sem_modificar_os_registros(self):
        outra = deepcopy(self.faixa)
        outra["nome"] = "Outra faixa com ID conflitante"
        self.gravar(self.perfil_a, [self.faixa, outra])
        antes = self.arquivo.read_bytes()
        resposta = self.associar(["calmo"])
        self.assertEqual(resposta.status_code, 409, resposta.text)
        self.assertEqual(self.arquivo.read_bytes(), antes)

    def test_associacao_e_importacoes_concorrentes_preservam_edicao_e_novas_faixas(self):
        catalogo = catalogo_ficticio()
        inicio = Barrier(4)

        def executar(indice):
            with contexto_usuario(self.perfil_a["usuario_id"], self.raiz):
                inicio.wait(timeout=5)
                if indice == 0:
                    return referencia.atualizar_associacoes_musica(self.faixa["id"], ["calmo"])
                return referencia.importar_catalogo_referencia()

        with patch.object(referencia, "carregar_catalogo_referencia", return_value=catalogo):
            with ThreadPoolExecutor(max_workers=4) as executor:
                list(executor.map(executar, range(4)))
        salvas = json.loads(self.arquivo.read_text())
        self.assertEqual(len(salvas), 2)
        associada = next(m for m in salvas if m["id"] == self.faixa["id"])
        self.assertEqual(associada["sentimentos_associados"], ["calmo"])
        self.assertEqual(associada["curadoria"], CURADORIA_PESSOAL)
        self.assertEqual(len(associada["revisoes_associacoes"]), 1)
        self.assertEqual({m["id"] for m in salvas}, {m["id"] for m in catalogo["musicas"]})

    def test_armazenamento_invalido_e_falha_atomica_preservam_arquivo(self):
        for conteudo in (b'{"invalido":true}', b'[{"id":', b'["invalido"]'):
            with self.subTest(conteudo=conteudo):
                self.arquivo.write_bytes(conteudo)
                resposta = self.associar(["calmo"])
                self.assertIn(resposta.status_code, (422, 503), resposta.text)
                self.assertEqual(self.arquivo.read_bytes(), conteudo)
        self.gravar(self.perfil_a, [self.faixa])
        antes = self.arquivo.read_bytes()
        with patch.object(storage.os, "replace", side_effect=OSError("Falha fictícia")):
            resposta = self.associar(["calmo"])
        self.assertEqual(resposta.status_code, 503, resposta.text)
        self.assertEqual(self.arquivo.read_bytes(), antes)
        self.assertFalse(list(self.arquivo.parent.glob(".rhythmmind-*.tmp")))


if __name__ == "__main__":
    unittest.main()
