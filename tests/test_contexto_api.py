"""Finalidade, contexto e consultas HTTP sobre dados fictícios temporários."""

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import main as api
from core import storage
from core.feedback import resumir_avaliacoes
from tests.apoio_autenticacao import ClienteAutenticado, dados_autenticados


RELATO = "  Relato fictício: estou cansado.\n"


class _ContextoApiBase(unittest.TestCase):
    def setUp(self):
        self.raiz = self.enterContext(dados_autenticados())
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

    def editar(self, identificador, **campos):
        return self.client.post("/api/contexto-sessao", json={
            "sessao_id": identificador, **campos,
        })

    def cliente_sem_credencial(self):
        return self.enterContext(TestClient(
            api.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50001),
        ))


class ContextoSessaoApiTests(_ContextoApiBase):
    def test_criacao_preserva_relato_e_normaliza_metadados_sem_inferir_emocoes(self):
        resposta = self.criar(finalidade="  Ficar feliz  ", contexto="  Sem energia em casa\n")
        registro = self.ler()[resposta["sessao_id"]]
        self.assertEqual(registro["texto_usuario"], RELATO)
        self.assertEqual(registro["finalidade"], "Ficar feliz")
        self.assertEqual(registro["contexto"], "Sem energia em casa")
        self.assertEqual(resposta["finalidade"], registro["finalidade"])
        self.assertEqual(resposta["contexto"], registro["contexto"])
        self.assertEqual(registro["analise"]["emocoes"], [])
        self.assertEqual(registro["analise"]["estado_desejado"], [])
        self.assertFalse(registro["progresso"]["emocoes_confirmadas"])

    def test_criacao_ausente_nula_ou_branca_nao_inventa_finalidade_contexto(self):
        for campos in ({}, {"finalidade": None, "contexto": None},
                       {"finalidade": " \n", "contexto": "\t "}):
            with self.subTest(campos=campos):
                resposta = self.criar(**campos)
                registro = self.ler()[resposta["sessao_id"]]
                self.assertIn("finalidade", registro)
                self.assertIn("contexto", registro)
                self.assertIsNone(registro["finalidade"])
                self.assertIsNone(registro["contexto"])
                self.assertIsNone(resposta["finalidade"])
                self.assertIsNone(resposta["contexto"])

    def test_criacao_aceita_limites_e_recusa_tipos_ou_comprimento_sem_gravar(self):
        resposta = self.criar(finalidade="f" * 200, contexto="c" * 500)
        self.assertEqual(len(resposta["finalidade"]), 200)
        self.assertEqual(len(resposta["contexto"]), 500)
        antes = self.historico.read_bytes()
        for campos in ({"finalidade": "f" * 201}, {"contexto": "c" * 501},
                       {"finalidade": " " + "f" * 200}, {"contexto": 1},
                       {"finalidade": False}, {"contexto": ["casa"]}):
            with self.subTest(campos=campos):
                invalida = self.client.post("/api/registrar-estado", json={
                    "texto_atual": RELATO, **campos,
                })
                self.assertEqual(invalida.status_code, 422, invalida.text)
                self.assertEqual(self.historico.read_bytes(), antes)

    def test_metadados_nao_alteram_recomendacoes_para_a_mesma_analise(self):
        comum = {"emocoes_confirmadas": ["cansado"], "texto_desejado": "calmo"}
        sem = self.criar(**comum)
        com = self.criar(finalidade="Estudar", contexto="Treino fictício", **comum)
        self.assertNotEqual(sem["sessao_id"], com["sessao_id"])
        for campo in ("emocoes_atuais", "estado_desejado", "estrategia", "recomendacoes"):
            self.assertEqual(sem[campo], com[campo])

    def test_edicao_parcial_preserva_omitido_e_permite_limpar_explicitamente(self):
        identificador = self.criar(finalidade="Focar", contexto="Estudo")["sessao_id"]
        resposta = self.editar(identificador, finalidade="  Descansar  ")
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertEqual(self.ler()[identificador]["finalidade"], "Descansar")
        self.assertEqual(self.ler()[identificador]["contexto"], "Estudo")
        for campos in ({"finalidade": None}, {"contexto": "  \n"}):
            with self.subTest(campos=campos):
                self.assertEqual(self.editar(identificador, **campos).status_code, 200)
                for campo in campos:
                    self.assertIsNone(self.ler()[identificador][campo])

    def test_edicao_concluida_preserva_identidade_respostas_e_campos_legados(self):
        identificador = self.criar(
            finalidade="Focar", contexto="Estudo", emocoes_confirmadas=["cansado"],
            texto_desejado="calmo",
        )["sessao_id"]
        registros = self.ler()
        registros[identificador]["escuta"] = {"faixas": []}
        registros[identificador]["feedback"] = {"ajudou": False, "motivo": "Fictício"}
        registros[identificador]["extra_legado"] = {"observacao": "Fictícia"}
        storage.salvar_json(str(self.historico), registros)
        anterior = deepcopy(registros[identificador])
        with patch.object(api, "detectar_emocoes_no_texto", side_effect=AssertionError("Não reanalisar")), \
             patch.object(api, "recomendar_musicas", side_effect=AssertionError("Não recalcular")):
            resposta = self.editar(identificador, contexto="Em casa")
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertEqual(self.ler()[identificador], {**anterior, "contexto": "Em casa"})

    def test_edicao_invalida_ou_sem_campos_nao_grava(self):
        identificador = self.criar(finalidade="Focar", contexto="Estudo")["sessao_id"]
        antes = self.historico.read_bytes()
        for campos in ({}, {"finalidade": "f" * 201}, {"contexto": "c" * 501},
                       {"contexto": 23}, {"finalidade": {}},
                       {"texto_usuario": "Outro relato"},
                       {"contexto": "Casa", "usuario_id": "outro-perfil"}):
            with self.subTest(campos=campos):
                resposta = self.editar(identificador, **campos)
                self.assertEqual(resposta.status_code, 422, resposta.text)
                self.assertEqual(self.historico.read_bytes(), antes)
        resposta = self.client.post("/api/contexto-sessao", json={
            "sessao_id": identificador, "data_hora": identificador, "contexto": "Casa",
        })
        self.assertEqual(resposta.status_code, 422)
        self.assertEqual(self.historico.read_bytes(), antes)

    def test_edicao_inexistente_ou_erro_de_escrita_nao_perde_dados(self):
        identificador = self.criar(contexto="Estudo")["sessao_id"]
        antes = self.historico.read_bytes()
        self.assertEqual(self.editar("inexistente", contexto="Casa").status_code, 404)
        with patch.object(storage.os, "replace", side_effect=OSError("Falha fictícia")):
            resposta = self.editar(identificador, contexto="Casa")
        self.assertEqual(resposta.status_code, 503, resposta.text)
        self.assertEqual(self.historico.read_bytes(), antes)
        self.assertEqual(list(self.historico.parent.glob(".rhythmmind-*.tmp")), [])

    def test_edicao_de_legado_aceita_alias_sem_migrar_demais_campos(self):
        chave = "01/01/2000 10:00:00"
        legado = {
            "data_hora": chave, "texto_usuario": "Relato fictício antigo",
            "analise": {"emocoes": [], "estado_desejado": []}, "recomendacoes": [],
            "campo_desconhecido": {"preservar": True},
        }
        storage.salvar_json(str(self.historico), {chave: legado})
        resposta = self.client.post("/api/contexto-sessao", json={
            "data_hora": chave, "finalidade": "Descansar",
        })
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertEqual(self.ler(), {chave: {**legado, "finalidade": "Descansar"}})

    def test_metadados_e_filtros_exigem_autenticacao_e_isolam_contas(self):
        identificador = self.criar(finalidade="Focar", contexto="Estudo")["sessao_id"]
        antes = self.historico.read_bytes()
        anonimo = self.cliente_sem_credencial()
        dados = {"sessao_id": identificador, "contexto": "Outra conta"}
        self.assertEqual(anonimo.post("/api/contexto-sessao", json=dados).status_code, 401)
        self.assertEqual(anonimo.get("/api/historico", params={"finalidade": "Focar"}).status_code, 401)
        credenciais = {"nome_usuario": "outra_conta_contexto", "senha": "senha-ficticia-contexto-123!"}
        self.assertEqual(anonimo.post("/api/auth/registrar", json=credenciais).status_code, 201)
        entrada = anonimo.post("/api/auth/entrar", json=credenciais)
        self.assertEqual(entrada.status_code, 200)
        headers = {"Authorization": "Bearer " + entrada.json()["token_acesso"]}
        self.assertEqual(anonimo.post("/api/contexto-sessao", json=dados, headers=headers).status_code, 404)
        consulta = anonimo.get("/api/historico", params={"finalidade": "Focar"}, headers=headers)
        self.assertEqual(consulta.status_code, 200)
        self.assertEqual(consulta.json()["registros"], {})
        self.assertEqual(consulta.json()["total"], 0)
        self.assertEqual(self.historico.read_bytes(), antes)


class HistoricoFiltradoApiTests(_ContextoApiBase):
    def setUp(self):
        super().setUp()
        self.registros = {
            "negativo": self.registro("04/11/2026 00:00:00", {"ajudou": False}),
            "positivo": self.registro("04/11/2026 23:59:59", {"ajudou": True}),
            "outro_dia": self.registro("05/11/2026 10:00:00", None, finalidade="Descansar"),
            "legado_sem_data": self.registro("Data fictícia inválida", None),
        }
        storage.salvar_json(str(self.historico), self.registros)

    @staticmethod
    def registro(data_hora, feedback, *, finalidade="Concentração"):
        return {
            "data_hora": data_hora, "texto_usuario": "Relato fictício: cansado",
            "finalidade": finalidade, "contexto": "Estudo em casa",
            "analise": {"emocoes": ["cansado"], "estado_desejado": []},
            "recomendacoes": [], "feedback": feedback,
        }

    def test_historico_sem_filtro_preserva_registros_e_resumo_anteriores(self):
        antes = self.historico.read_bytes()
        resposta = self.client.get("/api/historico")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json()["registros"], self.registros)
        self.assertEqual(resposta.json()["total"], 4)
        self.assertEqual(resposta.json()["avaliacoes_sessoes"], resumir_avaliacoes(self.registros))
        self.assertEqual(self.historico.read_bytes(), antes)

    def test_filtros_combinados_resumem_so_o_recorte_sem_mudar_padroes_gerais(self):
        antes = self.historico.read_bytes()
        filtros = {"data_inicio": "2026-11-04", "data_fim": "2026-11-04",
                   "finalidade": "CONCENTRACAO", "contexto": "estudo"}
        resposta = self.client.get("/api/historico", params=filtros)
        self.assertEqual(resposta.status_code, 200, resposta.text)
        recorte = {chave: self.registros[chave] for chave in ("negativo", "positivo")}
        self.assertEqual(resposta.json()["registros"], recorte)
        self.assertEqual(resposta.json()["total"], 2)
        self.assertEqual(resposta.json()["avaliacoes_sessoes"], resumir_avaliacoes(recorte))
        filtros["avaliacao"] = "negativo"
        negativa = self.client.get("/api/historico", params=filtros)
        self.assertEqual(negativa.status_code, 200)
        self.assertEqual(negativa.json()["registros"], {"negativo": self.registros["negativo"]})
        self.assertEqual(negativa.json()["avaliacoes_sessoes"],
                         resumir_avaliacoes({"negativo": self.registros["negativo"]}))
        padroes = self.client.get("/api/padroes")
        self.assertEqual(padroes.status_code, 200)
        self.assertEqual(padroes.json()["avaliacoes_sessoes"], resumir_avaliacoes(self.registros))
        self.assertEqual(self.historico.read_bytes(), antes)

    def test_filtro_sem_resultados_retorna_200_e_resumo_zerado(self):
        antes = self.historico.read_bytes()
        resposta = self.client.get("/api/historico", params={"contexto": "contexto inexistente"})
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json()["registros"], {})
        self.assertEqual(resposta.json()["total"], 0)
        self.assertEqual(resposta.json()["avaliacoes_sessoes"], resumir_avaliacoes({}))
        self.assertEqual(self.historico.read_bytes(), antes)

    def test_filtros_invalidos_sao_422_sem_escrita(self):
        antes = self.historico.read_bytes()
        for filtros in ({"data_inicio": "04/11/2026"}, {"data_fim": "2026-02-30"},
                        {"data_inicio": "2026-11-05", "data_fim": "2026-11-04"},
                        {"avaliacao": "false"}, {"contexto": " "}, {"finalidade": ""}):
            with self.subTest(filtros=filtros):
                resposta = self.client.get("/api/historico", params=filtros)
                self.assertEqual(resposta.status_code, 422, resposta.text)
                self.assertEqual(self.historico.read_bytes(), antes)


if __name__ == "__main__":
    unittest.main()
