# Catálogo de referência — músicas reais

Versão inicial `2026-11-11.1`, consultada em 11/11/2026. O artefato distribuído é
[`data/catalogo_referencia.json`](../data/catalogo_referencia.json), com 66 faixas:
60 selecionadas entre cinco playlists fornecidas pelo autor e seis alternativas
instrumentais. Não é uma cópia completa das playlists.

## Fontes e alcance da consulta

As páginas públicas do Spotify permitiram consultar faixas de “Excuse me”,
“Funk”, “sertanejola”, “Rap” e “Internacional”. Foram selecionadas 12 faixas
distintas por lista, evitando repetir gravações que aparecem em mais de uma.
Uma sexta URL não disponibilizou os metadados da playlist, inclusive com o link
de convite fornecido. Não se inferiu seu conteúdo.

As páginas principais expuseram os primeiros 30 itens; os players incorporados
de algumas listas expuseram até 100. A consulta não usou paginação autenticada
nem representa acesso à conta ou análise integral das listas maiores.

Cada faixa registra URL pública, identificador da gravação, título, crédito de
artistas, álbum, data da consulta e duração original em milissegundos. O nome
preserva indicações como “Ao Vivo”, “Acústico” e “Sped Up Version”; essas edições
não são intercambiáveis com outras gravações de mesmo título. A duração visível
`m:ss` é arredondada; o valor original e a observação de duração conservam a precisão.

As seis faixas complementares são de Ludovico Einaudi e Yiruma. Foram consultadas
na Apple iTunes Search API e vinculadas às respectivas edições na Apple Music.
As URLs por faixa estão no próprio JSON e aparecem na interface. Disponibilidade
de reprodução depende do serviço e da região; os links são fontes de metadados.

O artefato não contém URLs de playlists pessoais, proprietários, cookies, tokens,
parâmetros de convite ou arquivos de áudio. Não existe sincronização automática
com o Spotify.

## Separação entre metadados e curadoria

- `proveniencia` contém os dados consultados na fonte pública. `id` recebe prefixo
  do provedor, sem alterar o identificador original em `id_fonte`.
- `curadoria` identifica o status **provisório**, método, versão e justificativa
  das associações propostas pelo projeto. São pontos de partida exploratórios,
  não preferências já confirmadas pelo titular ou rótulos fornecidos pelo Spotify.
- `sentimentos_associados` e `estrategias` são associações editoriais utilizadas
  pelo motor determinístico existente. Não comprovam uma resposta emocional.
- `bpm` fica `null`. Energia, valência e intensidade não foram preenchidas.
  `caracterizacao` contém apenas duração obtida nos metadados; listas de anotações
  emocionais e de estimativas de sistema ficam vazias.
- As músicas não entram no contexto da LLM. Interpretação e recomendação mantêm
  suas responsabilidades existentes. Nenhum efeito fisiológico/clínico é prometido.

O retorno sobre a experiência continua sendo individual e registrado por sessão;
ele não reclassifica globalmente as faixas. Os exemplos fictícios anteriores não
foram substituídos por títulos reais nos testes.

## Como usar na interface

1. Entre na conta do RhythmMind e abra **Minhas músicas**.
2. Em **Seleção inicial de músicas reais**, expanda a lista para consultar faixas,
   álbuns, links das fontes e associações provisórias.
3. Clique em **Adicionar seleção ao meu catálogo**. O resultado mostra quantas
   faixas entraram e quantas já existiam. Suas faixas anteriores são preservadas.

Não há seed automático em todas as contas. O catálogo compartilhado é uma
referência somente leitura; a ação explícita cria cópias pessoais, que passam a
participar das próximas recomendações. Sessões antigas conservam suas escolhas.
O arquivo pessoal é ignorado pelo Git; atualizar o código não importa nem
sobrescreve dados na máquina do usuário.

## HTTP

As duas rotas exigem o mesmo Bearer token das demais APIs pessoais e usam
`Cache-Control: no-store`.

`GET /api/catalogo-referencia` retorna:

```json
{"versao":"2026-11-11.1","total":66,"descricao":"…","musicas":[]}
```

No exemplo acima, `musicas` foi abreviado; a resposta real contém as 66 faixas.
A consulta não grava no catálogo da conta.

`POST /api/catalogo-referencia/importar` aceita `{}` ou `{"ids":null}` para o lote
completo, `{"ids":["identificador_da_faixa"]}` para uma seleção e `{"ids":[]}`
para nenhuma faixa. O limite de seleção é 300 identificadores. Exemplo de resposta
para uma conta inicialmente vazia:

```json
{"versao":"2026-11-11.1","importadas":66,"ja_existentes":0,"total":66}
```

Não são aceitos usuário, caminho de arquivo ou lote arbitrário na requisição.
ID desconhecido produz 422 antes de qualquer escrita; referência inválida ou
indisponível produz 503. Falha de substituição do arquivo preserva o anterior.
Sem autenticação, ambas as rotas retornam 401.

## Integridade e manutenção

O serviço lê o JSON pelo caminho absoluto do módulo, pois o desenvolvimento local
usa outro diretório de dados. Valida o lote inteiro antes da importação, prepara
cópias independentes e deduplica por ID e nome/artista normalizados. Em caso de
duplicata, o cadastro pessoal prevalece sem receber alterações da referência.
Uma repetição sem novas faixas não regrava o arquivo.

O lock de músicas cobre a leitura/mescla/escrita da importação e o cadastro manual
no mesmo processo. A escrita usa temporário, `fsync` e `os.replace`. Isso não cria
uma garantia de coordenação entre múltiplos processos; o inicializador local
permanece com seu modelo de execução existente.

Testes novos cobrem autenticação, isolamento entre contas, validação/proveniência,
seleção parcial, idempotência, falha de gravação, concorrência com cadastro manual
e preservação do histórico/catálogo legado. O controlador web também verifica
cliques duplicados, respostas atrasadas e reset de sessão. Todas as gravações de
teste usam contas/diretórios temporários próprios.
