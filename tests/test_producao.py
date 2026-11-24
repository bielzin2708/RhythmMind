"""Modo de producao para container (Cloud Run) mantendo restricoes locais por padrao."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from api import google_auth
from api.main import app
from api.producao import (
    ambiente_producao,
    preparar_producao,
    resolver_diretorio_dados,
    resolver_porta,
)


_ORIGEM_PRODUCAO = "https://rhythmmind-demo.southamerica-east1.run.app"
_CLIENT_ID = "123456-ficticio.apps.googleusercontent.com"
_CLIENT_SECRET = "segredo-OAuth-inventado-apenas-para-teste"


class ProducaoHelpersTests(unittest.TestCase):
    def test_resolver_porta_padrao_e_validacao(self):
        self.assertEqual(resolver_porta({}), 8080)
        self.assertEqual(resolver_porta({"PORT": "9000"}), 9000)
        for invalida in ("0", "65536", "-1", "abc", ""):
            with self.subTest(port=invalida), self.assertRaises(ValueError):
                resolver_porta({"PORT": invalida})

    def test_resolver_diretorio_dados_cria_pasta_configurada(self):
        with TemporaryDirectory() as pasta:
            destino = Path(pasta) / "dados-cloud"
            resolvido = resolver_diretorio_dados(environ={"RHYTHMMIND_DIRETORIO_DADOS": str(destino)})
            self.assertEqual(resolvido, destino.resolve())
            self.assertTrue(resolvido.is_dir())

    def test_preparar_producao_nao_falha_nem_vaza_segredos(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(preparar_producao(), "desabilitado")
        with patch.dict(os.environ, {
            "RHYTHMMIND_AMBIENTE": "producao",
            "RHYTHMMIND_GOOGLE_CLIENT_ID": _CLIENT_ID,
            "RHYTHMMIND_GOOGLE_CLIENT_SECRET": _CLIENT_SECRET,
        }, clear=True):
            self.assertEqual(preparar_producao(), "invalido")
        with patch.dict(os.environ, {
            "RHYTHMMIND_AMBIENTE": "producao",
            "RHYTHMMIND_GOOGLE_CLIENT_ID": _CLIENT_ID,
            "RHYTHMMIND_GOOGLE_CLIENT_SECRET": _CLIENT_SECRET,
            "RHYTHMMIND_GOOGLE_REDIRECT_URI": _ORIGEM_PRODUCAO + "/api/auth/google/callback",
        }, clear=True):
            self.assertEqual(preparar_producao(), "habilitado")


class ProducaoApiTests(unittest.TestCase):
    def test_ambiente_producao_permite_fluxo_completo_e_restaura_bloqueio_ao_sair(self):
        temporario = self.enterContext(TemporaryDirectory(prefix="rhythmmind-prod-"))
        with ambiente_producao(temporario) as raiz_dados:
            self.assertNotEqual(raiz_dados, Path.cwd().resolve())
            with TestClient(
                app,
                base_url=_ORIGEM_PRODUCAO,
                client=("203.0.113.10", 50000),
            ) as cliente:
                saude = cliente.get("/healthz")
                self.assertEqual(saude.status_code, 200, saude.text)
                self.assertEqual(saude.json(), {"status": "ok"})
                self.assertEqual(saude.headers["cache-control"], "no-store")

                pagina = cliente.get("/")
                self.assertEqual(pagina.status_code, 200)

                reg = cliente.post("/api/auth/registrar", json={
                    "nome_usuario": "amiga_teste",
                    "senha": "senha-ficticia-segura-123",
                })
                self.assertEqual(reg.status_code, 201, reg.text)

                token = cliente.post("/api/auth/entrar", json={
                    "nome_usuario": "amiga_teste",
                    "senha": "senha-ficticia-segura-123",
                }).json()["token_acesso"]

                auth_headers = {"Authorization": f"Bearer {token}"}
                eu = cliente.get("/api/auth/eu", headers=auth_headers)
                self.assertEqual(eu.status_code, 200, eu.text)
                usuario_id = eu.json()["usuario_id"]

                importacao = cliente.post("/api/catalogo-referencia/importar", headers=auth_headers)
                self.assertEqual(importacao.status_code, 200, importacao.text)

                relato = cliente.post("/api/registrar-estado", headers=auth_headers, json={
                    "texto_atual": "Estou um pouco cansada hoje, quero descansar.",
                })
                self.assertEqual(relato.status_code, 200, relato.text)

                self.assertTrue((raiz_dados / "data" / "acesso.sqlite3").is_file())
                self.assertTrue((raiz_dados / "data" / "usuarios" / usuario_id / "historico.json").is_file())
                self.assertTrue((raiz_dados / "data" / "usuarios" / usuario_id / "musicas_usuario.json").is_file())

        # Ao sair do contexto, a restricao local volta imediatamente.
        with TestClient(app, base_url=_ORIGEM_PRODUCAO, client=("203.0.113.10", 50000)) as externo:
            self.assertEqual(externo.get("/").status_code, 403)
            self.assertEqual(externo.get("/healthz").status_code, 403)

    def test_producao_sem_diretorio_dados_falha_fechado_503(self):
        temporario = self.enterContext(TemporaryDirectory(prefix="rhythmmind-prod-"))
        with ambiente_producao(temporario):
            with patch.object(app.state, "diretorio_dados", None):
                with TestClient(app, base_url=_ORIGEM_PRODUCAO, client=("203.0.113.10", 50000)) as cliente:
                    self.assertEqual(cliente.get("/healthz").status_code, 503)
                    self.assertEqual(cliente.get("/api/auth/google/config").status_code, 503)

    def test_google_oauth_em_producao_atras_de_proxy_https_emite_cookies_secure(self):
        temporario = self.enterContext(TemporaryDirectory(prefix="rhythmmind-prod-"))
        self.enterContext(ambiente_producao(temporario))
        self.enterContext(patch.dict(os.environ, {
            "RHYTHMMIND_AMBIENTE": "producao",
            "RHYTHMMIND_GOOGLE_CLIENT_ID": _CLIENT_ID,
            "RHYTHMMIND_GOOGLE_CLIENT_SECRET": _CLIENT_SECRET,
            "RHYTHMMIND_GOOGLE_REDIRECT_URI": _ORIGEM_PRODUCAO + "/api/auth/google/callback",
        }))
        self.enterContext(patch.object(google_auth, "validar_codigo_google", return_value={
            "iss": "https://accounts.google.com", "sub": "google-prod-ficticio-1",
        }))

        # Simula container HTTP interno atras do load balancer HTTPS do Cloud Run.
        base_http_interna = _ORIGEM_PRODUCAO.replace("https://", "http://")
        proxy_https = {"X-Forwarded-Proto": "https"}
        with TestClient(
            app,
            base_url=base_http_interna,
            client=("169.254.1.1", 50000),
            follow_redirects=False,
        ) as cliente:
            cfg = cliente.get("/api/auth/google/config", headers=proxy_https)
            self.assertEqual(cfg.status_code, 200)
            self.assertEqual(cfg.json(), {
                "disponivel": True,
                "inicio_url": "/api/auth/google/iniciar",
                "armazenamento": "temporario",
            })

            iniciar = cliente.get("/api/auth/google/iniciar", headers=proxy_https)
            self.assertEqual(iniciar.status_code, 303, iniciar.text)
            set_cookies_iniciar = " ".join(iniciar.headers.get_list("set-cookie"))
            self.assertIn("Secure", set_cookies_iniciar)
            vinculo = iniciar.cookies.get("rhythmmind_google_fluxo")
            self.assertTrue(vinculo)
            params = parse_qs(urlsplit(iniciar.headers["location"]).query)

            # Em nuvem, o navegador envia o cookie Secure via HTTPS e o proxy encaminha no cabecalho.
            retorno = cliente.get(
                "/api/auth/google/callback",
                params={"state": params["state"][0], "code": "codigo-ficticio"},
                headers={**proxy_https, "Cookie": f"rhythmmind_google_fluxo={vinculo}"},
            )
            self.assertEqual(retorno.status_code, 303, retorno.text)
            self.assertEqual(retorno.headers["location"], "/?google=concluir")
            set_cookies_cb = " ".join(retorno.headers.get_list("set-cookie"))
            self.assertIn("Secure", set_cookies_cb)
            entrada = retorno.cookies.get("rhythmmind_google_entrada")
            self.assertTrue(entrada)

            concluir = cliente.post(
                "/api/auth/google/concluir",
                headers={
                    **proxy_https,
                    "Origin": _ORIGEM_PRODUCAO,
                    "Sec-Fetch-Site": "same-origin",
                    "Cookie": f"rhythmmind_google_entrada={entrada}",
                },
            )
            self.assertEqual(concluir.status_code, 200, concluir.text)
            self.assertIn("token_acesso", concluir.json())

        # Também confirma fluxo automatico via cookie jar HTTPS e bloqueio de origem diferente.
        with TestClient(
            app,
            base_url=_ORIGEM_PRODUCAO,
            client=("203.0.113.10", 50000),
            follow_redirects=False,
        ) as cliente_https:
            iniciar_https = cliente_https.get("/api/auth/google/iniciar")
            self.assertEqual(iniciar_https.status_code, 303)
            params_https = parse_qs(urlsplit(iniciar_https.headers["location"]).query)
            retorno_https = cliente_https.get(
                "/api/auth/google/callback",
                params={"state": params_https["state"][0], "code": "codigo-ficticio"},
            )
            self.assertEqual(retorno_https.headers["location"], "/?google=concluir")
            negado = cliente_https.post(
                "/api/auth/google/concluir",
                headers={"Origin": "https://outro.run.app", "Sec-Fetch-Site": "same-origin"},
            )
            self.assertEqual(negado.status_code, 403)
            ok = cliente_https.post(
                "/api/auth/google/concluir",
                headers={"Origin": _ORIGEM_PRODUCAO, "Sec-Fetch-Site": "same-origin"},
            )
            self.assertEqual(ok.status_code, 200)
            self.assertIn("token_acesso", ok.json())


if __name__ == "__main__":
    unittest.main()
