"""Testes de domínio do catálogo, limites de validação da API e escrita concorrente."""

from concurrent.futures import ThreadPoolExecutor
import unittest

from api.main import app
from core import catalogo, storage
from core.contexto import contexto_usuario
from tests.apoio_autenticacao import ClienteAutenticado, dados_autenticados


class CatalogoDominioTests(unittest.TestCase):
    def test_validar_duracao_aceita_formatos_validos_e_rejeita_invalidos(self):
        self.assertTrue(catalogo.validar_duracao("3:05"))
        self.assertTrue(catalogo.validar_duracao("99:59"))
        for invalido in (None, "", "   ", "3:60", "120:00", "3:05\n", "abc", "-1:20"):
            with self.subTest(invalido=invalido):
                self.assertFalse(catalogo.validar_duracao(invalido))

    def test_validar_bpm_respeita_faixa_plausivel(self):
        self.assertIsNone(catalogo.validar_bpm(None))
        self.assertIsNone(catalogo.validar_bpm("  "))
        self.assertEqual(catalogo.validar_bpm("120"), 120)
        self.assertEqual(catalogo.validar_bpm("40"), 40)
        self.assertEqual(catalogo.validar_bpm("220"), 220)
        for invalido in ("39", "221", "rapido", "120bpm"):
            with self.subTest(invalido=invalido):
                self.assertEqual(catalogo.validar_bpm(invalido), -1)

    def test_inferencias_do_catalogo_derivam_contextos_estrategias_e_percepcoes(self):
        sentimentos = ["calmo", "foco"]
        tags = ["rock"]
        contextos = catalogo.inferir_contextos_para_musica(sentimentos, tags)
        estrategias = catalogo.inferir_estrategias_para_musica(sentimentos, tags, 110)
        self.assertIn("estudar", contextos)
        self.assertIn("trabalhar", contextos)
        self.assertIn("foco_cognitivo", estrategias)
        self.assertIn("ativacao_gradual", estrategias)
        self.assertEqual(catalogo.inferir_energia_para_musica(["calmo"], [], 68), "baixa")
        self.assertEqual(catalogo.inferir_energia_para_musica(["animado"], [], 140), "alta")
        self.assertEqual(catalogo.inferir_valencia_para_musica(["feliz"], []), "alta")
        self.assertEqual(catalogo.inferir_valencia_para_musica(["triste"], []), "baixa")
        self.assertEqual(catalogo.inferir_intensidade_para_musica(["explosivo"], [], 150), "alta")
        tags_inferidas = catalogo.inferir_tags_a_partir_da_percepcao(
            "música calma e suave para estudar e relaxar",
            ["calmo", "foco"],
            90,
        )
        self.assertTrue({"calmo", "leve", "foco"}.issubset(set(tags_inferidas)))


class ValidacoesEntradaApiTests(unittest.TestCase):
    def setUp(self):
        self.raiz = self.enterContext(dados_autenticados())
        self.client = self.enterContext(ClienteAutenticado(
            app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000),
        ))

    def test_cadastro_musica_rejeita_nome_ou_artista_em_branco(self):
        for payload in (
            {"nome": "   ", "artista": "Artista Fictício", "duracao": "3:00", "sentimentos_texto": "calmo"},
            {"nome": "Faixa Fictícia", "artista": "   ", "duracao": "3:00", "sentimentos_texto": "calmo"},
        ):
            with self.subTest(payload=payload):
                resposta = self.client.post("/api/musicas", json=payload)
                self.assertEqual(resposta.status_code, 422, resposta.text)

    def test_registrar_estado_rejeita_relato_acima_de_4000_caracteres(self):
        resposta = self.client.post("/api/registrar-estado", json={
            "texto_atual": "a" * 4001,
        })
        self.assertEqual(resposta.status_code, 422, resposta.text)

        resposta_desejo = self.client.post("/api/registrar-estado", json={
            "texto_atual": "Estou cansado hoje.",
            "texto_desejado": "b" * 4001,
        })
        self.assertEqual(resposta_desejo.status_code, 422, resposta_desejo.text)

    def test_feedback_exige_booleano_estrito_em_ajudou(self):
        criacao = self.client.post("/api/registrar-estado", json={
            "texto_atual": "Estou cansado após o expediente.",
        })
        self.assertEqual(criacao.status_code, 200, criacao.text)
        sessao_id = criacao.json()["sessao_id"]

        for valor_invalido in ("true", "sim", 1, 0):
            with self.subTest(valor_invalido=valor_invalido):
                resposta = self.client.post("/api/feedback", json={
                    "sessao_id": sessao_id,
                    "ajudou": valor_invalido,
                })
                self.assertEqual(resposta.status_code, 422, resposta.text)

    def test_salvar_musica_usuario_concorrente_preserva_todas_as_faixas(self):
        total = 12
        usuario_id = "00000000-0000-4000-8000-000000000099"

        def gravar(indice):
            with contexto_usuario(usuario_id, self.raiz):
                return storage.salvar_musica_usuario({
                    "id": f"faixa_{indice}",
                    "nome": f"Faixa Fictícia {indice}",
                    "artista": "Artista Fictício",
                    "duracao": "3:00",
                    "duracao_segundos": 180,
                    "sentimentos_associados": ["calmo"],
                })

        with ThreadPoolExecutor(max_workers=4) as executor:
            resultados = list(executor.map(gravar, range(total)))

        self.assertEqual(len(resultados), total)
        with contexto_usuario(usuario_id, self.raiz):
            musicas = storage.carregar_json(storage.ARQ_MUSICAS, [])
        self.assertEqual({m["id"] for m in musicas}, {f"faixa_{i}" for i in range(total)})


if __name__ == "__main__":
    unittest.main()
