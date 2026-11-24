# Catálogo de referência — músicas reais

Versão `2026-11-13.3`. O artefato distribuído é
[`data/catalogo_referencia.json`](../data/catalogo_referencia.json), com 500 faixas:

- 66 faixas da seleção inicial: 60 de cinco playlists fornecidas pelo autor e
  seis alternativas instrumentais de Ludovico Einaudi e Yiruma;
- 434 faixas adicionais, distribuídas entre cinco playlists públicas fornecidas
  pelo autor (92, 92, 89, 90 e 71 faixas: 30 na primeira rodada, 50 na segunda,
  100 na terceira e 254 nesta rodada — respectivamente 51, 51, 50, 51 e 51).
  Links indisponíveis ou restritos por convite que não expuseram faixas
  publicamente não foram usados.

Não é uma cópia completa das playlists nem representa acesso à conta do Spotify.

## Fontes e limites da consulta

Os dados do Spotify vieram das páginas e players públicos: identificador da
gravação, título, crédito de artistas, duração e álbum quando exposto. Os links
públicos maiores podem mostrar somente os primeiros 100 itens; links indisponíveis
ou que não expuseram faixas não foram usados. Não houve paginação autenticada,
aceite de convite, reprodução, download de áudio ou leitura de playlists privadas.

As seis faixas instrumentais foram consultadas na Apple iTunes Search API e
vinculadas às respectivas edições na Apple Music. A disponibilidade de reprodução
depende do serviço e da região; os links são fontes de metadados.

O artefato não contém URLs de playlists pessoais, nomes de proprietários, cookies,
tokens ou parâmetros de convite. Cada faixa mantém somente sua URL pública de
referência e a data da consulta.

## Metadados, associações e recomendações

- `proveniencia` guarda os dados consultados. Álbum desconhecido permanece `null`.
- As 66 faixas anteriores mantêm `curadoria.status = "provisoria"` e suas
  associações editoriais exploratórias.
- As 434 novas usam `curadoria.status = "pendente"`, sem sentimentos, estratégias
  ou contextos inferidos a partir de título, artista, gênero ou playlist.
- `bpm` permanece `null`; energia, valência e intensidade não são inventadas.
- Uma faixa pendente não participa das recomendações. Ela passa a participar
  somente depois que o titular indica ao menos uma sensação no catálogo pessoal.
- Salvar a lista de sensações vazia remove a faixa das próximas recomendações sem
  apagar a música. Sessões já registradas preservam suas escolhas.
- As músicas não entram no contexto da LLM, e nenhum efeito fisiológico ou clínico
  é prometido.

Alterar as sensações modifica somente a cópia pessoal do usuário autenticado. A
referência compartilhada, as outras contas e o histórico continuam intactos. O
registro pessoal conserva revisões anteriores das associações para rastreabilidade.

## Como usar na interface

1. Entre na conta e abra **Minhas músicas**.
2. Expanda **Adicionar seleção ao meu catálogo**. A prévia fechada não cria os
   cartões; ao abrir, são mostradas 25 faixas por vez, com busca sem distinção de
   maiúsculas ou acentos.
3. Clique em **Adicionar seleção ao meu catálogo**. Faixas já existentes são
   preservadas e contabilizadas, sem duplicação.
4. Nas faixas pendentes, use **Indicar sensações**. As sugestões seguintes só
   considerarão a faixa depois dessa confirmação pessoal.

Não existe seed automático em todas as contas. O arquivo pessoal é ignorado pelo
Git; atualizar o código não importa nem sobrescreve dados na máquina do usuário.

## HTTP

As rotas exigem o mesmo Bearer token das demais APIs pessoais e usam
`Cache-Control: no-store`.

`GET /api/catalogo-referencia` não grava dados e retorna, de forma abreviada:

```json
{
  "versao": "2026-11-13.3",
  "total": 500,
  "pronta_para_recomendar": 66,
  "pendentes_associacao": 434,
  "descricao": "…",
  "musicas": []
}
```

`POST /api/catalogo-referencia/importar` aceita `{}` ou `{"ids":null}` para o
lote completo, `{"ids":["identificador_da_faixa"]}` para uma seleção e
`{"ids":[]}` para nenhuma faixa. O limite defensivo é 600 identificadores;
IDs desconhecidos invalidam o lote inteiro antes de qualquer escrita.

Para uma conta inicialmente vazia, a importação completa responde:

```json
{"versao":"2026-11-13.3","importadas":500,"ja_existentes":0,"total":500}
```

`PATCH /api/musicas/{musica_id}/associacoes` recebe somente categorias válidas:

```json
{"sentimentos_associados":["calmo","foco"]}
```

A resposta é `{"musica": {...}}`. Lista vazia é válida. Faixa inexistente retorna
404, ocorrência ambígua retorna 409 e corpo inválido retorna 422. Sem autenticação,
as rotas retornam 401; uma conta não consegue consultar nem alterar a cópia de outra.

## Integridade e testes

O serviço valida o arquivo inteiro antes da importação, deduplica por ID e por
nome/artista normalizados e faz a escrita pessoal por temporário, `fsync` e
`os.replace`. O lock cobre importação, cadastro manual e edição de associações no
mesmo processo. Em duplicatas, a versão pessoal prevalece sem ser sobrescrita.

Os testes cobrem autenticação, isolamento entre contas, origem e esquema dos dados,
seleção parcial, idempotência, concorrência, falha de gravação, histórico,
recomendação de faixas classificadas e exclusão das pendentes. No navegador,
cobrem busca, paginação, prévia recolhida, edição, lista vazia, repetição de cliques,
respostas atrasadas e troca de sessão. Os testes usam diretórios e contas temporários.
