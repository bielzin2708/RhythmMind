# RhythmMind — núcleo Python

O núcleo trata feedback ausente no histórico e nos padrões e registra
a escolha e a confirmação de escuta das faixas por sessão. Novas sessões
recebem UUID estável, separado da data/hora, e preservam o relato antes
da análise, com salvamento progressivo e retomada pelo identificador.
Os contratos do analisador e dos cadastros e os arquivos pessoais foram preservados.
Consulte [versionamento](docs/versionamento.md) para preparar um clone com catálogo
fictício e [validação do salvamento](docs/salvamento_progressivo.md) para os ajustes desta etapa.

## Contas e acesso local

A API agora tem cadastro, entrada, identificação e encerramento de acesso.
Senhas usam Argon2id; credenciais expiram e podem ser revogadas no servidor.
Históricos e músicas pessoais ficam separados pelo UUID da conta autenticada,
sem atribuição automática de arquivos legados. Consulte [execução, decisões e
limites](docs/autenticacao_isolamento.md) e a [ordem das próximas rodadas](docs/proximas_etapas.md).

O acesso também oferece **Continuar com Google**, quando as credenciais
OAuth do aplicativo estão configuradas no servidor. O modo opcional
`python -m api.desenvolvimento --persistente` conserva contas e histórico
localmente entre reinicializações; sem a opção, os dados continuam temporários.
Veja o [guia de configuração e teste do login Google](docs/login_google.md).

## Seu espaço na interface web

Depois de entrar, a página **Seu espaço** apresenta as etapas pendentes e os
registros recentes da própria conta. **Começar um relato** inicia uma sessão;
**Sua sessão** permite voltar à etapa aberta. A navegação no topo também oferece
**Meu diário** e **Minhas músicas**. A home reúne a saudação e o início do relato
em um destaque, seguidos de continuidade, registros recentes e acessos rápidos.
As áreas compartilham a identidade do acesso e se adaptam ao celular.

**Sua conta** abre perfil, exportação, preferências visuais, informações sobre
o projeto e saída. **Resumo dos meus registros** expande os indicadores de
sessões, último estado confirmado, escutas informadas e faixas no catálogo.
Nas preferências, a variação sutil dos tons da onda pode ser pausada;
a preferência de movimento reduzido do dispositivo é respeitada.

O botão de sol/lua no cabeçalho alterna entre claro e escuro, inclusive no acesso.
Em **Sua conta → Preferências visuais**, também é possível escolher **Usar o
sistema** e suavizar os brilhos decorativos. Tema, suavização e transição de cores
são controles independentes. O tema e a suavização ficam salvos neste navegador;
somente essas preferências visuais são armazenadas, sem relatos ou credenciais.
Se o armazenamento estiver bloqueado, os controles continuam funcionando na aba.
O escuro usa marinho profundo e acentos azuis dessaturados, com a onda sem halos
luminosos. O claro usa fundo de papel/bege suave, cartões sem branco puro e ações
azuis, mantendo o texto escuro legível.
As [referências e os papéis das cores](docs/temas_visuais.md) documentam essa direção.
No claro, `color-scheme: only light` solicita ao navegador que preserve a paleta
em vez de escurecê-la automaticamente. Esse ajuste não desativa o modo de alto
contraste (`forced-colors`) do dispositivo.
Algumas configurações que forçam Auto Dark mesmo com o sistema claro podem
ignorar essa proteção. Se o tema **Claro** aparecer cinza/preto, confira o filtro
de escurecimento do navegador. A paleta clara da aplicação não usa esses fundos.

O diário mostra os registros primeiro. Filtros e padrões ficam em expansões;
os filtros aplicados continuam indicados mesmo recolhidos. Detalhes, correção,
exportação e exclusão permanecem restritos à própria conta.

Os cartões consultam a API autenticada. Uma escuta não informada, a escolha
de nenhuma faixa e um retorno negativo continuam sendo situações distintas.
O texto ainda não enviado permanece no formulário durante a navegação interna.
Antes de iniciar outro relato, abrir outro registro ou sair, a interface pede
confirmação se isso descartar alterações. O rascunho não é gravado no armazenamento
do navegador; o salvamento no servidor ocorre ao enviar o relato.

Na revisão, as categorias sugeridas aparecem primeiro e as demais podem ser
expandidas por dimensão, sem perder seleções. Registros sem sugestões explicam
a ausência de critério ou de faixas sugeridas, sem criar uma pendência de escuta.
Para verificar as regras e proteções do frontend, execute
`node --test tests/js/*.mjs` (Node.js 24 ou posterior), além da suíte Python
descrita abaixo.

## Negação e expressões compostas

O analisador usa regras locais para negação e reconhece os compostos já
documentados no dicionário. “Não estou triste” não atribui tristeza nem
felicidade; “sem energia” reconhece cansaço. O relato original e a revisão
antes das recomendações continuam preservados.

Veja [alcance, exemplos antes/depois e limitações](docs/negacao_expressoes.md).
As regras não representam compreensão completa da linguagem.

## Revisão e escolha de seguir sem categoria

A pessoa pode confirmar as sugestões, corrigir a interpretação ou escolher
seguir sem categoria para o estado atual. No terminal, digite `sem categoria`
na confirmação ou no refinamento. Na API, envie `"emocoes_confirmadas": []`.
Enter no terminal, detecção vazia ou campo ausente/null na API não escolhem
essa opção automaticamente.

A escolha fica salva antes da pergunta sobre o estado desejado e aparece
explicitamente no histórico. Sem categoria atual, as sugestões usam apenas
as regras disponíveis para o desejo informado. Sem uma estratégia aplicável,
a sessão é salva sem recomendações e com uma explicação; não recebe uma
categoria de neutralidade nem uma estratégia de espelhamento automática.

Veja o [contrato, exemplos e limites](docs/seguir_sem_categoria.md).

## Finalidade, contexto e filtros do histórico

Cada sessão pode incluir uma finalidade (o que a pessoa busca com a escuta)
e um contexto (situação ou atividade), ambos opcionais e sem inferência
automática. No menu do terminal, a opção **1** oferece essas informações
depois de salvar o relato; a opção **11** permite preenchê-las ou editá-las
depois. Cada resposta é salva antes da próxima pergunta.

A opção **12** filtra o histórico por período, finalidade, contexto e retorno
da sessão. Na API, esses filtros estão em `GET /api/historico`; a finalidade
e o contexto podem ser enviados na criação ou em `POST /api/contexto-sessao`.
Os filtros só consultam os registros; não alteram recomendações nem migram
históricos antigos. Veja [formatos e exemplos](docs/finalidade_contexto_historico.md).

## Escolha musical e motivos por faixa

A sessão pode pedir de **1 a 10 sugestões**, mantendo **3** como padrão.
No menu **1**, a quantidade é oferecida antes da revisão; o menu **13**
permite alterá-la enquanto as recomendações ainda estão pendentes. Na API,
use `limite_recomendacoes` na criação ou na retomada antes de recomendar.

Cada faixa nova recebe uma explicação dos critérios usados na seleção,
mostrada no terminal e registrada em `motivos_recomendacoes` na API.
As explicações usam as anotações do catálogo, sem atribuir efeitos emocionais
comprovados às músicas. Listas já salvas mantêm sua ordem, índices e motivos.
Veja [contrato e limites](docs/escolha_musical_explicada.md).

## Catálogo de músicas reais

Em **Minhas músicas → Adicionar seleção ao meu catálogo**, uma requisição copia
a seleção de [96 faixas reais](data/catalogo_referencia.json) para a própria conta.
A prévia tem busca e paginação e mostra títulos, artistas, álbuns conhecidos e
fontes antes da importação. Repetir a ação evita duplicatas e preserva os
cadastros existentes; outras contas continuam com seus próprios catálogos.

As 66 faixas iniciais mantêm associações editoriais provisórias. Outras 30 faixas,
distribuídas entre quatro playlists fornecidas pelo autor, entram com as sensações
pendentes: cada titular pode indicá-las ou alterá-las em **Minhas músicas** antes
que participem das recomendações. BPM, energia, valência e efeitos emocionais não
foram inferidos. Consulte [fontes, limites e contratos](docs/catalogo_referencia.md).

## Caracterização musical opcional

O bloco opcional `caracterizacao` separa características acústicas, anotações
emocionais e estimativas do sistema, com unidade/escala e procedência.
Dados ausentes continuam desconhecidos; os campos antigos são preservados.
O recomendador mantém sua pontuação, ordem e limite padrão de três faixas.

Veja o [formato e as regras de validação](docs/caracterizacao_musical.md)
e os exemplos fictícios em [musicas_exemplo.json](data/musicas_exemplo.json).
A leitura de catálogos antigos não migra os arquivos; novos cadastros e
importações registram a procedência desconhecida quando não documentada.

## Piloto offline de anotações musicais

Há um [piloto DEAM com 24 registros](avaliacao/dados/deam_piloto_v1.json),
separado do catálogo. Ele preserva médias de valência/ativação na escala
original e a procedência do arquivo usado. Não contém áudio nem alimenta
as recomendações. Os exemplos do aplicativo continuam fictícios.

Veja [origem, termos de uso, limitações e reprodução](docs/avaliacao_musical.md).
O preparador usa somente a biblioteca padrão e não faz downloads.

## Ambiente e testes (PowerShell)

Execute na raiz do projeto, na pasta que contém `main.py`. Ambiente verificado nesta máquina: Python 3.12.6 no Windows.
Use `.venv-local` para preservar o ambiente virtual copiado da outra máquina.

```powershell
python -m venv .venv-local
.\.venv-local\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv-local\Scripts\python.exe -m pip check
.\.venv-local\Scripts\python.exe -B -m unittest discover -s tests -v
```

Não é necessário ativar o ambiente. Os testes usam `unittest`, da biblioteca padrão,
e o `TestClient` da API, em memória, sem abrir porta. HTTPX2 é a dependência do
cliente recomendada pela versão instalada do Starlette:
https://starlette.dev/testclient/

## API local com dados fictícios

```powershell
.\.venv-local\Scripts\python.exe -B -m api.desenvolvimento
```

Abra http://127.0.0.1:8000/docs. Use exclusivamente relatos fictícios.
O inicializador cria uma base fictícia em diretório temporário. Contas novas
começam com histórico e catálogo pessoal vazios; cadastre suas próprias faixas
fictícias pela API. Os arquivos globais fictícios do inicializador ficam separados
como legado, sem atribuição a contas. As alterações feitas na API são descartadas
ao encerrar normalmente com Ctrl+C. Nenhum histórico ou catálogo pessoal do
projeto é usado. O dicionário de referência rastreado é copiado para o temporário.
O diretório temporário pode permanecer após encerramento forçado do processo.

O servidor escuta em 127.0.0.1, sem confiar em cabeçalhos de proxy. A API
recusa cliente ou Host externos e retorna 503 fora do diretório de dados
explicitamente autorizado. A antiga inicialização direta com
`uvicorn api.main:app` fica bloqueada nas requisições. Não use reload,
workers, proxy ou publicação na rede nesta fase.

Além da restrição local, as rotas pessoais exigem uma credencial Bearer obtida
em `/api/auth/entrar`, após cadastro em `/api/auth/registrar`. Use Authorize no
Swagger. `/api/auth/eu` identifica a conta e `/api/auth/sair` encerra esse acesso.
Os testes verificam autenticação e isolamento; endurecimento e revisão de
segurança continuam necessários antes de qualquer uso real.

Para a CLI fictícia temporária, execute
`.\.venv-local\Scripts\python.exe -B desenvolvimento_terminal.py`.
Ela é uma ferramenta de desenvolvimento e não autentica nem seleciona perfis.
O comando antigo `main.py` continua atendendo os arquivos legados locais.

## Salvamento progressivo e retomada

Antes desta etapa, o terminal gravava somente depois de toda a coleta de
feedback e retornava sem salvar quando não havia músicas. A API já separava
feedback/escuta, mas só persistia depois da análise e recomendação.

Agora um relato válido é um texto não vazio, independentemente de o
dicionário reconhecer suas palavras. O texto original é preservado exatamente
como recebido, incluindo espaços e quebras de linha. A sessão recebe UUID e
data/hora de criação e é salva **antes de detectar categorias ou recomendar**.

O primeiro salvamento mantém análise confirmada, escolha, escuta e feedback
pendentes. As listas vazias iniciais não significam que a pessoa escolheu
nenhuma categoria ou faixa. Os marcadores em `progresso` distinguem as etapas:

```json
{
  "analise": {"emocoes": [], "estado_desejado": []},
  "texto_desejado": null,
  "estrategia": null,
  "recomendacoes": [],
  "escuta": null,
  "feedback": null,
  "progresso": {
    "emocoes_confirmadas": false,
    "estado_desejado_informado": false,
    "recomendacoes_geradas": false
  }
}
```

Após cada informação fornecida, a mesma sessão é atualizada. UUID, data/hora
de criação e relato original permanecem imutáveis. O estado desejado conserva
o texto informado e sua análise; seu marcador indica que o texto foi informado,
não que categorias inferidas tenham sido confirmadas pela pessoa.

`analise.emocoes=[]` com `progresso.emocoes_confirmadas=true` registra a
escolha explícita de seguir sem categoria. Com o marcador `false`, a revisão
continua pendente. Registros legados sem marcador não recebem essa escolha
automaticamente.

A etapa de recomendação é salva mesmo se o resultado for uma lista vazia.
`recomendacoes_geradas=false` significa pendência; `true` com lista vazia
significa que a busca foi concluída sem sugestões. Isso não cria escolha
de nenhuma faixa nem avaliação negativa. Recomendações já salvas não são
recalculadas na retomada, preservando os índices usados pela escolha/escuta.

### Terminal

A opção **1** informa o ID imediatamente após salvar o relato. Interrupção
por Ctrl+C ou fim da entrada conserva as etapas já gravadas. A opção **10**
retoma pelo UUID ou pela chave legada, sem criar outra sessão.

A escolha é salva antes das perguntas de escuta, com `ouvida=null` nas
faixas cuja escuta ainda não foi informada. Cada sim/não de escuta é salvo antes
da próxima pergunta. Enter mantém a escuta ainda não informada.

Cada resposta do feedback também é salva antes da pergunta seguinte.
`coleta_concluida=false` distingue uma coleta parcial do terminal. Na
retomada, a avaliação sim/não já fornecida e os detalhes já gravados são
preservados; apenas as respostas faltantes são pedidas. Feedback antigo
ou enviado pela API, sem esse marcador, mantém sua compatibilidade.
A avaliação explícita conta nas estatísticas mesmo se seus detalhes
opcionais ainda estiverem pendentes.

As opções **8** e **9** permitem editar escolha/escuta e feedback. Cada
resposta explícita atualiza somente a informação respondida; Enter mantém
valores anteriores, quando disponíveis. Interromper a edição conserva os
detalhes ainda não substituídos. A seleção explícita substitui a lista de
faixas, preservando a escuta das faixas que continuam selecionadas até uma
nova resposta sim/não. A opção **10** continua pedindo apenas dados pendentes.

### Evolução da API

`POST /api/registrar-estado` salva primeiro o relato. Os campos anteriores
da resposta permanecem, acrescidos de `texto_usuario`, `progresso`,
`pendencias` e `emocoes_detectadas`.

Sem `emocoes_confirmadas`, a resposta 200 representa uma sessão salva com
confirmação pendente. As sugestões do analisador aparecem apenas em
`emocoes_detectadas`; não são copiadas para `analise.emocoes` nem para
`emocoes_atuais`. Relatos não reconhecidos também ficam preservados.
Essa evolução substitui a inferência automática de confirmação e o antigo
422 para ausência de categorias reconhecidas. Texto vazio continua inválido.

Envie `emocoes_confirmadas: []` para concluir explicitamente a revisão sem
categoria. Uma lista com itens vazios, como `[""]`, continua inválida. Essa
escolha também pode ser feita na retomada; omissão/null preservam a revisão
atual e não desfazem uma escolha já salva.

`texto_desejado` ausente ou `null` agora significa informação pendente.
Envie `""` explicitamente para continuar sem definir um estado desejado.
A recomendação aguarda a revisão (categorias confirmadas ou escolha explícita
de seguir sem categoria) e essa resposta.
Clientes que antes omitiam o desejo e esperavam recomendações imediatamente
devem enviar `""` para manter esse comportamento.

Use `POST /api/retomar-sessao` para continuar um UUID já salvo:

```json
{
  "sessao_id": "11111111-1111-4111-8111-111111111111",
  "emocoes_confirmadas": ["cansado"],
  "texto_desejado": "calmo"
}
```

Os dois campos de etapa são opcionais. O endpoint também aceita a chave
legada pelas referências já documentadas. Ele nunca cria UUID, altera o
relato original ou reinicia etapas concluídas. Alterações incompatíveis
com categorias/desejo/recomendações já salvos retornam 409. Identificador
inexistente retorna 404. O texto do estado desejado já persistido também é
preservado se sua análise falhar: uma retomada pode omiti-lo ou reenviar o
mesmo texto; outro valor retorna 409. Consultas e registros antigos não são migrados.

`POST /api/escuta` mantém seu contrato. Em `POST /api/feedback`, motivo e
melhoria omitidos preservam os valores anteriores; valores vazios explícitos
ainda podem substituí-los. Uma atualização HTTP não marca automaticamente
como concluídos detalhes pendentes da coleta do terminal.

Falha de armazenamento retorna **503**, com objeto em `detail` contendo
`sessao_id`, `relato_salvo` e `mensagem`. Na primeira gravação,
`relato_salvo=false`; o ID proposto não identifica uma sessão persistida.
Em falhas posteriores, `true` indica que a sessão pode ser consultada e
retomada. Falha de análise/recomendação retorna **500** com o ID já salvo.
O terminal comunica a etapa que falhou, sem anunciar conclusão indevida.
Se o relato já foi salvo, retome esse ID em vez de reenviar a criação.

### Escrita e limites da garantia

O JSON é escrito em arquivo temporário no mesmo diretório. Depois de concluir
a serialização, fechar e sincronizar o arquivo, `os.replace` substitui o
anterior. Falha durante serialização ou antes da substituição preserva o
último arquivo salvo. Antes de gravar sessões, um histórico existente inválido
é recusado; ele não é substituído silenciosamente por um histórico vazio.

Os testes usam somente dados fictícios em armazenamento temporário.
Incluem interrupções após o primeiro salvamento, escolha e feedback;
retomada com o mesmo UUID; releitura por outro processo Python e outro
cliente HTTP; falhas iniciais/posteriores e durante escrita; e preservação
de legado e respostas anteriores. Os 46 testes existentes foram mantidos
sem alterar suas expectativas nesta rodada.

A garantia de releitura/retomada depende do **mesmo arquivo de armazenamento**.
O inicializador `api.desenvolvimento` continua descartável: ao encerrar,
remove a base fictícia; um novo lançamento cria outra. Os testes de
retomada mantêm o mesmo diretório temporário entre os fluxos.

Permanecem fora desta garantia gravações concorrentes de múltiplos processos,
falhas do dispositivo e recuperação de dados sobrescritos anteriormente.
Não houve teste de queda de energia nem publicação de servidor real.
Autenticação, autorização por registro e isolamento entre contas continuam
obrigatórios antes do uso real.

## Semântica da correção

| Valor persistido | Interpretação da consulta | Entra nos resultados? |
| --- | --- | --- |
| `feedback=null`, `{}` ou chave ausente | Retorno ainda não registrado | Não |
| `ajudou=null`, ausente ou não booleano | Sem avaliação válida registrada | Não |
| `{"ajudou": false}` | Retorno negativo da sessão | Sim |
| `{"ajudou": true}` | Retorno positivo da sessão | Sim |

Não existe opção explícita de ficar sem avaliação no modelo atual:
o terminal pede sim/não e a API exige `ajudou: bool`. A correção não inventa
essa decisão para dados ausentes nem altera os registros consultados.
Os valores não booleanos legados são preservados, sem serem contados;
não há saneamento ou migração nesta rodada.

Um retorno negativo indica que as recomendações não fizeram sentido;
não permite concluir que houve piora emocional. Nem o retorno positivo
comprova melhora clínica ou efeito de uma faixa.

Os resultados são contados **por sessão**. Mesmo quando escolha e escuta
são registradas, não há avaliação individual das faixas. Por isso os rankings
de músicas aprovadas/reprovadas foram retirados. As faixas continuam visíveis como sugestões no histórico.
As frequências de emoções, desejos e estratégias descrevem todas as sessões,
inclusive as ainda sem retorno; não são medidas de eficácia.

Exemplo: quatro sessões com `null`, `{}`, `false` e `true` produzem
**2 sessões avaliadas de 4**, 1 retorno positivo, 1 negativo e 2 ainda não
registrados. Não há porcentagem calculada sobre todas as sessões.

## Identificação estável das sessões

Antes, a chave do histórico era a data/hora com precisão de segundos.
Duas criações no mesmo segundo usavam a mesma chave e a segunda substituía
a primeira. Agora terminal e API usam `core.sessoes.criar_sessao`, que gera
`str(uuid.uuid4())` **uma única vez na criação**. A biblioteca `uuid` faz
parte do Python; nenhuma dependência nova foi necessária.

Cada sessão nova contém `sessao_id` e `data_hora`, e é salva sob a chave
igual a `sessao_id`. A data/hora permanece no formato anterior, apenas
como informação descritiva. Por exemplo (identificadores fictícios):

| Criação | Chave anterior | Nova chave | Data/hora preservada |
| --- | --- | --- | --- |
| A | `01/01/2000 10:00:00` | `11111111-1111-4111-8111-111111111111` | `01/01/2000 10:00:00` |
| B | `01/01/2000 10:00:00` | `22222222-2222-4222-8222-222222222222` | `01/01/2000 10:00:00` |

A releitura e as atualizações reutilizam a chave salva e não geram UUID.
Não há migração nesta rodada: registros legados continuam sob suas chaves
originais, sem acrescentar `sessao_id` ao registro bruto. Um histórico pode
conter chaves UUID e legadas ao mesmo tempo.

Todas as buscas são pela **chave exata**. Nunca é feita uma busca pelo valor
descritivo de `data_hora`. Se houver uma chave legada igual à data de duas
sessões novas, essa chave continua identificando somente o registro legado.

### Terminal

A criação informa o ID salvo. O histórico mostra ID/chave legada e data/hora
separadamente. Na opção **4**, informe o identificador para ver uma sessão,
ou Enter para ver todas. A opção **8** atualiza escolha/escuta e a nova opção
**9** atualiza feedback da sessão indicada. Ambas aceitam UUID ou chave
legada exata. A opção **7** continua encerrando o programa.

### API

`POST /api/registrar-estado` retorna `sessao_id` além de `data_hora`.
Clientes devem guardar e reutilizar o `sessao_id` retornado.

`POST /api/feedback` e `POST /api/escuta` passam a aceitar `sessao_id`:

```json
{
  "sessao_id": "11111111-1111-4111-8111-111111111111",
  "ajudou": true,
  "motivo": "Exemplo fictício"
}
```

Para compatibilidade, o campo antigo `data_hora` permanece como alias da
chave persistida, destinado aos clientes legados. Não é um filtro por data.
O campo `sessao_id` também aceita diretamente uma chave legada. Informe
exatamente um valor não nulo entre `sessao_id` e `data_hora`: nenhum,
ambos ou uma referência vazia resultam em 422 sem gravar. Enviar o outro
campo com `null` conta como apenas uma referência. Identificador inexistente
retorna 404. Use `sessao_id` para novas integrações.

A consulta individual é `GET /api/historico/sessao?sessao_id=...`.
O parâmetro aceita UUID ou chave legada, inclusive datas com barras, pois
é enviado na query. A resposta é `{"sessao_id": "<chave>", "registro": {...}}`.
Para legado, o identificador do envelope é a chave original; o registro
bruto não é alterado. `GET /api/historico` continua retornando o mapa
completo, agora com chaves UUID para novas sessões e chaves antigas para
legadas. Escolha, escuta e feedback permanecem independentes.

### Verificação e limites

Os testes congelam o relógio na mesma data/hora e criam sessões no terminal,
na API e entre as duas interfaces. Verificam UUIDv4, uma geração por criação,
releitura estável, atualização isolada de feedback/escuta, IDs inexistentes,
referências inválidas e convivência com legado. Os dois testes anteriores
que usavam a data de uma sessão nova como chave passam a usar `sessao_id`;
suas verificações de feedback e escuta foram mantidas.

UUID elimina a colisão de chaves por segundo. Não resolve gravações JSON
concorrentes nem falhas do dispositivo e não recupera registros
que já tenham sido sobrescritos antes desta mudança. Não substitui
autenticação, autorização por registro ou isolamento entre contas.

## Escolha e confirmação de escuta por sessão

Na API, novas sessões começam com `escuta=null`. No terminal, a informação
pode ser preenchida no cadastro ou adiada com Enter. Nos registros antigos,
o campo ausente continua ausente: as consultas não reescrevem o arquivo.

| Informação | Significado |
| --- | --- |
| `escuta` ausente ou `null` | Escolha e escuta ainda não informadas |
| `{"faixas": []}` | Pessoa informou que não escolheu nenhuma sugestão |
| Faixa com `ouvida=null` ou omitida no envio | Escolhida; escuta ainda não informada |
| Faixa com `ouvida=false` | Pessoa informou que não ouviu |
| Faixa com `ouvida=true` | Pessoa confirmou escuta por autodeclaração |

Cada `indice_recomendacao` começa em 1 e referencia a lista de sugestões
salva na própria sessão. Não é o ID global do catálogo. Essa referência
permite usar o histórico existente sem migrar músicas ou armazenamento.

No terminal, após as sugestões, informe números separados por vírgula,
`nenhuma` para uma escolha explícita de nenhuma sugestão, ou Enter para
informar depois. Para cada escolhida, responda sim/não/Enter à pergunta
de escuta. A opção **8** permite registrar ou corrigir esses dados de uma
sessão existente; **7** continua encerrando o programa. Enter na pergunta
de quais faixas foram escolhidas cancela a atualização sem gravar. Ao
informar as faixas, a seleção substitui a lista anterior. A escuta das faixas
mantidas é conservada; Enter mantém seu sim/não anterior. Faixas novas começam
com `ouvida=null`, e Enter conserva essa pendência. Uma nova resposta sim/não
substitui apenas a escuta daquela faixa. Esse comportamento da opção **8**
difere do envio HTTP completo documentado abaixo.

A nova rota `POST /api/escuta` recebe:

```json
{
  "sessao_id": "11111111-1111-4111-8111-111111111111",
  "faixas": [
    {"indice_recomendacao": 1, "ouvida": true},
    {"indice_recomendacao": 2, "ouvida": null}
  ]
}
```

Use o `sessao_id` real retornado por `POST /api/registrar-estado`
no ambiente fictício. A resposta contém `status` e o objeto `escuta` salvo.
A lista `faixas` é obrigatória: ausência ou `null` resulta em 422; apenas
`[]` representa a decisão explícita de não escolher nenhuma sugestão.

O envio substitui **toda** a escolha/escuta anterior daquela sessão.
Não modifica as sugestões, o feedback nem outras sessões. Índices repetidos,
fora da lista, não inteiros e valores de escuta diferentes de booleano/null
são recusados com 422 sem gravar. Campos desconhecidos também são recusados.
Sessão inexistente retorna 404. O histórico HTTP preserva o objeto salvo.

Escolha, escuta e avaliação são informações independentes. Informar que
nenhuma faixa foi escolhida não cria feedback negativo; confirmar escuta
não cria feedback positivo. Enviar feedback não preenche escolha ou escuta.
O histórico do terminal mostra a escuta informada para cada escolhida.
Os padrões continuam usando somente o feedback da sessão, sem resultado
individual por faixa ou novas medidas de eficácia.

## Contrato das consultas HTTP

`GET /api/historico` preserva `total` e `registros` (incluindo feedback
bruto) e acrescenta `avaliacoes_sessoes`, `limitacao_resultados_por_faixa`
e `interpretacao_retornos`.

`GET /api/padroes` preserva as frequências e a síntese descritiva, acrescenta
os mesmos campos e **remove** `musicas_aprovadas` e `musicas_reprovadas`.
Consumidores desses dois campos precisam ser ajustados. Um histórico vazio
também retorna o resumo com zeros, sem inferir resultado.

```json
{
  "avaliacoes_sessoes": {
    "sessoes_totais": 4,
    "sessoes_avaliadas": 2,
    "retornos_positivos": 1,
    "retornos_negativos": 1,
    "retornos_nao_registrados": 2
  }
}
```

## Escopo e próximos passos

Os testes cobrem a matriz de feedback no terminal e nas rotas HTTP, mistura
de sessões, consultas sem gravar alterações, ciclo registrar/consultar/avaliar,
ausência de atribuição por faixa e as restrições locais. Todos os dados de
teste são inventados e gravados em diretórios temporários.

Os testes de escolha/escuta cobrem legado sem informação, escolha explícita
de nenhuma faixa, escuta sim/não/não informada, validação sem gravação,
atualização pelo terminal e pela API, independência do feedback e proteção local.

A criação com UUID e o acesso por identificação legada foram implementados
sem migrar os arquivos existentes ou modificar a caracterização musical.

A base de autenticação e isolamento está descrita em
[contas e acesso](docs/autenticacao_isolamento.md). Migração automática de legados,
concorrência de escrita no mesmo JSON, validação completa de registros antigos
e revisão do analisador emocional permanecem fora desta entrega.
