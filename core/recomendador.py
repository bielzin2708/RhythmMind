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
    
    # === 1. NOVA LÓGICA: TRANSIÇÃO EMOCIONAL (PONTE) ===
    # Se há um salto brusco de uma emoção densa para um desejo de alta energia
    if emocoes.intersection(baixa_energia) and desejos.intersection(alta_energia):
        return "transicao_emocional", "Notei um grande salto entre o que sentes agora e o que desejas alcançar. Vou usar uma estratégia de transição emocional: em vez de um choque abrupto, procurarei músicas que sirvam de ponte para te guiar suavemente."
    
    # === 2. LÓGICAS PADRÃO ===
    elif "foco" in desejos or "foco" in emocoes:
        return "foco_cognitivo", "Vou sugerir músicas que ajudam a manter a concentração e o foco cognitivo, sem distrações excessivas."
        
    elif "raiva" in emocoes or "explosivo" in emocoes:
        return "catarse", "Vou usar uma estratégia de catarse: músicas mais intensas para ajudar a extravasar o que estás a sentir agora."
        
    elif "cansado" in emocoes and ("disposto" in desejos or "animado" in desejos):
        return "ativacao_gradual", "Vou usar uma estratégia de ativação gradual: músicas que tentam tirar-te da inércia sem jogar uma intensidade extrema logo de início."
        
    elif "calmo" in desejos or "relaxar" in desejos:
        return "descompressao", "Vou focar numa estratégia de descompressão: músicas mais tranquilas para ajudar a baixar o ritmo e relaxar."
        
    elif "animado" in desejos or "disposto" in desejos:
        return "ativacao", "Vou procurar uma ativação energética: músicas com um ritmo mais para cima para te dar aquele empurrãozinho."
        
    else:
        return "espelhamento", "Vou seguir uma estratégia de espelhamento: músicas que combinam e acolhem o que estás a sentir neste momento."


def recomendar_musicas(emocoes_atuais, estado_desejado=None, ajuste_aprendizagem=None):
    """
    Recomenda músicas com base no estado emocional atual e no estado desejado.
    Retorna (nome_estrategia, explicacao, lista_de_musicas[:3]).
    """
    if estado_desejado is None:
        estado_desejado = []
    if ajuste_aprendizagem is None:
        ajuste_aprendizagem = {}

    todas_musicas = carregar_musicas_usuario()

    # Definir a estratégia
    nome_estrategia, explicacao = definir_estrategia(emocoes_atuais, estado_desejado)
    
    recomendadas = []
    
    # Avaliar cada música
    for musica in todas_musicas:
        score = 0
        estrategias_musica = musica.get("estrategias", [])
        sentimentos_musica = musica.get("sentimentos_associados", [])
        
        # Lógica de Pontuação Base
        if nome_estrategia in estrategias_musica:
            score += 3
            
        for emocao in emocoes_atuais:
            if emocao in sentimentos_musica:
                score += 2
                
        # === A MÁGICA DA TRANSIÇÃO EMOCIONAL (PONTE) ===
        # Se o sistema escolheu fazer a ponte, bonificamos as músicas intermediárias
        if nome_estrategia == "transicao_emocional":
            emocoes_ponte = {"calmo", "reflexivo", "foco", "normal"}
            for emocao in emocoes_ponte:
                if emocao in sentimentos_musica:
                    score += 2
            # Músicas de ativação gradual são excelentes pontes
            if "ativacao_gradual" in estrategias_musica:
                score += 2
                
        # Aplica a Aprendizagem
        chave_busca = f"{musica.get('nome')} - {musica.get('artista')}"
        if chave_busca in ajuste_aprendizagem:
            score += ajuste_aprendizagem[chave_busca]
                
        # Se a música pontuou positivamente, entra para a lista
        if score > 0:
            recomendadas.append((score, musica))
            
    # Ordenar da maior pontuação para a menor
    recomendadas.sort(key=lambda x: x[0], reverse=True)
    
    # Extrair apenas as músicas
    lista_final = [musica for score, musica in recomendadas]
    
    return nome_estrategia, explicacao, lista_final[:3]