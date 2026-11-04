"""Caracterização opcional, sem inferência de valores ou migração de registros."""

from copy import deepcopy
from math import isfinite


VERSAO_ESTRUTURA = 1
CAMPOS_LEGADOS = (
    "id", "nome", "artista", "duracao", "bpm", "energia", "valencia",
    "intensidade", "sentimentos_associados", "contextos", "estrategias",
    "tags", "percepcao_usuario",
)
_GRUPOS = {
    "caracteristicas_acusticas": {"bpm", "duracao"},
    "anotacoes_emocionais": {"valencia", "ativacao"},
    "estimativas_sistema": {"bpm", "valencia", "ativacao", "energia", "intensidade"},
}
_METADADOS = {"fonte", "metodo", "versao"}
_CAMPOS_OBSERVACAO = {"atributo", "valor", "unidade", "escala"} | _METADADOS


def _erro(caminho, mensagem):
    raise ValueError(f"{caminho}: {mensagem}")


def _objeto(valor, caminho):
    if not isinstance(valor, dict):
        _erro(caminho, "deve ser um objeto.")


def _chaves(valor, permitidas, caminho):
    extras = set(valor) - permitidas
    if extras:
        nomes = ", ".join(sorted(str(chave) for chave in extras))
        _erro(caminho, f"campos não reconhecidos: {nomes}.")


def _texto_opcional(valor, caminho):
    if valor is not None and (not isinstance(valor, str) or not valor.strip()):
        _erro(caminho, "deve ser texto não vazio ou null.")


def _numero(valor):
    return type(valor) is int or (type(valor) is float and isfinite(valor))


def _validar_metadados(dados, caminho):
    _objeto(dados, caminho)
    _chaves(dados, _METADADOS, caminho)
    for campo, valor in dados.items():
        _texto_opcional(valor, f"{caminho}.{campo}")


def _validar_escala(escala, valor, caminho):
    _objeto(escala, caminho)
    if "categorias" in escala:
        _chaves(escala, {"categorias", "descricao"}, caminho)
        categorias = escala["categorias"]
        if not isinstance(categorias, list) or not categorias:
            _erro(caminho, "categorias deve ser uma lista não vazia.")
        for categoria in categorias:
            if not isinstance(categoria, str) or not categoria.strip():
                _erro(caminho, "cada categoria deve ser texto não vazio.")
        if len(set(categorias)) != len(categorias):
            _erro(caminho, "categorias não podem se repetir.")
        if valor is not None and (not isinstance(valor, str) or valor not in categorias):
            _erro(caminho, "o valor deve pertencer às categorias declaradas.")
    else:
        _chaves(escala, {"minimo", "maximo", "descricao"}, caminho)
        minimo, maximo = escala.get("minimo"), escala.get("maximo")
        if not _numero(minimo) or not _numero(maximo) or minimo >= maximo:
            _erro(caminho, "minimo e maximo devem ser finitos, com minimo < maximo.")
        if valor is not None and (not _numero(valor) or not minimo <= valor <= maximo):
            _erro(caminho, "o valor deve ser numérico, finito e estar na escala declarada.")
    _texto_opcional(escala.get("descricao"), f"{caminho}.descricao")


def _validar_observacao(observacao, grupo, caminho):
    _objeto(observacao, caminho)
    _chaves(observacao, _CAMPOS_OBSERVACAO, caminho)
    atributo = observacao.get("atributo")
    if not isinstance(atributo, str) or atributo not in _GRUPOS[grupo]:
        _erro(caminho, f"atributo não permitido em {grupo}.")
    for campo in _METADADOS:
        _texto_opcional(observacao.get(campo), f"{caminho}.{campo}")

    valor = observacao.get("valor")
    unidade = observacao.get("unidade")
    escala = observacao.get("escala")
    if unidade is not None and escala is not None:
        _erro(caminho, "declare unidade ou escala, sem combinar as duas.")

    if atributo in {"bpm", "duracao"}:
        esperada = "bpm" if atributo == "bpm" else "s"
        if escala is not None:
            _erro(caminho, f"{atributo} deve usar unidade '{esperada}', sem escala.")
        if unidade is not None and unidade != esperada:
            _erro(caminho, f"a unidade de {atributo} deve ser '{esperada}'.")
        if valor is not None:
            if unidade != esperada:
                _erro(caminho, f"valor conhecido de {atributo} exige unidade '{esperada}'.")
            if not _numero(valor) or valor <= 0:
                _erro(caminho, f"{atributo} deve ser numérico, finito e maior que zero.")
    else:
        if unidade is not None:
            _erro(caminho, f"{atributo} deve usar uma escala, sem unidade.")
        if valor is not None and escala is None:
            _erro(caminho, f"valor conhecido de {atributo} exige escala explícita.")
        if escala is not None:
            _validar_escala(escala, valor, f"{caminho}.escala")


def validar_caracterizacao(bloco):
    """Valida somente o esquema opcional, sem preencher ou alterar o argumento."""
    _objeto(bloco, "caracterizacao")
    _chaves(bloco, {"versao_estrutura", "procedencia_legado"} | set(_GRUPOS), "caracterizacao")
    if type(bloco.get("versao_estrutura")) is not int or bloco["versao_estrutura"] != VERSAO_ESTRUTURA:
        _erro("caracterizacao.versao_estrutura", "versão não suportada; informe o inteiro 1.")

    for grupo in _GRUPOS:
        observacoes = bloco.get(grupo, [])
        if not isinstance(observacoes, list):
            _erro(f"caracterizacao.{grupo}", "deve ser uma lista.")
        for indice, observacao in enumerate(observacoes):
            _validar_observacao(observacao, grupo, f"caracterizacao.{grupo}[{indice}]")

    procedencia = bloco.get("procedencia_legado", {})
    _objeto(procedencia, "caracterizacao.procedencia_legado")
    _chaves(procedencia, set(CAMPOS_LEGADOS), "caracterizacao.procedencia_legado")
    for campo, metadados in procedencia.items():
        _validar_metadados(metadados, f"caracterizacao.procedencia_legado.{campo}")


def validar_musica(musica):
    """Aceita legado sem caracterização; não valida nem reinterpreta campos antigos."""
    _objeto(musica, "musica")
    bloco = musica.get("caracterizacao")
    if bloco is not None:
        validar_caracterizacao(bloco)


def _com_metadados(dados):
    resultado = deepcopy(dados)
    resultado["fonte"] = resultado.get("fonte") or "desconhecida"
    resultado.setdefault("metodo", None)
    resultado.setdefault("versao", None)
    return resultado


def obter_caracterizacao(musica):
    """Retorna uma visão independente, com pendências e procedência explícitas."""
    validar_musica(musica)
    resultado = deepcopy(musica.get("caracterizacao") or {})
    resultado.setdefault("versao_estrutura", VERSAO_ESTRUTURA)
    for grupo in _GRUPOS:
        resultado.setdefault(grupo, [])
        resultado[grupo] = [_com_metadados(item) for item in resultado[grupo]]
        for observacao in resultado[grupo]:
            observacao.setdefault("valor", None)
    procedencia = resultado.setdefault("procedencia_legado", {})
    for campo in CAMPOS_LEGADOS:
        if campo in musica:
            procedencia.setdefault(campo, {})
    resultado["procedencia_legado"] = {
        campo: _com_metadados(metadados) for campo, metadados in procedencia.items()
    }
    return resultado


def preparar_musica(musica):
    """Copia o registro e anexa a visão validada, preservando todos os campos antigos."""
    resultado = deepcopy(musica)
    resultado["caracterizacao"] = obter_caracterizacao(musica)
    return resultado
