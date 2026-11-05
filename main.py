import os
import re
from datetime import datetime
from collections import Counter
from core.analisador_texto import detectar_emocoes_no_texto, remover_acentos, separar_papeis_texto
from core.recomendador import (
    recomendar_musicas, explicar_recomendacoes, validar_limite_recomendacoes,
)
from core.escuta import preparar_escuta
from core.historico import filtrar_historico
from core.sessoes import (
    criar_sessao, salvar_nova_sessao, atualizar_sessao, recomendacoes_registradas,
    validar_metadados_sessao,
)
from core.feedback import (
    classificar_feedback, resumir_avaliacoes, NAO_REGISTRADO, POSITIVO,
    LIMITACAO_POR_FAIXA, INTERPRETACAO_RETORNOS,
)
from core.storage import salvar_musica_usuario, carregar_todas_musicas, carregar_json, salvar_json, ARQ_HISTORICO

# ============================================================
# BLOCO A - VALIDAÇÕES PARA ADICIONAR MÚSICA
# ============================================================
def validar_duracao(duracao):
    if re.match(r"^\d{1,2}:[0-5]\d$", duracao):
        return True
    return False

def validar_bpm(bpm_texto):
    if not bpm_texto.strip():
        return None
    try:
        bpm = int(bpm_texto)
        if 40 <= bpm <= 220:
            return bpm
        return -1
    except ValueError:
        return -1

# ============================================================
# BLOCO B - INFERÊNCIAS AUTOMÁTICAS
# ============================================================
def inferir_contextos_para_musica(sentimentos, tags):
    contextos = []
    sent_set = set(sentimentos)
    tags_set = set(tags)

    if sent_set.intersection({"animado", "disposto", "explosivo", "raiva"}): contextos.append("treinar")
    if sent_set.intersection({"calmo", "normal", "reflexivo", "foco"}): contextos.extend(["relaxar", "estudar"])
    if sent_set.intersection({"triste", "sofrendo", "amor", "reflexivo"}): contextos.extend(["reflexao", "entender"])
    if tags_set.intersection({"rock", "rap", "trap", "pop"}): contextos.append("trabalhar")
    if tags_set.intersection({"bebedeira", "curticao", "curtição", "festa", "dançante", "dancante"}): contextos.append("social")

    if not contextos: contextos.append("entender")
    return list(dict.fromkeys(contextos))

def inferir_estrategias_para_musica(sentimentos, tags, bpm):
    estrategias = []
    sent_set = set(sentimentos)

    if sent_set.intersection({"triste", "sofrendo", "amor", "reflexivo"}): estrategias.append("espelhamento")
    if sent_set.intersection({"triste", "sofrendo", "ansioso", "cansado", "calmo", "reflexivo"}): estrategias.append("descompressao")
    if sent_set.intersection({"animado", "disposto", "feliz"}): estrategias.append("ativacao")
    if sent_set.intersection({"raiva", "explosivo"}): estrategias.append("catarse")
    if sent_set.intersection({"calmo", "normal", "reflexivo", "foco"}): estrategias.append("foco_cognitivo")
    if bpm is not None and 95 <= bpm <= 130: estrategias.append("ativacao_gradual")

    if not estrategias: estrategias.append("espelhamento")
    return list(dict.fromkeys(estrategias))

def inferir_energia_para_musica(sentimentos, tags, bpm):
    sent_set = set(sentimentos)
    tags_set = set(tags)

    if (sent_set.intersection({"animado", "disposto", "explosivo", "raiva"}) or
        tags_set.intersection({"energia", "dançante", "dancante", "festa", "curticao", "curtição"}) or
        (bpm is not None and bpm >= 135)):
        return "alta"
    if (sent_set.intersection({"calmo", "triste", "sofrendo"}) or
        tags_set.intersection({"leve", "suave", "acústico", "acustico"}) or
        (bpm is not None and bpm <= 85)):
        return "baixa"
    return "media"

def inferir_valencia_para_musica(sentimentos, tags):
    sent_set = set(sentimentos)
    tags_set = set(tags)

    if (sent_set.intersection({"triste", "sofrendo", "raiva", "explosivo", "ansioso"}) or
        tags_set.intersection({"dor", "saudade", "sombria", "triste", "desilusao", "desilusão"})):
        return "baixa"
    if (sent_set.intersection({"feliz", "amor", "animado", "disposto"}) or
        tags_set.intersection({"alegria", "feliz", "festa", "energia"})):
        return "alta"
    return "media"

def inferir_intensidade_para_musica(sentimentos, tags, bpm):
    sent_set = set(sentimentos)
    tags_set = set(tags)

    if (sent_set.intersection({"explosivo", "raiva"}) or
        tags_set.intersection({"intensa", "intenso", "pesada", "pesado", "rock", "trap", "energia"}) or
        (bpm is not None and bpm >= 145)):
        return "alta"
    if (sent_set.intersection({"calmo"}) or
        tags_set.intersection({"leve", "suave", "sensivel", "sensível", "acustico", "acústico"}) or
        (bpm is not None and bpm <= 85)):
        return "baixa"
    return "media"

def inferir_tags_a_partir_da_percepcao(texto_percepcao, sentimentos, bpm):
    """Gera tags automáticas a partir da percepção livre do usuário."""
    tags = []
    if not texto_percepcao:
        return tags

    texto = remover_acentos(texto_percepcao)

    mapa = {
        "treinar": ["treino", "treinar", "academia", "malhar", "correr", "esporte"],
        "leve":    ["leve", "levinha", "suave", "delicada", "delicado"],
        "pesada":  ["pesada", "pesado", "forte", "intensa", "intenso"],
        "festa":   ["festa", "balada", "dançar", "dancar", "curtir"],
        "pensativo": ["pensativo", "pensar", "refletir", "reflexao", "reflexivo"],
        "energia": ["energia", "agitado", "agitada", "empolgante"],
        "triste":  ["triste", "choro", "chorar", "saudade", "melancolia"],
        "foco":    ["foco", "concentrar", "estudar", "trabalhar"],
        "calmo":   ["calmo", "calma", "relaxar", "descansar", "tranquilo"],
    }

    palavras = texto.split()
    for tag, termos in mapa.items():
        for termo in termos:
            if termo in palavras or termo in texto:
                if tag not in tags:
                    tags.append(tag)
                break

    return tags

# ============================================================
# BLOCO C - LEITURA DE DADOS PARA ADICIONAR MÚSICA
# ============================================================
def ler_sensacoes_musica():
    """Pergunta que tipo de sensação a música transmite. Obrigatório."""
    print("\nQue tipo de sensação essa música transmite?")
    print("Exemplos: calma, tristeza, energia, foco, reflexão, raiva, alegria.")
    print("Você pode escrever uma ou mais sensações separadas por vírgula.")
    while True:
        texto = input("> ").strip()
        if not texto:
            print("⚠️ As sensações são obrigatórias. Por favor, descreva o que a música transmite.")
            continue
        sentimentos = detectar_emocoes_no_texto(texto)
        if not sentimentos:
            print("⚠️ Não consegui reconhecer essas sensações. Tenta palavras como: feliz, triste, animado, calmo, foco, raiva.")
            continue
        return sentimentos

def ler_percepcao_musica():
    """Pergunta uma descrição livre sobre a música. Opcional."""
    print("\nAgora descreva com suas palavras o que essa música provoca ou combina.")
    print("Exemplos: me dá vontade de treinar, parece leve, me deixa pensativo, tem uma energia forte, combina com festa.")
    print("Se não quiser descrever, pressione Enter.")
    texto = input("> ").strip()
    return texto

def exibir_resumo_nova_musica(nova_musica, tags_percepcao):
    """Mostra resumo humanizado da música antes de confirmar o salvamento."""
    print("\n=== Resumo da música ===")
    print(f"\nMúsica:  {nova_musica['nome']}")
    print(f"Artista: {nova_musica['artista']}")
    print(f"Duração: {nova_musica['duracao']}")
    bpm_exibir = str(nova_musica['bpm']) if nova_musica['bpm'] is not None else "Não informado"
    print(f"BPM:     {bpm_exibir}")

    print("\nSentimentos associados:")
    for s in nova_musica["sentimentos_associados"]:
        print(f"  - {s}")

    if nova_musica.get("percepcao_usuario"):
        print(f"\nPercepção informada:\n  \"{nova_musica['percepcao_usuario']}\"")

    if tags_percepcao:
        print("\nPercepções identificadas pelo sistema:")
        for t in tags_percepcao:
            print(f"  - {t}")

    print()

# ============================================================
# BLOCO D - FUNÇÃO PRINCIPAL PARA ADICIONAR MÚSICA (OPÇÃO 3)
# ============================================================
def adicionar_musica():
    print("\n--- Adicionar Nova Música ---")

    # 1. Nome
    while True:
        nome = input("\nNome da música (obrigatório): ").strip()
        if not nome:
            print("⚠️ O nome não pode estar vazio.")
        elif len(nome) > 80:
            print("⚠️ O nome deve ter no máximo 80 caracteres.")
        elif nome.isdigit():
            print("⚠️ O nome não pode conter apenas números.")
        else:
            break

    # 2. Artista
    while True:
        artista = input("Artista (obrigatório): ").strip()
        if not artista:
            print("⚠️ O artista não pode estar vazio.")
        elif len(artista) > 80:
            print("⚠️ O artista deve ter no máximo 80 caracteres.")
        else:
            break

    # 3. Duração
    while True:
        duracao = input("Duração (ex: 3:45): ").strip()
        if validar_duracao(duracao):
            break
        print("⚠️ Formato inválido. Use m:ss ou mm:ss. Os segundos devem ser entre 00 e 59.")

    # 4. BPM
    while True:
        bpm_texto = input("BPM (opcional, pressione Enter para pular): ").strip()
        bpm = validar_bpm(bpm_texto)
        if bpm == -1:
            print("⚠️ BPM inválido. Se preenchido, deve ser um número entre 40 e 220.")
        else:
            break

    # 5. Sensações (obrigatório)
    sentimentos = ler_sensacoes_musica()

    # 6. Percepção livre (opcional)
    percepcao = ler_percepcao_musica()

    # 7. Gerar campos automáticos
    tags_percepcao = inferir_tags_a_partir_da_percepcao(percepcao, sentimentos, bpm)
    tags_finais = list(dict.fromkeys(tags_percepcao))

    contextos = inferir_contextos_para_musica(sentimentos, tags_finais)
    estrategias = inferir_estrategias_para_musica(sentimentos, tags_finais, bpm)
    energia = inferir_energia_para_musica(sentimentos, tags_finais, bpm)
    valencia = inferir_valencia_para_musica(sentimentos, tags_finais)
    intensidade = inferir_intensidade_para_musica(sentimentos, tags_finais, bpm)

    id_musica = f"{re.sub(r'[^a-z0-9]', '', nome.lower())}_{re.sub(r'[^a-z0-9]', '', artista.lower())}"

    nova_musica = {
        "id": id_musica,
        "nome": nome,
        "artista": artista,
        "bpm": bpm,
        "duracao": duracao,
        "energia": energia,
        "valencia": valencia,
        "intensidade": intensidade,
        "sentimentos_associados": sentimentos,
        "contextos": contextos,
        "estrategias": estrategias,
        "tags": tags_finais,
        "percepcao_usuario": percepcao
    }

    # 8. Mostrar resumo
    exibir_resumo_nova_musica(nova_musica, tags_percepcao)

    # 9. Verificar duplicidade (só aqui, depois do resumo)
    todas = carregar_todas_musicas()
    duplicada = any(
        remover_acentos(m.get("nome", "")) == remover_acentos(nome) and
        remover_acentos(m.get("artista", "")) == remover_acentos(artista)
        for m in todas
    )
    if duplicada:
        print("⚠️ Já existe uma música cadastrada com esse nome e artista.")

    # 10. Confirmar salvamento
    while True:
        confirmacao = input("Deseja salvar essa música?\nSim ou não?\n> ").strip().lower()
        if confirmacao in ['sim', 's']:
            salvar_musica_usuario(nova_musica)
            print(f"\n✅ Música '{nome}' de '{artista}' adicionada com sucesso!")
            break
        elif confirmacao in ['não', 'nao', 'n']:
            print("\n❌ Cadastro cancelado. A música não foi salva.")
            break
        else:
            print("Por favor, responda apenas 'sim' ou 'não'.")

# ============================================================
# BLOCO E - FUNÇÕES DE LISTAGEM (OPÇÃO 2)
# ============================================================
def exibir_lista_paginada(lista_musicas):
    if not lista_musicas:
        print("\n⚠️ Nenhuma música encontrada com estes critérios.")
        return

    total = len(lista_musicas)
    itens_por_pagina = 10
    total_paginas = (total + itens_por_pagina - 1) // itens_por_pagina
    pagina_atual = 1

    while True:
        inicio = (pagina_atual - 1) * itens_por_pagina
        fim = min(inicio + itens_por_pagina, total)

        print(f"\n--- Mostrando {inicio + 1}-{fim} de {total} músicas ---")
        print(f"--- Página {pagina_atual} de {total_paginas} ---")

        for m in lista_musicas[inicio:fim]:
            sentimentos = ", ".join(m.get("sentimentos_associados", []))
            print(f"- {m['nome']} | Artista: {m['artista']} | Duração: {m.get('duracao', 'N/D')}")
            print(f"  Sentimentos: {sentimentos}\n")

        print("Opções:")
        if pagina_atual < total_paginas: print("N - Próxima página")
        if pagina_atual > 1: print("A - Página anterior")
        print("S - Sair da listagem")

        escolha = input("> ").strip().lower()
        if escolha == 'n' and pagina_atual < total_paginas:
            pagina_atual += 1
        elif escolha == 'a' and pagina_atual > 1:
            pagina_atual -= 1
        elif escolha == 's':
            break
        else:
            print("⚠️ Opção inválida.")

def opcao_ver_musicas():
    while True:
        print("\n=== Buscar músicas cadastradas ===")
        print("1 - Filtrar por sentimento")
        print("2 - Buscar por nome/artista")
        print("3 - Ver todas com paginação")
        print("4 - Voltar")

        opcao = input("Escolha uma opção (1-4):\n> ").strip()
        if opcao == '4':
            break

        todas_musicas = carregar_todas_musicas()

        if opcao == '1':
            termo = input("\nDigite o sentimento para filtrar (ex: felicidade, calma, animado) ou 'todos':\n> ").strip().lower()
            if termo == 'todos':
                confirma = input("\nVocê escolheu ver a base completa sem filtro. Deseja continuar?\nSim ou não?\n> ").strip().lower()
                if confirma in ['sim', 's']:
                    exibir_lista_paginada(todas_musicas)
            else:
                emocoes_buscadas = detectar_emocoes_no_texto(termo)
                if not emocoes_buscadas:
                    emocoes_buscadas = [termo]
                musicas_filtradas = [
                    m for m in todas_musicas
                    if any(e in m.get("sentimentos_associados", []) for e in emocoes_buscadas)
                ]
                exibir_lista_paginada(musicas_filtradas)

        elif opcao == '2':
            termo = input("\nDigite parte do nome da música ou do artista:\n> ").strip()
            termo_limpo = remover_acentos(termo)
            musicas_filtradas = [
                m for m in todas_musicas
                if termo_limpo in remover_acentos(m.get("nome", ""))
                or termo_limpo in remover_acentos(m.get("artista", ""))
            ]
            exibir_lista_paginada(musicas_filtradas)

        elif opcao == '3':
            confirma = input("\nDeseja listar todas as músicas cadastradas?\nSim ou não?\n> ").strip().lower()
            if confirma in ['sim', 's']:
                exibir_lista_paginada(todas_musicas)
        else:
            print("⚠️ Opção inválida.")

# ============================================================
# BLOCO F - HISTÓRICO E PADRÕES (OPÇÕES 4 E 6)
# ============================================================
def coletar_escuta(recomendacoes, ao_atualizar=None, anterior=None, editar=False):
    """Salva cada resposta; editar permite corrigir sem apagar respostas pendentes."""
    print("\n--- Escolha e escuta das faixas ---")
    if anterior is not None and not editar:
        escuta = preparar_escuta(recomendacoes, anterior["faixas"])
    else:
        conhecidas = {}
        if anterior is not None:
            validada = preparar_escuta(recomendacoes, anterior["faixas"])
            conhecidas = {
                faixa["indice_recomendacao"]: faixa["ouvida"]
                for faixa in validada["faixas"]
            }
        while True:
            resposta = input(
                "Quais sugestões você escolheu? Digite os números separados por vírgula (ex: 1,3).\n"
                "Digite 'nenhuma' se não escolheu nenhuma; Enter para informar depois.\n> "
            ).strip().lower()
            if not resposta:
                return None
            try:
                indices = [] if resposta == "nenhuma" else [
                    int(item.strip()) for item in resposta.split(",")
                ]
                escuta = preparar_escuta(recomendacoes, [
                    {"indice_recomendacao": indice, "ouvida": conhecidas.get(indice)}
                    for indice in indices
                ])
            except ValueError as erro:
                print(f"Escolha inválida: {erro}")
                continue
            break
        if ao_atualizar is not None:
            ao_atualizar(escuta)

    for faixa in escuta["faixas"]:
        if faixa["ouvida"] is not None and not editar:
            continue
        musica = recomendacoes[faixa["indice_recomendacao"] - 1]
        manter = "Enter para manter a resposta anterior" if faixa["ouvida"] is not None else "Enter para informar depois"
        while True:
            resposta = input(
                f"Você ouviu '{musica['nome']}' ({musica['artista']})?\n"
                f"Sim / não / {manter}.\n> "
            ).strip().lower()
            if not resposta:
                break
            if resposta in {"sim", "s", "não", "nao", "n"}:
                faixa["ouvida"] = resposta in {"sim", "s"}
                if ao_atualizar is not None:
                    ao_atualizar(escuta)
                break
            print("Responda 'sim', 'não' ou pressione Enter para manter a informação atual.")
    return escuta


def exibir_escuta_da_sessao(registro):
    escuta = registro.get("escuta")
    if escuta is None:
        print("Escolha e escuta ainda não informadas.")
        return
    try:
        if not isinstance(escuta, dict) or set(escuta) != {"faixas"}:
            raise ValueError("Estrutura de escuta inválida.")
        escuta = preparar_escuta(registro.get("recomendacoes", []), escuta["faixas"])
    except ValueError:
        print("Registro de escolha e escuta inválido; revise os dados desta sessão.")
        return
    if not escuta["faixas"]:
        print("Escolha registrada: nenhuma faixa.")
        return
    print("Faixas escolhidas (escuta informada pela pessoa):")
    for faixa in escuta["faixas"]:
        indice = faixa["indice_recomendacao"]
        musica = registro["recomendacoes"][indice - 1]
        ouvida = faixa["ouvida"]
        estado = "ainda não informada" if ouvida is None else ("sim" if ouvida else "não")
        print(f"- {indice}. {musica['nome']} ({musica['artista']}) | Escuta informada: {estado}")


def selecionar_sessao(historico):
    """Solicita a chave persistida; aceita também a identificação legada."""
    for chave, registro in historico.items():
        print(f"- {chave} | Data/hora: {registro.get('data_hora', 'não informada')}")
    chave = input("Digite o ID da sessão ou a chave legada, ou Enter para voltar:\n> ").strip()
    if not chave:
        return None
    if chave not in historico:
        print("Sessão não encontrada.")
        return None
    return chave


def exibir_recomendacoes_da_sessao(registro, *, incluir_faixas=True):
    """Exibe somente os motivos persistidos, sem reinterpretar sessões antigas."""
    recomendacoes = registro.get("recomendacoes", [])
    motivos = registro.get("motivos_recomendacoes")
    por_indice = {}
    if isinstance(motivos, list):
        for motivo in motivos:
            if not isinstance(motivo, dict):
                continue
            indice = motivo.get("indice_recomendacao")
            explicacao = motivo.get("explicacao")
            if type(indice) is int and isinstance(explicacao, str) and explicacao.strip():
                por_indice.setdefault(indice, explicacao)
    for indice, musica in enumerate(recomendacoes, 1):
        if incluir_faixas:
            print(f"{indice}. {musica['nome']} - {musica['artista']}")
        if indice in por_indice:
            print(f"   Motivo da sugestão {indice}: {por_indice[indice]}")
        elif isinstance(motivos, list):
            print(f"   Motivo da sugestão {indice}: não registrado.")
    if recomendacoes and motivos is None:
        print("Motivos por faixa não registrados nesta sessão.")


def opcao_registrar_escuta():
    historico = carregar_json(ARQ_HISTORICO, {})
    if not historico:
        print("Você ainda não tem sessões para registrar escolha e escuta.")
        return
    print("\n=== Registrar escolha e escuta de uma sessão ===")
    chave = selecionar_sessao(historico)
    if chave is None:
        return
    registro = historico[chave]
    recomendacoes = registro.get("recomendacoes", [])
    if not recomendacoes:
        print("Esta sessão não possui sugestões para escolher.")
        return
    exibir_recomendacoes_da_sessao(registro)
    exibir_escuta_da_sessao(registro)
    if registro.get("escuta") is not None:
        print("A nova seleção substituirá a lista anterior; Enter conserva a escuta já registrada.")
    try:
        escuta = coletar_escuta(
            recomendacoes,
            ao_atualizar=lambda valor: _gravar_etapa_cli(chave, escuta=valor),
            anterior=registro.get("escuta"), editar=True,
        )
    except (KeyboardInterrupt, EOFError):
        print("Fluxo interrompido; as etapas já salvas foram preservadas.")
        return
    except OSError:
        print("Falha ao salvar escolha ou escuta. A última versão salva foi preservada.")
        return
    if escuta is None:
        print("Nenhuma alteração de escolha ou escuta foi salva.")
        return
    print("Escolha e escuta da sessão salvas.")


def opcao_registrar_feedback():
    historico = carregar_json(ARQ_HISTORICO, {})
    if not historico:
        print("Você ainda não tem sessões para registrar feedback.")
        return
    print("\n=== Registrar feedback de uma sessão ===")
    chave = selecionar_sessao(historico)
    if chave is None:
        return
    try:
        coletar_feedback(
            ao_atualizar=lambda valor: _gravar_etapa_cli(chave, feedback=valor),
            anterior=historico[chave].get("feedback"), editar=True,
        )
    except (KeyboardInterrupt, EOFError):
        print("Fluxo interrompido; as etapas já salvas foram preservadas.")
        return
    except OSError:
        print("Falha ao salvar feedback. A última versão salva foi preservada.")
        return
    print("Feedback da sessão salvo.")


def coletar_metadados_sessao(identificador):
    """Salva cada informação opcional antes de pedir a próxima."""
    registro = carregar_json(ARQ_HISTORICO, {})[identificador]
    perguntas = (
        ("finalidade", "Para que você quer usar a música nesta sessão?", "não informada"),
        ("contexto", "Em que situação você está?", "não informado"),
    )
    for campo, pergunta, ausente in perguntas:
        while True:
            atual = registro.get(campo) or ausente
            resposta = input(
                f"\n{pergunta}\nValor atual: {atual}.\n"
                "Enter para manter ou continuar sem informar; '-' para apagar.\n> "
            )
            comando = resposta.strip()
            if not comando:
                break
            try:
                campos = validar_metadados_sessao(**{campo: None if comando == "-" else resposta})
            except ValueError as erro:
                print(str(erro))
                continue
            registro = _gravar_etapa_cli(identificador, **campos)
            break
    return registro


def opcao_registrar_contexto():
    historico = carregar_json(ARQ_HISTORICO, {})
    if not historico:
        print("Você ainda não tem sessões para registrar finalidade e contexto.")
        return
    print("\n=== Finalidade e contexto da sessão ===")
    try:
        identificador = selecionar_sessao(historico)
        if identificador is None:
            return
        coletar_metadados_sessao(identificador)
    except (KeyboardInterrupt, EOFError):
        print("Fluxo interrompido; as informações já salvas foram preservadas.")
        return
    except OSError:
        print("Falha ao salvar finalidade ou contexto. A última versão salva foi preservada.")
        return
    except KeyError:
        print("Sessão não encontrada.")
        return
    print("Finalidade e contexto da sessão registrados.")


def coletar_limite_recomendacoes(identificador):
    """Registra a quantidade antes de gerar a lista que ancora escolhas e escuta."""
    registro = carregar_json(ARQ_HISTORICO, {})[identificador]
    if recomendacoes_registradas(registro):
        print("As sugestões desta sessão já estão salvas; a quantidade não pode ser alterada.")
        return registro
    atual = registro.get("limite_recomendacoes", 3)
    while True:
        resposta = input(
            f"\nQuantas sugestões você quer receber (1 a 10)? Enter para manter {atual}.\n> "
        ).strip()
        if not resposta:
            limite = validar_limite_recomendacoes(atual)
        else:
            if re.fullmatch(r"[0-9]+", resposta) is None:
                print("Informe um número inteiro de 1 a 10.")
                continue
            try:
                limite = validar_limite_recomendacoes(int(resposta))
            except ValueError as erro:
                print(str(erro))
                continue
        if registro.get("limite_recomendacoes") != limite:
            registro = _gravar_etapa_cli(identificador, limite_recomendacoes=limite)
        return registro


def opcao_quantidade_sugestoes():
    historico = carregar_json(ARQ_HISTORICO, {})
    if not historico:
        print("Você ainda não tem sessões para configurar sugestões.")
        return
    print("\n=== Quantidade de sugestões da sessão ===")
    try:
        identificador = selecionar_sessao(historico)
        if identificador is None:
            return
        coletar_limite_recomendacoes(identificador)
    except (KeyboardInterrupt, EOFError):
        print("Fluxo interrompido; as informações já salvas foram preservadas.")
    except OSError:
        print("Falha ao salvar a quantidade. A última versão salva foi preservada.")
    except KeyError:
        print("Sessão não encontrada.")


def opcao_filtrar_historico():
    perguntas = (
        ("data_inicio", "Data inicial (AAAA-MM-DD)"),
        ("data_fim", "Data final (AAAA-MM-DD)"),
        ("finalidade", "Trecho da finalidade"),
        ("contexto", "Trecho do contexto"),
        ("avaliacao", "Retorno da sessão (positivo, negativo ou nao_registrado)"),
    )
    print("\n=== Filtrar histórico ===\nEnter deixa o campo sem filtro.")
    try:
        filtros = {campo: input(f"{pergunta}:\n> ").strip() or None for campo, pergunta in perguntas}
    except (KeyboardInterrupt, EOFError):
        print("Consulta interrompida.")
        return
    opcao_ver_historico(**filtros)


def opcao_ver_historico(sessao_id=None, **filtros):
    print("\n=== Histórico de Interações ===")
    historico = carregar_json(ARQ_HISTORICO, {})
    if sessao_id is not None:
        if sessao_id not in historico:
            print("Sessão não encontrada.")
            return
        historico = {sessao_id: historico[sessao_id]}

    tem_registros = bool(historico)
    try:
        historico = filtrar_historico(historico, **filtros)
    except ValueError as erro:
        print(f"Filtro inválido: {erro}")
        return
    if not historico:
        if tem_registros:
            print("Nenhuma sessão corresponde aos filtros informados.")
        else:
            print("⚠️ Você ainda não tem registros no histórico.")
        return

    for identificador, reg in historico.items():
        print(f"\n[Sessão: {identificador}]")
        print(f"Data/hora: {reg.get('data_hora', 'não informada')}")
        print(f"Estado relatado: '{reg.get('texto_usuario', '')}'")
        print(f"Finalidade: {reg.get('finalidade') or 'não informada'}")
        print(f"Contexto: {reg.get('contexto') or 'não informado'}")
        analise = reg.get('analise', {})
        emocoes = analise.get("emocoes", [])
        progresso = reg.get("progresso", {})
        if emocoes:
            descricao_emocoes = ', '.join(emocoes)
        elif progresso.get("emocoes_confirmadas"):
            descricao_emocoes = "sem categoria (escolha explícita)"
        else:
            descricao_emocoes = "pendentes" if progresso else "não informadas"
        print(f"Emoções confirmadas: {descricao_emocoes}")
        est_desejado = analise.get('estado_desejado', [])
        desejo = ', '.join(est_desejado) if est_desejado else "Não definido"
        if not progresso.get("estado_desejado_informado", True):
            desejo = "pendente"
        print(f"Estado desejado: {desejo}")
        recoms = reg.get('recomendacoes', [])
        musicas_str = ", ".join([f"{m['nome']} ({m['artista']})" for m in recoms])
        if not progresso.get("recomendacoes_geradas", True):
            musicas_str = "pendentes"
        print(f"Músicas recomendadas: {musicas_str}")
        if recoms and progresso.get("recomendacoes_geradas", True):
            exibir_recomendacoes_da_sessao(reg, incluir_faixas=False)
        exibir_escuta_da_sessao(reg)
        fb = reg.get("feedback")
        estado_feedback = classificar_feedback(fb)
        if estado_feedback == NAO_REGISTRADO:
            print("Retorno ainda não registrado.")
        else:
            ajudou_str = "Sim" if estado_feedback == POSITIVO else "Não"
            print(f"Retorno da sessão — Fez sentido? {ajudou_str} | Motivo: {fb.get('motivo', '')}")
        print(LIMITACAO_POR_FAIXA)
        print(INTERPRETACAO_RETORNOS)
        print("-" * 50)

# Mapa para humanizar emoções no relatório reflexivo
_EMOCAO_HUMANIZADA = {
    "triste": "tristeza",
    "cansado": "cansaço",
    "ansioso": "ansiedade",
    "calmo": "calma",
    "animado": "animação",
    "disposto": "disposição",
    "reflexivo": "reflexão",
    "feliz": "felicidade",
    "foco": "foco",
    "raiva": "raiva",
    "sofrendo": "sofrimento",
    "explosivo": "intensidade",
    "amor": "amor",
    "normal": "equilíbrio",
}

def opcao_ver_padroes():
    historico = carregar_json(ARQ_HISTORICO, {})

    if not historico:
        print("\n⚠️ O sistema precisa de mais registros no histórico para gerar um relatório de padrões.")
        return

    emocoes_count = Counter()
    desejos_count = Counter()
    estrategias_count = Counter()
    avaliacoes = resumir_avaliacoes(historico)

    for reg in historico.values():
        analise = reg.get("analise", {})

        for e in analise.get("emocoes", []):
            emocoes_count[e] += 1
        for d in analise.get("estado_desejado", []):
            desejos_count[d] += 1

        estrategia_usada = reg.get("estrategia", "")
        if estrategia_usada:
            estrategias_count[estrategia_usada] += 1

    print("\n=== Os Seus Padrões Pessoais ===")
    print("Este relatório ajuda você a refletir sobre seus estados emocionais e")
    print("a forma como usa a música para se autorregular.\n")

    if emocoes_count:
        top_emocoes = [f"{_EMOCAO_HUMANIZADA.get(k, k)} ({v}x)" for k, v in emocoes_count.most_common(3)]
        print(f"🔹 Estados mais frequentes: {', '.join(top_emocoes)}")

    if desejos_count:
        top_desejos = [f"{_EMOCAO_HUMANIZADA.get(k, k)} ({v}x)" for k, v in desejos_count.most_common(3)]
        print(f"🔹 O que mais procura sentir: {', '.join(top_desejos)}")
    else:
        print("🔹 O que mais procura sentir: ainda sem padrão claro")

    print(f"\nSessões avaliadas: {avaliacoes['sessoes_avaliadas']} de {avaliacoes['sessoes_totais']}.")
    print(f"Retornos positivos: {avaliacoes['retornos_positivos']}")
    print(f"Retornos negativos: {avaliacoes['retornos_negativos']}")
    print(f"Retorno ainda não registrado: {avaliacoes['retornos_nao_registrados']}")
    print(INTERPRETACAO_RETORNOS)
    print(LIMITACAO_POR_FAIXA)

    # Síntese reflexiva — sem expor termos técnicos
    print("\n=== Síntese Reflexiva ===")
    if emocoes_count and desejos_count:
        emocao_top = _EMOCAO_HUMANIZADA.get(emocoes_count.most_common(1)[0][0], emocoes_count.most_common(1)[0][0])
        desejo_top = _EMOCAO_HUMANIZADA.get(desejos_count.most_common(1)[0][0], desejos_count.most_common(1)[0][0])
        print(
            f"Com base no seu diário, parece que você costuma buscar apoio musical\n"
            f"quando se sente com '{emocao_top}', buscando alcançar um estado de '{desejo_top}'.\n"
            f"Observar esses padrões pode te ajudar a antecipar e acolher melhor\n"
            f"seus estados antes que se tornem muito pesados."
        )
    elif emocoes_count:
        emocao_top = _EMOCAO_HUMANIZADA.get(emocoes_count.most_common(1)[0][0], emocoes_count.most_common(1)[0][0])
        print(
            f"Você costuma buscar apoio musical quando se sente com '{emocao_top}'.\n"
            f"Continue usando o sistema para refinar esse padrão."
        )
    else:
        print("Continue usando o sistema para gerarmos uma síntese sobre o seu perfil emocional.")

    print("================================")

# ============================================================
# INTERFACE E MENUS PRINCIPAIS
# ============================================================
def exibir_proposta():
    print("\n=== Proposta do Sistema ===")
    print()
    print("O RhythmMind é um diário musical emocional e uma ferramenta de apoio reflexivo.")
    print()
    print("Com base no que você relata sentir, o sistema busca músicas que possam")
    print("apoiar o seu momento — seja para acolher, para energizar, para focar")
    print("ou simplesmente para acompanhar o que você está vivendo.")
    print()
    print("IMPORTANTE:")
    print("O RhythmMind NÃO é uma ferramenta clínica, médica ou de diagnóstico.")
    print("Não substitui acompanhamento profissional de nenhum tipo.")
    print("Toda recomendação é experimental e subjetiva — baseada apenas")
    print("no que você descreve, sem qualquer análise psicológica real.")
    print()
    print("Use com curiosidade e sem expectativas fixas.")
    print("===========================\n")

def ler_opcao_menu():
    while True:
        print("\n=== RhythmMind ===")
        print("1 - Registrar estado atual e receber recomendação")
        print("2 - Ver músicas cadastradas")
        print("3 - Adicionar música")
        print("4 - Ver histórico")
        print("5 - Ver proposta do sistema")
        print("6 - Ver seus padrões pessoais")
        print("7 - Sair")
        print("8 - Registrar escolha e escuta de uma sessão")
        print("9 - Registrar feedback de uma sessão")
        print("10 - Retomar uma sessão salva")
        print("11 - Finalidade e contexto da sessão")
        print("12 - Filtrar histórico")
        print("13 - Quantidade de sugestões da sessão")

        opcao = input("Escolha uma opção (1-13): ").strip()
        if opcao in [str(numero) for numero in range(1, 14)]:
            return opcao
        print("⚠️ Opção inválida. Por favor, digite apenas um número de 1 a 13.")

def analise_tem_estado_identificado(emocoes):
    """Retorna True se a análise conseguiu reconhecer pelo menos um sentimento válido."""
    return bool(emocoes)

def solicitar_refinamento_estado(texto_original):
    """Permite corrigir a interpretação ou escolher explicitamente não usar categoria."""
    print("\nVamos refinar a interpretação ou seguir sem categoria.")
    while True:
        texto_manual = input(
            "\nDigite apenas os sentimentos que descrevem melhor o que você está sentindo agora.\n"
            "Exemplos: triste, cansado, ansioso, calmo, reflexivo, animado, com raiva, sem energia.\n"
            "Ou digite 'sem categoria' para continuar sem atribuir uma categoria ao relato.\n> "
        )
        if texto_manual.strip().lower() == "sem categoria":
            return []
        emocoes = detectar_emocoes_no_texto(separar_papeis_texto(texto_manual)[0])
        if analise_tem_estado_identificado(emocoes):
            return emocoes
        print("\nAinda não consegui reconhecer nenhum desses termos.")
        print("Você pode tentar outros termos ou digitar 'sem categoria'.")

# Mapa de adjetivos humanizados para a mensagem de transição
_ADJETIVOS_ESTADO_DESEJADO = {
    "calmo": "calmo",
    "feliz": "feliz",
    "foco": "focado",
    "disposto": "disposto",
    "animado": "animado",
    "reflexivo": "reflexivo",
    "normal": "equilibrado",
    "amor": "leve",
    "triste": "leve",
    "cansado": "disposto",
    "sofrendo": "leve",
    "ansioso": "calmo",
    "raiva": "calmo",
    "explosivo": "calmo",
}

def construir_mensagem_transicao(estado_desejado):
    """Monta a frase humana que substitui o antigo resumo técnico da interpretação."""
    if not estado_desejado:
        return (
            "Com base no que você contou, vou buscar músicas que possam apoiar esse "
            "momento. Depois de ouvir, me diga se as recomendações fizeram sentido para você."
        )
    adjetivos = [_ADJETIVOS_ESTADO_DESEJADO.get(e, e) for e in estado_desejado]
    adjetivos = list(dict.fromkeys(adjetivos))
    if len(adjetivos) <= 2:
        descricao = " e ".join(adjetivos)
    else:
        descricao = ", ".join(adjetivos[:-1]) + f" e {adjetivos[-1]}"
    return (
        f"Com base no que você contou, vou buscar músicas que possam te ajudar a entrar "
        f"em um modo mais {descricao}. Depois de ouvir, me diga se as recomendações "
        f"fizeram sentido para você."
    )

def coletar_feedback(ao_atualizar=None, anterior=None, editar=False):
    """Retoma pendências ou edita cada resposta sem apagar as demais."""
    anterior = dict(anterior) if isinstance(anterior, dict) else {}
    ajudou = anterior.get("ajudou")
    motivo = anterior.get("motivo", "")
    existe_melhoria = anterior.get("existe_melhoria")
    melhoria = anterior.get("melhoria", "")

    def salvar_parcial(concluida=False):
        if ao_atualizar is not None:
            ao_atualizar({
                **anterior,
                "ajudou": ajudou, "motivo": motivo,
                "existe_melhoria": existe_melhoria, "melhoria": melhoria,
                "coleta_concluida": concluida,
            })

    if editar or type(ajudou) is not bool:
        manter = " Enter para manter a resposta anterior." if type(ajudou) is bool else ""
        while True:
            resposta = input(
                "Essas recomendações fizeram sentido para você?\n"
                f"Sim ou não?{manter}\n> "
            ).strip().lower()
            if editar and not resposta and type(ajudou) is bool:
                break
            if resposta in {"sim", "s", "não", "nao", "n"}:
                ajudou = resposta in {"sim", "s"}
                break
            print("Por favor, responda 'sim' ou 'não'.")
        salvar_parcial()

    pergunta = "O que fez sentido nessas recomendações?" if ajudou else "O que não fez sentido nessas recomendações?"
    if editar or not motivo:
        manter = " Enter para manter o motivo anterior." if motivo else ""
        while True:
            resposta = input(f"Por quê? {pergunta}{manter}\n> ").strip()
            if editar and not resposta and motivo:
                break
            if resposta:
                motivo = resposta
                break
            print("Por favor, escreva pelo menos uma palavra.")
        salvar_parcial()

    if editar or type(existe_melhoria) is not bool:
        manter = " Enter para manter a resposta anterior." if type(existe_melhoria) is bool else ""
        while True:
            resposta = input(f"Existe algo que pode melhorar?\nSim ou não?{manter}\n> ").strip().lower()
            if editar and not resposta and type(existe_melhoria) is bool:
                break
            if resposta in {"sim", "s", "não", "nao", "n"}:
                existe_melhoria = resposta in {"sim", "s"}
                if not existe_melhoria:
                    melhoria = ""
                break
            print("Por favor, responda 'sim' ou 'não'.")
        salvar_parcial()

    if existe_melhoria and (editar or not melhoria):
        manter = " Enter para manter o detalhe anterior." if melhoria else ""
        while True:
            resposta = input(f"Descreva o que poderia melhorar:{manter}\n> ").strip()
            if editar and not resposta and melhoria:
                break
            if resposta:
                melhoria = resposta
                break
            print("Por favor, descreva ao menos brevemente o que poderia melhorar.")
    salvar_parcial(concluida=True)
    return ajudou, motivo, existe_melhoria, melhoria


def _gravar_etapa_cli(identificador, **campos):
    return atualizar_sessao(ARQ_HISTORICO, identificador, **campos)


def continuar_sessao(identificador):
    """Retoma o arquivo existente, sem criar UUID ou repetir etapas concluídas."""
    try:
        registro = carregar_json(ARQ_HISTORICO, {})[identificador]
        if not recomendacoes_registradas(registro):
            progresso = dict(registro["progresso"])
            if not progresso["emocoes_confirmadas"]:
                emocoes = detectar_emocoes_no_texto(separar_papeis_texto(registro["texto_usuario"])[0])
                if not analise_tem_estado_identificado(emocoes):
                    emocoes = solicitar_refinamento_estado(registro["texto_usuario"])
                else:
                    print("\nCategorias detectadas (aguardando sua confirmação):")
                    for emocao in emocoes:
                        print(f"  - {emocao}")
                    while True:
                        resposta = input(
                            "Isso faz sentido para você?\n"
                            "Sim para confirmar, não para corrigir, ou 'sem categoria' para continuar sem categoria.\n> "
                        ).strip().lower()
                        if resposta == "sem categoria":
                            emocoes = []
                            break
                        if resposta in {"sim", "s"}:
                            break
                        if resposta in {"não", "nao", "n"}:
                            emocoes = solicitar_refinamento_estado(registro["texto_usuario"])
                            break
                        print("Por favor, responda 'sim', 'não' ou 'sem categoria'.")
                analise = dict(registro["analise"])
                analise["emocoes"] = emocoes
                progresso["emocoes_confirmadas"] = True
                registro = _gravar_etapa_cli(identificador, analise=analise, progresso=progresso)

            if not progresso["estado_desejado_informado"]:
                texto = registro.get("texto_desejado")
                if texto is None:
                    texto = input(
                        "\nComo você gostaria de se sentir?\n"
                        "Exemplos: mais calmo, focado ou disposto. Enter para continuar sem definir.\n> "
                    )
                    registro = _gravar_etapa_cli(identificador, texto_desejado=texto)
                analise = dict(registro["analise"])
                analise["estado_desejado"] = detectar_emocoes_no_texto(texto) if texto else []
                progresso["estado_desejado_informado"] = True
                registro = _gravar_etapa_cli(identificador, analise=analise, progresso=progresso)

            analise = registro["analise"]
            if analise["emocoes"]:
                print(f"\n{construir_mensagem_transicao(analise['estado_desejado'])}\n")
            else:
                print("\nVocê escolheu seguir sem categoria para o estado atual.")
                print("As sugestões dependem das regras disponíveis para o estado desejado informado.\n")
            limite = validar_limite_recomendacoes(registro.get("limite_recomendacoes", 3))
            opcoes = {} if limite == 3 else {"limite": limite}
            estrategia, explicacao, recomendacoes = recomendar_musicas(
                analise["emocoes"], analise["estado_desejado"], **opcoes,
            )
            motivos = explicar_recomendacoes(analise["emocoes"], estrategia, recomendacoes)
            progresso["recomendacoes_geradas"] = True
            registro = _gravar_etapa_cli(
                identificador, estrategia=estrategia, explicacao=explicacao,
                recomendacoes=recomendacoes, motivos_recomendacoes=motivos,
                limite_recomendacoes=limite, progresso=progresso,
            )

        recomendacoes = registro.get("recomendacoes", [])
        if not recomendacoes:
            if registro.get("estrategia") is None and registro.get("explicacao"):
                print(registro["explicacao"])
            print("Não encontrei músicas para esta sessão. O relato permanece salvo.")
            return
        print("Recomendações salvas:")
        exibir_recomendacoes_da_sessao(registro)
        coletar_escuta(
            recomendacoes,
            ao_atualizar=lambda escuta: _gravar_etapa_cli(identificador, escuta=escuta),
            anterior=registro.get("escuta"),
        )
        # Uma avaliação já registrada não é substituída ao retomar.
        feedback = registro.get("feedback") or {}
        if classificar_feedback(feedback) == NAO_REGISTRADO or feedback.get("coleta_concluida") is False:
            coletar_feedback(
                ao_atualizar=lambda feedback: _gravar_etapa_cli(identificador, feedback=feedback),
                anterior=feedback,
            )
        print("Etapas informadas salvas na mesma sessão.")
    except (KeyboardInterrupt, EOFError):
        print(f"\nFluxo interrompido. As etapas já salvas permanecem na sessão {identificador}.")
    except OSError:
        print(f"Falha ao salvar etapa da sessão {identificador}. A última versão salva foi preservada.")
    except KeyError:
        print("Sessão não encontrada.")
    except Exception:
        print(f"Não foi possível concluir a etapa. Consulte a sessão {identificador} para retomar.")


def opcao_retomar_sessao():
    historico = carregar_json(ARQ_HISTORICO, {})
    if not historico:
        print("Você ainda não tem sessões para retomar.")
        return
    identificador = selecionar_sessao(historico)
    if identificador is not None:
        continuar_sessao(identificador)


def opcao_registar_estado(*, coletar_contexto=False, limite_recomendacoes=3):
    limite_recomendacoes = validar_limite_recomendacoes(limite_recomendacoes)
    print("\n--- Registrar Estado e Receber Recomendação ---")
    while True:
        texto = input("Como você está se sentindo agora? Pode escrever com suas próprias palavras.\n> ")
        if texto.strip():
            break
        print("Informe um relato não vazio.")
    registro = criar_sessao(
        data_hora=datetime.now().strftime("%d/%m/%Y %H:%M:%S"), texto_usuario=texto,
        limite_recomendacoes=limite_recomendacoes,
    )
    try:
        salvar_nova_sessao(ARQ_HISTORICO, registro)
    except OSError:
        print("Falha ao salvar o relato. A sessão não foi registrada.")
        return
    identificador = registro["sessao_id"]
    print(f"Relato salvo. ID da sessão: {identificador}")
    print(f"Data/hora de criação: {registro['data_hora']}")
    if coletar_contexto:
        try:
            coletar_metadados_sessao(identificador)
            coletar_limite_recomendacoes(identificador)
        except (KeyboardInterrupt, EOFError):
            print(f"Fluxo interrompido. As informações já salvas permanecem na sessão {identificador}.")
            return
        except OSError:
            print(f"Falha ao salvar informações da sessão {identificador}. A última versão salva foi preservada.")
            return
    continuar_sessao(identificador)

def main():
    print("CLI de desenvolvimento: nao autentica usuarios. Contas pessoais usam a API autenticada.")
    while True:
        opcao = ler_opcao_menu()

        if opcao == '1':
            opcao_registar_estado(coletar_contexto=True)
        elif opcao == '2':
            opcao_ver_musicas()
        elif opcao == '3':
            adicionar_musica()
        elif opcao == '4':
            identificador = input("ID da sessão ou chave legada (Enter para ver todas):\n> ").strip()
            opcao_ver_historico(identificador or None)
        elif opcao == '5':
            exibir_proposta()
        elif opcao == '6':
            opcao_ver_padroes()
        elif opcao == '8':
            opcao_registrar_escuta()
        elif opcao == '9':
            opcao_registrar_feedback()
        elif opcao == '10':
            opcao_retomar_sessao()
        elif opcao == '11':
            opcao_registrar_contexto()
        elif opcao == '12':
            opcao_filtrar_historico()
        elif opcao == '13':
            opcao_quantidade_sugestoes()
        elif opcao == '7':
            print("\nA encerrar o RhythmMind... Até logo e fica bem!")
            break

if __name__ == "__main__":
    main()
