"""Quantidade e motivos das sugestões HTTP, usando somente dados fictícios."""

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import main as api
from core import storage
from tests.apoio_autenticacao import ClienteAutenticado, dados_autenticados


RELATO = "  Relato fictício: estou cansado.\n"
CATALOGO = [
    {"id": f"faixa_ficticia_{indice}", "nome": f"Faixa Inventada {indice}",
     "artista": "Artista Fictício", "sentimentos_associados": ["cansado", "calmo"],
     "estrategias": ["descompressao"]}
    for indice in range(1, 7)
]


class EscolhaMusicalApiTests(unittest.TestCase):
    def setUp(self):
        self.raiz = self.enterContext(dados_autenticados())
        storage.salvar_json(storage.ARQ_MUSICAS, deepcopy(CATALOGO))
        self.historico = Path(storage.resolver_caminho(storage.ARQ_HISTORICO))
        self.client = self.enterContext(ClienteAutenticado(
            api.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000),
        ))

    def ler(self):
        return storage.carregar_json(str(self.historico), {})

    def criar(self, **campos):
        resposta = self.client.post("/api/registrar-estado", json={
            "texto_atual": RELATO, **campos,
        })
        self.assertEqual(resposta.status_code, 200, resposta.text)
        return resposta.json()

    def completa(self, **campos):
        return self.criar(**{
            "emocoes_confirmadas": ["cansado"], "texto_desejado": "calmo", **campos,
        })

    def retomar(self, identificador, **campos):
        return self.client.post("/api/retomar-sessao", json={
            "sessao_id": identificador, **campos,
        })

    def conferir_motivos(self, corpo):
        motivos = corpo["motivos_recomendacoes"]
        self.assertEqual(len(motivos), len(corpo["recomendacoes"]))
        self.assertEqual([motivo["indice_recomendacao"] for motivo in motivos],
                         list(range(1, len(motivos) + 1)))
        for motivo in motivos:
            self.assertTrue(motivo["explicacao"].strip())
            self.assertTrue(motivo["criterios"])
            self.assertEqual(motivo["pontuacao"], sum(
                criterio["pontos"] for criterio in motivo["criterios"]
            ))

    def test_criacao_pendente_registra_padrao_e_nao_inventa_motivos(self):
        corpo = self.criar()
        registro = self.ler()[corpo["sessao_id"]]
        self.assertEqual(corpo["limite_recomendacoes"], 3)
        self.assertEqual(corpo["motivos_recomendacoes"], [])
        self.assertEqual(registro["limite_recomendacoes"], 3)
        self.assertEqual(registro["motivos_recomendacoes"], [])
        self.assertFalse(registro["progresso"]["recomendacoes_geradas"])
        self.assertEqual(registro["texto_usuario"], RELATO)

    def test_cinco_sugestoes_preservam_prefixo_musicas_brutas_e_motivos_salvos(self):
        padrao = self.completa()
        ampliada = self.completa(limite_recomendacoes=5)
        self.assertEqual(padrao["recomendacoes"], CATALOGO[:3])
        self.assertEqual(ampliada["recomendacoes"], CATALOGO[:5])
        self.assertEqual(ampliada["recomendacoes"][:3], padrao["recomendacoes"])
        self.conferir_motivos(ampliada)
        registro = self.ler()[ampliada["sessao_id"]]
        self.assertEqual(registro["recomendacoes"], ampliada["recomendacoes"])
        self.assertEqual(registro["motivos_recomendacoes"], ampliada["motivos_recomendacoes"])
        self.assertEqual(storage.carregar_todas_musicas(), CATALOGO)

    def test_limites_inclusivos_nao_completam_catalogo_com_faixas_inventadas(self):
        for limite in (1, 10):
            with self.subTest(limite=limite):
                corpo = self.completa(limite_recomendacoes=limite)
                self.assertEqual(corpo["limite_recomendacoes"], limite)
                self.assertEqual(corpo["recomendacoes"], CATALOGO[:limite])
                self.conferir_motivos(corpo)

    def test_limite_na_criacao_exige_inteiro_estrito_antes_de_salvar(self):
        antes = self.historico.read_bytes()
        for limite in (None, False, True, 0, 11, 3.0, "5", [], {}):
            with self.subTest(limite=limite):
                resposta = self.client.post("/api/registrar-estado", json={
                    "texto_atual": RELATO, "limite_recomendacoes": limite,
                })
                self.assertEqual(resposta.status_code, 422, resposta.text)
                self.assertEqual(self.historico.read_bytes(), antes)

    def test_limite_invalido_na_retomada_nao_salva_nem_confirma_analise(self):
        identificador = self.criar()["sessao_id"]
        antes = self.historico.read_bytes()
        for limite in (False, True, 0, 11, 3.0, "5", [], {}):
            with self.subTest(limite=limite):
                resposta = self.retomar(
                    identificador, limite_recomendacoes=limite,
                    emocoes_confirmadas=["cansado"], texto_desejado="calmo",
                )
                self.assertEqual(resposta.status_code, 422, resposta.text)
                self.assertEqual(self.historico.read_bytes(), antes)

    def test_conflitos_pendentes_nao_alteram_quantidade_na_mesma_requisicao(self):
        identificador = self.criar(emocoes_confirmadas=["cansado"])["sessao_id"]
        antes = self.historico.read_bytes()
        for emocoes, status in ((["feliz"], 409), ([" "], 422)):
            with self.subTest(emocoes=emocoes):
                resposta = self.retomar(
                    identificador, limite_recomendacoes=5, emocoes_confirmadas=emocoes,
                )
                self.assertEqual(resposta.status_code, status)
                self.assertEqual(self.historico.read_bytes(), antes)

        with patch.object(api, "detectar_emocoes_no_texto", side_effect=RuntimeError("Falha fictícia")):
            falha = self.client.post("/api/registrar-estado", json={
                "texto_atual": RELATO, "emocoes_confirmadas": ["cansado"], "texto_desejado": "calmo",
            })
        self.assertEqual(falha.status_code, 500)
        identificador = falha.json()["detail"]["sessao_id"]
        antes = self.historico.read_bytes()
        resposta = self.retomar(identificador, limite_recomendacoes=5, texto_desejado="animado")
        self.assertEqual(resposta.status_code, 409)
        self.assertEqual(self.historico.read_bytes(), antes)

    def test_limite_pendente_e_preservado_por_omissao_ou_null(self):
        identificador = self.criar(limite_recomendacoes=5)["sessao_id"]
        for campos in ({}, {"limite_recomendacoes": None}):
            with self.subTest(campos=campos):
                antes = self.historico.read_bytes()
                resposta = self.retomar(identificador, **campos)
                self.assertEqual(resposta.status_code, 200, resposta.text)
                self.assertEqual(resposta.json()["limite_recomendacoes"], 5)
                self.assertEqual(self.historico.read_bytes(), antes)

    def test_alteracao_do_limite_e_salva_antes_de_falha_de_analise(self):
        identificador = self.criar()["sessao_id"]
        inicial = deepcopy(self.ler()[identificador])
        with patch.object(api, "detectar_emocoes_no_texto", side_effect=RuntimeError("Falha fictícia")):
            resposta = self.retomar(identificador, limite_recomendacoes=5)
        self.assertEqual(resposta.status_code, 500, resposta.text)
        self.assertEqual(resposta.json()["detail"]["sessao_id"], identificador)
        parcial = self.ler()[identificador]
        self.assertEqual(parcial["limite_recomendacoes"], 5)
        self.assertFalse(parcial["progresso"]["recomendacoes_geradas"])
        self.assertEqual(parcial["recomendacoes"], [])
        self.assertEqual(parcial["motivos_recomendacoes"], [])
        resposta = self.retomar(
            identificador, emocoes_confirmadas=["cansado"], texto_desejado="calmo",
        )
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertEqual(len(resposta.json()["recomendacoes"]), 5)
        self.assertEqual(len(self.ler()), 1)
        for campo in ("sessao_id", "data_hora", "texto_usuario"):
            self.assertEqual(self.ler()[identificador][campo], inicial[campo])

    def test_limite_concluido_e_idempotente_e_recusa_mudanca_inclusive_sem_faixas(self):
        for analise in ({"emocoes_confirmadas": ["cansado"], "texto_desejado": "calmo"},
                        {"emocoes_confirmadas": [], "texto_desejado": ""}):
            with self.subTest(analise=analise):
                identificador = self.criar(limite_recomendacoes=5, **analise)["sessao_id"]
                antes = self.historico.read_bytes()
                for campos in ({}, {"limite_recomendacoes": None}, {"limite_recomendacoes": 5}):
                    resposta = self.retomar(identificador, **campos)
                    self.assertEqual(resposta.status_code, 200, resposta.text)
                    self.assertEqual(self.historico.read_bytes(), antes)
                self.assertEqual(self.retomar(identificador, limite_recomendacoes=3).status_code, 409)
                self.assertEqual(self.historico.read_bytes(), antes)

    def test_retomada_e_consultas_nao_reclassificam_motivos_apos_mudar_catalogo(self):
        corpo = self.completa(limite_recomendacoes=5)
        identificador = corpo["sessao_id"]
        antes = self.historico.read_bytes()
        storage.salvar_json(storage.ARQ_MUSICAS, [])
        with patch.object(api, "recomendar_musicas", side_effect=AssertionError("Não recalcular")), \
             patch.object(api, "explicar_recomendacoes", side_effect=AssertionError("Não reexplicar")):
            retomada = self.retomar(identificador, limite_recomendacoes=5)
            self.assertEqual(retomada.status_code, 200, retomada.text)
            self.assertEqual(retomada.json()["motivos_recomendacoes"], corpo["motivos_recomendacoes"])
            consulta = self.client.get("/api/historico/sessao", params={"sessao_id": identificador})
            self.assertEqual(consulta.status_code, 200)
            self.assertEqual(consulta.json()["registro"]["motivos_recomendacoes"], corpo["motivos_recomendacoes"])
            self.assertEqual(self.client.get("/api/historico").status_code, 200)
        self.assertEqual(self.historico.read_bytes(), antes)

    def test_escolha_da_quinta_faixa_preserva_motivos_identidade_e_feedback(self):
        corpo = self.completa(limite_recomendacoes=5)
        identificador = corpo["sessao_id"]
        inicial = deepcopy(self.ler()[identificador])
        faixas = [{"indice_recomendacao": 5, "ouvida": True}]
        escolha = self.client.post("/api/escuta", json={"sessao_id": identificador, "faixas": faixas})
        self.assertEqual(escolha.status_code, 200, escolha.text)
        retorno = self.client.post("/api/feedback", json={
            "sessao_id": identificador, "ajudou": False, "motivo": "Exemplo fictício",
        })
        self.assertEqual(retorno.status_code, 200, retorno.text)
        atual = self.ler()[identificador]
        self.assertEqual(atual["escuta"], {"faixas": faixas})
        self.assertIs(atual["feedback"]["ajudou"], False)
        for campo in ("sessao_id", "data_hora", "texto_usuario", "recomendacoes", "motivos_recomendacoes"):
            self.assertEqual(atual[campo], inicial[campo])

    def test_falha_ao_explicar_conserva_etapas_anteriores_para_retomada(self):
        with patch.object(api, "explicar_recomendacoes", side_effect=RuntimeError("Falha fictícia")):
            resposta = self.client.post("/api/registrar-estado", json={
                "texto_atual": RELATO, "emocoes_confirmadas": ["cansado"],
                "texto_desejado": "calmo", "limite_recomendacoes": 5,
            })
        self.assertEqual(resposta.status_code, 500, resposta.text)
        identificador = resposta.json()["detail"]["sessao_id"]
        registro = self.ler()[identificador]
        self.assertEqual(registro["limite_recomendacoes"], 5)
        self.assertTrue(registro["progresso"]["emocoes_confirmadas"])
        self.assertTrue(registro["progresso"]["estado_desejado_informado"])
        self.assertFalse(registro["progresso"]["recomendacoes_geradas"])
        self.assertEqual(registro["recomendacoes"], [])
        self.assertEqual(registro["motivos_recomendacoes"], [])
        retomada = self.retomar(identificador)
        self.assertEqual(retomada.status_code, 200, retomada.text)
        self.assertEqual(len(self.ler()), 1)
        self.conferir_motivos(retomada.json())

    def test_escrita_final_e_atomica_para_musicas_motivos_e_progresso(self):
        atualizar_real = api.atualizar_sessao
        versao_anterior = []

        def falhar_na_etapa_final(caminho, identificador, **campos):
            if campos.get("progresso", {}).get("recomendacoes_geradas"):
                self.assertIn("recomendacoes", campos)
                self.assertIn("motivos_recomendacoes", campos)
                self.assertEqual(len(campos["recomendacoes"]), 5)
                self.assertEqual(len(campos["motivos_recomendacoes"]), 5)
                versao_anterior.append(self.historico.read_bytes())
                with patch.object(storage.os, "replace", side_effect=OSError("Falha fictícia")):
                    return atualizar_real(caminho, identificador, **campos)
            return atualizar_real(caminho, identificador, **campos)

        with patch.object(api, "atualizar_sessao", side_effect=falhar_na_etapa_final):
            resposta = self.client.post("/api/registrar-estado", json={
                "texto_atual": RELATO, "emocoes_confirmadas": ["cansado"],
                "texto_desejado": "calmo", "limite_recomendacoes": 5,
            })
        self.assertEqual(resposta.status_code, 503, resposta.text)
        self.assertEqual(len(versao_anterior), 1)
        self.assertEqual(self.historico.read_bytes(), versao_anterior[0])
        identificador = resposta.json()["detail"]["sessao_id"]
        anterior = self.ler()[identificador]
        self.assertEqual(anterior["recomendacoes"], [])
        self.assertEqual(anterior["motivos_recomendacoes"], [])
        self.assertFalse(anterior["progresso"]["recomendacoes_geradas"])
        self.assertEqual(list(self.historico.parent.glob(".rhythmmind-*.tmp")), [])
        retomada = self.retomar(identificador)
        self.assertEqual(retomada.status_code, 200, retomada.text)
        self.conferir_motivos(retomada.json())

    def test_legado_sem_motivos_nao_e_migrado_e_recusa_limite_retroativo(self):
        chave = "01/01/2000 10:00:00"
        legado = {
            "data_hora": chave, "texto_usuario": "Relato antigo fictício",
            "analise": {"emocoes": ["cansado"], "estado_desejado": ["calmo"]},
            "estrategia": "descompressao", "recomendacoes": CATALOGO[:3],
            "feedback": {"ajudou": False, "motivo": "Retorno fictício"},
        }
        storage.salvar_json(str(self.historico), {chave: legado})
        antes = self.historico.read_bytes()
        with patch.object(api, "recomendar_musicas", side_effect=AssertionError("Não recalcular")), \
             patch.object(api, "explicar_recomendacoes", side_effect=AssertionError("Não reexplicar")):
            for campos in ({}, {"limite_recomendacoes": None}):
                resposta = self.retomar(chave, **campos)
                self.assertEqual(resposta.status_code, 200, resposta.text)
                self.assertIsNone(resposta.json()["motivos_recomendacoes"])
                self.assertIsNone(resposta.json()["limite_recomendacoes"])
            consulta = self.client.get("/api/historico/sessao", params={"sessao_id": chave})
            self.assertEqual(consulta.status_code, 200)
            self.assertEqual(consulta.json()["registro"], legado)
            self.assertEqual(self.retomar(chave, limite_recomendacoes=3).status_code, 409)
        self.assertEqual(self.historico.read_bytes(), antes)

    def test_limite_e_motivos_continuam_protegidos_pela_conta(self):
        identificador = self.criar(limite_recomendacoes=5)["sessao_id"]
        antes = self.historico.read_bytes()
        anonimo = self.enterContext(TestClient(
            api.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50001),
        ))
        dados = {"sessao_id": identificador, "limite_recomendacoes": 7}
        self.assertEqual(anonimo.post("/api/retomar-sessao", json=dados).status_code, 401)
        credenciais = {"nome_usuario": "outra_conta_escolha", "senha": "senha-ficticia-escolha-123!"}
        self.assertEqual(anonimo.post("/api/auth/registrar", json=credenciais).status_code, 201)
        entrada = anonimo.post("/api/auth/entrar", json=credenciais)
        self.assertEqual(entrada.status_code, 200)
        headers = {"Authorization": "Bearer " + entrada.json()["token_acesso"]}
        self.assertEqual(anonimo.post("/api/retomar-sessao", json=dados, headers=headers).status_code, 404)
        consulta = anonimo.get("/api/historico", headers=headers)
        self.assertEqual(consulta.status_code, 200)
        self.assertEqual(consulta.json()["registros"], {})
        self.assertEqual(self.historico.read_bytes(), antes)

    def test_sem_categoria_atual_motivos_nao_inventam_confirmacao_emocional(self):
        corpo = self.criar(
            emocoes_confirmadas=[], texto_desejado="calmo", limite_recomendacoes=5,
        )
        self.assertEqual(corpo["emocoes_atuais"], [])
        self.assertEqual(len(corpo["recomendacoes"]), 5)
        self.conferir_motivos(corpo)
        for motivo in corpo["motivos_recomendacoes"]:
            self.assertNotIn("emocao_confirmada", [criterio["tipo"] for criterio in motivo["criterios"]])


if __name__ == "__main__":
    unittest.main()
