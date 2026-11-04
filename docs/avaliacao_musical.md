# Piloto de preparação de anotações musicais

Esta etapa verifica ingestão, escala e rastreabilidade. Não treina, executa
ou avalia um classificador e não modifica o recomendador. O conjunto está em
[`avaliacao/dados/deam_piloto_v1.json`](../avaliacao/dados/deam_piloto_v1.json).
Ele não é carregado pelo aplicativo nem pelos importadores do catálogo.

## Fonte e significado

Usamos 24 registros do CSV de anotações estáticas DEAM para os recortes
de 2013/2014, que contém 1.744 IDs. O manual distingue essas notas globais,
na escala de 1 a 9, das anotações dinâmicas em outra escala. Mantemos a
escala publicada, sem normalizar ou derivar notas de séries temporais.

| Coluna de origem | Representação no piloto |
| --- | --- |
| `song_id` | `id_fonte` e identificador `deam:<song_id>` |
| `valence_mean` | Anotação emocional `valencia`, escala 1 a 9 |
| `arousal_mean` | Anotação emocional `ativacao`, escala 1 a 9 |
| `valence_std` | `dispersao_publicada.valencia_desvio_padrao` |
| `arousal_std` | `dispersao_publicada.ativacao_desvio_padrao` |

As cinco colunas também ficam preservadas como texto em `colunas_originais`.
O desvio padrão descreve dispersão das notas publicadas; não vira confiança
de um modelo. Médias agregadas não são rótulos individuais de cada anotador.
Um registro refere-se ao recorte anotado, não necessariamente à música inteira.

Não incluímos títulos, artistas, áudio, letras, BPM ou nomes de sentimentos
inferidos. `caracteristicas_acusticas` e `estimativas_sistema` ficam vazias.
Estas são anotações de pesquisa externas, não relatos ou feedback do RhythmMind.
Não representam o efeito de ouvir uma faixa sobre uma pessoa.

Fontes originais:

- [Página DEAM, CVML/Universidade de Genebra](https://cvml.unige.ch/databases/DEAM/).
- [Manual DEAM, incluindo a seção 3](https://cvml.unige.ch/databases/DEAM/manual.pdf).
- Aljanaki, Anna; Yang, Yi-Hsuan; Soleymani, Mohammad (2017).
  *Developing a benchmark for emotional analysis of music*. PLoS ONE 12(3),
  e0173392. [DOI: 10.1371/journal.pone.0173392](https://doi.org/10.1371/journal.pone.0173392).
  Esta é a publicação final; a referência preliminar de 2016 do manual não
  foi reproduzida como se fosse o artigo publicado.

## Download efetivamente usado e termos

O servidor CVML respondeu HTTP 503 durante a verificação. O texto do manual
foi consultado na versão indexada pela busca; não foi possível baixar o PDF
diretamente. O ZIP foi obtido do [registro 11400122 do Zenodo](https://zenodo.org/records/11400122),
um espelho de terceiros, sem atribuir seu depósito aos autores da DEAM.

Existe divergência: a seção 3 do manual declara Creative Commons BY-NC,
sem especificar versão, enquanto a [API desse registro Zenodo](https://zenodo.org/api/records/11400122)
declara `cc-by-4.0`. O piloto mantém uso de pesquisa não comercial e atribuição
aos autores originais. Não foi adotada a declaração mais permissiva do espelho.
A divergência permanece registrada; esta etapa não resolve os termos para
um futuro produto comercial nem concede direitos sobre os áudios.

O MD5 publicado pelo espelho foi conferido no download. Os SHA-256 abaixo
identificam os bytes efetivamente usados; não comprovam igualdade com o
arquivo do servidor original, que permaneceu indisponível.

| Item | Identificação |
| --- | --- |
| ZIP | `DEAM_Annotations.zip`, 4.718.003 bytes |
| MD5 publicado pelo espelho e conferido | `31731747c2a52a3332c17f9dc9a4b1e8` |
| SHA-256 do ZIP | `8aef028d6b3d8592b755ae6aefc61c0f9962dce8af9c6bd231d4dc59d59670fd` |
| Membro do ZIP | `annotations/annotations averaged per song/song_level/static_annotations_averaged_songs_1_2000.csv` |
| SHA-256 do CSV | `b07312724c1add58c09849eeee90c5b53cc54b5e4a97ff3e4f9505d5aa2a1b94` |

Somente o JSON reduzido é versionado. ZIP e áudio não fazem parte do
repositório. Preserve esta atribuição e os termos ao reutilizar o piloto.

## Seleção e reprodução

Para cada ID elegível, calculamos SHA-256 do texto ASCII
`rhythmmind-deam-piloto-v1:<song_id>`, com ID inteiro sem zeros à esquerda.
Selecionamos os 24 menores hashes em ordem lexicográfica e apresentamos
os registros em ordem crescente de ID. As notas não participam da seleção;
não houve estratificação, ajuste de distribuição ou escolha por resultados.

Baixe manualmente o [ZIP do espelho auditado](https://zenodo.org/api/records/11400122/files/DEAM_Annotations.zip/content)
para `avaliacao/cache/DEAM_Annotations.zip` ou outro diretório local. A pasta
`avaliacao/cache/` é ignorada pelo Git. Da raiz do repositório, execute com
o Python do ambiente do projeto:

```powershell
.\.venv-local\Scripts\python.exe -B -m avaliacao.preparar_deam avaliacao/cache/DEAM_Annotations.zip --saida avaliacao/cache/piloto_reproduzido.json
```

Em Linux, o comando equivalente é:

```bash
python -B -m avaliacao.preparar_deam avaliacao/cache/DEAM_Annotations.zip --saida avaliacao/cache/piloto_reproduzido.json
```

O módulo não acessa rede e não extrai arquivos no disco. Confere SHA-256
do ZIP e do CSV, cabeçalho, IDs únicos positivos, quantidade de origem,
números finitos, médias entre 1 e 9 e desvios não negativos. Campo numérico
vazio é erro, nunca zero. Um download diferente exige revisão explícita da
fonte, não atualização automática dos hashes. `--quantidade` permite outro
tamanho positivo até 1.744, mantendo o método documentado.

A saída deve ser um **arquivo novo**. Uma saída existente é recusada, mesmo
que seja o piloto anterior. Para comparar, gere em outro caminho: com os
mesmos bytes de entrada e a quantidade padrão, o JSON é idêntico ao versionado.
O preparador não lê nem grava catálogo, histórico ou dados pessoais.

Os testes do parser e do comando usam arquivos sintéticos temporários e
não dependem do ZIP ou da rede. Há também validação do JSON versionado.

Verificação desta etapa em Python 3.12.14, Linux: **135 testes aprovados**,
sendo 117 anteriores e 18 novos; `pip check` sem conflitos. O comando
completo de testes é `python -B -m unittest discover -s tests -v`. Também
foi feita uma reprodução independente com o ZIP auditado: o JSON produzido
foi idêntico, byte a byte, ao versionado. O código do aplicativo e os três
arquivos de referência em `data/` foram preservados.

## Limites e próximo experimento

Os 24 registros formam um piloto de ingestão, não um conjunto representativo
de gêneros, idiomas ou ouvintes, nem uma divisão de treino/teste. Nenhuma
métrica de previsão ou eficácia foi calculada. Emoção percebida no conteúdo,
objetivo da escuta e retorno de uma sessão continuam conceitos distintos.

Antes de avaliar estimadores, será necessário definir a tarefa, obter
entradas com origem e permissão documentadas e fixar uma divisão por música
antes de ajustar modelos. Se houver segmentos da mesma música, deverão
permanecer na mesma divisão. Para previsão numérica, poderão ser comparados
erro absoluto e RMSE com uma referência simples, sempre na escala declarada.
Essas são decisões para o próximo experimento, não resultados desta etapa.

O catálogo do aplicativo e os testes de sessões continuam fictícios. A
integração com Spotify ou modelos de IA não faz parte deste piloto.
Autenticação, autorização por registro e isolamento entre contas continuam
obrigatórios antes do uso real do aplicativo.
