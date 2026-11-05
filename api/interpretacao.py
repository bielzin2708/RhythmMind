"""API de interpretação e revisão, com contratos para uma futura interface web."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from api.autenticacao import usuario_autenticado
from core.interpretacao.llm import criar_interpretador_llm_do_ambiente
from core.interpretacao.servico import (
    ErroInterpretacao, InterpretacaoRegistrada, MotoresInterpretacao,
    PedidoInterpretacao, PedidoRevisao, ResultadoRevisao,
    interpretar_sessao, obter_interpretacao, revisar_interpretacao,
)


router = APIRouter(tags=["interpretação"], dependencies=[Depends(usuario_autenticado)])


def obter_motores():
    """Configuração só do servidor; motor externo exige escolha explícita no pedido."""
    return MotoresInterpretacao(llm=criar_interpretador_llm_do_ambiente())


def _executar(funcao, *args):
    try:
        return funcao(*args)
    except ErroInterpretacao as erro:
        raise HTTPException(status_code=erro.status, detail=str(erro)) from erro


@router.post("/api/interpretacoes", response_model=InterpretacaoRegistrada)
def interpretar(pedido: PedidoInterpretacao, motores: MotoresInterpretacao = Depends(obter_motores)):
    """Salva sugestões separadas da confirmação, com motor e base identificados.

    A sessão deve estar pendente. Repetir o pedido reutiliza o rascunho;
    regenerar=true cria outro. Fallback lexical exige permissão explícita.
    """
    return _executar(interpretar_sessao, pedido, motores)


@router.get("/api/interpretacoes/{sessao_id}", response_model=InterpretacaoRegistrada)
def consultar_interpretacao(sessao_id: UUID):
    """Lê o rascunho salvo, sem executar modelo ou gerar recomendações."""
    return _executar(obter_interpretacao, sessao_id)


@router.post("/api/revisoes-interpretacao", response_model=ResultadoRevisao)
def revisar(pedido: PedidoRevisao):
    """Confirma estado e desejo explicitamente; [] representa escolha sem categoria.

    texto_desejado é obrigatório: use vazio para seguir sem definir desejo.
    Revisão, músicas e motivos são persistidos juntos. Mesmo pedido é idempotente.
    """
    return _executar(revisar_interpretacao, pedido)
