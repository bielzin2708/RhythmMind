"""Adaptação lexical substituível, sem rede, modelos externos ou inferência geral.

O recorte de intenção reconhece apenas marcadores explícitos e fronteiras locais.
Não resolve discurso indireto, metáforas, correferência ou temporalidade geral;
os sinais locais desses limites geram pedidos de revisão, nunca diagnósticos.
"""

import re
from typing import Literal, Protocol

from core.analisador_texto import detectar_emocoes_com_dicionario, extrair_palavras
from core.interpretacao.base import BaseConhecimento
from core.interpretacao.contratos import ParteInterpretacao, PropostaInterpretacao, SugestaoCategoria


class Interpretador(Protocol):
    origem: Literal["dicionario", "llm", "mock"]
    identificador: str

    def interpretar(
        self, texto_original: str, texto_desejado: str | None, base: BaseConhecimento,
    ) -> PropostaInterpretacao: ...


_INTENCAO = re.compile(
    r"\b(?:(?:eu\s+)?(?:não|nao|nem|nunca|jamais)\s+)?"
    r"(?:quero|gostaria(?:\s+de)?|pretendo|busco|desejo|almejo|meu\s+objetivo\s+[eé])\b",
    re.IGNORECASE,
)
_FRONTEIRA = re.compile(
    r"[,;:.!?\n\r…–—]+|\b(?:mas|por[eé]m|contudo|todavia|entretanto)\b",
    re.IGNORECASE,
)
_ESTADO_EXPLICITO = re.compile(
    r"\b(?:(?:e|agora|hoje|atualmente)\s+)?(?:eu\s+)?"
    r"(?:(?:não|nao|nem|nunca|jamais)\s+)?(?:estou|me\s+sinto|sinto-me|ando)\b",
    re.IGNORECASE,
)
_TEMPORAL = re.compile(
    r"\b(?:ontem|antigamente|estava|estive|era|fui|amanha|amanhã|estarei|serei)\b",
    re.IGNORECASE,
)
_OUTRA_PESSOA = re.compile(
    r"\b(?:ele|ela|eles|elas|voc[eê]|voc[eê]s|"
    r"(?:meu|minha)\s+(?:amig[oa]|pai|m[aã]e|irm[aã]o?|namorad[oa]|professor[a]?))\b",
    re.IGNORECASE,
)


def _recortar_intencoes(texto):
    """Retorna intervalos literais de intenção sem consumir um novo estado explícito."""
    intervalos = []
    inicio = 0
    fronteiras = list(_FRONTEIRA.finditer(texto))
    segmentos = [(fronteira.start(), fronteira.end()) for fronteira in fronteiras]
    segmentos.append((len(texto), len(texto)))
    for fim, proximo_inicio in segmentos:
        marcadores = list(_INTENCAO.finditer(texto, inicio, fim))
        for indice, marcador in enumerate(marcadores):
            final = marcadores[indice + 1].start() if indice + 1 < len(marcadores) else fim
            novo_estado = _ESTADO_EXPLICITO.search(texto, marcador.end(), final)
            if novo_estado:
                final = novo_estado.start()
            while final > marcador.start() and texto[final - 1].isspace():
                final -= 1
            if final > marcador.start():
                intervalos.append((marcador.start(), final))
        inicio = proximo_inicio
    return intervalos


def _separar_papeis(texto):
    intervalos = _recortar_intencoes(texto)
    atual = []
    inicio = 0
    for primeiro, ultimo in intervalos:
        atual.append(texto[inicio:primeiro])
        inicio = ultimo
    atual.append(texto[inicio:])
    # A quebra de linha evita transportar negação de uma oração para outra.
    intencoes = [texto[primeiro:ultimo] for primeiro, ultimo in intervalos]
    trecho_literal = texto[intervalos[0][0]:intervalos[-1][1]] if intervalos else None
    return "\n".join(atual), intencoes, trecho_literal


def _ambiguidades_locais(texto, categorias, dicionario):
    mensagens = []
    if _TEMPORAL.search(texto):
        mensagens.append("Há uma referência temporal; confirme a quais momentos as categorias se referem.")
    if _OUTRA_PESSOA.search(texto):
        mensagens.append("Há referência a outra pessoa; confirme de quem é o estado descrito.")
    if categorias:
        unidades = {}
        for categoria, sinonimos in dicionario.items():
            for sinonimo in sinonimos:
                chave = tuple(extrair_palavras(sinonimo))
                if chave:
                    unidade = unidades.setdefault(chave, {"texto": sinonimo, "categorias": set()})
                    unidade["categorias"].add(categoria)
        # Preserva todas as expressões para aplicar a mesma precedência/negação.
        indices = {str(indice): unidade for indice, unidade in enumerate(unidades.values())}
        ativas = detectar_emocoes_com_dicionario(
            texto, {indice: [unidade["texto"]] for indice, unidade in indices.items()},
        )
        if any(len(indices[indice]["categorias"]) > 1 for indice in ativas):
            mensagens.append("Um termo corresponde a mais de uma categoria do dicionário; revise as sugestões.")
    return mensagens


def _parte(texto, dicionario, papel, mensagens_extras=()):
    categorias = detectar_emocoes_com_dicionario(texto, dicionario)
    mensagens = list(dict.fromkeys([*_ambiguidades_locais(texto, categorias, dicionario), *mensagens_extras]))
    if mensagens:
        estado = "ambigua"
        resumo = f"A interpretação lexical do estado {papel} precisa de revisão."
    elif categorias:
        estado = "sugestoes"
        resumo = f"Categorias lexicais sugeridas para o estado {papel}; confirme antes de continuar."
    else:
        estado = "sem_correspondencia"
        resumo = f"Não foram encontradas categorias lexicais para o estado {papel}."
    return ParteInterpretacao(
        estado=estado,
        sugestoes=[SugestaoCategoria(categoria=categoria) for categoria in categorias],
        ambiguidades=mensagens,
        resumo=resumo,
    )


class InterpretadorLexical:
    origem = "dicionario"
    identificador = "lexical_contextual_v1"

    def interpretar(
        self, texto_original: str, texto_desejado: str | None, base: BaseConhecimento,
    ) -> PropostaInterpretacao:
        dicionario = base.dicionario
        atual, intencoes, trecho_literal = _separar_papeis(texto_original)
        desejo_no_relato = "\n".join(intencoes)
        desejo = texto_desejado if texto_desejado is not None else desejo_no_relato
        mensagens = []
        categorias_relato = detectar_emocoes_com_dicionario(desejo_no_relato, dicionario)
        if texto_desejado is not None and intencoes:
            categorias_separadas = detectar_emocoes_com_dicionario(texto_desejado, dicionario)
            if set(categorias_separadas) != set(categorias_relato):
                mensagens.append("O estado desejado informado separadamente difere da intenção no relato; confirme sua escolha.")
        if len(intencoes) > 1:
            mensagens.append("O relato contém vários trechos de intenção; revise o estado desejado e o trecho destacado.")
        if intencoes and _OUTRA_PESSOA.search(texto_original):
            mensagens.append("Há referência a outra pessoa; confirme de quem é o estado descrito.")
        return PropostaInterpretacao(
            estado_atual=_parte(atual, dicionario, "atual"),
            estado_desejado=_parte(desejo, dicionario, "desejado", mensagens),
            texto_intencao=trecho_literal,
        )
