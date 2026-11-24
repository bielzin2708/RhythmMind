from core.storage import carregar_musicas_usuario, ARQ_HISTORICO, carregar_json

def definir_estrategia(emocoes_atuais, estado_desejado):
    """
    Define a estratégia musical com base no estado atual e no estado desejado,
    retornando o nome técnico e uma explicação amigável para o utilizador.
    """
    emocoes = set(emocoes_atuais)
    desejos = set(estado_desejado)
    
    baixa_energia = {"triste", "sofrendo", "cansado", "ansioso"}
    alta_energia = {"animado", "disposto", "feliz", "explosivo", "raiva"}
    
    # === 1. ATIVAÇÃO GRADUAL (regra específica antes da ponte genérica) ===
    # Cansaço com desejo de disposição tem uma regra própria; antes ela ficava
    # inalcançável porque a transição emocional também cobre esse par.
    if "cansado" in emocoes and ("disposto" in desejos or "animado" in desejos):
        return "ativacao_gradual", "Vou usar uma estratégia de ativação gradual: músicas que ajudam a sair da inércia sem começar com uma intensidade extrema."

    # === 2. TRANSIÇÃO EMOCIONAL (PONTE) ===
    # Se há um salto brusco de uma emoção densa para um desejo de alta energia
    elif emocoes.intersection(baixa_energia) and desejos.intersection(alta_energia):
        return "transicao_emocional", "Há uma distância grande entre o que você sente agora e o que deseja alcançar. Vou usar uma estratégia de transição: em vez de uma mudança brusca, procuro músicas que sirvam de ponte, aos poucos."
    
    # === 3. LÓGICAS PADRÃO ===
    elif "foco" in desejos or "foco" in emocoes:
        return "foco_cognitivo", "Vou sugerir músicas que ajudam a manter a concentração, sem distrações excessivas."
        
    elif "raiva" in emocoes or "explosivo" in emocoes:
        return "catarse", "Vou usar uma estratégia de catarse: músicas mais intensas para ajudar a extravasar o que você está sentindo agora."
        
    elif "calmo" in desejos or "relaxar" in desejos:
        return "descompressao", "Vou seguir uma estratégia de descompressão: músicas mais tranquilas para ajudar a baixar o ritmo e relaxar."
        
    elif "animado" in desejos or "disposto" in desejos:
        return "ativacao", "Vou procurar uma ativação: músicas com um ritmo mais para cima para dar aquele empurrãozinho."
        
    elif not emocoes:
        if desejos:
            explicacao = "As regras atuais não definem uma estratégia para o estado desejado informado sem uma categoria para o estado atual."
        else:
            explicacao = "Sem categoria para o estado atual e sem um estado desejado reconhecido, não há critério para sugerir músicas."
        return None, explicacao

    else:
        return "espelhamento", "Vou seguir uma estratégia de espelhamento: músicas que combinam com o que você está sentindo neste momento e acolhem isso."


def validar_limite_recomendacoes(limite):
    """Aceita somente inteiros entre um e dez, sem coerção de booleanos/textos."""
    if type(limite) is not int or not 1 <= limite <= 10:
        raise ValueError("O limite de recomendações deve ser um inteiro de 1 a 10.")
    return limite


def _pontuar_musica(musica, emocoes_atuais, estrategia, ajuste_aprendizagem):
    """Produz a pontuação e seus critérios a partir dos mesmos campos do cadastro."""
    criterios = []
    estrategias_musica = musica.get("estrategias", [])
    sentimentos_musica = musica.get("sentimentos_associados", [])

    if estrategia in estrategias_musica:
        criterios.append({"tipo": "estrategia", "valor": estrategia, "pontos": 3})
    for emocao in emocoes_atuais:
        if emocao in sentimentos_musica:
            criterios.append({"tipo": "emocao_confirmada", "valor": emocao, "pontos": 2})

    if estrategia == "transicao_emocional":
        # A ordem fixa só organiza a explicação; os pesos existentes são preservados.
        for emocao in ("calmo", "reflexivo", "foco", "normal"):
            if emocao in sentimentos_musica:
                criterios.append({"tipo": "categoria_ponte", "valor": emocao, "pontos": 2})
        if "ativacao_gradual" in estrategias_musica:
            criterios.append({
                "tipo": "estrategia_ponte", "valor": "ativacao_gradual", "pontos": 2,
            })

    chave_busca = f"{musica.get('nome')} - {musica.get('artista')}"
    ajuste = ajuste_aprendizagem.get(chave_busca, 0)
    if ajuste != 0:
        criterios.append({"tipo": "ajuste_informado", "pontos": ajuste})
    return sum(criterio["pontos"] for criterio in criterios), criterios


def _explicar_criterios(criterios):
    nomes_estrategias = {
        "transicao_emocional": "transição emocional", "foco_cognitivo": "foco",
        "catarse": "catarse", "ativacao_gradual": "ativação gradual",
        "descompressao": "descompressão", "ativacao": "ativação",
        "espelhamento": "acompanhamento do estado atual",
    }
    frases = []
    for criterio in criterios:
        tipo = criterio["tipo"]
        valor = criterio.get("valor")
        if tipo == "estrategia":
            nome = nomes_estrategias.get(valor, valor)
            frases.append(f"A faixa está cadastrada para a estratégia de {nome}.")
        elif tipo == "emocao_confirmada":
            frases.append(f"O cadastro associa a faixa à categoria '{valor}', confirmada por você.")
        elif tipo == "categoria_ponte":
            frases.append(f"A categoria '{valor}' consta no cadastro e é usada pela regra de transição.")
        elif tipo == "estrategia_ponte":
            frases.append("O cadastro inclui ativação gradual, usada pela regra de transição.")
        elif tipo == "ajuste_informado":
            frases.append("Um ajuste de pontuação informado foi considerado na ordenação.")
    return " ".join(frases) or "Não há critérios registrados suficientes para explicar esta sugestão."


def explicar_recomendacoes(emocoes_atuais, estrategia, recomendacoes, ajuste_aprendizagem=None):
    """Explica só as faixas recebidas, na ordem dada, sem reler ou alterar o catálogo.

    A chamada pertence à geração das sugestões. Registros antigos não recebem
    explicações retroativas ao serem consultados ou retomados.
    """
    if ajuste_aprendizagem is None:
        ajuste_aprendizagem = {}
    explicacoes = []
    for indice, musica in enumerate(recomendacoes, 1):
        pontuacao, criterios = _pontuar_musica(
            musica, emocoes_atuais, estrategia, ajuste_aprendizagem,
        )
        explicacoes.append({
            "indice_recomendacao": indice,
            "pontuacao": pontuacao,
            "criterios": criterios,
            "explicacao": _explicar_criterios(criterios),
        })
    return explicacoes


def musica_elegivel(musica):
    """Metadados públicos ou associações retiradas não entram no ranking sozinhos."""
    curadoria = musica.get("curadoria") or {}
    return not (isinstance(curadoria, dict)
                and curadoria.get("status") in {"pendente", "informada_pelo_usuario"}
                and not musica.get("sentimentos_associados") and not musica.get("estrategias"))


def recomendar_musicas(emocoes_atuais, estado_desejado=None, ajuste_aprendizagem=None, *, limite=3,
                       musicas=None):
    """
    Recomenda músicas com base no estado emocional atual e no estado desejado.
    Retorna (nome_estrategia, explicacao, lista_de_musicas[:limite]), com padrão 3.
    Sem categoria atual nem estratégia aplicável ao desejo, retorna (None, explicacao, []).
    `musicas` permite ordenar outra lista (por exemplo, a seleção inicial) sem
    gravar nada no catálogo da conta; ausente, usa o catálogo pessoal.
    """
    limite = validar_limite_recomendacoes(limite)
    if estado_desejado is None:
        estado_desejado = []
    if ajuste_aprendizagem is None:
        ajuste_aprendizagem = {}

    # Definir a estratégia
    nome_estrategia, explicacao = definir_estrategia(emocoes_atuais, estado_desejado)
    if nome_estrategia is None:
        return None, explicacao, []
    if not emocoes_atuais:
        explicacao = (
            "As sugestões usam apenas o estado desejado informado; "
            "nenhuma categoria foi atribuída ao estado atual. " + explicacao
        )

    todas_musicas = carregar_musicas_usuario() if musicas is None else musicas
    
    recomendadas = []
    
    # Avaliar cada música
    for musica in todas_musicas:
        # Metadados públicos e associações retiradas precisam de uma associação
        # pessoal antes de voltar ao ranking, inclusive quando existe feedback.
        if not musica_elegivel(musica):
            continue
        score, _criterios = _pontuar_musica(
            musica, emocoes_atuais, nome_estrategia, ajuste_aprendizagem,
        )
                
        # Se a música pontuou positivamente, entra para a lista
        if score > 0:
            recomendadas.append((score, musica))
            
    # Ordenar da maior pontuação para a menor
    recomendadas.sort(key=lambda x: x[0], reverse=True)
    
    # Extrair apenas as músicas
    lista_final = [musica for score, musica in recomendadas]
    
    return nome_estrategia, explicacao, lista_final[:limite]
