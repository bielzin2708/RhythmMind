"""Avaliação sintética: contrato, isolamento offline e relato honesto de falhas."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from core.interpretacao.base import carregar_base
from core.interpretacao.llm import InterpretadorLLM
from scripts import avaliar_interpretacao as avaliacao


RAIZ = Path(__file__).resolve().parents[1]
GRUPOS = (
    "escrita_direta", "variacao_escrita", "negacao", "estado_intencao",
    "coexistencia", "ambiguidade",
)


def conjunto_ficticio():
    casos = []
    for indice, grupo in enumerate(GRUPOS):
        for numero in range(3):
            casos.append({
                "id": f"T{indice}{numero}", "grupo": grupo,
                "texto_original": "Estou triste", "texto_desejado": None,
                "esperado": {
                    "estado_atual": ["triste"], "estado_desejado": [],
                    "objetivos": [], "contextos": [], "precisa_esclarecimento": False,
                },
                "nota": "Fixture fictícia para verificar o contrato do avaliador.",
            })
    return {
        "versao": "rhythmmind.casos-interpretacao.v1", "natureza": "sintetico",
        "nota": "Fixture de estrutura; não representa avaliação com usuários.",
        "casos": casos,
    }


class TransporteFalho:
    def post_json(self, *args, **kwargs):
        raise RuntimeError("Bearer segredo-ficticio-nao-exportar")


class AvaliacaoInterpretacaoTests(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.casos = self.pasta / "casos.json"
        self.base = carregar_base(caminho_dicionario=RAIZ / "data/dicionario_emocional.json")

    def escrever(self, documento=None):
        self.casos.write_text(json.dumps(
            conjunto_ficticio() if documento is None else documento, ensure_ascii=False,
        ), encoding="utf-8")
        return self.casos

    def documento(self):
        return avaliacao.carregar_casos(self.escrever())[0]

    def executar_cli(self, *argumentos):
        saida, erros = io.StringIO(), io.StringIO()
        with redirect_stdout(saida), redirect_stderr(erros):
            codigo = avaliacao.main(list(argumentos))
        return codigo, saida.getvalue(), erros.getvalue()

    def test_carregamento_exige_dataset_sintetico_e_preserva_hash_rastreavel(self):
        caminho = self.escrever()
        documento, assinatura = avaliacao.carregar_casos(caminho)
        self.assertEqual(len(documento["casos"]), 18)
        self.assertEqual(documento["natureza"], "sintetico")
        self.assertRegex(assinatura, r"^[0-9a-f]{64}$")
        self.assertEqual(avaliacao.carregar_casos(caminho)[1], assinatura)

    def test_dataset_invalido_e_recusado_antes_de_acessar_motor_externo(self):
        casos = []
        dados = conjunto_ficticio()
        dados["natureza"] = "relatos_reais"
        casos.append(dados)
        dados = conjunto_ficticio()
        dados["casos"][1]["id"] = dados["casos"][0]["id"]
        casos.append(dados)
        dados = conjunto_ficticio()
        dados["casos"][0]["esperado"]["estado_atual"] = ["categoria_inventada"]
        casos.append(dados)
        dados = conjunto_ficticio()
        dados["casos"][0]["usuario_id"] = "identidade-inventada"
        casos.append(dados)
        dados = conjunto_ficticio()
        dados["casos"] = dados["casos"][:-3]
        casos.append(dados)
        for dados in casos:
            with self.subTest(dados=dados), patch.object(
                avaliacao, "criar_interpretador_llm_do_ambiente",
                side_effect=AssertionError("Não deve consultar configuração/provedor"),
            ):
                self.escrever(dados)
                codigo, _, _ = self.executar_cli(
                    "--casos", str(self.casos), "--saida", str(self.pasta / "saida"), "--llm", "real",
                )
                self.assertEqual(codigo, 2)
                self.assertFalse((self.pasta / "saida/comparacao_interpretacao.json").exists())

    def test_json_corrompido_ou_chaves_repetidas_nao_sao_aceitos(self):
        for texto in ("{", "null", '{"versao":"v1","versao":"v2"}'):
            with self.subTest(texto=texto):
                self.casos.write_text(texto, encoding="utf-8")
                with self.assertRaises(ValueError):
                    avaliacao.carregar_casos(self.casos)

    def test_mock_nao_copia_oraculo_nem_recebe_metricas_de_qualidade(self):
        relatorio = avaliacao.avaliar_casos(self.documento(), self.base, modo_llm="mock")
        resumo = relatorio["resumo"]["motores"]
        self.assertEqual(resumo["dicionario"]["validos_estruturalmente"], 18)
        self.assertEqual(resumo["llm"]["validos_estruturalmente"], 18)
        self.assertTrue(resumo["llm"]["simulado"])
        self.assertIsNone(resumo["llm"]["metricas"])
        self.assertIsNone(resumo["llm"]["criterio_minimo"])
        for caso in relatorio["casos"]:
            lexical = caso["resultados"]["dicionario"]
            mock = caso["resultados"]["llm"]
            self.assertEqual(lexical["estado_atual"], ["triste"])
            self.assertEqual(mock["estado_atual"], [])
            self.assertTrue(mock["precisa_esclarecimento"])
            self.assertIsNone(mock["comparacao"])
            self.assertIsNone(mock["erro"])
            self.assertGreaterEqual(mock["tempo_ms"], 0)
            self.assertIsNotNone(lexical["comparacao"])

    def test_alterar_esperado_nao_altera_resposta_simulada(self):
        original = self.documento()
        modificado = deepcopy(original)
        for caso in modificado["casos"]:
            caso["esperado"]["estado_atual"] = ["feliz", "animado"]
            caso["esperado"]["estado_desejado"] = ["calmo"]
            caso["esperado"]["precisa_esclarecimento"] = True
        primeiro = avaliacao.avaliar_casos(original, self.base, modo_llm="mock")
        segundo = avaliacao.avaliar_casos(modificado, self.base, modo_llm="mock")
        for a, b in zip(primeiro["casos"], segundo["casos"]):
            for campo in ("estado_atual", "estado_desejado", "objetivos", "contextos", "precisa_esclarecimento"):
                self.assertEqual(a["resultados"]["llm"][campo], b["resultados"]["llm"][campo])

    def test_falha_externa_aparece_por_caso_sem_segredo_nem_fallback_disfarcado(self):
        motor = InterpretadorLLM(
            provedor="openai", modelo="modelo-ficticio", chave="segredo-ficticio-nao-exportar",
            cliente=TransporteFalho(),
        )
        relatorio = avaliacao.avaliar_casos(self.documento(), self.base, modo_llm="real", motor_llm=motor)
        resumo = relatorio["resumo"]["motores"]
        self.assertEqual(resumo["dicionario"]["validos_estruturalmente"], 18)
        self.assertEqual(resumo["llm"]["validos_estruturalmente"], 0)
        self.assertEqual(resumo["llm"]["falhas"], 18)
        self.assertFalse(resumo["llm"]["simulado"])
        for caso in relatorio["casos"]:
            resultado = caso["resultados"]["llm"]
            self.assertFalse(resultado["valido_estruturalmente"])
            self.assertTrue(resultado["erro"])
            self.assertIsNone(resultado["estado_atual"])
        self.assertNotIn("segredo-ficticio-nao-exportar", json.dumps(relatorio))
        self.assertNotIn("segredo-ficticio-nao-exportar", avaliacao.gerar_markdown(relatorio))

    def test_metricas_distinguem_papeis_e_falhas_nao_passam_criterio_minimo(self):
        documento = self.documento()
        # A regra lexical encontra triste no estado atual, mas calmo é só intenção.
        dirigido = next(caso for caso in documento["casos"] if caso["grupo"] == "estado_intencao")
        dirigido["texto_original"] = "Estou triste e quero ficar calmo"
        dirigido["esperado"]["estado_desejado"] = ["calmo"]
        relatorio = avaliacao.avaliar_casos(documento, self.base, modo_llm="mock")
        resumo = relatorio["resumo"]["motores"]["dicionario"]
        self.assertEqual(resumo["metricas"]["acertos_estado_atual_e_desejado"], 18)
        self.assertTrue(resumo["criterio_minimo"]["aprovado"])
        metricas = resumo["metricas"]["categorias"]
        self.assertEqual(metricas["estado_atual"]["por_categoria"]["triste"]["tp"], 18)
        self.assertEqual(metricas["estado_desejado"]["por_categoria"]["calmo"]["tp"], 1)
        self.assertEqual(metricas["estado_atual"]["por_categoria"]["calmo"]["fp"], 0)

        dirigido["esperado"]["estado_atual"] = ["feliz"]
        divergente = avaliacao.avaliar_casos(documento, self.base, modo_llm="mock")
        resumo = divergente["resumo"]["motores"]["dicionario"]
        self.assertEqual(resumo["metricas"]["acertos_estado_atual_e_desejado"], 17)
        self.assertFalse(resumo["criterio_minimo"]["aprovado"])
        self.assertEqual(resumo["criterio_minimo"]["grupos"]["estado_intencao"]["acertos"], 2)

        motor = InterpretadorLLM(provedor="openai", modelo="falso", chave="teste", cliente=TransporteFalho())
        falhas = avaliacao.avaliar_casos(documento, self.base, modo_llm="real", motor_llm=motor)
        resumo = falhas["resumo"]["motores"]["llm"]
        self.assertEqual(resumo["metricas"]["acertos_estado_atual_e_desejado"], 0)
        self.assertEqual(resumo["metricas"]["categorias"]["estado_desejado"]["por_categoria"]["calmo"]["fn"], 1)
        self.assertFalse(resumo["criterio_minimo"]["aprovado"])

    def test_main_mock_e_offline_mesmo_com_credencial_configurada(self):
        self.escrever()
        destino = self.pasta / "resultados"
        env = {
            "RHYTHMMIND_LLM_PROVIDER": "openai", "RHYTHMMIND_LLM_MODEL": "modelo-ficticio",
            "RHYTHMMIND_LLM_API_KEY": "segredo-ficticio-nao-usar",
        }
        with patch.dict(os.environ, env), patch(
            "core.interpretacao.llm.ClienteJSON.post_json", side_effect=AssertionError("Rede proibida neste teste"),
        ), patch.object(avaliacao, "criar_interpretador_llm_do_ambiente", side_effect=AssertionError("Config real não deve ser lida")):
            codigo, _, erros = self.executar_cli("--casos", str(self.casos), "--saida", str(destino))
        self.assertEqual(codigo, 0, erros)
        relatorio = json.loads((destino / "comparacao_interpretacao.json").read_text(encoding="utf-8"))
        markdown = (destino / "comparacao_interpretacao.md").read_text(encoding="utf-8")
        self.assertTrue(relatorio["resumo"]["motores"]["llm"]["simulado"])
        self.assertEqual(markdown, avaliacao.gerar_markdown(relatorio))
        self.assertNotIn("segredo-ficticio-nao-usar", markdown)

    def test_main_real_sem_configuracao_nao_faz_output_nem_finge_llm(self):
        self.escrever()
        destino = self.pasta / "resultados-reais"
        with patch.object(avaliacao, "criar_interpretador_llm_do_ambiente", return_value=None):
            codigo, _, erros = self.executar_cli(
                "--casos", str(self.casos), "--saida", str(destino), "--llm", "real",
            )
        self.assertEqual(codigo, 2)
        self.assertTrue(erros)
        self.assertFalse((destino / "comparacao_interpretacao.json").exists())

    def test_script_pode_ser_executado_fora_da_pasta_do_repositorio(self):
        self.escrever()
        destino = self.pasta / "fora-repo"
        env = {chave: valor for chave, valor in os.environ.items()
               if not chave.startswith("RHYTHMMIND_LLM_")}
        processo = subprocess.run(
            [sys.executable, str(RAIZ / "scripts/avaliar_interpretacao.py"),
             "--casos", str(self.casos), "--saida", str(destino), "--llm", "mock"],
            cwd=self.pasta, env=env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(processo.returncode, 0, processo.stderr)
        resultado = json.loads((destino / "comparacao_interpretacao.json").read_text(encoding="utf-8"))
        self.assertEqual(resultado["resumo"]["motores"]["dicionario"]["total"], 18)

    def test_markdown_escapa_dados_livres_sem_injetar_html_ou_linhas(self):
        documento = self.documento()
        ataque = 'Estou triste | <script>alert("ficticio")</script>\nlinha extra'
        documento["casos"][0]["texto_original"] = ataque
        relatorio = avaliacao.avaliar_casos(documento, self.base, modo_llm="mock")
        markdown = avaliacao.gerar_markdown(relatorio)
        self.assertNotIn("<script>", markdown)
        self.assertNotIn(ataque, markdown)
        self.assertIn("T00", markdown)


if __name__ == "__main__":
    unittest.main()
