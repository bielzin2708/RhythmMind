"""Adaptação lexical substituível, sem rede, modelos externos ou inferência geral.

O recorte de intenção reconhece apenas marcadores explícitos e fronteiras locais.
Não resolve discurso indireto, metáforas, correferência ou temporalidade geral;
os sinais locais desses limites geram pedidos de revisão, nunca diagnósticos.
"""

import re
from typing import Literal, Protocol

from core.analisador_texto import detectar_emocoes_com_dicionario, extrair_palavras, separar_papeis_texto
from core.interpretacao.base import BaseConhecimento
from core.interpretacao.contratos import ParteInterpretacao, PropostaInterpretacao, SugestaoCategoria


class Interpretador(Protocol):
    origem: Literal["dicionario", "llm", "mock"]
    identificador: str

    def interpretar(
        self, texto_original: str, texto_desejado: str | None, base: BaseConhecimento,
    ) -> PropostaInterpretacao: ...


_TEMPORAL = re.compile(
    r"\b(?:ontem|antigamente|estava|estive|era|fui|amanha|amanhã|estarei|serei)\b",
    re.IGNORECASE,
)
_OUTRA_PESSOA = re.compile(
    r"\b(?:ele|ela|eles|elas|voc[eê]|voc[eê]s|"
    r"(?:meu|minha)\s+(?:amig[oa]|pai|m[aã]e|irm[aã]o?|namorad[oa]|professor[a]?))\b",
    re.IGNORECASE,
)


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
    identificador = "lexical_contextual_v3"

    def interpretar(
        self, texto_original: str, texto_desejado: str | None, base: BaseConhecimento,
    ) -> PropostaInterpretacao:
        dicionario = base.dicionario
        atual, intencoes, trecho_literal = separar_papeis_texto(texto_original)
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
        parte_atual = _parte(atual, dicionario, "atual")
        parte_desejada = _parte(desejo, dicionario, "desejado", mensagens)
        precisa_esclarecimento = (
            parte_atual.estado in {"ambigua", "sem_correspondencia"}
            or parte_desejada.estado == "ambigua"
        )
        referencias = ["RM01", "RM05", "RM06", "RM07", "RM08"]
        if len(parte_atual.sugestoes) > 1 or len(parte_desejada.sugestoes) > 1:
            referencias.insert(1, "RM02")
        return PropostaInterpretacao(
            estado_atual=parte_atual,
            estado_desejado=parte_desejada,
            texto_intencao=trecho_literal,
            resumo_reflexivo=(
                "Esta leitura lexical é provisória. Confirme o que representa seu momento "
                "e sua intenção; você também pode continuar sem categoria."
            ),
            precisa_esclarecimento=precisa_esclarecimento,
            referencias_base=referencias,
        )
