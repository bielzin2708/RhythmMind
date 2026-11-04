"""Autenticacao e isolamento: contas, relatos e armazenamento exclusivamente ficticios."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient
from pwdlib import PasswordHash

from api import autenticacao as auth_api
from api import main as api
from api.desenvolvimento import dados_ficticios_temporarios
from core import autenticacao, storage
from core.contexto import contexto_usuario, usuario_atual


SENHA_A = "senha_ficticia_A_123!"
SENHA_B = "senha_ficticia_B_456!"
MUSICA = {
    "nome": "Faixa Pessoal Ficticia", "artista": "Artista Inventado",
    "duracao": "3:00", "sentimentos_texto": "calmo",
}


class AutenticacaoIsolamentoTests(unittest.TestCase):
    def setUp(self):
        self.raiz = self.enterContext(dados_ficticios_temporarios())
        self.anonimo = self.cliente()
        self.perfil_a, self.token_a = self.cadastrar("conta_a_ficticia", SENHA_A)
        self.perfil_b, self.token_b = self.cadastrar("conta_b_ficticia", SENHA_B)
        self.a = self.cliente(self.token_a)
        self.b = self.cliente(self.token_b)
        self.banco = self.raiz / "data" / "acesso.sqlite3"

    def cliente(self, token=None):
        headers = {"Authorization": "Bearer " + token} if token else {}
        return self.enterContext(TestClient(
            api.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000), headers=headers,
        ))

    def cadastrar(self, nome, senha):
        resposta = self.anonimo.post("/api/auth/registrar", json={"nome_usuario": nome, "senha": senha})
        self.assertEqual(resposta.status_code, 201, resposta.text)
        perfil = resposta.json()
        entrada = self.anonimo.post("/api/auth/entrar", json={"nome_usuario": nome, "senha": senha})
        self.assertEqual(entrada.status_code, 200, entrada.text)
        return perfil, entrada.json()["token_acesso"]

    def criar_sessao(self, cliente, texto="Relato ficticio: cansado.", **campos):
        resposta = cliente.post("/api/registrar-estado", json={"texto_atual": texto, **campos})
        self.assertEqual(resposta.status_code, 200, resposta.text)
        return resposta.json()["sessao_id"]

    def consultar(self, cliente, identificador, **params):
        return cliente.get("/api/historico/sessao", params={"sessao_id": identificador, **params})

    def arquivo(self, perfil, nome):
        return self.raiz / "data" / "usuarios" / perfil["usuario_id"] / nome

    def test_cadastro_identidade_e_nome_normalizado_sem_senha_na_resposta(self):
        self.assertEqual(set(self.perfil_a), {"usuario_id", "nome_usuario", "criado_em"})
        self.assertEqual(UUID(self.perfil_a["usuario_id"]).version, 4)
        self.assertNotEqual(self.perfil_a["usuario_id"], self.perfil_b["usuario_id"])
        self.assertEqual(self.a.get("/api/auth/eu").json(), self.perfil_a)
        self.assertEqual(self.anonimo.get("/api/auth/eu").status_code, 401)
        duplicada = self.anonimo.post("/api/auth/registrar", json={
            "nome_usuario": "CONTA_A_FICTICIA", "senha": SENHA_A,
        })
        self.assertEqual(duplicada.status_code, 409)
        entrada = self.anonimo.post("/api/auth/entrar", json={
            "nome_usuario": "CONTA_A_FICTICIA", "senha": SENHA_A,
        })
        self.assertEqual(entrada.status_code, 200)
        self.assertEqual(self.cliente(entrada.json()["token_acesso"]).get("/api/auth/eu").json(),
                         self.perfil_a)

    def test_senhas_argon2_e_tokens_somente_hash_no_banco(self):
        with closing(sqlite3.connect(self.banco)) as conexao:
            hash_senha = conexao.execute(
                "SELECT senha_hash FROM usuarios WHERE usuario_id = ?", (self.perfil_a["usuario_id"],)
            ).fetchone()[0]
            tokens = {linha[0] for linha in conexao.execute("SELECT token_hash FROM acessos")}
        self.assertTrue(hash_senha.startswith("$argon2id$"))
        self.assertTrue(PasswordHash.recommended().verify(SENHA_A, hash_senha))
        self.assertIn(hashlib.sha256(self.token_a.encode("ascii")).hexdigest(), tokens)
        bruto = self.banco.read_bytes()
        for segredo in (SENHA_A, SENHA_B, self.token_a, self.token_b):
            self.assertNotIn(segredo.encode("utf-8"), bruto)
        reaberto = autenticacao.RepositorioAcesso(self.banco)
        self.assertEqual(reaberto.identificar(self.token_a), self.perfil_a)

    def test_login_invalido_tem_resposta_generica_sem_eco_de_senha(self):
        respostas = []
        for nome, senha in (("conta_a_ficticia", SENHA_B), ("nao_existe_ficticio", SENHA_A)):
            resposta = self.anonimo.post("/api/auth/entrar", json={"nome_usuario": nome, "senha": senha})
            self.assertEqual(resposta.status_code, 401)
            self.assertEqual(resposta.headers["www-authenticate"], "Bearer")
            self.assertNotIn(senha, resposta.text)
            respostas.append(resposta.json())
        self.assertEqual(*respostas)
        for dados in (
            {"nome_usuario": "conta_c_ficticia", "senha": "curta"},
            {"nome_usuario": "../nao_permitido", "senha": SENHA_A},
            {"nome_usuario": "conta_c_ficticia", "senha": SENHA_A, "usuario_id": self.perfil_b["usuario_id"]},
        ):
            resposta = self.anonimo.post("/api/auth/registrar", json=dados)
            self.assertEqual(resposta.status_code, 422)
            self.assertNotIn(dados["senha"], resposta.text)

    def test_todas_operacoes_pessoais_recusam_credencial_ausente_ou_invalida(self):
        casos = [
            ("GET", "/api/auth/eu", {}),
            ("POST", "/api/auth/sair", {}),
            ("GET", "/api/historico", {}),
            ("GET", "/api/padroes", {}),
            ("GET", "/api/musicas", {}),
            ("GET", "/api/historico/sessao", {"params": {"sessao_id": "uuid-ficticio"}}),
            ("POST", "/api/registrar-estado", {"json": {"texto_atual": "Relato ficticio"}}),
            ("POST", "/api/retomar-sessao", {"json": {"sessao_id": "uuid-ficticio"}}),
            ("POST", "/api/escuta", {"json": {"sessao_id": "uuid-ficticio", "faixas": []}}),
            ("POST", "/api/feedback", {"json": {"sessao_id": "uuid-ficticio", "ajudou": True}}),
            ("POST", "/api/musicas", {"json": MUSICA}),
        ]
        for credencial in (None, "Bearer " + "a" * 43, "Basic credencial_ficticia",
                           "Bearer " + self.perfil_a["usuario_id"]):
            for metodo, rota, argumentos in casos:
                with self.subTest(credencial=credencial is not None, metodo=metodo, rota=rota):
                    headers = {"Authorization": credencial} if credencial else {}
                    resposta = self.anonimo.request(metodo, rota, headers=headers, **argumentos)
                    self.assertEqual(resposta.status_code, 401, resposta.text)
        self.assertFalse(self.arquivo(self.perfil_a, "historico.json").exists())
        self.assertFalse(self.arquivo(self.perfil_b, "musicas_usuario.json").exists())

    def test_logout_revoga_credencial_atual_sem_revogar_outra_entrada(self):
        entrada = self.anonimo.post("/api/auth/entrar", json={
            "nome_usuario": "conta_a_ficticia", "senha": SENHA_A,
        }).json()
        outra_entrada = self.cliente(entrada["token_acesso"])
        self.assertNotEqual(entrada["token_acesso"], self.token_a)
        self.assertEqual(self.a.post("/api/auth/sair").status_code, 204)
        self.assertEqual(self.a.get("/api/auth/eu").status_code, 401)
        self.assertEqual(self.a.get("/api/historico").status_code, 401)
        self.assertEqual(self.a.post("/api/auth/sair").status_code, 401)
        self.assertEqual(outra_entrada.get("/api/auth/eu").status_code, 200)
        self.assertEqual(self.b.get("/api/auth/eu").status_code, 200)

    def test_expiracao_absoluta_validada_no_servidor_inclusive_limite(self):
        with closing(sqlite3.connect(self.banco)) as conexao:
            expira = conexao.execute("SELECT expira_em FROM acessos WHERE token_hash = ?",
                (hashlib.sha256(self.token_a.encode("ascii")).hexdigest(),)).fetchone()[0]
        with patch.object(autenticacao, "agora", return_value=expira - 0.01):
            self.assertEqual(self.a.get("/api/auth/eu").status_code, 200)
        with patch.object(autenticacao, "agora", return_value=expira):
            self.assertEqual(self.a.get("/api/auth/eu").status_code, 401)
            self.assertEqual(self.a.get("/api/historico").status_code, 401)
            self.assertEqual(self.a.post("/api/auth/sair").status_code, 401)

    def test_historicos_padroes_e_feedback_isolados(self):
        id_a = self.criar_sessao(self.a, "Relato ficticio A")
        id_b1 = self.criar_sessao(self.b, "Relato ficticio B1")
        id_b2 = self.criar_sessao(self.b, "Relato ficticio B2")
        self.assertEqual(self.a.post("/api/feedback", json={"sessao_id": id_a, "ajudou": False}).status_code, 200)
        self.assertEqual(self.b.post("/api/feedback", json={"sessao_id": id_b1, "ajudou": True}).status_code, 200)
        historico_a = self.a.get("/api/historico").json()
        historico_b = self.b.get("/api/historico").json()
        self.assertEqual(set(historico_a["registros"]), {id_a})
        self.assertEqual(set(historico_b["registros"]), {id_b1, id_b2})
        resumo_a = self.a.get("/api/padroes").json()["avaliacoes_sessoes"]
        resumo_b = self.b.get("/api/padroes").json()["avaliacoes_sessoes"]
        self.assertEqual((resumo_a["sessoes_totais"], resumo_a["retornos_negativos"]), (1, 1))
        self.assertEqual((resumo_b["sessoes_totais"], resumo_b["retornos_positivos"],
                          resumo_b["retornos_nao_registrados"]), (2, 1, 1))
        self.assertNotIn(id_b1, json.dumps(historico_a))
        self.assertNotIn(id_a, json.dumps(historico_b))
        self.assertNotIn("Relato ficticio B", json.dumps(self.a.get("/api/padroes").json()))

    def test_uuid_conhecido_de_outro_titular_nao_permite_leitura_ou_escrita(self):
        id_b = self.criar_sessao(self.b)
        arquivo_b = self.arquivo(self.perfil_b, "historico.json")
        antes = arquivo_b.read_bytes()
        respostas = [
            self.consultar(self.a, id_b),
            self.a.post("/api/retomar-sessao", json={"sessao_id": id_b, "texto_desejado": "calmo"}),
            self.a.post("/api/escuta", json={"sessao_id": id_b, "faixas": []}),
            self.a.post("/api/feedback", json={"sessao_id": id_b, "ajudou": False}),
        ]
        for resposta in respostas:
            self.assertEqual(resposta.status_code, 404)
        self.assertEqual(arquivo_b.read_bytes(), antes)
        self.assertEqual(self.a.get("/api/historico").json()["total"], 0)
        self.assertEqual(self.consultar(self.b, id_b).status_code, 200)

    def test_titular_nao_pode_ser_forjado_no_corpo_query_ou_cabecalho(self):
        id_b = self.criar_sessao(self.b)
        arquivo_b = self.arquivo(self.perfil_b, "historico.json")
        antes = arquivo_b.read_bytes()
        corpos = [
            ("/api/registrar-estado", {"texto_atual": "Relato ficticio A"}),
            ("/api/retomar-sessao", {"sessao_id": id_b}),
            ("/api/escuta", {"sessao_id": id_b, "faixas": []}),
            ("/api/feedback", {"sessao_id": id_b, "ajudou": True}),
            ("/api/musicas", MUSICA),
        ]
        for rota, dados in corpos:
            resposta = self.a.post(rota, json={**dados, "usuario_id": self.perfil_b["usuario_id"]})
            self.assertEqual(resposta.status_code, 422, resposta.text)
        consulta = self.consultar(self.a, id_b, usuario_id=self.perfil_b["usuario_id"])
        self.assertEqual(consulta.status_code, 404)
        self.assertEqual(self.a.get("/api/historico",
            headers={"X-Usuario-Id": self.perfil_b["usuario_id"]},
            params={"usuario_id": self.perfil_b["usuario_id"]}).json()["total"], 0)
        self.assertEqual(arquivo_b.read_bytes(), antes)
        self.assertFalse(self.arquivo(self.perfil_a, "historico.json").exists())

    def test_catalogo_pessoal_e_recomendacoes_nao_usam_musicas_de_outro_usuario(self):
        resposta = self.b.post("/api/musicas", json={**MUSICA, "nome": "Faixa B Ficticia"})
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(self.a.get("/api/musicas").json()["total"], 0)
        id_vazia = self.criar_sessao(self.a, emocoes_confirmadas=["cansado"], texto_desejado="calmo")
        registro = self.consultar(self.a, id_vazia).json()["registro"]
        self.assertEqual(registro["recomendacoes"], [])
        self.assertIsNone(registro["escuta"])
        self.assertIsNone(registro["feedback"])
        resposta = self.a.post("/api/musicas", json={**MUSICA, "nome": "Faixa A Ficticia"})
        self.assertEqual(resposta.status_code, 200)
        id_a = self.criar_sessao(self.a, emocoes_confirmadas=["cansado"], texto_desejado="calmo")
        recomendadas = self.consultar(self.a, id_a).json()["registro"]["recomendacoes"]
        self.assertEqual([m["nome"] for m in recomendadas], ["Faixa A Ficticia"])
        self.assertEqual([m["nome"] for m in self.b.get("/api/musicas").json()["musicas"]], ["Faixa B Ficticia"])

    def test_mesmo_id_musical_em_duas_contas_continua_isolado(self):
        self.assertEqual(self.a.post("/api/musicas", json=MUSICA).status_code, 200)
        self.assertEqual(self.b.post("/api/musicas", json={**MUSICA, "sentimentos_texto": "animado"}).status_code, 200)
        a = self.a.get("/api/musicas").json()["musicas"][0]
        b = self.b.get("/api/musicas").json()["musicas"][0]
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(a["sentimentos_associados"], ["calmo"])
        self.assertEqual(b["sentimentos_associados"], ["animado"])
        self.assertEqual(self.a.get("/api/musicas", params={"sentimento": "animado"}).json()["total"], 0)

    def test_progressivo_retomada_mesmo_uuid_e_pendencias_por_titular(self):
        self.assertEqual(self.a.post("/api/musicas", json=MUSICA).status_code, 200)
        id_a = self.criar_sessao(self.a, "Relato ficticio A interrompido")
        inicial = self.consultar(self.a, id_a).json()["registro"]
        self.assertFalse(any(inicial["progresso"].values()))
        self.assertIsNone(inicial["escuta"])
        self.assertIsNone(inicial["feedback"])
        self.assertEqual(self.b.post("/api/retomar-sessao", json={"sessao_id": id_a}).status_code, 404)
        novo = self.cliente(self.token_a)
        retomada = novo.post("/api/retomar-sessao", json={
            "sessao_id": id_a, "emocoes_confirmadas": ["cansado"], "texto_desejado": "calmo",
        })
        self.assertEqual(retomada.status_code, 200, retomada.text)
        self.assertEqual(self.a.post("/api/escuta", json={"sessao_id": id_a, "faixas": [
            {"indice_recomendacao": 1, "ouvida": None},
        ]}).status_code, 200)
        self.assertEqual(self.a.post("/api/feedback", json={"sessao_id": id_a, "ajudou": True}).status_code, 200)
        antes = self.arquivo(self.perfil_a, "historico.json").read_bytes()
        self.assertEqual(self.a.post("/api/retomar-sessao", json={"sessao_id": id_a}).status_code, 200)
        atual = self.consultar(self.a, id_a).json()["registro"]
        self.assertEqual(atual["sessao_id"], id_a)
        self.assertEqual(atual["data_hora"], inicial["data_hora"])
        self.assertEqual(atual["texto_usuario"], inicial["texto_usuario"])
        self.assertIsNone(atual["escuta"]["faixas"][0]["ouvida"])
        self.assertIs(atual["feedback"]["ajudou"], True)
        self.assertEqual(self.arquivo(self.perfil_a, "historico.json").read_bytes(), antes)
        self.assertEqual(self.a.post("/api/escuta", json={"sessao_id": id_a, "faixas": []}).status_code, 200)
        self.assertEqual(self.consultar(self.a, id_a).json()["registro"]["escuta"], {"faixas": []})

    def test_legado_sem_autoria_nao_e_atribuido_ao_primeiro_ou_proximo_cadastro(self):
        legado = self.raiz / "data" / "historico.json"
        legado.write_text(json.dumps({"01/01/2000 10:00:00": {
            "texto_usuario": "Relato legado ficticio sem autoria", "feedback": {"ajudou": True},
        }}), encoding="utf-8")
        musicas_legadas = self.raiz / "data" / "musicas_usuario.json"
        historico_antes, catalogo_antes = legado.read_bytes(), musicas_legadas.read_bytes()
        for cliente in (self.a, self.b):
            self.assertEqual(cliente.get("/api/historico").json()["total"], 0)
            self.assertEqual(cliente.get("/api/musicas").json()["total"], 0)
            self.assertEqual(cliente.get("/api/padroes").json()["avaliacoes_sessoes"]["sessoes_totais"], 0)
            self.assertEqual(self.consultar(cliente, "01/01/2000 10:00:00").status_code, 404)
        perfil_c, token_c = self.cadastrar("conta_c_ficticia", "senha_ficticia_C_789!")
        self.assertEqual(self.cliente(token_c).get("/api/historico").json()["total"], 0)
        self.assertFalse(self.arquivo(perfil_c, "historico.json").exists())
        self.assertEqual(legado.read_bytes(), historico_antes)
        self.assertEqual(musicas_legadas.read_bytes(), catalogo_antes)

    def test_arquivos_legados_preexistentes_ao_primeiro_cadastro_permanecem_separados(self):
        with dados_ficticios_temporarios() as outra_raiz:
            legado = outra_raiz / "data" / "historico.json"
            legado.write_text(json.dumps({"chave-legada-ficticia": {
                "texto_usuario": "Relato ficticio anterior a qualquer conta", "feedback": None,
            }}), encoding="utf-8")
            catalogo = outra_raiz / "data" / "musicas_usuario.json"
            antes = (legado.read_bytes(), catalogo.read_bytes())
            with TestClient(api.app, base_url="http://127.0.0.1",
                            client=("127.0.0.1", 50000)) as cliente:
                perfil = cliente.post("/api/auth/registrar", json={
                    "nome_usuario": "primeira_ficticia", "senha": SENHA_A,
                })
                self.assertEqual(perfil.status_code, 201)
                acesso = cliente.post("/api/auth/entrar", json={
                    "nome_usuario": "primeira_ficticia", "senha": SENHA_A,
                })
                cliente.headers["Authorization"] = "Bearer " + acesso.json()["token_acesso"]
                self.assertEqual(cliente.get("/api/historico").json()["total"], 0)
                self.assertEqual(cliente.get("/api/musicas").json()["total"], 0)
                self.assertEqual(self.consultar(cliente, "chave-legada-ficticia").status_code, 404)
            self.assertEqual((legado.read_bytes(), catalogo.read_bytes()), antes)

    def test_namespace_cruzado_recusado_e_contexto_restaurado(self):
        id_b = self.criar_sessao(self.b)
        arquivo_b = self.arquivo(self.perfil_b, "historico.json")
        self.assertIsNone(usuario_atual())
        with contexto_usuario(self.perfil_a["usuario_id"], self.raiz):
            with self.assertRaises(PermissionError):
                storage.carregar_json(arquivo_b)
            with self.assertRaises(PermissionError):
                storage.salvar_json(arquivo_b, {})
            self.assertEqual(storage.carregar_json(storage.ARQ_HISTORICO, {}), {})
        self.assertIsNone(usuario_atual())
        self.assertEqual(self.consultar(self.b, id_b).status_code, 200)

    def test_requisicoes_concorrentes_de_contas_distintas_nao_compartilham_contexto(self):
        def criar(cliente, prefixo):
            for indice in range(4):
                self.criar_sessao(cliente, f"Relato ficticio {prefixo} {indice}")
        with ThreadPoolExecutor(max_workers=2) as executor:
            futuros = [executor.submit(criar, self.a, "A"), executor.submit(criar, self.b, "B")]
            for futuro in futuros:
                futuro.result(timeout=30)
        for cliente, prefixo in ((self.a, "A"), (self.b, "B")):
            registros = cliente.get("/api/historico").json()["registros"]
            self.assertEqual(len(registros), 4)
            self.assertTrue(all(r["texto_usuario"].startswith(f"Relato ficticio {prefixo}") for r in registros.values()))
        self.assertIsNone(usuario_atual())

    def test_cache_e_falha_de_armazenamento_nao_expoem_dados_ou_segredos(self):
        for rota in ("/api/auth/eu", "/api/historico", "/api/musicas", "/api/padroes"):
            self.assertEqual(self.a.get(rota).headers["cache-control"], "no-store")
        with patch.object(auth_api, "RepositorioAcesso",
                          side_effect=sqlite3.OperationalError("detalhe_interno_ficticio")):
            resposta = self.a.get("/api/historico")
        self.assertEqual(resposta.status_code, 503)
        self.assertNotIn("detalhe_interno_ficticio", resposta.text)
        self.assertNotIn(self.token_a, resposta.text)

    def test_roteador_cobre_todas_rotas_pessoais(self):
        for caminho, operacoes in api.app.openapi()["paths"].items():
            if caminho.startswith("/api/") and not caminho.startswith("/api/auth/"):
                for metodo, operacao in operacoes.items():
                    with self.subTest(rota=caminho, metodo=metodo):
                        self.assertIn({"HTTPBearer": []}, operacao.get("security", []))
        url = f"/data/usuarios/{self.perfil_b['usuario_id']}/historico.json"
        self.assertEqual(self.a.get(url).status_code, 404)

    def test_rotas_de_acesso_mantem_bloqueio_local_e_ambiente_autorizado(self):
        corpo = {"nome_usuario": "conta_local_ficticia", "senha": SENHA_A}
        with TestClient(api.app, base_url="http://127.0.0.1",
                        client=("203.0.113.10", 50000)) as externo:
            resposta = externo.post("/api/auth/registrar", json=corpo,
                                    headers={"X-Forwarded-For": "127.0.0.1"})
            self.assertEqual(resposta.status_code, 403)
        with TestClient(api.app, base_url="http://exemplo.invalid",
                        client=("127.0.0.1", 50000)) as host_invalido:
            self.assertEqual(host_invalido.post("/api/auth/entrar", json=corpo).status_code, 403)
        with patch.object(api.app.state, "diretorio_desenvolvimento", None):
            self.assertEqual(self.a.get("/api/auth/eu").status_code, 503)
            self.assertEqual(self.anonimo.post("/api/auth/registrar", json=corpo).status_code, 503)


if __name__ == "__main__":
    unittest.main()
