"""C01/C02: operações do titular com HTTP real e persistência fictícia A/B."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from api import main as api
from api.desenvolvimento import dados_ficticios_temporarios
from api.interpretacao import obter_motores
from core import storage
from core.contexto import contexto_usuario
from core.interpretacao.servico import MotoresInterpretacao
from tests.test_interpretacao_concorrencia import _MotorPausado


class TitularApiTests(unittest.TestCase):
    def setUp(self):
        self.raiz = self.enterContext(dados_ficticios_temporarios())
        self.anonimo = self.cliente()
        self.perfil_a, self.a, self.token_a = self.cadastrar("titular_a_ficticio")
        self.perfil_b, self.b, self.token_b = self.cadastrar("titular_b_ficticio")

    def cliente(self, token=None):
        return self.enterContext(TestClient(
            api.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000),
            headers={"Authorization": f"Bearer {token}"} if token else {},
        ))

    def cadastrar(self, nome):
        dados = {"nome_usuario": nome, "senha": "senha-ficticia-titular-123!"}
        cadastro = self.anonimo.post("/api/auth/registrar", json=dados)
        self.assertEqual(cadastro.status_code, 201, cadastro.text)
        entrada = self.anonimo.post("/api/auth/entrar", json=dados)
        self.assertEqual(entrada.status_code, 200, entrada.text)
        token = entrada.json()["token_acesso"]
        return cadastro.json(), self.cliente(token), token

    def arquivo(self, perfil):
        return self.raiz / "data/usuarios" / perfil["usuario_id"] / "historico.json"

    def criar(self, cliente, **campos):
        resposta = cliente.post("/api/registrar-estado", json={
            "texto_atual": "Estou triste e quero ficar feliz", "finalidade": "relaxar",
            "contexto": "Relato fictício para C01/C02", **campos,
        })
        self.assertEqual(resposta.status_code, 200, resposta.text)
        return resposta.json()["sessao_id"]

    def consultar(self, cliente, identificador):
        return cliente.get("/api/historico/sessao", params={"sessao_id": identificador})

    def corrigir(self, cliente, identificador, **campos):
        return cliente.patch("/api/historico/sessao", json={
            "sessao_id": identificador, "alteracoes": {"observacoes": "Observação corrigida fictícia"},
            **campos,
        })

    def test_c01_corrigir_reler_exportar_e_excluir_sem_tocar_b(self):
        id_a, id_b = self.criar(self.a), self.criar(self.b)
        antes_b = self.arquivo(self.perfil_b).read_bytes()
        original = self.consultar(self.a, id_a).json()["registro"]
        resposta = self.corrigir(self.a, id_a, alteracoes={
            "finalidade": "estudar", "contexto": "Em casa", "observacoes": "Correção fictícia C01",
        }, motivo="Corrigir a atividade registrada", revisao_esperada=0)
        self.assertEqual(resposta.status_code, 200, resposta.text)
        corrigido = resposta.json()["registro"]
        self.assertEqual(corrigido["finalidade"], "estudar")
        self.assertEqual(corrigido["revisao_registro"], 1)
        self.assertEqual(corrigido["correcoes"][0]["campos"]["finalidade"],
                         {"anterior": "relaxar", "novo": "estudar"})
        for campo in original.keys() - {"finalidade", "contexto"}:
            self.assertEqual(corrigido[campo], original[campo], campo)
        self.assertEqual(self.consultar(self.a, id_a).json()["registro"], corrigido)
        exportacao = self.a.get("/api/historico/exportacao")
        self.assertEqual(exportacao.status_code, 200, exportacao.text)
        self.assertEqual(exportacao.json()["registros"], {id_a: corrigido})
        self.assertEqual(exportacao.headers["cache-control"], "no-store")
        self.assertIn("attachment", exportacao.headers["content-disposition"])
        for segredo in (self.token_a, self.token_b, "senha-ficticia-titular-123!", id_b):
            self.assertNotIn(segredo, exportacao.text)
        exclusao = self.a.delete("/api/historico/sessao", params={"sessao_id": id_a})
        self.assertEqual(exclusao.status_code, 200, exclusao.text)
        self.assertEqual(exclusao.json()["total_excluido"], 1)
        self.assertEqual(self.consultar(self.a, id_a).status_code, 404)
        self.assertEqual(json.loads(self.arquivo(self.perfil_a).read_text()), {})
        self.assertNotIn("Correção fictícia C01", self.arquivo(self.perfil_a).read_text())
        self.assertEqual(self.a.get("/api/historico/exportacao").json()["total"], 0)
        self.assertEqual(self.arquivo(self.perfil_b).read_bytes(), antes_b)
        self.assertEqual(self.consultar(self.b, id_b).status_code, 200)

    def test_c02_sem_autenticacao_recusa_leitura_alteracao_exportacao_exclusao(self):
        id_a = self.criar(self.a)
        antes = self.arquivo(self.perfil_a).read_bytes()
        operacoes = [
            ("GET", "/api/historico", {}),
            ("GET", "/api/historico/sessao", {"params": {"sessao_id": id_a}}),
            ("GET", "/api/historico/exportacao", {}),
            ("PATCH", "/api/historico/sessao", {"json": {"sessao_id": id_a, "alteracoes": {"contexto": "X"}}}),
            ("DELETE", "/api/historico/sessao", {"params": {"sessao_id": id_a}}),
            ("DELETE", "/api/historico", {"params": {"confirmar": "true"}}),
        ]
        for headers in ({}, {"Authorization": "Bearer " + "a" * 43}):
            for metodo, rota, campos in operacoes:
                with self.subTest(metodo=metodo, rota=rota, credencial=bool(headers)):
                    resposta = self.anonimo.request(metodo, rota, headers=headers, **campos)
                    self.assertEqual(resposta.status_code, 401, resposta.text)
                    self.assertNotIn("Relato fictício", resposta.text)
        self.assertEqual(self.arquivo(self.perfil_a).read_bytes(), antes)

    def test_c02_a_nao_le_corrige_exporta_ou_exclui_registro_de_b(self):
        id_a, id_b = self.criar(self.a), self.criar(self.b, texto_atual="Relato exclusivo fictício de B")
        antes_b = self.arquivo(self.perfil_b).read_bytes()
        respostas = [
            self.consultar(self.a, id_b), self.corrigir(self.a, id_b),
            self.a.get("/api/historico/exportacao", params={"sessao_id": id_b}),
            self.a.delete("/api/historico/sessao", params={"sessao_id": id_b}),
        ]
        for resposta in respostas:
            self.assertEqual(resposta.status_code, 404, resposta.text)
            self.assertNotIn("Relato exclusivo", resposta.text)
        self.assertEqual(self.arquivo(self.perfil_b).read_bytes(), antes_b)
        self.assertEqual(set(self.a.get("/api/historico/exportacao").json()["registros"]), {id_a})
        self.assertEqual(self.corrigir(self.a, id_a).status_code, 200)

    def test_exclusao_total_exige_confirmacao_e_preserva_conta_catalogo_e_b(self):
        ids = {self.criar(self.a), self.criar(self.a)}
        self.criar(self.b)
        antes_b = self.arquivo(self.perfil_b).read_bytes()
        with contexto_usuario(self.perfil_a["usuario_id"], self.raiz):
            storage.salvar_json(storage.ARQ_MUSICAS, [{"nome": "Faixa fictícia preservada"}])
            catalogo = Path(storage.resolver_caminho(storage.ARQ_MUSICAS))
            antes_catalogo = catalogo.read_bytes()
        for params in ({}, {"confirmar": "false"}, {"confirmar": "true", "usuario_id": self.perfil_b["usuario_id"]}):
            self.assertEqual(self.a.delete("/api/historico", params=params).status_code, 422)
            self.assertEqual(set(json.loads(self.arquivo(self.perfil_a).read_text())), ids)
        excluido = self.a.delete("/api/historico", params={"confirmar": "true"})
        self.assertEqual(excluido.status_code, 200, excluido.text)
        self.assertEqual(set(excluido.json()["registros_excluidos"]), ids)
        self.assertEqual(self.a.get("/api/historico").json()["total"], 0)
        self.assertEqual(self.a.get("/api/auth/eu").status_code, 200)
        self.assertEqual(catalogo.read_bytes(), antes_catalogo)
        self.assertEqual(self.arquivo(self.perfil_b).read_bytes(), antes_b)
        self.assertEqual(self.a.delete("/api/historico", params={"confirmar": "true"}).json()["total_excluido"], 0)

    def test_exportacao_unica_e_nova_exportacao_refletem_correcao_sem_criar_copias(self):
        id_a, outro = self.criar(self.a), self.criar(self.a)
        exportacao = self.a.get("/api/historico/exportacao", params={"sessao_id": id_a})
        self.assertEqual(set(exportacao.json()["registros"]), {id_a})
        self.corrigir(self.a, id_a)
        nova = self.a.get("/api/historico/exportacao", params={"sessao_id": id_a})
        self.assertEqual(nova.json()["registros"][id_a]["observacoes"], "Observação corrigida fictícia")
        self.assertNotIn("observacoes", exportacao.json()["registros"][id_a])
        self.assertTrue(self.consultar(self.a, outro).json()["registro"])
        arquivos = list(self.arquivo(self.perfil_a).parent.iterdir())
        self.assertEqual([p.name for p in arquivos], ["historico.json"])

    def test_correcao_valida_limites_campos_e_referencia_sem_alterar_identidade(self):
        id_a = self.criar(self.a)
        antes = self.arquivo(self.perfil_a).read_bytes()
        casos = [
            {"alteracoes": {}}, {"alteracoes": {"texto_usuario": "outro relato"}},
            {"alteracoes": {"analise": {}}}, {"alteracoes": {"correcoes": []}},
            {"alteracoes": {"contexto": "X" * 501}}, {"alteracoes": {"observacoes": "X" * 4001}},
            {"alteracoes": {"finalidade": 42}}, {"revisao_esperada": True},
            {"revisao_esperada": -1}, {"usuario_id": self.perfil_b["usuario_id"]},
            {"data_hora": "legado"}, {"motivo": "X" * 501},
        ]
        for campos in casos:
            with self.subTest(campos=campos):
                resposta = self.corrigir(self.a, id_a, **campos)
                self.assertEqual(resposta.status_code, 422, resposta.text)
                self.assertEqual(self.arquivo(self.perfil_a).read_bytes(), antes)

    def test_rastreabilidade_sequencial_limpeza_e_versao_obsoleta(self):
        id_a = self.criar(self.a)
        r = self.corrigir(self.a, id_a, alteracoes={"observacoes": " Primeira "}, revisao_esperada=0)
        self.assertEqual(r.status_code, 200, r.text)
        antes = self.arquivo(self.perfil_a).read_bytes()
        self.assertEqual(self.corrigir(self.a, id_a, revisao_esperada=0).status_code, 409)
        self.assertEqual(self.arquivo(self.perfil_a).read_bytes(), antes)
        igual = self.corrigir(self.a, id_a, alteracoes={"observacoes": "Primeira"}, revisao_esperada=1)
        self.assertEqual(igual.json()["campos_alterados"], [])
        self.assertEqual(self.arquivo(self.perfil_a).read_bytes(), antes)
        r = self.corrigir(self.a, id_a, alteracoes={"observacoes": None}, revisao_esperada=1)
        registro = r.json()["registro"]
        self.assertEqual(registro["revisao_registro"], 2)
        self.assertEqual(registro["correcoes"][1]["campos"]["observacoes"], {"anterior": "Primeira", "novo": None})

    def test_rota_anterior_de_contexto_compartilha_rastreabilidade_da_correcao(self):
        id_a = self.criar(self.a)
        primeiro = self.corrigir(self.a, id_a, alteracoes={"contexto": "Correção A"})
        self.assertEqual(primeiro.status_code, 200, primeiro.text)
        antiga = self.a.post("/api/contexto-sessao", json={"sessao_id": id_a, "contexto": "Mudança B"})
        self.assertEqual(antiga.status_code, 200, antiga.text)
        self.assertEqual(set(antiga.json()), {"sessao_id", "finalidade", "contexto"})
        registro = self.consultar(self.a, id_a).json()["registro"]
        self.assertEqual(registro["revisao_registro"], 2)
        self.assertEqual(registro["correcoes"][-1]["campos"]["contexto"],
                         {"anterior": "Correção A", "novo": "Mudança B"})
        self.assertEqual(self.corrigir(self.a, id_a, revisao_esperada=1).status_code, 409)

    def test_correcoes_concorrentes_com_mesma_revisao_nao_sobrescrevem_decisao(self):
        id_a = self.criar(self.a)
        barreira = Barrier(2, timeout=5)

        def corrigir_depois_da_barreira(observacao):
            barreira.wait()
            return self.corrigir(self.a, id_a, alteracoes={"observacoes": observacao}, revisao_esperada=0)

        with ThreadPoolExecutor(max_workers=2) as executor:
            tarefas = [executor.submit(corrigir_depois_da_barreira, observacao)
                       for observacao in ("Correção concorrente A", "Correção concorrente B")]
            respostas = [tarefa.result(timeout=10) for tarefa in tarefas]
        self.assertEqual(sorted(r.status_code for r in respostas), [200, 409])
        vencedora = next(r.json()["registro"] for r in respostas if r.status_code == 200)
        registro = self.consultar(self.a, id_a).json()["registro"]
        self.assertEqual(registro, vencedora)
        self.assertEqual(len(registro["correcoes"]), 1)

    def test_nucleo_sem_contexto_autenticado_nao_acessa_historico_global(self):
        from core.titular import ErroTitular, corrigir_registro, excluir_registros, exportar_registros
        global_arquivo = self.raiz / storage.ARQ_HISTORICO
        antes = global_arquivo.read_bytes()
        for funcao, argumentos in ((exportar_registros, ()), (excluir_registros, ()),
                                  (corrigir_registro, ("ficticio", {"observacoes": "X"}))):
            with self.subTest(funcao=funcao.__name__), self.assertRaises(ErroTitular) as erro:
                funcao(*argumentos)
            self.assertEqual(erro.exception.status, 401)
            self.assertEqual(global_arquivo.read_bytes(), antes)

    def test_corrupcao_ou_falha_de_gravacao_nao_descarta_registros(self):
        id_a = self.criar(self.a)
        arquivo = self.arquivo(self.perfil_a)
        antes = arquivo.read_bytes()
        with patch("core.titular.storage.salvar_json", side_effect=OSError("Caminho privado fictício")):
            for resposta in (self.corrigir(self.a, id_a),
                             self.a.delete("/api/historico/sessao", params={"sessao_id": id_a}),
                             self.a.delete("/api/historico", params={"confirmar": "true"})):
                self.assertEqual(resposta.status_code, 503, resposta.text)
                self.assertNotIn("Caminho privado", resposta.text)
                self.assertEqual(arquivo.read_bytes(), antes)
        for invalido in (b"{", b"[]", b"\xff"):
            arquivo.write_bytes(invalido)
            for resposta in (self.corrigir(self.a, id_a), self.a.get("/api/historico/exportacao"),
                             self.a.delete("/api/historico", params={"confirmar": "true"})):
                self.assertEqual(resposta.status_code, 503, resposta.text)
                self.assertEqual(arquivo.read_bytes(), invalido)

    def test_registro_legado_por_chave_exata_pode_ser_corrigido_exportado_e_excluido(self):
        chave = "01/11/2026 10:00:00"
        with contexto_usuario(self.perfil_a["usuario_id"], self.raiz):
            storage.salvar_json(storage.ARQ_HISTORICO, {chave: {"texto_usuario": "Relato legado fictício"}})
        resposta = self.a.patch("/api/historico/sessao", json={"data_hora": chave, "alteracoes": {"observacoes": "Correção legada"}})
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertNotIn("sessao_id", resposta.json()["registro"])
        exportado = self.a.get("/api/historico/exportacao", params={"data_hora": chave})
        self.assertEqual(exportado.status_code, 200, exportado.text)
        self.assertEqual(set(exportado.json()["registros"]), {chave})
        self.assertEqual(self.a.delete("/api/historico/sessao", params={"data_hora": chave}).status_code, 200)
        self.assertEqual(json.loads(self.arquivo(self.perfil_a).read_text()), {})

    def test_exclusao_remove_interpretacao_correcoes_feedback_e_escuta(self):
        id_a = self.criar(self.a)
        self.assertEqual(self.a.post("/api/interpretacoes", json={"sessao_id": id_a}).status_code, 200)
        self.corrigir(self.a, id_a)
        with contexto_usuario(self.perfil_a["usuario_id"], self.raiz):
            registros = storage.carregar_json(storage.ARQ_HISTORICO, {})
            registros[id_a].update(feedback={"comentario": "Comentário fictício a remover"}, escuta={"observacao": "Escuta fictícia a remover"})
            storage.salvar_json(storage.ARQ_HISTORICO, registros)
        self.assertEqual(self.a.delete("/api/historico/sessao", params={"sessao_id": id_a}).status_code, 200)
        self.assertEqual(json.loads(self.arquivo(self.perfil_a).read_text()), {})
        self.assertEqual(self.a.get(f"/api/interpretacoes/{id_a}").status_code, 404)
        self.assertFalse(list(self.arquivo(self.perfil_a).parent.glob("*.tmp")))

    def test_interpretacao_em_andamento_nao_recria_sessao_excluida(self):
        id_a = self.criar(self.a)
        motor = _MotorPausado()
        with patch.dict(api.app.dependency_overrides, {obter_motores: lambda: MotoresInterpretacao(llm=motor)}):
            with ThreadPoolExecutor(max_workers=1) as executor:
                tarefa = executor.submit(self.a.post, "/api/interpretacoes", json={"sessao_id": id_a, "motor": "llm"})
                try:
                    self.assertTrue(motor.entrou.wait(timeout=5))
                    exclusao = self.a.delete("/api/historico/sessao", params={"sessao_id": id_a})
                    self.assertEqual(exclusao.status_code, 200, exclusao.text)
                finally:
                    motor.liberar.set()
                self.assertEqual(tarefa.result(timeout=5).status_code, 409)
        self.assertEqual(json.loads(self.arquivo(self.perfil_a).read_text()), {})

    def test_exportacao_e_exclusao_com_id_inexistente_nao_expoem_outros_dados(self):
        for referencia in (str(uuid4()), "../../usuarios/outro/historico.json"):
            with self.subTest(referencia=referencia):
                for resposta in (self.a.get("/api/historico/exportacao", params={"sessao_id": referencia}),
                                 self.a.delete("/api/historico/sessao", params={"sessao_id": referencia})):
                    self.assertEqual(resposta.status_code, 404, resposta.text)
        self.assertFalse(self.arquivo(self.perfil_a).exists())


if __name__ == "__main__":
    unittest.main()
