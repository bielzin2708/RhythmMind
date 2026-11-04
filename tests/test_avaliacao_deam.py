"""Ingestão offline: fontes sintéticas temporárias e o piloto externo identificado."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from avaliacao import preparar_deam as deam
from core.caracterizacao import validar_musica


RAIZ = Path(__file__).resolve().parents[1]
CABECALHO = "song_id, valence_mean, valence_std, arousal_mean, arousal_std\n"


def csv_ficticio(linhas="12,2.25,0,7.5,1.10\n"):
    return (CABECALHO + linhas).encode("utf-8")


def zip_ficticio(conteudo, membro=deam.MEMBRO_CSV):
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w", zipfile.ZIP_DEFLATED) as pacote:
        pacote.writestr(membro, conteudo)
    return memoria.getvalue()


class LeituraDeamTests(unittest.TestCase):
    def test_preserva_colunas_e_aceita_bom_sem_alterar_escala(self):
        entrada = b"\xef\xbb\xbf" + csv_ficticio("12, 2.25,0,7.5,1.10\n\n")
        registro, = deam.ler_anotacoes(entrada)
        self.assertEqual(registro["id_fonte"], 12)
        self.assertEqual(registro["valence_mean"], 2.25)
        self.assertEqual(registro["arousal_mean"], 7.5)
        self.assertEqual(registro["valence_std"], 0)
        self.assertEqual(registro["colunas_originais"]["valence_mean"], " 2.25")
        self.assertEqual(registro["colunas_originais"]["arousal_std"], "1.10")

    def test_aceita_extremos_da_escala_e_zero_real_de_dispersao(self):
        registros = deam.ler_anotacoes(csv_ficticio("1,1,0,9,0\n2,9,0,1,0\n"))
        self.assertEqual([r["valence_mean"] for r in registros], [1, 9])
        self.assertEqual([r["arousal_mean"] for r in registros], [9, 1])

    def test_recusa_conteudo_sem_bytes_ou_utf8(self):
        for entrada in (None, "texto", b"\xff"):
            with self.subTest(entrada=entrada), self.assertRaises(ValueError):
                deam.ler_anotacoes(entrada)

    def test_recusa_cabecalho_ausente_duplicado_trocado_ou_extra(self):
        entradas = [
            b"", csv_ficticio().replace(b"valence_std", b"valence_mean"),
            csv_ficticio().replace(b"valence_mean", b"nota"),
            csv_ficticio().replace(b"song_id, valence_mean", b"valence_mean, song_id"),
            csv_ficticio().replace(b"arousal_std\n", b"arousal_std,extra\n"),
        ]
        for entrada in entradas:
            with self.subTest(entrada=entrada), self.assertRaises(ValueError):
                deam.ler_anotacoes(entrada)

    def test_recusa_medias_ausentes_nao_finitas_ou_fora_da_escala(self):
        for coluna in (1, 3):
            for valor in ("", "null", "nan", "inf", "-inf", "0", "9.01", "texto"):
                campos = ["12", "2.25", "0", "7.5", "1.10"]
                campos[coluna] = valor
                with self.subTest(coluna=coluna, valor=valor), self.assertRaises(ValueError):
                    deam.ler_anotacoes(csv_ficticio(",".join(campos) + "\n"))

    def test_recusa_desvios_ausentes_negativos_ou_nao_finitos(self):
        for coluna in (2, 4):
            for valor in ("", "-0.01", "NaN", "inf", "texto"):
                campos = ["12", "2.25", "0", "7.5", "1.10"]
                campos[coluna] = valor
                with self.subTest(coluna=coluna, valor=valor), self.assertRaises(ValueError):
                    deam.ler_anotacoes(csv_ficticio(",".join(campos) + "\n"))

    def test_recusa_ids_invalidos_e_repetidos_inclusive_com_zeros(self):
        for identificador in ("", "0", "-1", "1.5", "١٢", "abc"):
            with self.subTest(id=identificador), self.assertRaises(ValueError):
                deam.ler_anotacoes(csv_ficticio(f"{identificador},2,0,7,1\n"))
        for repetido in ("12", "012"):
            with self.subTest(repetido=repetido), self.assertRaises(ValueError):
                deam.ler_anotacoes(csv_ficticio(f"12,2,0,7,1\n{repetido},4,0,6,1\n"))

    def test_recusa_registros_incompletos_csv_malformado_e_conjunto_vazio(self):
        for linhas in ("12,2,0,7\n", "12,2,0,7,1,extra\n", '"12,2,0,7,1\n', "\n"):
            with self.subTest(linhas=linhas), self.assertRaises(ValueError):
                deam.ler_anotacoes(csv_ficticio(linhas))


class SelecaoEConversaoTests(unittest.TestCase):
    def test_selecao_repetivel_independe_da_ordem_e_das_notas(self):
        registros = deam.ler_anotacoes(csv_ficticio(
            "".join(f"{i},2,0,7,1\n" for i in range(1, 41))
        ))
        original = deepcopy(registros)
        selecionados = deam.selecionar_registros(registros)
        self.assertEqual(registros, original)
        self.assertEqual(len(selecionados), 24)
        ids = [r["id_fonte"] for r in selecionados]
        self.assertEqual(ids, sorted(set(ids)))
        outros = deepcopy(list(reversed(registros)))
        for registro in outros:
            registro["valence_mean"] = 9
            registro["arousal_mean"] = 1
        self.assertEqual([r["id_fonte"] for r in deam.selecionar_registros(outros)], ids)

    def test_recusa_quantidade_invalida_sem_preenchimento_ou_repeticao(self):
        registros = deam.ler_anotacoes(csv_ficticio())
        for quantidade in (0, -1, 2, True, 1.0, "1", None):
            with self.subTest(quantidade=quantidade), self.assertRaises(ValueError):
                deam.selecionar_registros(registros, quantidade)
        self.assertEqual(deam.selecionar_registros(registros, 1), registros)

    def test_conversao_separa_anotacoes_de_estimativas_e_preserva_fonte(self):
        registro, = deam.ler_anotacoes(csv_ficticio())
        original = deepcopy(registro)
        convertido = deam.construir_registro(
            registro, fonte="fonte_sintetica", versao_fonte="teste-1"
        )
        validar_musica(convertido)
        self.assertEqual(registro, original)
        self.assertEqual(convertido["id"], "deam:12")
        self.assertEqual(convertido["dispersao_publicada"], {
            "valencia_desvio_padrao": 0, "ativacao_desvio_padrao": 1.10,
        })
        bloco = convertido["caracterizacao"]
        self.assertEqual(bloco["caracteristicas_acusticas"], [])
        self.assertEqual(bloco["estimativas_sistema"], [])
        for item, atributo, valor in zip(
            bloco["anotacoes_emocionais"], ("valencia", "ativacao"), (2.25, 7.5)
        ):
            self.assertEqual(item["atributo"], atributo)
            self.assertEqual(item["valor"], valor)
            self.assertEqual((item["escala"]["minimo"], item["escala"]["maximo"]), (1, 9))
            self.assertEqual(item["fonte"], "fonte_sintetica")
            self.assertEqual(item["versao"], "teste-1")
            self.assertEqual(item["metodo"], "media_estatica_publicada_de_anotacoes")
        for campo in ("nome", "artista", "bpm", "sentimentos_associados", "feedback", "audio"):
            self.assertNotIn(campo, convertido)
        convertido["colunas_originais"]["valence_mean"] = "alterado"
        self.assertEqual(registro, original)


class PreparacaoArquivoTests(unittest.TestCase):
    def setUp(self):
        self.raiz = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.zip = self.raiz / "fonte_ficticia.zip"
        self.saida = self.raiz / "resultado.json"

    def fonte_ficticia_auditada(self, quantidade=1744):
        conteudo = csv_ficticio("".join(f"{i},2.25,0,7.5,1.10\n" for i in range(1, quantidade + 1)))
        pacote = zip_ficticio(conteudo)
        self.zip.write_bytes(pacote)
        # Só a fixture temporária é autorizada nestes testes; hashes reais ficam preservados.
        self.enterContext(patch.object(deam, "SHA256_ZIP", sha256(pacote).hexdigest()))
        self.enterContext(patch.object(deam, "SHA256_CSV", sha256(conteudo).hexdigest()))

    def executar_com_erro(self):
        with redirect_stderr(io.StringIO()) as erro, self.assertRaises(SystemExit) as saida:
            deam.main([str(self.zip), "--saida", str(self.saida)])
        self.assertEqual(saida.exception.code, 2)
        return erro.getvalue()

    def test_comando_completo_com_zip_sintetico_valida_e_grava_apenas_saida(self):
        self.fonte_ficticia_auditada()
        antes = self.zip.read_bytes()
        with redirect_stdout(io.StringIO()):
            retorno = deam.main([str(self.zip), "--saida", str(self.saida)])
        self.assertEqual(retorno, 0)
        resultado = json.loads(self.saida.read_text(encoding="utf-8"))
        self.assertEqual(len(resultado["registros"]), 24)
        self.assertEqual(resultado["selecao"]["elegiveis"], 1744)
        for registro in resultado["registros"]:
            validar_musica(registro)
        self.assertEqual(self.zip.read_bytes(), antes)
        self.assertEqual({p.name for p in self.raiz.iterdir()}, {self.zip.name, self.saida.name})

    def test_saida_existente_e_preservada(self):
        self.fonte_ficticia_auditada()
        anterior = b'{"registro_ficticio":"preservar"}\n'
        self.saida.write_bytes(anterior)
        self.executar_com_erro()
        self.assertEqual(self.saida.read_bytes(), anterior)

    def test_recusa_zip_diferente_sem_criar_saida(self):
        self.zip.write_bytes(zip_ficticio(csv_ficticio()))
        self.assertIn("SHA-256 do ZIP", self.executar_com_erro())
        self.assertFalse(self.saida.exists())

    def test_recusa_csv_alterado_ou_membro_ausente_sem_criar_saida(self):
        for membro in (deam.MEMBRO_CSV, "outro.csv"):
            pacote = zip_ficticio(csv_ficticio(), membro)
            self.zip.write_bytes(pacote)
            with self.subTest(membro=membro), patch.object(deam, "SHA256_ZIP", sha256(pacote).hexdigest()):
                self.executar_com_erro()
                self.assertFalse(self.saida.exists())

    def test_recusa_conjunto_com_quantidade_de_origem_alterada(self):
        self.fonte_ficticia_auditada(40)
        self.assertIn("Quantidade de registros", self.executar_com_erro())
        self.assertFalse(self.saida.exists())


class PilotoVersionadoTests(unittest.TestCase):
    def setUp(self):
        self.piloto = json.loads((RAIZ / "avaliacao/dados/deam_piloto_v1.json").read_text(encoding="utf-8"))

    def test_manifesto_declara_origem_restricao_e_selecao_sem_notas(self):
        fonte = self.piloto["fonte"]
        self.assertEqual(fonte["sha256_zip"], deam.SHA256_ZIP)
        self.assertEqual(fonte["sha256_csv"], deam.SHA256_CSV)
        self.assertEqual(fonte["download"], deam.URL_ZIP)
        self.assertEqual(fonte["artigo"]["doi"], deam.DOI_ARTIGO)
        self.assertTrue(fonte["licenca"]["divergencia_documentada"])
        self.assertEqual(fonte["licenca"]["restricao_adotada_no_piloto"],
                         "pesquisa_nao_comercial_com_atribuicao")
        self.assertIsNone(fonte["licenca"]["versao_declarada_manual"])
        self.assertEqual(self.piloto["selecao"]["elegiveis"], 1744)
        self.assertEqual(self.piloto["selecao"]["selecionados"], 24)
        self.assertFalse(self.piloto["selecao"]["usa_notas_na_selecao"])
        self.assertFalse(self.piloto["selecao"]["normaliza_escalas"])

    def test_24_ids_unicos_e_conversao_fiel_as_colunas_publicadas(self):
        registros = self.piloto["registros"]
        ids = [registro["id_fonte"] for registro in registros]
        self.assertEqual(len(ids), 24)
        self.assertEqual(ids, sorted(set(ids)))
        for registro in registros:
            with self.subTest(id=registro["id"]):
                validar_musica(registro)
                colunas = registro["colunas_originais"]
                original, = deam.ler_anotacoes(csv_ficticio(
                    ",".join(colunas[c] for c in deam.COLUNAS) + "\n"
                ))
                self.assertEqual(deam.construir_registro(
                    original, fonte=f"DEAM / {deam.MEMBRO_CSV}", versao_fonte=f"sha256:{deam.SHA256_CSV}"
                ), registro)


if __name__ == "__main__":
    unittest.main()
