"""Interface pública local e assets, sem ampliar acesso aos registros pessoais."""

from html.parser import HTMLParser
from unittest.mock import patch
import unittest

from fastapi.testclient import TestClient

from api.desenvolvimento import dados_ficticios_temporarios
from api.main import app
from core import storage


class _Pagina(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = []
        self.ids = []
        self.formularios = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "script" and "src" in attrs:
            self.assets.append(attrs["src"])
        if tag == "link" and attrs.get("rel") in {"stylesheet", "icon"}:
            self.assets.append(attrs["href"])
        if tag == "form":
            self.formularios.append(attrs)


class InterfaceWebTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(dados_ficticios_temporarios())
        self.client = self.enterContext(TestClient(
            app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000),
        ))

    def test_raiz_e_app_servem_interface_sem_autenticacao(self):
        for caminho in ("/", "/app"):
            with self.subTest(caminho=caminho):
                resposta = self.client.get(caminho)
                self.assertEqual(resposta.status_code, 200, resposta.text)
                self.assertIn("text/html", resposta.headers["content-type"])
                self.assertIn('<html lang="pt-BR">', resposta.text)
                self.assertIn("RhythmMind", resposta.text)
                self.assertIn('id="auth-login-form"', resposta.text)

    def test_assets_estaticos_respondem_200_com_tipos_corretos(self):
        for arquivo in ("styles.css", "auth.css", "workspace.css", "themes.css", "theme.js", "home.js", "app.js", "api.js", "ui.js", "session.js", "history.js", "narrative-draft.js", "review-categories.js", "listening-state.js", "catalog-reference.js"):
            with self.subTest(arquivo=arquivo):
                resposta = self.client.get(f"/static/{arquivo}")
                self.assertEqual(resposta.status_code, 200, resposta.text)
                self.assertTrue(resposta.content)
                self.assertIn("text/css" if arquivo.endswith("css") else "javascript",
                              resposta.headers["content-type"])

    def test_pagina_referencia_assets_locais_existentes_e_nao_duplica_ids(self):
        pagina = _Pagina()
        pagina.feed(self.client.get("/").text)
        self.assertEqual(len(pagina.ids), len(set(pagina.ids)))
        self.assertTrue(pagina.assets)
        for asset in pagina.assets:
            self.assertTrue(asset.startswith("/static/"))
            self.assertEqual(self.client.get(asset).status_code, 200)

    def test_formularios_nao_enviam_senha_ou_relato_pela_query_sem_javascript(self):
        pagina = _Pagina()
        pagina.feed(self.client.get("/").text)
        self.assertTrue(pagina.formularios)
        for formulario in pagina.formularios:
            with self.subTest(formulario=formulario.get("id")):
                self.assertEqual(formulario.get("method", "get").lower(), "post")

    def test_interface_nao_embute_registros_e_api_pessoal_continua_autenticada(self):
        storage.salvar_json(storage.ARQ_HISTORICO, {
            "ficticio": {"texto_usuario": "Relato privado fictício não deve aparecer no HTML"},
        })
        resposta = self.client.get("/")
        self.assertNotIn("Relato privado fictício", resposta.text)
        for caminho in ("/api/historico", "/api/padroes", "/api/historico/exportacao"):
            self.assertEqual(self.client.get(caminho).status_code, 401)

    def test_assets_nao_expoem_codigo_ou_arquivos_fora_da_pasta_estatica(self):
        for caminho in ("/static/ausente.js", "/static/%2e%2e/api/main.py", "/static/%2e%2e/data/historico.json"):
            with self.subTest(caminho=caminho):
                self.assertEqual(self.client.get(caminho).status_code, 404)

    def test_interface_tem_csp_sem_scripts_inline_e_nao_e_cacheada(self):
        for caminho in ("/", "/app", "/static/app.js", "/static/styles.css"):
            resposta = self.client.get(caminho)
            self.assertEqual(resposta.headers["cache-control"], "no-store")
            self.assertEqual(resposta.headers["x-content-type-options"], "nosniff")
            csp = resposta.headers["content-security-policy"]
            self.assertIn("script-src 'self'", csp)
            self.assertNotIn("unsafe-inline", csp)

    def test_novas_rotas_preservam_restricao_local_e_ambiente_temporario(self):
        with patch.object(app.state, "diretorio_desenvolvimento", None):
            self.assertEqual(self.client.get("/").status_code, 503)
            self.assertEqual(self.client.get("/static/app.js").status_code, 503)
        with TestClient(app, base_url="http://exemplo.invalid", client=("203.0.113.10", 50000)) as externo:
            self.assertEqual(externo.get("/").status_code, 403)
            self.assertEqual(externo.get("/static/styles.css").status_code, 403)


if __name__ == "__main__":
    unittest.main()
