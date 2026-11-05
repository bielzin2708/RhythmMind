"""Adaptador externo com transporte falso no fluxo HTTP real e persistência isolada."""

from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from api import main as api
from core import storage
from core.interpretacao.base import BaseIndisponivel, carregar_base
from core.interpretacao.llm import InterpretadorLLM
from tests.apoio_autenticacao import ClienteAutenticado, dados_autenticados
from tests.test_interpretacao_api import CATALOGO, RELATO, proposta_ficticia


def proposta_llm():
    proposta = proposta_ficticia()
    for campo in ("estado_atual", "estado_desejado"):
        proposta[campo]["sugestoes"][0]["confianca_autodeclarada"] = None
    return {
        **proposta,
        "objetivos": ["estudar"], "contextos": ["estudar"],
        "resumo_reflexivo": "Talvez tristeza e vontade de se sentir feliz; confirme sua leitura.",
        "precisa_esclarecimento": False,
        "referencias_base": ["RM01", "RM05", "RM06"],
    }


class ClienteLLMFalso:
    def __init__(self, proposta=None, erro=None):
        self.proposta = proposta_llm() if proposta is None else proposta
        self.erro = erro
        self.chamadas = []

    def post_json(self, url, headers, payload, timeout):
        self.chamadas.append(deepcopy(payload))
        if self.erro:
            raise self.erro
        return {"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": json.dumps(self.proposta, ensure_ascii=False),
        }}]}


class InterpretacaoLLMApiTests(unittest.TestCase):
    def setUp(self):
        self.raiz = self.enterContext(dados_autenticados())
        storage.salvar_json(storage.ARQ_MUSICAS, deepcopy(CATALOGO))
        self.historico = Path(storage.resolver_caminho(storage.ARQ_HISTORICO))
        self.client = self.enterContext(ClienteAutenticado(
            api.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000),
        ))

    def criar(self):
        resposta = self.client.post("/api/registrar-estado", json={
            "texto_atual": RELATO, "finalidade": "estudar", "contexto": "Em casa",
        })
        self.assertEqual(resposta.status_code, 200, resposta.text)
        return resposta.json()["sessao_id"]

    def injetar(self, cliente, modelo="modelo-ficticio-v1"):
        motor = InterpretadorLLM(provedor="openai", modelo=modelo,
                                 chave="chave-ficticia-unitaria", cliente=cliente)
        self.enterContext(patch("api.interpretacao.criar_interpretador_llm_do_ambiente", return_value=motor))

    def interpretar(self, identificador, **campos):
        return self.client.post("/api/interpretacoes", json={
            "sessao_id": identificador, "motor": "llm", **campos,
        })

    def test_llm_salva_apenas_sugestoes_e_revisao_gera_musicas_do_catalogo(self):
        proposta = proposta_llm()
        transporte = ClienteLLMFalso(proposta)
        self.injetar(transporte)
        identificador = self.criar()
        antes = storage.carregar_json(str(self.historico), {})[identificador]
        resposta = self.interpretar(identificador)
        self.assertEqual(resposta.status_code, 200, resposta.text)
        corpo = resposta.json()
        self.assertEqual(corpo["motor_utilizado"], "llm")
        self.assertEqual((corpo["provedor"], corpo["modelo"]), ("openai", "modelo-ficticio-v1"))
        self.assertEqual(corpo["proposta"]["referencias_base"], ["RM01", "RM05", "RM06"])
        salvo = storage.carregar_json(str(self.historico), {})[identificador]
        self.assertEqual({k: v for k, v in salvo.items() if k != "interpretacao"}, antes)
        self.assertEqual(salvo["recomendacoes"], [])
        self.assertEqual(self.interpretar(identificador).json(), corpo)
        self.assertEqual(len(transporte.chamadas), 1)
        revisao = self.client.post("/api/revisoes-interpretacao", json={
            "sessao_id": identificador, "interpretacao_id": corpo["interpretacao_id"],
            "emocoes_confirmadas": ["triste"], "estado_desejado_confirmado": ["feliz"],
            "texto_desejado": "quero ficar feliz",
        })
        self.assertEqual(revisao.status_code, 200, revisao.text)
        self.assertTrue(revisao.json()["recomendacoes"])
        self.assertTrue(all(musica in CATALOGO for musica in revisao.json()["recomendacoes"]))
        self.assertEqual(len(transporte.chamadas), 1)

    def test_erro_externo_nao_muda_sessao_e_fallback_e_local_identificado(self):
        self.injetar(ClienteLLMFalso(erro=TimeoutError("chave-ficticia-unitaria")))
        identificador = self.criar()
        antes = self.historico.read_bytes()
        falha = self.interpretar(identificador)
        self.assertEqual(falha.status_code, 503)
        self.assertNotIn("chave-ficticia-unitaria", falha.text)
        self.assertEqual(self.historico.read_bytes(), antes)
        alternativa = self.interpretar(identificador, permitir_fallback_dicionario=True)
        self.assertEqual(alternativa.status_code, 200, alternativa.text)
        corpo = alternativa.json()
        self.assertEqual(corpo["fallback_motivo"], "falha_motor")
        self.assertEqual(corpo["motor_utilizado"], "dicionario")
        self.assertIsNone(corpo["provedor"])
        self.assertIsNone(corpo["modelo"])
        self.assertFalse(storage.carregar_json(str(self.historico), {})[identificador]["progresso"]["emocoes_confirmadas"])

    def test_saida_fora_do_contrato_exige_fallback_explicito(self):
        casos = []
        for campo, valor in (("objetivos", ["curar"]), ("referencias_base", ["RM99"]),
                             ("recomendacoes", [{"id": "inventado"}]),
                             ("resumo_reflexivo", "Você tem depressão com 99% de certeza.")):
            casos.append({**proposta_llm(), campo: valor})
        categoria_inventada = proposta_llm()
        categoria_inventada["estado_atual"]["sugestoes"][0]["categoria"] = "depressao"
        casos.append(categoria_inventada)
        for proposta in casos:
            with self.subTest(proposta=proposta):
                self.injetar(ClienteLLMFalso(proposta))
                identificador = self.criar()
                antes = self.historico.read_bytes()
                self.assertEqual(self.interpretar(identificador).status_code, 503)
                self.assertEqual(self.historico.read_bytes(), antes)
                alternativa = self.interpretar(identificador, permitir_fallback_dicionario=True)
                self.assertEqual(alternativa.status_code, 200, alternativa.text)
                self.assertEqual(alternativa.json()["fallback_motivo"], "saida_invalida")

    def test_motor_local_explicito_nao_chama_provedor_configurado(self):
        transporte = ClienteLLMFalso(erro=AssertionError("Não deve chamar rede"))
        self.injetar(transporte)
        resposta = self.interpretar(self.criar(), motor="dicionario")
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertEqual(transporte.chamadas, [])

    def test_modelo_configurado_alterado_invalida_reuso(self):
        proposta = proposta_llm()
        primeiro = ClienteLLMFalso(proposta)
        self.injetar(primeiro)
        identificador = self.criar()
        resposta = self.interpretar(identificador).json()
        segundo = ClienteLLMFalso(proposta)
        self.injetar(segundo, modelo="modelo-ficticio-v2")
        atualizada = self.interpretar(identificador)
        self.assertEqual(atualizada.status_code, 200, atualizada.text)
        self.assertNotEqual(resposta["interpretacao_id"], atualizada.json()["interpretacao_id"])
        self.assertEqual(len(segundo.chamadas), 1)


class SnapshotConhecimentoTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(dados_autenticados())

    def test_base_curada_ausente_ou_corrompida_falha_fechada(self):
        from core.interpretacao import base as modulo
        for conteudo in (None, "{", '{"versao":"v1","versao":"v2"}'):
            with self.subTest(conteudo=conteudo):
                arquivo = Path("base-curada-teste.json").resolve()
                if conteudo is not None:
                    arquivo.write_text(conteudo, encoding="utf-8")
                self.enterContext(patch.object(modulo, "ARQ_BASE_CONHECIMENTO", arquivo))
                with self.assertRaises(BaseIndisponivel):
                    carregar_base()

    def test_hash_detecta_mudanca_conceitual_e_snapshot_nao_compartilha_mutacao(self):
        from core.interpretacao import base as modulo
        primeiro = carregar_base()
        conhecimento = primeiro.conhecimento
        conhecimento["regras"][0]["enunciado"] += " Confirme com a pessoa."
        arquivo = Path("base-curada-modificada.json").resolve()
        arquivo.write_text(json.dumps(conhecimento, ensure_ascii=False), encoding="utf-8")
        with patch.object(modulo, "ARQ_BASE_CONHECIMENTO", arquivo):
            segundo = carregar_base()
        self.assertNotEqual(primeiro.sha256, segundo.sha256)
        self.assertNotEqual(primeiro.conhecimento, conhecimento)


if __name__ == "__main__":
    unittest.main()
