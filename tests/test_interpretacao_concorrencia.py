"""Concorrência HTTP controlada e preservação de decisões de contas fictícias."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Barrier, Event
import unittest
from unittest.mock import patch

from api import main as api
from api.interpretacao import obter_motores
from core import storage
from core.interpretacao import servico
from tests.apoio_autenticacao import ClienteAutenticado, dados_autenticados


RELATO = "Estou triste e quero ficar feliz"
CATALOGO = [
    {"id": "faixa_ficticia_triste", "nome": "Faixa Inventada Triste",
     "artista": "Artista Fictício", "sentimentos_associados": ["triste"],
     "estrategias": ["transicao_emocional"]},
    {"id": "faixa_ficticia_cansado", "nome": "Faixa Inventada Cansado",
     "artista": "Artista Fictício", "sentimentos_associados": ["cansado"],
     "estrategias": ["descompressao"]},
]


def _proposta_ficticia():
    def parte(categoria):
        return {
            "estado": "sugestoes",
            "sugestoes": [{"categoria": categoria, "evidencias": [categoria],
                           "confianca_autodeclarada": "media"}],
            "ambiguidades": [], "resumo": "Sugestão fictícia para revisão.",
        }
    return {"estado_atual": parte("triste"), "estado_desejado": parte("feliz"),
            "texto_intencao": "quero ficar feliz"}


class _MotorFicticio:
    origem = "mock"
    identificador = "concorrencia-ficticia-v1"

    def interpretar(self, texto_original, texto_desejado, base):
        return _proposta_ficticia()


class _MotorPausado(_MotorFicticio):
    def __init__(self):
        self.entrou = Event()
        self.liberar = Event()

    def interpretar(self, texto_original, texto_desejado, base):
        self.entrou.set()
        if not self.liberar.wait(timeout=5):
            raise AssertionError("A operação concorrente não liberou o motor fictício.")
        return super().interpretar(texto_original, texto_desejado, base)


class InterpretacaoConcorrenciaTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(dados_autenticados())
        storage.salvar_json(storage.ARQ_MUSICAS, deepcopy(CATALOGO))
        self.historico = Path(storage.resolver_caminho(storage.ARQ_HISTORICO))
        # Os headers são construídos na thread da fixture. Cada requisição
        # autentica a credencial real e estabelece seu próprio contexto pessoal.
        self.client = self.enterContext(ClienteAutenticado(
            api.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000),
        ))

    def criar(self, **campos):
        resposta = self.client.post("/api/registrar-estado", json={
            "texto_atual": RELATO, "limite_recomendacoes": 1, **campos,
        })
        self.assertEqual(resposta.status_code, 200, resposta.text)
        return resposta.json()["sessao_id"]

    def interpretar(self, sessao_id, **campos):
        return self.client.post("/api/interpretacoes", json={
            "sessao_id": sessao_id, **campos,
        })

    def rascunho(self, sessao_id, **campos):
        resposta = self.interpretar(sessao_id, **campos)
        self.assertEqual(resposta.status_code, 200, resposta.text)
        return resposta.json()

    def revisar(self, sessao_id, interpretacao_id, *, cansado=False):
        return self.client.post("/api/revisoes-interpretacao", json={
            "sessao_id": sessao_id, "interpretacao_id": interpretacao_id,
            "emocoes_confirmadas": ["cansado" if cansado else "triste"],
            "estado_desejado_confirmado": ["calmo" if cansado else "feliz"],
            "texto_desejado": "quero ficar calmo" if cansado else "quero ficar feliz",
        })

    def injetar(self, motor):
        self.enterContext(patch.dict(api.app.dependency_overrides, {
            obter_motores: lambda: servico.MotoresInterpretacao(llm=motor),
        }))

    def verificar_revisao_salva(self, sessao_id, resposta):
        corpo = resposta.json()
        registro = storage.carregar_json(str(self.historico), {}, estrito=True)[sessao_id]
        for campo in ("interpretacao", "analise", "texto_desejado", "recomendacoes",
                      "motivos_recomendacoes", "limite_recomendacoes", "progresso"):
            self.assertEqual(registro[campo], corpo[campo])
        self.assertEqual(corpo["interpretacao"]["estado_revisao"], "revisada")
        self.assertTrue(all(corpo["progresso"].values()))
        categoria = corpo["analise"]["emocoes"][0]
        self.assertEqual([musica["id"] for musica in corpo["recomendacoes"]],
                         ["faixa_ficticia_" + categoria])
        self.assertEqual(len(corpo["motivos_recomendacoes"]), 1)
        return corpo

    def test_duas_revisoes_conflitantes_salvam_so_a_decisao_vencedora(self):
        sessao_id = self.criar()
        rascunho = self.rascunho(sessao_id)
        barreira = Barrier(2, timeout=5)
        recomendar_original = servico.recomendar_musicas

        def recomendar_depois_das_duas_leituras(*args, **kwargs):
            barreira.wait()
            return recomendar_original(*args, **kwargs)

        with patch.object(servico, "recomendar_musicas",
                          side_effect=recomendar_depois_das_duas_leituras):
            with ThreadPoolExecutor(max_workers=2) as executor:
                tarefas = [executor.submit(self.revisar, sessao_id,
                                            rascunho["interpretacao_id"], cansado=valor)
                           for valor in (False, True)]
                respostas = [tarefa.result(timeout=10) for tarefa in tarefas]
        self.assertEqual(sorted(resposta.status_code for resposta in respostas), [200, 409],
                         [resposta.text for resposta in respostas])
        vencedora = next(resposta for resposta in respostas if resposta.status_code == 200)
        corpo = self.verificar_revisao_salva(sessao_id, vencedora)
        antes = self.historico.read_bytes()
        cansado_venceu = corpo["analise"]["emocoes"] == ["cansado"]
        repetida_perdedora = self.revisar(sessao_id, rascunho["interpretacao_id"],
                                         cansado=not cansado_venceu)
        self.assertEqual(repetida_perdedora.status_code, 409, repetida_perdedora.text)
        self.assertEqual(self.historico.read_bytes(), antes)
        consulta = self.client.get(f"/api/interpretacoes/{sessao_id}")
        self.assertEqual(consulta.status_code, 200, consulta.text)
        self.assertEqual(consulta.json(), corpo["interpretacao"])

    def test_motor_lento_nao_ressuscita_rascunho_depois_da_revisao(self):
        sessao_id = self.criar()
        anterior = self.rascunho(sessao_id)
        motor = _MotorPausado()
        self.injetar(motor)
        with ThreadPoolExecutor(max_workers=1) as executor:
            tarefa = executor.submit(self.interpretar, sessao_id, motor="llm", regenerar=True)
            try:
                self.assertTrue(motor.entrou.wait(timeout=5), "O motor não iniciou.")
                revisao = self.revisar(sessao_id, anterior["interpretacao_id"])
                self.assertEqual(revisao.status_code, 200, revisao.text)
                corpo = self.verificar_revisao_salva(sessao_id, revisao)
                antes = self.historico.read_bytes()
            finally:
                motor.liberar.set()
            atrasada = tarefa.result(timeout=10)
        self.assertEqual(atrasada.status_code, 409, atrasada.text)
        self.assertEqual(self.historico.read_bytes(), antes)
        consulta = self.client.get(f"/api/interpretacoes/{sessao_id}")
        self.assertEqual(consulta.status_code, 200, consulta.text)
        self.assertEqual(consulta.json(), corpo["interpretacao"])

    def test_motor_lento_nao_substitui_regeneracao_mais_recente(self):
        sessao_id = self.criar()
        anterior = self.rascunho(sessao_id)
        motor = _MotorPausado()
        self.injetar(motor)
        with ThreadPoolExecutor(max_workers=1) as executor:
            tarefa = executor.submit(self.interpretar, sessao_id, motor="llm", regenerar=True)
            try:
                self.assertTrue(motor.entrou.wait(timeout=5), "O motor não iniciou.")
                vigente = self.rascunho(sessao_id, regenerar=True)
                self.assertNotEqual(vigente["interpretacao_id"], anterior["interpretacao_id"])
                antes = self.historico.read_bytes()
            finally:
                motor.liberar.set()
            atrasada = tarefa.result(timeout=10)
        self.assertEqual(atrasada.status_code, 409, atrasada.text)
        self.assertEqual(self.historico.read_bytes(), antes)
        consulta = self.client.get(f"/api/interpretacoes/{sessao_id}")
        self.assertEqual(consulta.status_code, 200, consulta.text)
        self.assertEqual(consulta.json(), vigente)
        antiga = self.revisar(sessao_id, anterior["interpretacao_id"])
        self.assertEqual(antiga.status_code, 409, antiga.text)
        self.assertEqual(self.historico.read_bytes(), antes)

    def test_fluxo_antigo_atrasado_nao_sobrescreve_revisao_nova(self):
        sessao_id = self.criar()
        rascunho = self.rascunho(sessao_id)
        entrou = Event()
        liberar = Event()
        salvar_original = api._salvar_etapa_api

        def salvar_depois_da_revisao(*args, **kwargs):
            entrou.set()
            if not liberar.wait(timeout=5):
                raise AssertionError("A revisão não liberou a gravação antiga.")
            return salvar_original(*args, **kwargs)

        with patch.object(api, "_salvar_etapa_api", side_effect=salvar_depois_da_revisao):
            with ThreadPoolExecutor(max_workers=1) as executor:
                tarefa = executor.submit(self.client.post, "/api/retomar-sessao", json={
                    "sessao_id": sessao_id, "emocoes_confirmadas": ["cansado"],
                    "texto_desejado": "quero ficar calmo",
                })
                try:
                    self.assertTrue(entrou.wait(timeout=5), "O fluxo antigo não iniciou a gravação.")
                    revisao = self.revisar(sessao_id, rascunho["interpretacao_id"])
                    self.assertEqual(revisao.status_code, 200, revisao.text)
                    corpo = self.verificar_revisao_salva(sessao_id, revisao)
                    antes = self.historico.read_bytes()
                finally:
                    liberar.set()
                atrasada = tarefa.result(timeout=10)
        self.assertEqual(atrasada.status_code, 409, atrasada.text)
        self.assertEqual(self.historico.read_bytes(), antes)
        consulta = self.client.get(f"/api/interpretacoes/{sessao_id}")
        self.assertEqual(consulta.status_code, 200, consulta.text)
        self.assertEqual(consulta.json(), corpo["interpretacao"])

    def test_desejo_vazio_nao_aceita_evidencia_do_relato_e_fallback_e_explicito(self):
        sessao_id = self.criar(texto_desejado="")
        self.injetar(_MotorFicticio())
        antes = self.historico.read_bytes()
        invalida = self.interpretar(sessao_id, motor="llm")
        self.assertEqual(invalida.status_code, 503, invalida.text)
        self.assertEqual(self.historico.read_bytes(), antes)
        self.assertNotIn("interpretacao", storage.carregar_json(
            str(self.historico), {}, estrito=True,
        )[sessao_id])
        alternativa = self.rascunho(sessao_id, motor="llm", permitir_fallback_dicionario=True)
        self.assertEqual(alternativa["motor_solicitado"], "llm")
        self.assertEqual(alternativa["motor_utilizado"], "dicionario")
        self.assertEqual(alternativa["fallback_motivo"], "saida_invalida")
        self.assertEqual(alternativa["proposta"]["estado_desejado"]["sugestoes"], [])
        self.assertIsNone(alternativa["revisao"])
        registro = storage.carregar_json(str(self.historico), {}, estrito=True)[sessao_id]
        self.assertEqual(registro["texto_desejado"], "")
        self.assertFalse(registro["progresso"]["emocoes_confirmadas"])
        self.assertEqual(registro["recomendacoes"], [])


if __name__ == "__main__":
    unittest.main()
