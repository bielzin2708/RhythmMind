"""OIDC simulado de ponta a ponta; nenhuma conta ou rede Google real."""

import base64
import hashlib
import logging
import os
import sqlite3
import unittest
from contextlib import closing
from urllib.parse import parse_qs, urlencode, urlsplit
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import google_auth
from api.desenvolvimento import dados_ficticios_temporarios
from api.main import app
from core import autenticacao
from core.google_oidc import FalhaGoogleIndisponivel, FalhaIdentidadeGoogle


_ORIGEM = "http://127.0.0.1:8000"
_CONFIG = {
    "RHYTHMMIND_GOOGLE_CLIENT_ID": "123456-ficticio.apps.googleusercontent.com",
    "RHYTHMMIND_GOOGLE_CLIENT_SECRET": "segredo-OAuth-inventado-apenas-para-teste",
    "RHYTHMMIND_GOOGLE_REDIRECT_URI": _ORIGEM + "/api/auth/google/callback",
}


class GoogleAuthApiTests(unittest.TestCase):
    def setUp(self):
        self.raiz = self.enterContext(dados_ficticios_temporarios())
        self.enterContext(patch.dict(os.environ, _CONFIG))
        self.client = self.cliente()
        self.identidade = self.enterContext(patch.object(google_auth, "validar_codigo_google", return_value={
            "iss": "https://accounts.google.com", "sub": "google-ficticio-A",
        }))

    def cliente(self, origem=_ORIGEM, peer="127.0.0.1"):
        return self.enterContext(TestClient(
            app, base_url=origem, client=(peer, 50000), follow_redirects=False,
        ))

    def iniciar(self, cliente=None):
        cliente = cliente or self.client
        resposta = cliente.get("/api/auth/google/iniciar")
        self.assertEqual(resposta.status_code, 303, resposta.text)
        return parse_qs(urlsplit(resposta.headers["location"]).query)

    def retornar(self, params=None, cliente=None, **campos):
        cliente = cliente or self.client
        params = params or self.iniciar(cliente)
        return cliente.get("/api/auth/google/callback", params={
            "state": params["state"][0], "code": "codigo-google-ficticio", **campos,
        })

    def concluir(self, cliente=None, **headers):
        return (cliente or self.client).post("/api/auth/google/concluir", headers={
            "Origin": _ORIGEM, **headers,
        })

    def test_configuracao_publica_nao_expoe_credenciais_e_informa_armazenamento(self):
        resposta = self.client.get("/api/auth/google/config")
        self.assertEqual(resposta.json(), {
            "disponivel": True, "inicio_url": "/api/auth/google/iniciar", "armazenamento": "temporario",
        })
        for segredo in _CONFIG.values():
            self.assertNotIn(segredo, resposta.text)
        with patch.object(app.state, "armazenamento_persistente", True):
            self.assertEqual(self.client.get("/api/auth/google/config").json()["armazenamento"], "persistente")

    def test_configuracao_ausente_ou_parcial_recusa_inicio_sem_expor_segredos(self):
        for valores in ({chave: "" for chave in _CONFIG}, {"RHYTHMMIND_GOOGLE_CLIENT_SECRET": ""}):
            with self.subTest(valores=len(valores)), patch.dict(os.environ, valores):
                self.assertIs(self.client.get("/api/auth/google/config").json()["disponivel"], False)
                resposta = self.client.get("/api/auth/google/iniciar")
                self.assertEqual(resposta.status_code, 503)
                self.assertNotIn(_CONFIG["RHYTHMMIND_GOOGLE_CLIENT_SECRET"], resposta.text)

    def test_inicio_google_usa_pkce_state_nonce_e_cookie_http_only(self):
        resposta = self.client.get("/api/auth/google/iniciar")
        url = urlsplit(resposta.headers["location"])
        params = parse_qs(url.query)
        self.assertEqual((url.scheme, url.netloc), ("https", "accounts.google.com"))
        self.assertEqual(params["response_type"], ["code"])
        self.assertEqual(set(params["scope"][0].split()), {"openid", "profile", "email"})
        self.assertEqual(params["code_challenge_method"], ["S256"])
        self.assertNotIn("client_secret", params)
        self.assertNotIn("access_type", params)
        cookie = resposta.headers.get_list("set-cookie")[0]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=lax", cookie)
        self.assertIn("Max-Age=600", cookie)
        self.assertIn("Path=/api/auth/google", cookie)
        self.assertEqual(resposta.headers["referrer-policy"], "no-referrer")
        self.assertEqual(resposta.headers["cache-control"], "no-store")
        repositorio = autenticacao.RepositorioAcesso(self.raiz / "data/acesso.sqlite3")
        fluxo = repositorio.consumir_fluxo_google(
            params["state"][0], self.client.cookies.get("rhythmmind_google_fluxo"),
        )
        challenge = base64.urlsafe_b64encode(hashlib.sha256(fluxo["verifier"].encode("ascii")).digest()).rstrip(b"=").decode("ascii")
        self.assertEqual(params["code_challenge"], [challenge])
        self.assertEqual(params["nonce"], [fluxo["nonce"]])

    def test_inicio_canoniza_host_antes_de_criar_cookie(self):
        cliente = self.cliente("http://localhost:8000")
        resposta = cliente.get("/api/auth/google/iniciar")
        self.assertEqual(resposta.status_code, 303)
        self.assertEqual(resposta.headers["location"], _ORIGEM + "/api/auth/google/iniciar")
        self.assertNotIn("set-cookie", resposta.headers)
        self.identidade.assert_not_called()

    def test_fluxo_completo_entrega_token_so_por_post_e_reutiliza_perfil(self):
        perfis = []
        for _ in range(2):
            params = self.iniciar()
            resposta = self.retornar(params)
            self.assertEqual(resposta.status_code, 303)
            self.assertEqual(resposta.headers["location"], "/?google=concluir")
            cookie = resposta.headers.get_list("set-cookie")[-1]
            self.assertIn("rhythmmind_google_entrada=", cookie)
            self.assertIn("HttpOnly", cookie)
            self.assertIn("Max-Age=60", cookie)
            _, codigo, nonce, verifier = self.identidade.call_args.args
            self.assertEqual(codigo, "codigo-google-ficticio")
            self.assertEqual(params["nonce"], [nonce])
            self.assertEqual(len(verifier), 64)
            acesso = self.concluir()
            self.assertEqual(acesso.status_code, 200, acesso.text)
            dados = acesso.json()
            self.assertEqual(set(dados), {"token_acesso", "tipo_token", "expires_in", "expira_em"})
            self.assertEqual(dados["tipo_token"], "bearer")
            perfil = self.client.get("/api/auth/eu", headers={"Authorization": "Bearer " + dados["token_acesso"]})
            self.assertEqual(perfil.status_code, 200)
            perfis.append(perfil.json())
            for segredo in (dados["token_acesso"], "codigo-google-ficticio", "google-ficticio-A"):
                self.assertNotIn(segredo, resposta.headers["location"])
        self.assertEqual(perfis[0], perfis[1])

    def test_state_sem_cookie_ou_em_outro_navegador_nao_autentica(self):
        params = self.iniciar()
        outro = self.cliente()
        resposta = self.retornar(params, outro)
        self.assertEqual(resposta.headers["location"], "/?google=falha")
        self.identidade.assert_not_called()
        self.assertEqual(self.retornar(params).headers["location"], "/?google=concluir")

    def test_callback_repetido_nao_chama_provedor_novamente(self):
        params = self.iniciar()
        self.assertEqual(self.retornar(params).headers["location"], "/?google=concluir")
        self.assertEqual(self.retornar(params).headers["location"], "/?google=falha")
        self.identidade.assert_called_once()

    def test_cancelamento_e_erros_externos_nao_sao_ecoado_nem_criam_acesso(self):
        for erro, resultado in (("access_denied", "cancelado"), ("erro_inventado", "falha")):
            with self.subTest(erro=erro):
                params = self.iniciar()
                resposta = self.client.get("/api/auth/google/callback", params={
                    "state": params["state"][0], "error": erro,
                    "error_description": "segredo_externo_<script>alert(1)</script>",
                })
                self.assertEqual(resposta.headers["location"], "/?google=" + resultado)
                self.assertNotIn("segredo_externo", resposta.text + str(resposta.headers))
        self.identidade.assert_not_called()

    def test_falha_do_provedor_ou_identidade_recusada_nao_cria_conta(self):
        for erro, resultado in (
            (FalhaGoogleIndisponivel(), "indisponivel"),
            (FalhaIdentidadeGoogle(), "falha"),
        ):
            with self.subTest(erro=type(erro).__name__):
                self.identidade.side_effect = erro
                resposta = self.retornar()
                self.assertEqual(resposta.headers["location"], "/?google=" + resultado)
                self.assertNotIn("segredo_externo_ficticio", resposta.text + str(resposta.headers))
                self.assertEqual(self.concluir().status_code, 401)
        with closing(sqlite3.connect(self.raiz / "data/acesso.sqlite3")) as conexao:
            self.assertEqual(conexao.execute("SELECT count(*) FROM usuarios").fetchone()[0], 0)

    def test_campos_repetidos_e_codigo_ausente_recusados_antes_do_provedor(self):
        for variante in ("state_duplicado", "code_duplicado", "sem_code", "sem_state"):
            with self.subTest(variante=variante):
                params = self.iniciar()
                pares = [("state", params["state"][0]), ("code", "codigo-ficticio")]
                if variante == "state_duplicado":
                    pares.append(pares[0])
                elif variante == "code_duplicado":
                    pares.append(pares[1])
                elif variante == "sem_code":
                    pares.pop(1)
                else:
                    pares.pop(0)
                resposta = self.client.get("/api/auth/google/callback?" + urlencode(pares))
                self.assertEqual(resposta.headers["location"], "/?google=falha")
        self.identidade.assert_not_called()

    def test_estado_expirado_recusado(self):
        with patch.object(autenticacao, "agora", return_value=1000):
            params = self.iniciar()
        with patch.object(autenticacao, "agora", return_value=1600):
            resposta = self.retornar(params)
        self.assertEqual(resposta.headers["location"], "/?google=falha")
        self.identidade.assert_not_called()

    def test_conclusao_requer_origem_exata_e_nao_consume_tentativa_cross_site(self):
        self.retornar()
        for cabecalhos in ({}, {"Origin": "https://host-inventado.invalid"},
                           {"Origin": _ORIGEM, "Sec-Fetch-Site": "cross-site"}):
            with self.subTest(cabecalhos=cabecalhos):
                self.assertEqual(self.client.post("/api/auth/google/concluir", headers=cabecalhos).status_code, 403)
        self.assertEqual(self.concluir().status_code, 200)

    def test_conclusao_de_uso_unico_expira_e_nao_funciona_sem_cookie(self):
        self.assertEqual(self.concluir().status_code, 401)
        with patch.object(autenticacao, "agora", return_value=1000):
            self.retornar()
        with patch.object(autenticacao, "agora", return_value=1060):
            self.assertEqual(self.concluir().status_code, 401)
        self.retornar()
        self.assertEqual(self.concluir().status_code, 200)
        self.assertEqual(self.concluir().status_code, 401)
        self.assertEqual(self.client.get("/api/auth/google/concluir").status_code, 405)

    def test_google_e_conta_local_mantem_isolamento_e_logout(self):
        local = self.client.post("/api/auth/registrar", json={"nome_usuario": "google_ficticio", "senha": "abc123"})
        self.assertEqual(local.status_code, 201)
        local_token = self.client.post("/api/auth/entrar", json={"nome_usuario": "google_ficticio", "senha": "abc123"}).json()["token_acesso"]
        google_tokens = []
        for sub in ("google-ficticio-A", "google-ficticio-B"):
            self.identidade.return_value["sub"] = sub
            self.retornar()
            google_tokens.append(self.concluir().json()["token_acesso"])
        clientes = []
        for indice, token in enumerate([local_token, *google_tokens]):
            cliente = self.cliente()
            cliente.headers["Authorization"] = "Bearer " + token
            clientes.append(cliente)
            resposta = cliente.post("/api/registrar-estado", json={"texto_atual": f"Relato ficticio {indice}: cansado"})
            self.assertEqual(resposta.status_code, 200)
        for indice, cliente in enumerate(clientes):
            registros = cliente.get("/api/historico").json()["registros"]
            self.assertEqual(len(registros), 1)
            self.assertEqual(next(iter(registros.values()))["texto_usuario"], f"Relato ficticio {indice}: cansado")
        self.assertEqual(clientes[1].post("/api/auth/sair").status_code, 204)
        self.assertEqual(clientes[1].get("/api/historico").status_code, 401)
        self.assertEqual(clientes[2].get("/api/historico").status_code, 200)

    def test_rotas_google_preservam_bloqueio_local_e_cache(self):
        for cliente in (self.cliente(peer="203.0.113.10"), self.cliente("http://exemplo.invalid")):
            for rota in ("/config", "/iniciar", "/callback"):
                self.assertEqual(cliente.get("/api/auth/google" + rota).status_code, 403)
            self.assertEqual(cliente.post("/api/auth/google/concluir").status_code, 403)
        with patch.object(app.state, "diretorio_desenvolvimento", None):
            self.assertEqual(self.client.get("/api/auth/google/config").status_code, 503)
        self.retornar()
        resposta = self.concluir()
        self.assertEqual(resposta.headers["cache-control"], "no-store")
        self.assertEqual(resposta.headers["referrer-policy"], "no-referrer")

    def test_log_callback_nao_contem_codigo_state_ou_query(self):
        google_auth.configurar_logs_acesso_google()
        google_auth.configurar_logs_acesso_google()
        registro = logging.LogRecord(
            "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
            ("127.0.0.1", "GET", "/api/auth/google/callback?code=codigo_secreto&state=state_secreto", "1.1", 303), None,
        )
        self.assertTrue(logging.getLogger("uvicorn.access").filter(registro))
        self.assertIn("/api/auth/google/callback", registro.getMessage())
        self.assertNotIn("codigo_secreto", registro.getMessage())
        self.assertNotIn("state_secreto", registro.getMessage())


if __name__ == "__main__":
    unittest.main()
