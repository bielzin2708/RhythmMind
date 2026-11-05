"""Interpretação e revisão HTTP reais com relatos e faixas fictícios."""

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from api import main as api
from core import storage
from tests.apoio_autenticacao import ClienteAutenticado, dados_autenticados


RELATO = "Estou triste e quero ficar feliz"
CATALOGO = [
    {"id": f"faixa_ficticia_{indice}", "nome": f"Faixa Inventada {indice}",
     "artista": "Artista Fictício", "sentimentos_associados": ["triste", "calmo"],
     "estrategias": ["transicao_emocional", "descompressao", "espelhamento"]}
    for indice in range(1, 7)
]


def proposta_ficticia():
    def parte(categoria):
        return {
            "estado": "sugestoes",
            "sugestoes": [{"categoria": categoria, "evidencias": [categoria],
                           "confianca_autodeclarada": "media"}],
            "ambiguidades": [], "resumo": "Interpretação fictícia para revisão.",
        }
    return {"estado_atual": parte("triste"), "estado_desejado": parte("feliz"),
            "texto_intencao": "quero ficar feliz"}


class MotorFicticio:
    origem = "mock"
    identificador = "fake-v1"

    def __init__(self, resultado=None, erro=None):
        self.resultado = proposta_ficticia() if resultado is None else resultado
        self.erro = erro
        self.chamadas = []

    def interpretar(self, texto_original, texto_desejado, base):
        self.chamadas.append((texto_original, texto_desejado, base))
        if self.erro is not None:
            raise self.erro
        return deepcopy(self.resultado)


class InterpretacaoApiTests(unittest.TestCase):
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
        return resposta.json()["sessao_id"]

    def interpretar(self, identificador, **campos):
        return self.client.post("/api/interpretacoes", json={"sessao_id": identificador, **campos})

    def rascunho(self, sessao_id, **campos):
        resposta = self.interpretar(sessao_id, **campos)
        self.assertEqual(resposta.status_code, 200, resposta.text)
        return resposta.json()

    def revisar(self, sessao_id, interpretacao_id, **campos):
        return self.client.post("/api/revisoes-interpretacao", json={
            "sessao_id": sessao_id, "interpretacao_id": interpretacao_id,
            "emocoes_confirmadas": ["triste"], "estado_desejado_confirmado": ["feliz"],
            "texto_desejado": "quero ficar feliz", **campos,
        })

    def injetar(self, motor):
        from api.interpretacao import obter_motores
        from core.interpretacao.servico import MotoresInterpretacao
        self.enterContext(patch.dict(api.app.dependency_overrides, {
            obter_motores: lambda: MotoresInterpretacao(llm=motor),
        }))

    def test_dicionario_separa_relato_intencao_e_so_confirma_apos_revisao(self):
        identificador = self.criar(limite_recomendacoes=5)
        inicial = deepcopy(self.ler()[identificador])
        corpo = self.rascunho(identificador)
        self.assertEqual(corpo["sessao_id"], identificador)
        self.assertEqual(corpo["motor_solicitado"], "dicionario")
        self.assertEqual(corpo["motor_utilizado"], "dicionario")
        self.assertIsNone(corpo["fallback_motivo"])
        self.assertIsNone(corpo["revisao"])
        self.assertEqual(corpo["estado_revisao"], "pendente")
        self.assertRegex(corpo["base_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(corpo["hash_entrada"], r"^[0-9a-f]{64}$")
        self.assertTrue(corpo["motor_versao"])
        for campo, categoria in (("estado_atual", "triste"), ("estado_desejado", "feliz")):
            parte = corpo["proposta"][campo]
            self.assertEqual(parte["estado"], "sugestoes")
            self.assertEqual([s["categoria"] for s in parte["sugestoes"]], [categoria])
            self.assertEqual(parte["sugestoes"][0]["evidencias"], [])
            self.assertIsNone(parte["sugestoes"][0]["confianca_autodeclarada"])
        pendente = self.ler()[identificador]
        self.assertEqual(pendente["analise"], {"emocoes": [], "estado_desejado": []})
        self.assertFalse(pendente["progresso"]["emocoes_confirmadas"])
        self.assertFalse(pendente["progresso"]["estado_desejado_informado"])
        self.assertEqual(pendente["recomendacoes"], [])
        resposta = self.revisar(identificador, corpo["interpretacao_id"])
        self.assertEqual(resposta.status_code, 200, resposta.text)
        revisada = resposta.json()
        self.assertEqual(revisada["analise"], {"emocoes": ["triste"], "estado_desejado": ["feliz"]})
        self.assertEqual(revisada["texto_desejado"], "quero ficar feliz")
        self.assertEqual(revisada["limite_recomendacoes"], 5)
        self.assertEqual(len(revisada["recomendacoes"]), 5)
        self.assertEqual(len(revisada["motivos_recomendacoes"]), 5)
        self.assertTrue(all(musica in CATALOGO for musica in revisada["recomendacoes"]))
        self.assertTrue(all(revisada["progresso"].values()))
        self.assertIsInstance(revisada["interpretacao"]["revisao"], dict)
        self.assertEqual(revisada["interpretacao"]["estado_revisao"], "revisada")
        registro = self.ler()[identificador]
        self.assertEqual(registro["interpretacao"], revisada["interpretacao"])
        for campo in ("sessao_id", "data_hora", "texto_usuario"):
            self.assertEqual(registro[campo], inicial[campo])

    def test_get_nao_gera_rascunho_e_consulta_nao_regrava_snapshot(self):
        identificador = self.criar()
        antes = self.historico.read_bytes()
        self.assertEqual(self.client.get(f"/api/interpretacoes/{identificador}").status_code, 404)
        self.assertEqual(self.historico.read_bytes(), antes)
        corpo = self.rascunho(identificador)
        antes = self.historico.read_bytes()
        resposta = self.client.get(f"/api/interpretacoes/{identificador}")
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertEqual(resposta.json(), corpo)
        self.assertEqual(self.historico.read_bytes(), antes)

    def test_mock_tem_origem_explicita_e_cache_nao_reexecuta_nem_regrava(self):
        motor = MotorFicticio()
        self.injetar(motor)
        identificador = self.criar()
        primeiro = self.rascunho(identificador, motor="llm")
        self.assertEqual(primeiro["motor_solicitado"], "llm")
        self.assertEqual(primeiro["motor_utilizado"], "mock")
        self.assertEqual(primeiro["motor_versao"], "fake-v1")
        self.assertIsNone(primeiro["fallback_motivo"])
        antes = self.historico.read_bytes()
        self.assertEqual(self.rascunho(identificador, motor="llm"), primeiro)
        self.assertEqual(self.historico.read_bytes(), antes)
        self.assertEqual(len(motor.chamadas), 1)
        self.assertEqual(motor.chamadas[0][:2], (RELATO, None))

    def test_regenerar_invalida_identificador_anterior_sem_confirmar(self):
        motor = MotorFicticio()
        self.injetar(motor)
        identificador = self.criar()
        anterior = self.rascunho(identificador, motor="llm")
        atual = self.rascunho(identificador, motor="llm", regenerar=True)
        self.assertNotEqual(anterior["interpretacao_id"], atual["interpretacao_id"])
        self.assertEqual(len(motor.chamadas), 2)
        antes = self.historico.read_bytes()
        self.assertEqual(self.revisar(identificador, anterior["interpretacao_id"]).status_code, 409)
        self.assertEqual(self.historico.read_bytes(), antes)
        self.assertEqual(self.client.get(f"/api/interpretacoes/{identificador}").json(), atual)

    def test_metadados_nao_entram_no_hash_mas_texto_desejado_altera_entrada(self):
        motor = MotorFicticio()
        self.injetar(motor)
        identificador = self.criar(finalidade="Estudar", contexto="Casa")
        primeiro = self.rascunho(identificador, motor="llm")
        historico = self.ler()
        historico[identificador].update(finalidade="Descansar", contexto="Quarto")
        storage.salvar_json(str(self.historico), historico)
        antes = self.historico.read_bytes()
        self.assertEqual(self.rascunho(identificador, motor="llm"), primeiro)
        self.assertEqual(self.historico.read_bytes(), antes)
        self.assertEqual(len(motor.chamadas), 1)
        historico = self.ler()
        historico[identificador]["texto_desejado"] = "quero ficar calmo"
        storage.salvar_json(str(self.historico), historico)
        motor.resultado["estado_desejado"]["sugestoes"][0].update(
            categoria="calmo", evidencias=["calmo"],
        )
        segundo = self.rascunho(identificador, motor="llm")
        self.assertNotEqual(primeiro["hash_entrada"], segundo["hash_entrada"])
        self.assertNotEqual(primeiro["interpretacao_id"], segundo["interpretacao_id"])
        self.assertEqual(len(motor.chamadas), 2)
        self.assertEqual(motor.chamadas[-1][:2], (RELATO, "quero ficar calmo"))
        antes = self.historico.read_bytes()
        resposta = self.revisar(identificador, segundo["interpretacao_id"])
        self.assertEqual(resposta.status_code, 409, resposta.text)
        self.assertEqual(self.historico.read_bytes(), antes)

    def test_llm_indisponivel_exige_fallback_explicito_e_rotula_origem(self):
        identificador = self.criar()
        antes = self.historico.read_bytes()
        resposta = self.interpretar(identificador, motor="llm")
        self.assertEqual(resposta.status_code, 503, resposta.text)
        self.assertEqual(self.historico.read_bytes(), antes)
        corpo = self.rascunho(identificador, motor="llm", permitir_fallback_dicionario=True)
        self.assertEqual(corpo["motor_solicitado"], "llm")
        self.assertEqual(corpo["motor_utilizado"], "dicionario")
        self.assertEqual(corpo["fallback_motivo"], "indisponivel")
        self.assertIsNone(corpo["revisao"])

    def test_saida_mock_sem_evidencia_literal_extra_ou_json_invalido_nao_salva(self):
        sem_evidencia = proposta_ficticia()
        sem_evidencia["estado_atual"]["sugestoes"][0]["evidencias"] = []
        evidencia_inventada = proposta_ficticia()
        evidencia_inventada["estado_atual"]["sugestoes"][0]["evidencias"] = ["nunca foi escrito"]
        com_autoridade = {**proposta_ficticia(), "sessao_id": str(uuid4()),
                          "progresso": {"recomendacoes_geradas": True}}
        for saida in (sem_evidencia, evidencia_inventada, com_autoridade, "{json inválido"):
            with self.subTest(saida=saida):
                motor = MotorFicticio(resultado=saida)
                self.injetar(motor)
                identificador = self.criar()
                antes = self.historico.read_bytes()
                resposta = self.interpretar(identificador, motor="llm")
                self.assertEqual(resposta.status_code, 503, resposta.text)
                self.assertEqual(self.historico.read_bytes(), antes)
                corpo = self.rascunho(identificador, motor="llm", permitir_fallback_dicionario=True)
                self.assertEqual(corpo["motor_utilizado"], "dicionario")
                self.assertEqual(corpo["fallback_motivo"], "saida_invalida")
                self.assertEqual(self.ler()[identificador]["texto_usuario"], RELATO)

    def test_falha_do_motor_pode_cair_no_dicionario_sem_ocultar_motivo(self):
        self.injetar(MotorFicticio(erro=RuntimeError("Falha fictícia do provedor")))
        identificador = self.criar()
        antes = self.historico.read_bytes()
        self.assertEqual(self.interpretar(identificador, motor="llm").status_code, 503)
        self.assertEqual(self.historico.read_bytes(), antes)
        corpo = self.rascunho(identificador, motor="llm", permitir_fallback_dicionario=True)
        self.assertEqual(corpo["motor_utilizado"], "dicionario")
        self.assertEqual(corpo["fallback_motivo"], "falha_motor")

    def test_base_invalida_nao_interpreta_nem_modifica_relato(self):
        identificador = self.criar()
        antes = self.historico.read_bytes()
        storage.salvar_json(storage.ARQ_DICIONARIO, {"categoria_inventada": ["palavra"]})
        resposta = self.interpretar(identificador)
        self.assertEqual(resposta.status_code, 503, resposta.text)
        self.assertEqual(self.historico.read_bytes(), antes)

    def test_revisao_admite_corrigir_sugestoes_ou_seguir_sem_categoria(self):
        for atuais, desejadas, texto in (([], [], ""), (["cansado"], ["calmo"], "calmo")):
            with self.subTest(atuais=atuais):
                identificador = self.criar()
                corpo = self.rascunho(identificador)
                resposta = self.revisar(
                    identificador, corpo["interpretacao_id"], emocoes_confirmadas=atuais,
                    estado_desejado_confirmado=desejadas, texto_desejado=texto,
                )
                self.assertEqual(resposta.status_code, 200, resposta.text)
                revisada = resposta.json()
                self.assertEqual(revisada["analise"], {"emocoes": atuais, "estado_desejado": desejadas})
                self.assertTrue(revisada["progresso"]["emocoes_confirmadas"])
                self.assertTrue(revisada["progresso"]["estado_desejado_informado"])
                self.assertTrue(revisada["progresso"]["recomendacoes_geradas"])
                if not atuais and not desejadas:
                    self.assertEqual(revisada["recomendacoes"], [])
                    self.assertEqual(revisada["motivos_recomendacoes"], [])

    def test_revisao_requer_escolha_explicita_de_ambas_partes_e_texto(self):
        identificador = self.criar()
        corpo = self.rascunho(identificador)
        base = {"sessao_id": identificador, "interpretacao_id": corpo["interpretacao_id"],
                "emocoes_confirmadas": [], "estado_desejado_confirmado": [], "texto_desejado": ""}
        invalidos = []
        for campo in ("emocoes_confirmadas", "estado_desejado_confirmado", "texto_desejado"):
            invalidos.extend(({k: v for k, v in base.items() if k != campo}, {**base, campo: None}))
        for campo in ("emocoes_confirmadas", "estado_desejado_confirmado"):
            for valor in (["triste", "triste"], ["categoria_inventada"], [None], "triste"):
                invalidos.append({**base, campo: valor})
        invalidos.append({**base, "estado_desejado_confirmado": ["calmo"]})
        antes = self.historico.read_bytes()
        for payload in invalidos:
            with self.subTest(payload=payload):
                resposta = self.client.post("/api/revisoes-interpretacao", json=payload)
                self.assertEqual(resposta.status_code, 422, resposta.text)
                self.assertEqual(self.historico.read_bytes(), antes)

    def test_requisicao_interpretacao_nao_coage_flags_motor_ou_identificador(self):
        identificador = self.criar()
        antes = self.historico.read_bytes()
        invalidos = [{"motor": "inventado"}, {"motor": None},
                     {"regenerar": "false"}, {"regenerar": 1},
                     {"permitir_fallback_dicionario": "true"},
                     {"permitir_fallback_dicionario": None}, {"sessao_id": "../fora"}]
        for campos in invalidos:
            with self.subTest(campos=campos):
                self.assertEqual(self.interpretar(identificador, **campos).status_code, 422)
                self.assertEqual(self.historico.read_bytes(), antes)

    def test_revisao_repetida_reutiliza_recomendacoes_e_mudanca_conflita(self):
        identificador = self.criar()
        corpo = self.rascunho(identificador)
        primeira = self.revisar(identificador, corpo["interpretacao_id"])
        self.assertEqual(primeira.status_code, 200, primeira.text)
        storage.salvar_json(storage.ARQ_MUSICAS, [])
        antes = self.historico.read_bytes()
        with patch("core.interpretacao.servico.recomendar_musicas", side_effect=AssertionError("Não recalcular")), \
             patch("core.interpretacao.servico.explicar_recomendacoes", side_effect=AssertionError("Não reexplicar")):
            segunda = self.revisar(identificador, corpo["interpretacao_id"])
        self.assertEqual(segunda.status_code, 200, segunda.text)
        self.assertEqual(segunda.json(), primeira.json())
        self.assertEqual(self.historico.read_bytes(), antes)
        conflito = self.revisar(identificador, corpo["interpretacao_id"], emocoes_confirmadas=[])
        self.assertEqual(conflito.status_code, 409, conflito.text)
        self.assertEqual(self.historico.read_bytes(), antes)

    def test_falha_de_escrita_do_rascunho_preserva_sessao(self):
        identificador = self.criar()
        antes = self.historico.read_bytes()
        with patch.object(storage.os, "replace", side_effect=OSError("Falha fictícia")):
            resposta = self.interpretar(identificador)
        self.assertEqual(resposta.status_code, 503, resposta.text)
        self.assertEqual(self.historico.read_bytes(), antes)
        self.assertEqual(list(self.historico.parent.glob(".rhythmmind-*.tmp")), [])
        self.assertEqual(self.client.get(f"/api/interpretacoes/{identificador}").status_code, 404)

    def test_falha_de_escrita_da_revisao_preserva_snapshot_sem_confirmar(self):
        identificador = self.criar()
        corpo = self.rascunho(identificador)
        antes = self.historico.read_bytes()
        with patch.object(storage.os, "replace", side_effect=OSError("Falha fictícia")):
            resposta = self.revisar(identificador, corpo["interpretacao_id"])
        self.assertEqual(resposta.status_code, 503, resposta.text)
        self.assertEqual(self.historico.read_bytes(), antes)
        self.assertEqual(list(self.historico.parent.glob(".rhythmmind-*.tmp")), [])
        self.assertEqual(self.client.get(f"/api/interpretacoes/{identificador}").json(), corpo)
        registro = self.ler()[identificador]
        self.assertFalse(registro["progresso"]["emocoes_confirmadas"])
        self.assertEqual(registro["recomendacoes"], [])
        self.assertEqual(self.revisar(identificador, corpo["interpretacao_id"]).status_code, 200)

    def test_legado_e_categorias_ja_confirmadas_nao_recebem_rascunho(self):
        legado = self.criar()
        historico = self.ler()
        historico[legado].pop("progresso")
        storage.salvar_json(str(self.historico), historico)
        confirmada = self.criar(emocoes_confirmadas=["triste"])
        concluida = self.criar(emocoes_confirmadas=["triste"], texto_desejado="feliz")
        antes = self.historico.read_bytes()
        for identificador in (legado, confirmada, concluida):
            with self.subTest(sessao_id=identificador):
                resposta = self.interpretar(identificador)
                self.assertEqual(resposta.status_code, 409, resposta.text)
                self.assertEqual(self.historico.read_bytes(), antes)

    def test_conclusao_pelo_fluxo_anterior_impede_revisao_do_rascunho(self):
        identificador = self.criar()
        corpo = self.rascunho(identificador)
        antiga = self.client.post("/api/retomar-sessao", json={
            "sessao_id": identificador, "emocoes_confirmadas": ["triste"], "texto_desejado": "feliz",
        })
        self.assertEqual(antiga.status_code, 200, antiga.text)
        antes = self.historico.read_bytes()
        consulta = self.client.get(f"/api/interpretacoes/{identificador}")
        self.assertEqual(consulta.status_code, 200, consulta.text)
        self.assertEqual(consulta.json()["estado_revisao"], "superada")
        resposta = self.revisar(identificador, corpo["interpretacao_id"], texto_desejado="feliz")
        self.assertEqual(resposta.status_code, 409, resposta.text)
        self.assertEqual(self.historico.read_bytes(), antes)

    def test_rotas_exigem_token_e_sessao_de_outra_conta_retorna_404(self):
        identificador = self.criar()
        corpo = self.rascunho(identificador)
        revisao = {"sessao_id": identificador, "interpretacao_id": corpo["interpretacao_id"],
                   "emocoes_confirmadas": [], "estado_desejado_confirmado": [], "texto_desejado": ""}
        antes = self.historico.read_bytes()
        with TestClient(api.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as cliente:
            for metodo, caminho, payload in (
                ("POST", "/api/interpretacoes", {"sessao_id": identificador}),
                ("GET", f"/api/interpretacoes/{identificador}", None),
                ("POST", "/api/revisoes-interpretacao", revisao),
            ):
                self.assertEqual(cliente.request(metodo, caminho, json=payload).status_code, 401)
            credenciais = {"nome_usuario": "outra_conta_ficticia", "senha": "senha-ficticia-123!"}
            self.assertEqual(cliente.post("/api/auth/registrar", json=credenciais).status_code, 201)
            login = cliente.post("/api/auth/entrar", json=credenciais)
            self.assertEqual(login.status_code, 200, login.text)
            cabecalhos = {"Authorization": "Bearer " + login.json()["token_acesso"]}
            for metodo, caminho, payload in (
                ("POST", "/api/interpretacoes", {"sessao_id": identificador}),
                ("GET", f"/api/interpretacoes/{identificador}", None),
                ("POST", "/api/revisoes-interpretacao", revisao),
            ):
                self.assertEqual(cliente.request(metodo, caminho, json=payload, headers=cabecalhos).status_code, 404)
        self.assertEqual(self.historico.read_bytes(), antes)

    def test_middleware_local_tambem_protege_novas_rotas(self):
        identificador = self.criar()
        antes = self.historico.read_bytes()
        with ClienteAutenticado(api.app, base_url="http://127.0.0.1", client=("203.0.113.7", 50000)) as cliente:
            resposta = cliente.post("/api/interpretacoes", json={"sessao_id": identificador})
            self.assertEqual(resposta.status_code, 403, resposta.text)
        self.assertEqual(self.historico.read_bytes(), antes)


if __name__ == "__main__":
    unittest.main()
