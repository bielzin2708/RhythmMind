"""Operações do titular sobre o histórico isolado pela identidade autenticada.

A aplicação conserva uma única cópia ativa de cada registro no histórico pessoal.
Correções ficam dentro do próprio registro e são removidas junto com ele. Não são
criadas cópias de exportação ou arquivos de auditoria paralelos no servidor.
"""

from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from core import storage
from core.contexto import usuario_atual
from core.sessoes import _LOCK_HISTORICO, validar_metadados_sessao


POLITICA_RETENCAO = {
    "versao": "rhythmmind.registros.v1",
    "copia_ativa": "Histórico JSON do titular autenticado; sem backups automáticos de registros.",
    "correcoes": "Mantidas dentro da sessão até sua exclusão, incluindo os valores anteriores corrigidos.",
    "exclusao": "Remove a sessão inteira da cópia ativa, incluindo correções, interpretação, escuta e feedback.",
    "exportacoes": "Geradas na resposta HTTP, sem cópia persistida pelo servidor. Arquivos já baixados ficam sob controle do titular.",
    "alcance": "Operação limitada aos registros do histórico. Não exclui a conta nem o catálogo musical.",
}


class ErroTitular(Exception):
    def __init__(self, status, mensagem):
        super().__init__(mensagem)
        self.status = status


def _agora():
    return datetime.now(timezone.utc).isoformat()


def _ler_historico():
    # Sem contexto autenticado nunca deve haver fallback ao histórico global.
    if usuario_atual() is None:
        raise ErroTitular(401, "Autenticação necessária para operar os próprios registros.")
    try:
        historico = storage.carregar_json(storage.ARQ_HISTORICO, {}, estrito=True)
        if not isinstance(historico, dict) or any(
            not isinstance(chave, str) or not isinstance(registro, dict)
            for chave, registro in historico.items()
        ):
            raise ValueError("Formato inválido.")
        return historico
    except PermissionError as erro:
        raise ErroTitular(403, "Armazenamento pessoal não autorizado.") from erro
    except (OSError, ValueError, UnicodeError) as erro:
        raise ErroTitular(503, "Histórico indisponível para esta operação.") from erro


def _gravar(historico):
    try:
        storage.salvar_json(storage.ARQ_HISTORICO, historico)
    except PermissionError as erro:
        raise ErroTitular(403, "Armazenamento pessoal não autorizado.") from erro
    except OSError as erro:
        raise ErroTitular(503, "Não foi possível salvar. A última versão salva foi preservada.") from erro


def _obter(historico, identificador):
    if identificador not in historico:
        # Não distingue uma chave inexistente de uma chave de outro titular.
        raise ErroTitular(404, "Registro de histórico não encontrado.")
    return historico[identificador]


def _revisao(registro):
    revisao = registro.get("revisao_registro", 0)
    correcoes = registro.get("correcoes", [])
    if (isinstance(revisao, bool) or not isinstance(revisao, int) or revisao < 0
            or not isinstance(correcoes, list) or any(not isinstance(item, dict) for item in correcoes)):
        raise ErroTitular(503, "Rastreabilidade do registro indisponível.")
    return revisao, correcoes


def exportar_registros(identificador=None):
    """Snapshot completo dos registros próprios, sem credenciais ou cópia local."""
    with _LOCK_HISTORICO:
        historico = _ler_historico()
        registros = historico if identificador is None else {identificador: _obter(historico, identificador)}
        return {
            "versao": "rhythmmind.exportacao.v1",
            "exportado_em": _agora(),
            "total": len(registros),
            "registros": deepcopy(registros),
            "politica_retencao": deepcopy(POLITICA_RETENCAO),
        }


def corrigir_registro(identificador, alteracoes, *, motivo=None, revisao_esperada=None):
    """Corrige metadados/observações; não reinterpreta relatos nem refaz seleção."""
    if not isinstance(alteracoes, dict) or not alteracoes or set(alteracoes) - {
        "finalidade", "contexto", "observacoes",
    }:
        raise ErroTitular(422, "Informe apenas finalidade, contexto ou observacoes para corrigir.")
    try:
        campos = validar_metadados_sessao(**{
            campo: valor for campo, valor in alteracoes.items() if campo != "observacoes"
        })
        if "observacoes" in alteracoes:
            observacoes = alteracoes["observacoes"]
            if observacoes is not None and (not isinstance(observacoes, str) or len(observacoes) > 4000):
                raise ValueError("Observações devem ter até 4000 caracteres ou null.")
            campos["observacoes"] = observacoes.strip() or None if observacoes is not None else None
        if motivo is not None and (not isinstance(motivo, str) or len(motivo) > 500):
            raise ValueError("O motivo deve ter até 500 caracteres ou null.")
        if revisao_esperada is not None and (
            isinstance(revisao_esperada, bool) or not isinstance(revisao_esperada, int) or revisao_esperada < 0
        ):
            raise ValueError("A revisão esperada deve ser um inteiro não negativo.")
    except ValueError as erro:
        raise ErroTitular(422, str(erro)) from erro
    with _LOCK_HISTORICO:
        historico = _ler_historico()
        original = _obter(historico, identificador)
        revisao, correcoes = _revisao(original)
        if revisao_esperada is not None and revisao != revisao_esperada:
            raise ErroTitular(409, "O registro foi corrigido desde a última leitura. Consulte a versão atual.")
        mudancas = {
            campo: {"anterior": deepcopy(original.get(campo)), "novo": valor}
            for campo, valor in campos.items() if original.get(campo) != valor
        }
        registro = deepcopy(original)
        if mudancas:
            registro.update({campo: mudanca["novo"] for campo, mudanca in mudancas.items()})
            registro["revisao_registro"] = revisao + 1
            registro["correcoes"] = [*deepcopy(correcoes), {
                "id": str(uuid4()), "registrada_em": _agora(), "campos": mudancas,
                "motivo": motivo.strip() or None if motivo is not None else None,
            }]
            historico[identificador] = registro
            _gravar(historico)
        return {
            "sessao_id": identificador,
            "campos_alterados": list(mudancas),
            "revisao_registro": registro.get("revisao_registro", 0),
            "registro": registro,
        }


def excluir_registros(identificador=None):
    """Exclui atomicamente a sessão inteira, ou todos os registros próprios."""
    with _LOCK_HISTORICO:
        historico = _ler_historico()
        if identificador is None:
            excluidos = list(historico)
            historico.clear()
        else:
            _obter(historico, identificador)
            excluidos = [identificador]
            del historico[identificador]
        if excluidos:
            _gravar(historico)
        return {
            "alcance": "todos_os_registros_do_titular" if identificador is None else "registro_especifico",
            "total_excluido": len(excluidos),
            "registros_excluidos": excluidos,
            "politica_retencao": deepcopy(POLITICA_RETENCAO),
        }
