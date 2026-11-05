"""Base curta rastreável e contrato estrito de devolutiva externa."""

import json
from pathlib import Path
import unittest

from pydantic import ValidationError

from core.interpretacao.adaptadores import InterpretadorLexical
from core.interpretacao.contratos import (
    CATEGORIAS, CONTEXTOS, OBJETIVOS, REFERENCIAS_BASE,
    PropostaInterpretacao, PropostaLLM,
)


RAIZ = Path(__file__).resolve().parents[1]


def proposta_completa():
    return {
        "estado_atual": {
            "estado": "sugestoes",
            "sugestoes": [{"categoria": "triste", "evidencias": ["triste"]}],
            "ambiguidades": [],
            "resumo": "O relato pode indicar tristeza; confirme se isso faz sentido.",
        },
        "estado_desejado": {
            "estado": "sem_correspondencia", "sugestoes": [], "ambiguidades": [],
            "resumo": "Não foi informada uma intenção de mudança.",
        },
        "texto_intencao": None,
        "objetivos": [], "contextos": [],
        "resumo_reflexivo": "Talvez a tristeza descreva seu momento; você pode revisar esta leitura.",
        "precisa_esclarecimento": False,
        "referencias_base": ["RM01", "RM05", "RM06"],
    }


class BaseEnxutaTests(unittest.TestCase):
    def setUp(self):
        self.base = json.loads((RAIZ / "data/base_conhecimento.json").read_text(encoding="utf-8"))

    def test_vocabularios_correspondem_ao_contrato_e_dicionario(self):
        dicionario = json.loads((RAIZ / "data/dicionario_emocional.json").read_text(encoding="utf-8"))
        taxonomia = self.base["taxonomia"]
        self.assertEqual(set(taxonomia["categorias"]), set(dicionario))
        self.assertEqual(taxonomia["categorias"], list(CATEGORIAS))
        self.assertEqual(taxonomia["objetivos"], list(OBJETIVOS))
        self.assertEqual(taxonomia["contextos"], list(CONTEXTOS))
        self.assertEqual({item["id"] for item in taxonomia["estrategias"]}, {
            "transicao_emocional", "foco_cognitivo", "catarse", "ativacao_gradual",
            "descompressao", "ativacao", "espelhamento",
        })
        self.assertTrue(all(item["proposito"].strip() for item in taxonomia["estrategias"]))

    def test_regras_com_ids_unicos_fontes_e_limites_documentais(self):
        regras = self.base["regras"]
        self.assertEqual([regra["id"] for regra in regras], list(REFERENCIAS_BASE))
        self.assertTrue(all(regra["enunciado"].strip() and regra["fontes"] for regra in regras))
        self.assertTrue(all(isinstance(fonte, str) and fonte.strip() for regra in regras for fonte in regra["fontes"]))
        nota = self.base["fonte_documental"]["nota"]
        self.assertIn("vocabulários heurísticos", nota)
        self.assertIn("não constituem taxonomia científica validada", nota)
        self.assertIn("não um resultado experimental", nota)

    def test_base_pequena_sem_registros_de_musicas_ou_dados_pessoais(self):
        self.assertEqual(set(self.base), {"versao", "fonte_documental", "taxonomia", "regras"})
        self.assertLess(len(json.dumps(self.base, ensure_ascii=False).encode("utf-8")), 10000)
        def visitar(valor):
            if isinstance(valor, dict):
                self.assertFalse(set(valor) & {"artista", "nome_faixa", "musicas", "catalogo", "texto_usuario", "sessao_id"})
                for item in valor.values():
                    visitar(item)
            elif isinstance(valor, list):
                for item in valor:
                    visitar(item)
        visitar(self.base)


class ContratoLLMTests(unittest.TestCase):
    def test_legado_permanece_legivel_mas_llm_exige_campos_novos(self):
        dados = proposta_completa()
        antigo = {campo: dados[campo] for campo in ("estado_atual", "estado_desejado", "texto_intencao")}
        legado = PropostaInterpretacao.model_validate(antigo)
        self.assertIsNone(legado.resumo_reflexivo)
        self.assertEqual(legado.objetivos, [])
        for campo in ("texto_intencao", "objetivos", "contextos", "resumo_reflexivo", "precisa_esclarecimento", "referencias_base"):
            with self.subTest(campo=campo), self.assertRaises(ValidationError):
                PropostaLLM.model_validate({chave: valor for chave, valor in dados.items() if chave != campo})

    def test_somente_vocabulario_e_referencias_existentes_sem_repeticoes(self):
        for campo in ("objetivos", "contextos", "referencias_base"):
            for valor in (["inventado"], ["RM01", "RM01"] if campo == "referencias_base" else ["estudar", "estudar"], [123]):
                with self.subTest(campo=campo, valor=valor), self.assertRaises(ValidationError):
                    PropostaLLM.model_validate({**proposta_completa(), campo: valor})
        for refs in ([], ["RM99"]):
            with self.subTest(refs=refs), self.assertRaises(ValidationError):
                PropostaLLM.model_validate({**proposta_completa(), "referencias_base": refs})

    def test_nao_aceita_musicas_ou_autoridade_na_proposta(self):
        for campo in ("musicas", "recomendacoes", "diagnostico", "origem", "modelo", "categorias_confirmadas"):
            with self.subTest(campo=campo), self.assertRaises(ValidationError):
                PropostaLLM.model_validate({**proposta_completa(), campo: []})

    def test_ambiguidade_e_ausencia_de_estado_atual_exigem_esclarecimento(self):
        for parte in (
            {"estado": "ambigua", "sugestoes": [], "ambiguidades": ["Não ficou claro como você se sente."], "resumo": "Você pode contar um pouco mais?"},
            {"estado": "sem_correspondencia", "sugestoes": [], "ambiguidades": [], "resumo": "Você pode contar um pouco mais?"},
        ):
            dados = {**proposta_completa(), "estado_atual": parte}
            with self.subTest(estado=parte["estado"]), self.assertRaises(ValidationError):
                PropostaLLM.model_validate(dados)
            self.assertTrue(PropostaLLM.model_validate({**dados, "precisa_esclarecimento": True}).precisa_esclarecimento)
        with self.assertRaises(ValidationError):
            PropostaLLM.model_validate({**proposta_completa(), "precisa_esclarecimento": "sim"})

    def test_llm_nao_declara_confianca_emocional(self):
        for confianca in ("baixa", "media", "alta", 0.99, "99%"):
            dados = proposta_completa()
            dados["estado_atual"]["sugestoes"][0]["confianca_autodeclarada"] = confianca
            with self.subTest(confianca=confianca), self.assertRaises(ValidationError):
                PropostaLLM.model_validate(dados)

    def test_rejeita_alegacoes_clinicas_e_percentuais_na_linguagem_gerada(self):
        for texto in (
            "Você tem depressão.", "Isso é um diagnóstico de transtorno de ansiedade.",
            "Você tem TDAH.", "Você está 98% triste.", "Há noventa por cento de certeza.",
        ):
            for campo in ("resumo_reflexivo", "resumo", "ambiguidade"):
                dados = proposta_completa()
                if campo == "resumo_reflexivo":
                    dados[campo] = texto
                elif campo == "resumo":
                    dados["estado_atual"][campo] = texto
                else:
                    dados["estado_atual"].update(estado="ambigua", ambiguidades=[texto])
                    dados["precisa_esclarecimento"] = True
                with self.subTest(texto=texto, campo=campo), self.assertRaises(ValidationError):
                    PropostaLLM.model_validate(dados)

    def test_evidencias_literais_podem_conter_palavras_do_usuario(self):
        dados = proposta_completa()
        dados["estado_atual"]["sugestoes"][0]["evidencias"] = ["Tenho diagnóstico de depressão e me sinto triste 100% do tempo."]
        dados["texto_intencao"] = "quero falar do diagnóstico"
        resposta = PropostaLLM.model_validate(dados)
        self.assertEqual(resposta.estado_atual.sugestoes[0].evidencias, dados["estado_atual"]["sugestoes"][0]["evidencias"])

    def test_json_schema_expoe_enumeracoes_fechadas(self):
        schema = PropostaLLM.model_json_schema()
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["objetivos"]["items"]["enum"], list(OBJETIVOS))
        self.assertEqual(schema["properties"]["referencias_base"]["items"]["enum"], list(REFERENCIAS_BASE))
        self.assertEqual(schema["$defs"]["SugestaoCategoria"]["properties"]["categoria"]["enum"], list(CATEGORIAS))


class LexicalMetadadosTests(unittest.TestCase):
    def test_lexical_expoe_mesmos_campos_sem_inventar_contexto(self):
        # Snapshot explícito evita depender do cwd mutável de testes legados.
        from core.interpretacao.base import BaseConhecimento
        dicionario = json.loads((RAIZ / "data/dicionario_emocional.json").read_text(encoding="utf-8"))
        base = BaseConhecimento("0" * 64, json.dumps({"taxonomia": dicionario, "ordem_categorias": list(dicionario)}))
        motor = InterpretadorLexical()
        proposta = motor.interpretar("Estou triste e cansado, quero ficar calmo", None, base)
        self.assertEqual(motor.identificador, "lexical_contextual_v2")
        self.assertEqual({item.categoria for item in proposta.estado_atual.sugestoes}, {"triste", "cansado"})
        self.assertEqual({item.categoria for item in proposta.estado_desejado.sugestoes}, {"calmo"})
        self.assertEqual(proposta.objetivos, [])
        self.assertEqual(proposta.contextos, [])
        self.assertIn("RM02", proposta.referencias_base)
        self.assertTrue(proposta.resumo_reflexivo)
        self.assertIsInstance(proposta.precisa_esclarecimento, bool)
        for texto in ("...", "Ontem estava triste"):
            with self.subTest(texto=texto):
                self.assertTrue(motor.interpretar(texto, None, base).precisa_esclarecimento)
