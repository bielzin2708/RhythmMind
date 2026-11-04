# Caracterização musical opcional — versão 1

Esta estrutura prepara dados e validação. Não fornece um classificador,
não extrai áudio e não altera a pontuação das recomendações.

## Campos encontrados antes da alteração

| Campo legado | Significado no fluxo existente |
| --- | --- |
| `id`, `nome`, `artista`, `duracao` | Identificação e duração em texto |
| `bpm` | Valor digitado/importado; pode estar ausente ou ser `null` |
| `sentimentos_associados` | Categorias recebidas ou extraídas de texto pelo dicionário |
| `percepcao_usuario` | Texto livre opcional da CLI |
| `tags` | Texto/importação ou heurísticas da percepção livre |
| `contextos`, `estrategias` | Categorias recebidas ou calculadas pelas regras existentes |
| `energia`, `valencia`, `intensidade` | Rótulos legados recebidos ou calculados por heurísticas |

O código antigo usa BPM em algumas regras de energia, intensidade e
estratégias. Esses rótulos não são medidas acústicas documentadas nem
anotações humanas com escala. A estrutura nova não copia seus valores para
as observações novas e não modifica essas regras nesta etapa.

O recomendador continua usando `estrategias` e `sentimentos_associados`;
`nome`/`artista` identificam o ajuste já existente. Empates preservam a ordem
do catálogo e o limite padrão continua sendo três faixas. A
[quantidade opcional e os motivos por faixa](escolha_musical_explicada.md)
foram acrescentados em uma rodada posterior, sem mudar essa pontuação.
`core/recomendador.py` não foi alterado.

## Formato

O bloco `caracterizacao` é opcional. Se fornecido como objeto, exige
`versao_estrutura: 1`. Músicas sem o bloco ou com `caracterizacao: null`
continuam aceitas.

Cada grupo é uma lista para conservar observações de fontes, métodos ou
escalas diferentes, inclusive para o mesmo atributo. Elas não são agregadas,
normalizadas nem selecionadas automaticamente.

| Grupo | Atributos aceitos na versão 1 | Representação |
| --- | --- | --- |
| `caracteristicas_acusticas` | `bpm`, `duracao` | Número positivo com unidade `bpm` ou `s` |
| `anotacoes_emocionais` | `valencia`, `ativacao` | Valor na escala declarada |
| `estimativas_sistema` | `bpm`, `valencia`, `ativacao`, `energia`, `intensidade` | BPM com unidade; demais com escala |

Uma medição documentada de tempo pode ficar em características acústicas;
um BPM produzido por estimador fica em estimativas do sistema. Valência e
ativação percebidas são anotações emocionais; uma previsão dessas dimensões
fica em estimativas do sistema. A validação não verifica empiricamente a
origem declarada.

Exemplo de bloco válido, **inteiramente fictício**:

```json
{
  "caracterizacao": {
    "versao_estrutura": 1,
    "caracteristicas_acusticas": [
      {
        "atributo": "duracao",
        "valor": 180,
        "unidade": "s",
        "fonte": "exemplo_ficticio",
        "metodo": "dado_sintetico_sem_medicao",
        "versao": "demo-1"
      }
    ],
    "anotacoes_emocionais": [
      {
        "atributo": "valencia",
        "valor": -0.5,
        "escala": {
          "minimo": -1,
          "maximo": 1,
          "descricao": "Exemplo fictício: desagradável (-1) a agradável (1)"
        },
        "fonte": "anotador_ficticio",
        "metodo": "anotacao_sintetica",
        "versao": "demo-1"
      }
    ],
    "estimativas_sistema": [
      {
        "atributo": "bpm",
        "valor": 155.5,
        "unidade": "bpm",
        "fonte": "estimador_ficticio",
        "metodo": "demonstracao_sem_audio",
        "versao": "demo-1"
      }
    ]
  }
}
```

O BPM alto e a valência negativa coexistem nesse exemplo. Não há regra
nova convertendo BPM alto em alegria, BPM baixo em tristeza ou ativação
percebida em uma medida de energia acústica. Nenhum áudio foi analisado.

`data/musicas_exemplo.json` contém uma faixa com o bloco completo, incluindo
ativação percebida, e outra preservada no formato legado. Todos os valores,
fontes, anotadores e estimadores desses exemplos são fictícios.

## Ausência, escalas e validação

- Grupo omitido representa ausência de observações. A visão preparada usa
  lista vazia; um grupo explicitamente `null` é uma estrutura inválida.
- `valor` ausente ou `null` continua desconhecido. Não recebe zero, unidade,
  escala ou rótulo calculado. Zero explícito é válido quando pertence à
  escala declarada; BPM e duração exigem valor positivo.
- `fonte`, `metodo` e `versao` aceitam texto não vazio ou `null`.
  A visão preparada usa fonte `"desconhecida"` e método/versão `null`
  quando não há essa informação. `versao` identifica o método/fonte da
  observação; `versao_estrutura` identifica o formato do bloco.
- Uma escala numérica exige `minimo < maximo`, limites finitos e valor
  dentro dos limites inclusivos. Nenhuma conversão entre escalas é feita.
- Uma escala categórica usa, por exemplo,
  `{"categorias": ["baixa", "moderada", "alta"]}`. Categorias precisam ser
  únicas e não vazias, e o valor deve pertencer à lista. A ordem é
  conservada, sem inferência de distância entre categorias.
- `descricao` é opcional nas escalas e deve explicar seus significados
  sempre que houver documentação disponível.
- Valores conhecidos exigem unidade ou escala apropriada ao atributo.
  A versão 1 não aceita as duas simultaneamente na mesma observação.
- Booleanos não são números de medida. Strings numéricas, NaN, infinito,
  atributos/grupos/campos não reconhecidos e versões não suportadas são recusados.

A validação nova se aplica somente ao bloco opcional. Não saneia nem
reinterpreta valores antigos. O BPM novo aceita número positivo finito,
inclusive decimal; o cadastro de BPM legado mantém sua regra anterior
de inteiro entre 40 e 220.

## Procedência dos campos antigos

`procedencia_legado` relaciona campos antigos a `fonte`, `metodo` e
`versao`. Sem documentação por registro, por exemplo:

```json
{
  "bpm": {"fonte": "desconhecida", "metodo": null, "versao": null},
  "valencia": {"fonte": "desconhecida", "metodo": null, "versao": null}
}
```

Valores e rótulos antigos continuam nos campos originais. Um comentário
genérico de que um lote foi classificado manualmente não comprova a
procedência de cada registro. Documentação explicitamente fornecida no
bloco é preservada. Não se deduz uma escala para a valência legada.

`obter_caracterizacao(musica)` oferece essa visão em cópia profunda.
Consultar um catálogo antigo não migra nem grava os arquivos.
`preparar_musica(musica)` devolve uma cópia com o bloco e a procedência
explícita; não altera o argumento.

## Integrações

- `salvar_musica_usuario` valida e prepara somente a música nova.
  Registros anteriores permanecem com seus campos e valores originais.
  A função devolve o registro persistido.
- CLI e CSV mantêm suas perguntas/colunas e regras antigas. Não coletam
  novas observações; as listas novas ficam vazias. Os rótulos heurísticos
  antigos não são promovidos a novas anotações documentadas.
- O importador JSON aceita o bloco opcional, valida antes de gravar o lote
  e preserva suas observações. Mantém as regras antigas de preenchimento
  de contextos/estratégias e os avisos sobre divergências legadas.
- `POST /api/musicas` aceita `caracterizacao` opcional junto aos campos
  antigos e devolve o registro preparado. Bloco inválido resulta em 422
  antes da gravação; cadastro antigo continua aceito.
- A leitura do catálogo mantém os registros originais. O utilitário de
  baixo nível `salvar_json` continua genérico; não é um validador de catálogo.
- Feedback e escuta continuam no histórico da sessão. A experiência de
  uma pessoa em uma sessão não vira rótulo global da faixa.

Nenhum arquivo pessoal é migrado. Use exclusivamente os exemplos fictícios
e armazenamento temporário nesta etapa.

## Verificação e limites

Validação em 03/11/2026: **117 testes aprovados** (85 existentes e 32 novos),
Python 3.12.6 no Windows, com `pip check` sem conflitos. A suíte completa foi
executada em cópia temporária dos arquivos do índice Git, sem catálogo/CSV
pessoais, histórico ou ambientes virtuais. Há regressão HTTP com números não
finitos recebidos em JSON bruto: são rejeitados com 422 sem gravar no catálogo.

Os novos testes cobrem catálogo legado, cópias independentes, ausências,
escalas declaradas, procedência, entradas inválidas e integrações com
armazenamento/importadores/API. As regressões do recomendador verificam
resultado conhecido, ordem, empates, limite de três, explicação, estratégias
e ajuste existente com e sem o bloco novo. O feedback da sessão não grava
anotações no catálogo.

```powershell
.\.venv-local\Scripts\python.exe -m pip check
.\.venv-local\Scripts\python.exe -B -m unittest discover -s tests -v
```

A lista de atributos é inicial e explícita. A estrutura valida formatos,
unidades e escalas; não atesta precisão, concordância entre anotadores,
validade psicológica ou desempenho de estimadores. Não há agregação entre
fontes, integração com bases externas, obtenção de áudio ou avaliação de
classificadores. Não depende de atributos do plugin Spotify nem encaminha
conteúdo dessa plataforma a modelos de IA.

Autenticação, autorização por registro e isolamento entre contas continuam
obrigatórios antes de uso real. A API de desenvolvimento continua local,
com dados fictícios descartáveis, conforme o README.
