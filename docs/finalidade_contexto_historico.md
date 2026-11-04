# Finalidade, contexto e filtros do histórico

A sessão pode guardar dois textos opcionais informados pela pessoa:

- `finalidade`: o que busca com a escuta, como “acompanhar uma pausa”, até 200 caracteres.
- `contexto`: atividade ou situação, como “intervalo dos estudos”, até 500 caracteres.

Os limites contam o texto recebido antes de retirar espaços nas extremidades.
Textos vazios ou só com espaços são guardados como `null`. Um campo ausente
ou `null` não informa uma finalidade ou contexto, nem demonstra uma decisão
explícita de não responder. Eles ficam fora da análise emocional e não mudam
estratégias, pontuação ou recomendações. Não são deduzidos do relato nem
confundidos com os contextos acústicos/musicais do catálogo.

Novas sessões possuem esses campos, inicialmente `null`. Consultar ou
retomar um registro legado não acrescenta campos a ele. Registrar metadados
explicitamente em um legado altera apenas o que foi fornecido.

## Terminal

O menu **1** salva primeiro o relato e oferece finalidade e contexto antes
da revisão emocional. Enter deixa a informação ausente; cada resposta
preenchida é salva antes da próxima pergunta. Interromper conserva o relato
e qualquer informação já salva. Os metadados são opcionais e não bloqueiam
a revisão ou as recomendações.

O menu **11** seleciona uma sessão pelo UUID ou chave legada e permite
completar/editar os textos depois, inclusive após recomendar. Enter conserva
o valor anterior; `-` apaga explicitamente esse campo. Uma interrupção depois
da finalidade não apaga o contexto anterior nem exige repetir a finalidade.
O histórico mostra finalidade/contexto ausentes como não informados.

O menu **12** pede os filtros opcionais; Enter não aplica aquele filtro.
A opção **4** mantém a consulta completa ou por identificador exato, e a
opção **10** continua retomando apenas as etapas pendentes da sessão.

A função Python `opcao_registar_estado()` mantém a coleta antiga para
chamadas existentes; o menu usa `coletar_contexto=True` para o fluxo completo.
Os testes de compatibilidade também exercitam esse caminho anterior.

## API: criação e edição parcial

Em `POST /api/registrar-estado`, por exemplo:

```json
{
  "texto_atual": "Relato fictício: não estou triste.",
  "finalidade": "Acompanhar uma pausa",
  "contexto": "Intervalo dos estudos",
  "emocoes_confirmadas": [],
  "texto_desejado": "calmo"
}
```

O relato continua preservado exatamente como recebido. A resposta de estado
expõe os dois metadados e a sessão os salva antes de analisar ou recomendar.

Em `POST /api/contexto-sessao`, informe o identificador e ao menos um campo:

```json
{
  "sessao_id": "11111111-1111-4111-8111-111111111111",
  "finalidade": "Relaxar depois dos estudos"
}
```

Use o UUID real da criação. Omitir `contexto` preserva seu valor; enviar
`null` ou texto branco apaga apenas esse campo. O alias de referência
legada `data_hora` também é aceito, com as mesmas regras de identificação.
Pedidos sem metadados, campos extras, tipos inválidos ou textos acima do
limite retornam 422 sem escrita. Sessão inexistente ou pertencente a outra
conta retorna 404. Falha de armazenamento retorna 503 e conserva a versão
anterior salva. A rota exige a autenticação e as restrições locais existentes.

Editar finalidade/contexto não altera UUID, criação, relato, categorias,
desejo, recomendações, escuta, feedback ou outros campos. As restrições de
alteração das etapas já concluídas pela retomada continuam valendo.

## API: filtros

Em `GET /api/historico`, os parâmetros opcionais são combinados com **E**:

| Parâmetro | Regra |
| --- | --- |
| `data_inicio` | Data inicial inclusiva, `YYYY-MM-DD` |
| `data_fim` | Data final inclusiva, `YYYY-MM-DD` |
| `finalidade` | Trecho literal do texto, ignorando caixa e acentos |
| `contexto` | Trecho literal do texto, ignorando caixa e acentos |
| `avaliacao` | `positivo`, `negativo` ou `nao_registrado` |

Exemplo: `GET /api/historico?data_inicio=2026-11-01&data_fim=2026-11-04&contexto=estudos&avaliacao=nao_registrado`.

O período usa a data/hora de criação persistida, sem inferir data da chave
legada/UUID e sem converter fuso horário. Datas de registros são lidas no
formato existente `dd/mm/YYYY HH:MM:SS`. Legados sem data válida continuam
visíveis sem filtro temporal; um filtro temporal os exclui por não haver
data comprovada no período. A consulta preserva ordem e registros brutos,
sem regravar, migrar ou normalizar o histórico.

Filtros de texto brancos, datas inválidas, período invertido ou avaliação
desconhecida retornam 422, mesmo com histórico vazio. O menu do terminal
converte Enter em ausência de filtro antes de consultar.

`total`, `registros` e `avaliacoes_sessoes` refletem somente o recorte.
Sem correspondências, a resposta é 200 com registros vazios e resumo zero.
Sem filtros, mantém a consulta completa. `GET /api/padroes` continua sendo
o relatório geral da conta; os filtros desta rodada pertencem ao histórico.

O retorno negativo exige `ajudou=false` booleano, o positivo exige `true`.
Feedback ausente, `{}`, `null` ou sem booleano explícito continua
`nao_registrado`; não é a decisão explícita de seguir sem avaliação, que
permanece uma próxima etapa separada.

## Validação

Os testes usam somente relatos, contas e arquivos fictícios temporários:

```bash
.venv-local/bin/python -m pip check
.venv-local/bin/python -B -m unittest tests.test_historico_filtros tests.test_contexto_api tests.test_contexto_cli -v
.venv-local/bin/python -B -m unittest discover -s tests -v
```

Validação em 04/11/2026, Python 3.12 no Linux: **250 testes aprovados**
(206 anteriores preservados e 44 novos). `pip check` sem conflitos.
Os novos testes cobrem edição parcial e limites, interrupções da CLI,
isolamento de contas, preservação do legado, filtros combinados, limites
temporais inclusivos e consultas que não alteram o arquivo.
