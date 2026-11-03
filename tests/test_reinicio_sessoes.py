"""Reinicio real do Python sobre JSON temporario, sem arquivos pessoais."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import UUID


RAIZ_PROJETO = Path(__file__).resolve().parents[1]
RELATO = "Relato ficticio: estou cansado."
LEGADO = {
    "data_hora": "01/01/2000 10:00:00",
    "texto_usuario": "Relato legado ficticio",
    "analise": {"emocoes": ["cansado"], "estado_desejado": []},
    "recomendacoes": [],
    "feedback": {"ajudou": False, "motivo": "Motivo antigo ficticio"},
}


class ReinicioSessoesTests(unittest.TestCase):
    def setUp(self):
        self.raiz = Path(self.enterContext(TemporaryDirectory(prefix="rhythmmind-test-reinicio-")))
        self.data = self.raiz / "data"
        self.data.mkdir()
        self.historico = self.data / "historico.json"
        self.gravar(self.historico, {LEGADO["data_hora"]: LEGADO})
        self.gravar(self.data / "dicionario_emocional.json", {
            "cansado": ["cansado"], "calmo": ["calmo"],
        })
        self.gravar(self.data / "musicas_usuario.json", [{
            "id": "faixa_inventada", "nome": "Faixa inventada", "artista": "Artista ficticio",
            "sentimentos_associados": ["cansado", "calmo"],
            "estrategias": ["descompressao", "espelhamento"],
        }])

    def gravar(self, caminho, dados):
        caminho.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")

    def ler(self):
        return json.loads(self.historico.read_text(encoding="utf-8"))

    def executar(self, entrada, identificador=None):
        programa = (
            "import sys; sys.path.insert(0, sys.argv[1]); import main; "
            "main.opcao_registar_estado() if len(sys.argv) == 2 "
            "else main.continuar_sessao(sys.argv[2])"
        )
        argumentos = [sys.executable, "-B", "-c", programa, str(RAIZ_PROJETO)]
        if identificador is not None:
            argumentos.append(identificador)
        processo = subprocess.run(
            argumentos, input=entrada, capture_output=True, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}, cwd=self.raiz, timeout=20,
        )
        self.assertEqual(processo.returncode, 0, processo.stdout + processo.stderr)
        return processo.stdout

    def sessao_nova(self):
        historico = self.ler()
        self.assertEqual(historico[LEGADO["data_hora"]], LEGADO)
        novas = {chave: valor for chave, valor in historico.items() if chave != LEGADO["data_hora"]}
        self.assertEqual(len(novas), 1)
        identificador, registro = next(iter(novas.items()))
        self.assertEqual(UUID(identificador).version, 4)
        self.assertEqual(registro["sessao_id"], identificador)
        self.assertEqual(registro["texto_usuario"], RELATO)
        self.assertTrue(registro["data_hora"])
        return identificador, registro

    def test_fim_da_entrada_preserva_relato_e_retomada_apos_reiniciar(self):
        saida = self.executar(RELATO + "\n")
        self.assertIn("Fluxo interrompido", saida)
        identificador, inicial = self.sessao_nova()
        self.assertIsNone(inicial["texto_desejado"])
        self.assertIsNone(inicial["escuta"])
        self.assertIsNone(inicial["feedback"])
        self.assertFalse(any(inicial["progresso"].values()))
        self.executar("s\ncalmo\nnenhuma\ns\nMotivo ficticio\nn\n", identificador)
        chave, atual = self.sessao_nova()
        self.assertEqual(chave, identificador)
        self.assertEqual(atual["data_hora"], inicial["data_hora"])
        self.assertEqual(atual["escuta"], {"faixas": []})
        self.assertIs(atual["feedback"]["ajudou"], True)
        self.assertTrue(atual["feedback"]["coleta_concluida"])

    def test_interrupcao_apos_escolha_preserva_escuta_e_feedback_entre_processos(self):
        saida = self.executar(RELATO + "\ns\ncalmo\n1\n")
        self.assertIn("Fluxo interrompido", saida)
        identificador, inicial = self.sessao_nova()
        self.assertEqual(inicial["escuta"], {"faixas": [{"indice_recomendacao": 1, "ouvida": None}]})
        self.assertIsNone(inicial["feedback"])
        self.executar("s\nn\nMotivo ficticio\nn\n", identificador)
        _, concluida = self.sessao_nova()
        self.assertEqual(concluida["data_hora"], inicial["data_hora"])
        self.assertIs(concluida["escuta"]["faixas"][0]["ouvida"], True)
        self.assertIs(concluida["feedback"]["ajudou"], False)
        antes = self.historico.read_bytes()
        self.executar("", identificador)
        self.assertEqual(self.historico.read_bytes(), antes)
        self.assertEqual(self.sessao_nova()[1], concluida)

    def test_sem_recomendacoes_reabre_mesmo_uuid_com_etapas_pendentes(self):
        self.gravar(self.data / "musicas_usuario.json", [])
        self.executar(RELATO + "\ns\ncalmo\n")
        identificador, registro = self.sessao_nova()
        self.assertTrue(registro["progresso"]["recomendacoes_geradas"])
        self.assertEqual(registro["recomendacoes"], [])
        self.assertIsNone(registro["escuta"])
        self.assertIsNone(registro["feedback"])
        antes = self.historico.read_bytes()
        self.executar("", identificador)
        self.assertEqual(self.historico.read_bytes(), antes)
        self.assertEqual(self.sessao_nova()[1], registro)


if __name__ == "__main__":
    unittest.main()
