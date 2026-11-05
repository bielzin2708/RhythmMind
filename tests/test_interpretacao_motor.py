"""Contratos e limites reais da interpretação lexical, sem API nem rede."""

from contextlib import contextmanager
from dataclasses import FrozenInstanceError
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from pydantic import ValidationError

from core.interpretacao import (
    BaseIndisponivel, InterpretadorLexical, ParteInterpretacao,
    PropostaInterpretacao, SugestaoCategoria, carregar_base,
)
from core.interpretacao.contratos import CATEGORIAS


_DICIONARIO_REAL = json.loads(
    (Path(__file__).resolve().parents[1] / "data/dicionario_emocional.json").read_text(encoding="utf-8"),
)


@contextmanager
def _pasta_temporaria():
    anterior = Path.cwd()
    with tempfile.TemporaryDirectory() as pasta:
        os.chdir(pasta)
        try:
            yield Path(pasta)
        finally:
            os.chdir(anterior)


def _escrever_base(dicionario=None):
    arquivo = Path("data/dicionario_emocional.json")
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(
        json.dumps(_DICIONARIO_REAL if dicionario is None else dicionario, ensure_ascii=False),
        encoding="utf-8",
    )
    return arquivo


def _categorias(parte):
    return {sugestao.categoria for sugestao in parte.sugestoes}


class TestContratosInterpretacao(unittest.TestCase):
    def test_sugestao_exige_categoria_conhecida_e_strings_estritas(self):
        for dados in (
            {"categoria": "diagnostico"},
            {"categoria": "triste", "evidencias": [123]},
            {"categoria": "triste", "evidencias": [" "]},
            {"categoria": "triste", "evidencias": ["x" * 501]},
            {"categoria": "triste", "evidencias": ["x"] * 4},
            {"categoria": "triste", "confianca_autodeclarada": 0.99},
            {"categoria": "triste", "confirmada": True},
        ):
            with self.subTest(dados=dados), self.assertRaises(ValidationError):
                SugestaoCategoria.model_validate(dados)

    def test_defaults_nao_compartilham_listas(self):
        primeira = SugestaoCategoria(categoria="triste")
        segunda = SugestaoCategoria(categoria="triste")
        primeira.evidencias.append("trecho")
        self.assertEqual(segunda.evidencias, [])
        self.assertIsNone(segunda.confianca_autodeclarada)

    def test_estados_coerentes_e_categorias_sem_repeticoes(self):
        for dados in (
            {"estado": "sugestoes", "sugestoes": []},
            {"estado": "sem_correspondencia", "sugestoes": [{"categoria": "triste"}]},
            {"estado": "ambigua", "ambiguidades": []},
            {"estado": "sugestoes", "sugestoes": [{"categoria": "triste"}] * 2},
            {"estado": "sugestoes", "sugestoes": [{"categoria": "triste"}], "ambiguidades": ["conflito"]},
        ):
            with self.subTest(dados=dados), self.assertRaises(ValidationError):
                ParteInterpretacao.model_validate({"resumo": "Revise.", **dados})

    def test_ambiguidade_pode_nao_ter_candidato_mas_requer_mensagem_util(self):
        parte = ParteInterpretacao(estado="ambigua", ambiguidades=["Referência a outra pessoa."], resumo="Revise.")
        self.assertEqual(parte.sugestoes, [])
        for ambiguidades in ([" "], ["x"] * 6, [False], ["x" * 501]):
            with self.subTest(ambiguidades=ambiguidades), self.assertRaises(ValidationError):
                ParteInterpretacao(estado="ambigua", ambiguidades=ambiguidades, resumo="Revise.")

    def test_resumo_nao_pode_ser_branco_convertido_ou_excessivo(self):
        for resumo in (" ", "x" * 601, 123):
            with self.subTest(resumo=resumo), self.assertRaises(ValidationError):
                ParteInterpretacao(estado="sem_correspondencia", resumo=resumo)

    def test_contrato_recusa_autoridade_ou_estado_de_sessao(self):
        parte = {"estado": "sem_correspondencia", "resumo": "Sem correspondência."}
        for campo in ("id", "sessao_id", "categorias_confirmadas", "progresso", "origem"):
            with self.subTest(campo=campo), self.assertRaises(ValidationError):
                PropostaInterpretacao(estado_atual=parte, estado_desejado=parte, **{campo: "valor"})
        for trecho in (" ", 10, "x" * 4001):
            with self.subTest(trecho=trecho), self.assertRaises(ValidationError):
                PropostaInterpretacao(estado_atual=parte, estado_desejado=parte, texto_intencao=trecho)


class TestBaseConhecimento(unittest.TestCase):
    def test_ausente_nao_cai_em_default(self):
        with _pasta_temporaria(), self.assertRaises(BaseIndisponivel):
            carregar_base()

    def test_base_corrompida_ou_incompleta_nao_e_aceita(self):
        casos = ["{", "[]", "null", json.dumps({"triste": ["triste"]})]
        for conteudo in casos:
            with self.subTest(conteudo=conteudo), _pasta_temporaria():
                arquivo = _escrever_base()
                arquivo.write_text(conteudo, encoding="utf-8")
                with self.assertRaises(BaseIndisponivel):
                    carregar_base()

    def test_sinonimos_invalidos_e_categoria_extra_sao_recusados(self):
        for sinonimos in ([" "], [False], [1], {"triste": True}, None):
            with self.subTest(sinonimos=sinonimos), _pasta_temporaria():
                dados = {categoria: [categoria] for categoria in CATEGORIAS}
                dados["triste"] = sinonimos
                _escrever_base(dados)
                with self.assertRaises(BaseIndisponivel):
                    carregar_base()
        with _pasta_temporaria():
            _escrever_base({**_DICIONARIO_REAL, "categoria_nova": ["termo"]})
            with self.assertRaises(BaseIndisponivel):
                carregar_base()

    def test_chave_json_repetida_e_codificacao_invalida_sao_recusadas(self):
        with _pasta_temporaria():
            arquivo = _escrever_base()
            conteudo = arquivo.read_text(encoding="utf-8")
            arquivo.write_text(conteudo[:-1] + ', "triste": ["triste"]}', encoding="utf-8")
            with self.assertRaises(BaseIndisponivel):
                carregar_base()
            arquivo.write_bytes(b"\xff\xfe")
            with self.assertRaises(BaseIndisponivel):
                carregar_base()

    def test_hash_canonico_independe_de_formatacao_mas_registra_ordem_e_termos(self):
        with _pasta_temporaria():
            arquivo = _escrever_base()
            primeira = carregar_base()
            arquivo.write_text(json.dumps(_DICIONARIO_REAL, indent=8), encoding="utf-8")
            segunda = carregar_base()
            self.assertEqual(primeira, segunda)
            self.assertEqual(primeira.sha256, hashlib.sha256(primeira.conteudo_json.encode("utf-8")).hexdigest())
            _escrever_base(dict(reversed(list(_DICIONARIO_REAL.items()))))
            self.assertNotEqual(primeira.sha256, carregar_base().sha256)
            dados = dict(_DICIONARIO_REAL)
            dados["triste"] = [*_DICIONARIO_REAL["triste"], "abatidíssimo"]
            _escrever_base(dados)
            self.assertNotEqual(primeira.sha256, carregar_base().sha256)

    def test_copia_da_taxonomia_e_arquivo_mutado_nao_alteram_snapshot(self):
        with _pasta_temporaria():
            arquivo = _escrever_base()
            base = carregar_base()
            copia = base.dicionario
            copia["triste"].append("segredo")
            copia.pop("normal")
            arquivo.unlink()
            self.assertEqual(base.dicionario, _DICIONARIO_REAL)
            with self.assertRaises(FrozenInstanceError):
                base.sha256 = "outro"
            conteudo = json.loads(base.conteudo_json)
            self.assertEqual(set(conteudo), {
                "versao", "taxonomia", "ordem_categorias", "regras", "conhecimento_operacional",
            })
            self.assertEqual(conteudo["conhecimento_operacional"], base.conhecimento)
            self.assertEqual(list(base.dicionario), list(_DICIONARIO_REAL))


class TestInterpretadorLexical(unittest.TestCase):
    def setUp(self):
        with _pasta_temporaria():
            _escrever_base()
            self.base = carregar_base()
        self.motor = InterpretadorLexical()

    def interpretar(self, relato, desejo=None):
        return self.motor.interpretar(relato, desejo, self.base)

    def test_estado_atual_e_intencao_nao_se_misturam(self):
        for relato, trecho in (
            ("Estou triste e quero ficar feliz", "quero ficar feliz"),
            ("Quero ficar feliz, mas estou triste", "Quero ficar feliz"),
            ("Estou triste; gostaria de ficar feliz", "gostaria de ficar feliz"),
            ("Pretendo ficar feliz. Estou triste", "Pretendo ficar feliz"),
            ("Estou triste e meu objetivo é ficar feliz", "meu objetivo é ficar feliz"),
            ("Busco ficar feliz e estou triste", "Busco ficar feliz"),
        ):
            with self.subTest(relato=relato):
                proposta = self.interpretar(relato)
                self.assertEqual(_categorias(proposta.estado_atual), {"triste"})
                self.assertEqual(_categorias(proposta.estado_desejado), {"feliz"})
                self.assertEqual(proposta.texto_intencao, trecho)
                self.assertIn(proposta.texto_intencao, relato)

    def test_negacao_da_intencao_nao_vira_desejo_positivo(self):
        for relato in (
            "não quero ficar triste", "Nao gostaria de ficar triste", "nunca pretendo ficar triste",
            "jamais desejo ficar triste", "Eu não quero ficar triste",
        ):
            with self.subTest(relato=relato):
                proposta = self.interpretar(relato)
                self.assertEqual(_categorias(proposta.estado_atual), set())
                self.assertEqual(_categorias(proposta.estado_desejado), set())
                self.assertEqual(proposta.estado_desejado.estado, "sem_correspondencia")
                self.assertIn(proposta.texto_intencao, relato)

    def test_negacao_do_presente_e_do_desejo_tem_escopos_separados(self):
        proposta = self.interpretar("Não estou triste e quero ficar feliz")
        self.assertEqual(_categorias(proposta.estado_atual), set())
        self.assertEqual(_categorias(proposta.estado_desejado), {"feliz"})
        proposta = self.interpretar("Estou triste e não quero ficar feliz")
        self.assertEqual(_categorias(proposta.estado_atual), {"triste"})
        self.assertEqual(_categorias(proposta.estado_desejado), set())
        proposta = self.interpretar("Não quero ficar triste, quero ficar feliz")
        self.assertEqual(_categorias(proposta.estado_desejado), {"feliz"})
        self.assertEqual(proposta.estado_desejado.estado, "ambigua")

    def test_compostos_e_contrastes_continuam_respeitando_motor_lexical(self):
        proposta = self.interpretar("Estou sem energia, mas quero ficar feliz")
        self.assertEqual(_categorias(proposta.estado_atual), {"cansado"})
        self.assertEqual(_categorias(proposta.estado_desejado), {"feliz"})
        proposta = self.interpretar("Não estou sem energia; quero ficar feliz e não triste")
        self.assertEqual(_categorias(proposta.estado_atual), set())
        self.assertEqual(_categorias(proposta.estado_desejado), {"feliz"})

    def test_desejo_separado_e_fonte_propria_sem_transformar_presente(self):
        proposta = self.interpretar("Estou triste", "feliz")
        self.assertEqual(_categorias(proposta.estado_atual), {"triste"})
        self.assertEqual(_categorias(proposta.estado_desejado), {"feliz"})
        self.assertIsNone(proposta.texto_intencao)

    def test_conflito_entre_fontes_de_desejo_exige_revisao(self):
        proposta = self.interpretar("Estou triste e quero ficar feliz", "foco")
        self.assertEqual(_categorias(proposta.estado_desejado), {"foco"})
        self.assertEqual(proposta.estado_desejado.estado, "ambigua")
        self.assertTrue(any("separadamente" in mensagem for mensagem in proposta.estado_desejado.ambiguidades))
        proposta = self.interpretar("Estou triste e quero ficar feliz", "feliz")
        self.assertEqual(proposta.estado_desejado.estado, "sugestoes")

    def test_sem_intencao_ou_termo_conhecido_nao_inventa_categoria(self):
        for relato in ("Hoje fui passear", "Estou trste", "Parece que carrego o mundo nas costas"):
            with self.subTest(relato=relato):
                proposta = self.interpretar(relato)
                self.assertEqual(_categorias(proposta.estado_atual), set())
                self.assertEqual(_categorias(proposta.estado_desejado), set())
                self.assertIsNone(proposta.texto_intencao)

    def test_temporalidade_e_pessoa_sao_ambiguidades_e_nao_afirmacoes(self):
        for relato in ("Ontem estava triste", "Minha mãe está triste", "Ela está triste"):
            with self.subTest(relato=relato):
                proposta = self.interpretar(relato)
                self.assertEqual(proposta.estado_atual.estado, "ambigua")
                self.assertIn("triste", _categorias(proposta.estado_atual))
        proposta = self.interpretar('Ela disse: "quero ficar feliz"')
        self.assertEqual(proposta.estado_desejado.estado, "ambigua")

    def test_termo_compartilhado_na_taxonomia_exige_revisao(self):
        for relato, categorias in (("Estou agitado", {"animado", "ansioso"}), ("Estou tranquilo", {"calmo", "normal"})):
            with self.subTest(relato=relato):
                proposta = self.interpretar(relato)
                self.assertEqual(_categorias(proposta.estado_atual), categorias)
                self.assertEqual(proposta.estado_atual.estado, "ambigua")
        proposta = self.interpretar("Estou animado e ansioso, não agitado")
        self.assertEqual(proposta.estado_atual.estado, "sugestoes")

    def test_varias_intencoes_mantem_intervalo_literal_e_sinalizam_revisao(self):
        relato = "Quero ficar feliz, mas estou triste e desejo ter foco"
        proposta = self.interpretar(relato)
        self.assertEqual(_categorias(proposta.estado_atual), {"triste"})
        self.assertEqual(_categorias(proposta.estado_desejado), {"feliz", "foco"})
        self.assertEqual(proposta.estado_desejado.estado, "ambigua")
        self.assertIn(proposta.texto_intencao, relato)

    def test_origem_real_e_sem_evidencia_ou_confianca_fabricada(self):
        relato = "Estou triste e quero ficar feliz"
        copia = str(relato)
        proposta = self.interpretar(relato)
        self.assertEqual(relato, copia)
        self.assertEqual(self.motor.origem, "dicionario")
        for parte in (proposta.estado_atual, proposta.estado_desejado):
            for sugestao in parte.sugestoes:
                self.assertEqual(sugestao.evidencias, [])
                self.assertIsNone(sugestao.confianca_autodeclarada)


if __name__ == "__main__":
    unittest.main()
