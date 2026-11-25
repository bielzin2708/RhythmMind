"""Fluxo OAuth público em instâncias Vercel independentes, com Google e Blob simulados."""

import base64
import hashlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from api import google_auth
from api.main import app
from api.producao import ambiente_producao
from core import armazenamento_nuvem
from core.google_oidc import FalhaIdentidadeGoogle
from tests.test_armazenamento_nuvem import _FakeBlobStore


_ORIGEM = "https://rhythmmind-teste.vercel.app"
_CALLBACK = "/api/auth/google/callback"
_INICIAR = "/api/auth/google/iniciar"
_CONCLUIR = "/api/auth/google/concluir"


class LoginGoogleVercelTests(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ, {
            "RHYTHMMIND_AMBIENTE": "producao",
            "RHYTHMMIND_GOOGLE_CLIENT_ID": "123-ficticio.apps.googleusercontent.com",
            "RHYTHMMIND_GOOGLE_CLIENT_SECRET": "segredo-oauth-ficticio",
            "RHYTHMMIND_GOOGLE_REDIRECT_URI": _ORIGEM + _CALLBACK,
            "RHYTHMMIND_TOKEN_SECRET": "segredo-de-assinatura-ficticio-para-teste",
            "BLOB_READ_WRITE_TOKEN": "token-blob-ficticio",
        }))
        self.blob = _FakeBlobStore()
        self.enterContext(patch.object(armazenamento_nuvem, "_cliente_blob", return_value=self.blob))
        self.cliente = self.enterContext(TestClient(app, base_url=_ORIGEM, follow_redirects=False))
        self.codigos_usados = set()
        self.google = self.enterContext(patch.object(
            google_auth, "validar_codigo_google", side_effect=self.validar_no_google,
        ))

    def validar_no_google(self, config, codigo, nonce, verifier):
        if codigo in self.codigos_usados:
            raise FalhaIdentidadeGoogle()
        self.codigos_usados.add(codigo)
        return {"iss": "https://accounts.google.com", "sub": "identidade-google-ficticia"}

    def iniciar(self):
        with ambiente_producao(self.pasta / "inicio"):
            resposta = self.cliente.get(_INICIAR)
        self.assertEqual(resposta.status_code, 303)
        destino = urlsplit(resposta.headers["location"])
        self.assertEqual(destino.netloc, "accounts.google.com")
        return parse_qs(destino.query)

    def retornar(self, state, codigo, headers=None):
        with ambiente_producao(self.pasta / "callback"):
            return self.cliente.get(_CALLBACK, params={"state": state, "code": codigo}, headers=headers)

    def concluir(self, instancia="conclusao", **cabecalhos):
        with ambiente_producao(self.pasta / instancia):
            return self.cliente.post(_CONCLUIR, headers={"Origin": _ORIGEM, **cabecalhos})

    def test_login_entre_instancias_e_repeticao_da_entrega(self):
        parametros = self.iniciar()
        self.assertFalse(self.blob.objetos)
        codigo = "A" * 4096
        retorno = self.retornar(parametros["state"][0], codigo)
        self.assertEqual(retorno.headers["location"], "/?google=concluir")
        for cabecalho in retorno.headers.get_list("set-cookie"):
            self.assertLess(len(cabecalho.encode("ascii")), 4096)
            self.assertNotIn(codigo[:80], cabecalho)
        cookies = list(self.cliente.cookies.jar)
        self.assertTrue(cookies)
        for cookie in cookies:
            self.assertTrue(cookie.secure)
            self.assertTrue(cookie.has_nonstandard_attr("HttpOnly"))

        self.assertEqual(self.concluir(Origin="https://outra-origem.example").status_code, 403)
        self.google.assert_not_called()
        entrega = self.concluir()
        self.assertEqual(entrega.status_code, 200, entrega.text)
        token = entrega.json()["token_acesso"]
        self.assertEqual(self.codigos_usados, {codigo})
        _, _, nonce, verifier = self.google.call_args.args
        self.assertEqual(nonce, parametros["nonce"][0])
        resumo = hashlib.sha256(verifier.encode("ascii")).digest()
        self.assertEqual(base64.urlsafe_b64encode(resumo).rstrip(b"=").decode(), parametros["code_challenge"][0])
        with ambiente_producao(self.pasta / "perfil"):
            perfil = self.cliente.get("/api/auth/eu", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(perfil.status_code, 200, perfil.text)

        for cookie in cookies:
            self.cliente.cookies.jar.set_cookie(cookie)
        repetida = self.concluir("outra-conclusao")
        self.assertEqual(repetida.status_code, 401)
        self.assertNotIn("token_acesso", repetida.json())

    def test_callback_exige_state_do_mesmo_navegador_e_cookie_valido(self):
        for caso in ("outro_state", "sem_cookie", "adulterado", "expirado"):
            with self.subTest(caso=caso):
                state = self.iniciar()["state"][0]
                if caso == "outro_state":
                    self.iniciar()
                elif caso == "sem_cookie":
                    self.cliente.cookies.clear()
                elif caso == "adulterado":
                    for cookie in self.cliente.cookies.jar:
                        cookie.value = "invalido-" + cookie.value
                # Envie o cookie inclusive após o vencimento para exercitar o prazo no servidor.
                enviados = "; ".join(f"{c.name}={c.value}" for c in self.cliente.cookies.jar)
                instante = time.time() + (601 if caso == "expirado" else 0)
                with patch("time.time", return_value=instante):
                    resposta = self.retornar(state, "codigo-google-ficticio", {"Cookie": enviados})
                self.assertEqual(resposta.headers["location"], "/?google=falha")
                self.assertEqual(self.concluir().status_code, 401)
        self.google.assert_not_called()
        self.assertFalse(self.blob.objetos)

    def test_entrega_expirada_nao_troca_codigo_com_google(self):
        state = self.iniciar()["state"][0]
        resposta = self.retornar(state, "codigo-google-ficticio")
        self.assertEqual(resposta.headers["location"], "/?google=concluir")
        enviados = "; ".join(f"{c.name}={c.value}" for c in self.cliente.cookies.jar)
        with patch("time.time", return_value=time.time() + 61):
            self.assertEqual(self.concluir(Cookie=enviados).status_code, 401)
        self.google.assert_not_called()
        self.assertFalse(self.blob.objetos)
