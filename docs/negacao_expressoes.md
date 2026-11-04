# Negação e expressões compostas — regras locais v1

A interpretação continua lexical, com biblioteca padrão do Python e
dicionário local. Não há LLM, serviços externos, treinamento, probabilidades
ou análise sintática completa. A revisão pela pessoa continua necessária.

## Problemas reproduzidos antes da correção

O analisador anterior comparava cada sinônimo com palavras isoladas. Assim,
negadores não tinham efeito e expressões com espaços nunca eram encontradas.

| Relato fictício | Antes | Depois |
| --- | --- | --- |
| Não estou triste | `["triste"]` | `[]` |
| Não estou triste, estou cansado | `["triste", "cansado"]` | `["cansado"]` |
| Estou triste, mas não estou ansioso | `["triste", "ansioso"]` | `["triste"]` |
| Estou sem energia | `["animado"]` | `["cansado"]` |
| Estou feliz | `["feliz"]` | `["feliz"]` |
| Estou sem disposição | `["disposto"]` | `["cansado"]` |
| Estou fora de controle | `[]` | `["explosivo"]` |
| Estou no limite | `[]` | `["explosivo"]` |

Os quatro erros dos casos essenciais foram reproduzidos também por um teste
de regressão que falhou antes da implementação. O caso positivo já passava.

`[]` significa que nenhuma categoria afirmativa foi reconhecida segundo
essas regras. Não significa felicidade, neutralidade ou decisão explícita
de seguir sem categoria.

## Normalização e contrato

`detectar_emocoes_no_texto(texto)` continua retornando uma lista de categorias,
sem repetição, **na ordem das chaves do dicionário**, não na ordem do relato.
`remover_acentos` e `extrair_palavras` mantêm seus contratos anteriores.

A análise usa uma cópia normalizada em minúsculas e sem acentos. Não altera
o texto original, o dicionário ou o histórico. O dicionário é relido a cada
chamada, sem cache que esconda alterações na referência.

Casamentos continuam por palavras inteiras. `desanimado` não é uma
ocorrência interna de `animado`; `infeliz` não vira `feliz`.

## Expressões e sobreposição

Cada sinônimo do dicionário é convertido em uma sequência de palavras.
A busca avança da esquerda para a direita. Na posição atual, a sequência
mais longa vence; seus tokens são consumidos antes de examinar a próxima
posição. Não é uma busca pelo melhor conjunto global de expressões.

Os compostos já existentes na referência são:

| Expressão | Categoria documentada |
| --- | --- |
| sem energia | cansado |
| sem disposição | cansado |
| fora de controle | explosivo |
| no limite | explosivo |

Em `sem energia`, a expressão inteira produz `cansado`; a palavra interna
`energia` não produz simultaneamente `animado`. O `sem` interno pertence
à unidade do dicionário e não a cancela. Uma negação externa, como
`não estou sem energia`, suprime o composto inteiro, sem deixar a palavra
interna gerar animação e sem inferir disposição.

Uma palavra consumida pode aparecer de novo fora do composto:
`sem energia, mas agora energia` retorna `["animado", "cansado"]`,
conservando a ordem do dicionário.

Sinônimos iguais ligados a categorias distintas conservam todas elas:
`agitado` continua produzindo animado/ansioso, e `tranquilo`,
calmo/normal. Não foi acrescentada uma regra de desambiguação dessas palavras.

## Alcance explícito da negação

Fora de uma expressão reconhecida, estes tokens iniciam negação:

`não` (normalizado como `nao`), `nem`, `nunca`, `jamais` e `sem`.

A negação suprime as unidades seguintes até a primeira fronteira abaixo
ou até o fim do texto. Não há limite por contagem de palavras.

- Pontuação: vírgula, ponto e vírgula, dois-pontos, ponto, exclamação,
  interrogação, reticências Unicode (`…`), meia-risca (`–`) e travessão (`—`).
- Quebra de linha, inclusive CRLF.
- Palavras de contraste: `mas`, `porém`, `contudo`, `todavia`, `entretanto`.

As fronteiras encerram o alcance e não são atravessadas por compostos.
Entradas do dicionário com palavras de contraste internas não são usadas
como uma unidade nessa versão.

`e` e `ou` **não** encerram o alcance. Outro negador mantém a negação,
sem inverter seu sinal. Não se aplica lógica matemática de dupla negação.
Uma negação posterior não apaga uma ocorrência afirmativa já reconhecida:
`estou triste, mas não estou triste agora` ainda contém `triste`.

Os demais sinais, como aspas, parênteses, barras e hífen ASCII, são
separadores ignorados na tokenização. Por isso `sem-energia` casa como
`sem energia`, e `fora/de/controle` casa como `fora de controle`.
Espaços repetidos e tabulações também não impedem os compostos.

## Ambiguidades e limitações observáveis

Os resultados abaixo demonstram **limites**, não interpretações linguísticas
completas ou garantias de correção. A pessoa deve revisar as categorias.

| Texto | Resultado literal | Limitação |
| --- | --- | --- |
| Não estou triste e ansioso | `[]` | Pode haver ambiguidade sobre o que foi negado; a regra mantém o alcance através de “e” |
| Não só triste, mas cansado | `["cansado"]` | “não só” pode ser ênfase, mas essa construção não tem exceção própria |
| Sem dúvida feliz | `[]` | A locução “sem dúvida” não é distinguida de negação |
| Não li o livro e estou triste | `[]` | Sem análise sintática, a negação pode atingir outro predicado na mesma sequência |
| Deixei de estar triste | `["triste"]` | Negação indireta não é reconhecida |
| Triste, não | `["triste"]` | Negação posterior não desfaz a ocorrência anterior |
| Não estou↵triste | `["triste"]` | A quebra de linha encerra o alcance mesmo quando seria continuação da mesma oração |

Ironia, perguntas retóricas, intenção, fala de terceiros, temporalidade e
variações morfológicas não listadas no dicionário continuam sem tratamento
semântico próprio. Aspas não identificam quem está falando.
As categorias são sugestões para revisão, sem interpretação clínica.

## Lugares examinados e efeito da alteração

| Consumidor | Comportamento nesta rodada |
| --- | --- |
| Relato inicial na CLI e API | Detecção corrigida; texto salvo antes da análise e confirmação ainda pendente |
| Revisão/refinamento na CLI | Continua exigindo uma categoria reconhecida; interrupção conserva relato e UUID |
| Estado desejado | Mesmo analisador local, sem alterar o texto desejado salvo |
| `POST /api/detectar-emocoes` | Mesmo parâmetro query `texto` e resposta `emocoes_detectadas`; continua autenticado |
| Cadastro musical CLI/API | Usa as novas regras para o texto de sensações; ausência de categorias mantém repetição/422 do contrato anterior |
| Importador CSV | Usa as novas regras em `sentimentos_texto`; linhas sem categoria continuam ignoradas com aviso |
| Importador JSON classificado | Mantém os rótulos explícitos recebidos; não reinterpreta textos ou registros antigos |
| Busca de músicas por sentimento | Usa o mesmo retorno do analisador e mantém o fallback literal já existente |

O inicializador de desenvolvimento agora copia o dicionário de referência
rastreado para o diretório temporário, em vez da antiga versão mínima.
Isso torna os compostos disponíveis na API e no terminal fictício. Não
copia catálogos pessoais e não modifica a referência original.

A geração de tags a partir da percepção livre em `main.py` é uma heurística
separada de palavras/tags, não uma chamada deste analisador. Essa heurística,
as inferências musicais legadas e os campos de caracterização não foram
reescritos nesta rodada; não se deve atribuir a eles compreensão geral
de negação.

## Preservação e escopo

A autenticação, a autorização por titular, o isolamento, os contratos HTTP,
UUIDs e salvamento progressivo permanecem. Escolha de nenhuma faixa,
escuta pendente e feedback da experiência continuam distintos.

A fórmula de `core/recomendador.py` não foi alterada. Novas interpretações
podem resultar em outras sugestões depois da revisão, por mudarem os dados
de entrada, sem mudar os pesos ou a ordenação do recomendador.

Não há migração ou reanálise automática dos registros antigos.
Recomendações e análises já confirmadas e persistidas continuam conservadas
na retomada. Etapas ainda pendentes usam as regras atuais quando executadas.

A opção de seguir sem categoria permanece uma etapa separada. Não foram
implementados telas, filtros novos, exportação, exclusão, personalização
ou integração com Spotify.

## Verificação

Resultado final em 04/11/2026: **186 testes aprovados** (154 anteriores e 32 novos)
em Python 3.12.6 no Windows. `pip check` sem conflitos. A execução completa
levou 131,402 segundos, em cópia temporária dos arquivos preparados no índice
Git, sem histórico, catálogo/CSV pessoal, banco de acesso ou ambiente virtual
copiados do projeto. Nenhum teste anterior teve suas expectativas alteradas.

A referência de `ab7639d` foi executada antes da edição: 154 testes aprovados,
com dependências sem conflitos. Os novos testes cobrem os exemplos acima,
fronteiras, sobreposição, sinônimos compartilhados, aliases positivos,
preservação do texto e integração autenticada com API, CLI e importadores.
Todos os relatos, contas e arquivos de escrita usados nos testes são
fictícios e temporários.

```powershell
.\.venv-local\Scripts\python.exe -m pip check
.\.venv-local\Scripts\python.exe -B -m unittest discover -s tests -v
```

Para experimentar, execute `python -m api.desenvolvimento`, cadastre/entre
com conta fictícia e use a documentação em http://127.0.0.1:8000/docs.
O terminal fictício continua em `python desenvolvimento_terminal.py`.
As restrições locais e os limites antes de uso real da
[entrega de autenticação](autenticacao_isolamento.md) continuam aplicáveis.
