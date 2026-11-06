"""Configuracao e identidade Google, com transporte falso e assinaturas locais."""

import base64
import hashlib
import json
import os
import time
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.auth import crypt, jwt
import requests

from core import google_oidc as google


CLIENT_ID = "123456-test.apps.googleusercontent.com"
SECRET = "segredo-ficticio-nao-utilizavel"
STATE = "s" * 43
NONCE = "n" * 43
VERIFIER = "v" * 64
CODE = "codigo-ficticio-do-provedor"


class GoogleConfigTests(unittest.TestCase):
    def test_sem_credenciais_fica_desabilitado(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(google.carregar_config_google())

    def test_carrega_config_padrao_sem_expor_secret_no_repr(self):
        with patch.dict(os.environ, {
            "RHYTHMMIND_GOOGLE_CLIENT_ID": CLIENT_ID,
            "RHYTHMMIND_GOOGLE_CLIENT_SECRET": SECRET,
        }, clear=True):
            config = google.carregar_config_google()
        self.assertEqual(config.redirect_uri, "http://127.0.0.1:8000/api/auth/google/callback")
        self.assertEqual(config.origin, "http://127.0.0.1:8000")
        self.assertNotIn(SECRET, repr(config))

    def test_credenciais_parciais_e_malformadas_recusadas_sem_eco(self):
        for env in (
            {"RHYTHMMIND_GOOGLE_CLIENT_ID": CLIENT_ID},
            {"RHYTHMMIND_GOOGLE_CLIENT_SECRET": SECRET},
            {"RHYTHMMIND_GOOGLE_CLIENT_ID": "cliente-invalido", "RHYTHMMIND_GOOGLE_CLIENT_SECRET": SECRET},
            {"RHYTHMMIND_GOOGLE_CLIENT_ID": CLIENT_ID, "RHYTHMMIND_GOOGLE_CLIENT_SECRET": " "},
        ):
            with self.subTest(chaves=list(env)), patch.dict(os.environ, env, clear=True):
                with self.assertRaises(google.ConfiguracaoGoogleInvalida) as erro:
                    google.carregar_config_google()
                self.assertNotIn(SECRET, str(erro.exception))

    def test_redirect_aceita_apenas_retorno_local_exato(self):
        for uri in (
            "http://localhost:8000/api/auth/google/callback",
            "http://[::1]:8000/api/auth/google/callback",
            "https://localhost/api/auth/google/callback",
        ):
            with self.subTest(uri=uri):
                self.assertEqual(google.GoogleConfig(CLIENT_ID, SECRET, uri).redirect_uri, uri)
        for uri in (
            "https://exemplo.invalid/api/auth/google/callback",
            "http://127.0.0.1.evil.invalid/api/auth/google/callback",
            "http://usuario@localhost:8000/api/auth/google/callback",
            "http://localhost:8000/api/auth/google/callback?retorno=evil",
            "http://localhost:8000/api/auth/google/callback?",
            "http://localhost:8000/api/auth/google/callback#fragmento",
            "http://localhost:8000/api/auth/google/callback#",
            "http://localhost:8000/api/auth/google/callback/",
            "http://localhost:8000/outro",
            "http://localhost:0/api/auth/google/callback",
            "http://localhost:99999/api/auth/google/callback",
            "ftp://localhost:8000/api/auth/google/callback",
            "http://localhost:8000/api/auth/google/callback\n",
        ):
            with self.subTest(uri=uri), self.assertRaises(google.ConfiguracaoGoogleInvalida):
                google.GoogleConfig(CLIENT_ID, SECRET, uri)

    def test_url_pkce_tem_escopos_minimos_sem_secret_nem_refresh(self):
        config = google.GoogleConfig(CLIENT_ID, SECRET)
        url = config.url_autorizacao(STATE, NONCE, VERIFIER)
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.scheme + "://" + parsed.netloc + parsed.path,
                         "https://accounts.google.com/o/oauth2/v2/auth")
        self.assertEqual(query["scope"], ["openid profile email"])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["state"], [STATE])
        self.assertEqual(query["nonce"], [NONCE])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        esperado = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("=")
        self.assertEqual(query["code_challenge"], [esperado])
        for sigilo in (SECRET, VERIFIER):
            self.assertNotIn(sigilo, url)
        self.assertNotIn("access_type", query)
        self.assertNotIn("login_hint", query)


class GoogleIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        privada = chave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption())
        cls.publica = chave.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
        cls.signer = crypt.RSASigner.from_string(privada, key_id="chave-local-ficticia")

    def setUp(self):
        self.config = google.GoogleConfig(CLIENT_ID, SECRET)
        self.claims = {
            "iss": "https://accounts.google.com", "sub": "sujeito_ficticio_123",
            "aud": CLIENT_ID, "azp": CLIENT_ID, "nonce": NONCE,
            "iat": int(time.time()) - 10, "exp": int(time.time()) + 300,
            "email": "ficticio@example.invalid", "email_verified": True,
        }
        self.session = MagicMock()
        self.session.__enter__.return_value = self.session
        self.post = MagicMock(status_code=200)
        self.session.post.return_value = self.post
        certs = requests.Response()
        certs.status_code = 200
        certs._content = json.dumps({"chave-local-ficticia": self.publica}).encode()
        certs.headers["Content-Type"] = "application/json"
        self.session.request.return_value = certs
        self.enterContext(patch.object(google.requests, "Session", return_value=self.session))

    def executar(self, claims=None, token=None):
        if token is None:
            token = jwt.encode(self.signer, self.claims if claims is None else claims).decode()
        self.post.json.return_value = {
            "id_token": token, "access_token": "nao-conservar-access-token-ficticio",
            "refresh_token": "nao-conservar-refresh-token-ficticio",
        }
        return google.validar_codigo_google(self.config, CODE, NONCE, VERIFIER)

    def test_assinatura_real_local_nonce_aud_e_identidade_minima(self):
        identidade = self.executar()
        self.assertEqual(identidade, {"iss": "https://accounts.google.com", "sub": self.claims["sub"]})
        chamada = self.session.post.call_args
        self.assertEqual(chamada.args, ("https://oauth2.googleapis.com/token",))
        self.assertEqual(chamada.kwargs["data"]["client_secret"], SECRET)
        self.assertEqual(chamada.kwargs["data"]["code_verifier"], VERIFIER)
        self.assertEqual(chamada.kwargs["data"]["grant_type"], "authorization_code")
        self.assertFalse(chamada.kwargs["allow_redirects"])
        self.assertEqual(chamada.kwargs["timeout"], 10)
        cert_request = self.session.request.call_args
        self.assertEqual(cert_request.args[:2], ("GET", "https://www.googleapis.com/oauth2/v1/certs"))
        self.assertEqual(cert_request.kwargs["timeout"], 10)
        self.assertNotIn("verify", chamada.kwargs)  # TLS padrao verificado.

    def test_normaliza_issuer_google_legado(self):
        self.assertEqual(self.executar({**self.claims, "iss": "accounts.google.com"})["iss"],
                         "https://accounts.google.com")

    def test_recusa_nonce_aud_azp_emissor_tempo_e_subject_invalidos(self):
        for alteracoes in (
            {"nonce": "x" * 43}, {"nonce": None}, {"nonce": "não-ascii"},
            {"aud": "outro.apps.googleusercontent.com"}, {"aud": [CLIENT_ID]},
            {"azp": "outro.apps.googleusercontent.com"},
            {"iss": "https://emissor-falso.invalid"},
            {"exp": int(time.time()) - 30}, {"iat": int(time.time()) + 300},
            {"exp": None}, {"iat": True},
            {"sub": ""}, {"sub": "a" * 256}, {"sub": 123},
        ):
            with self.subTest(alteracoes=alteracoes), self.assertRaises(google.FalhaIdentidadeGoogle):
                self.executar({**self.claims, **alteracoes})

    def test_recusa_claims_obrigatorios_ausentes(self):
        for ausente in ("iss", "sub", "aud", "nonce", "iat", "exp"):
            claims = {k: v for k, v in self.claims.items() if k != ausente}
            with self.subTest(ausente=ausente), self.assertRaises(google.FalhaIdentidadeGoogle):
                self.executar(claims)

    def test_recusa_assinatura_incorreta_e_algoritmo_none(self):
        token = jwt.encode(self.signer, self.claims).decode()
        partes = token.split(".")
        assinatura = bytearray(base64.urlsafe_b64decode(partes[2] + "=" * (-len(partes[2]) % 4)))
        assinatura[0] ^= 1
        assinatura = base64.urlsafe_b64encode(assinatura).decode().rstrip("=")
        header_none = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
        for adulterado in (
            ".".join([partes[0], partes[1], assinatura]),
            ".".join([header_none, partes[1], ""]),
            "isto-nao-e-um-jwt",
        ):
            with self.subTest(tipo=adulterado[:12]), self.assertRaises(google.FalhaIdentidadeGoogle):
                self.executar(token=adulterado)

    def test_erros_do_provedor_nao_ecoam_segredos(self):
        for status, erro in (
            (302, google.FalhaIdentidadeGoogle), (400, google.FalhaIdentidadeGoogle),
            (401, google.FalhaIdentidadeGoogle), (429, google.FalhaGoogleIndisponivel),
            (500, google.FalhaGoogleIndisponivel), (503, google.FalhaGoogleIndisponivel),
        ):
            self.post.status_code = status
            self.post.text = SECRET + CODE
            with self.subTest(status=status), self.assertRaises(erro) as contexto:
                self.executar()
            for sigilo in (SECRET, CODE):
                self.assertNotIn(sigilo, str(contexto.exception))

    def test_resposta_json_invalida_e_sem_id_token(self):
        for resposta in ({}, [], {"id_token": ""}, {"id_token": 123}):
            self.post.json.return_value = resposta
            with self.subTest(resposta=resposta), self.assertRaises(google.FalhaIdentidadeGoogle):
                google.validar_codigo_google(self.config, CODE, NONCE, VERIFIER)
        self.post.json.side_effect = ValueError(SECRET)
        with self.assertRaises(google.FalhaIdentidadeGoogle) as contexto:
            google.validar_codigo_google(self.config, CODE, NONCE, VERIFIER)
        self.assertNotIn(SECRET, str(contexto.exception))

    def test_rede_e_certificados_tem_timeout_e_falha_segura(self):
        self.session.post.side_effect = requests.Timeout(SECRET)
        with self.assertRaises(google.FalhaGoogleIndisponivel):
            self.executar()
        self.session.post.side_effect = None
        self.session.request.side_effect = requests.Timeout(SECRET)
        with self.assertRaises(google.FalhaGoogleIndisponivel):
            self.executar()


if __name__ == "__main__":
    unittest.main()
