# Revisão com a escolha de seguir sem categoria

A revisão permite confirmar as sugestões do analisador, corrigir a
interpretação ou continuar sem atribuir categoria ao estado atual. Essa
escolha não altera o relato original nem significa neutralidade, felicidade,
ausência de sentimentos ou avaliação negativa.

## Estado persistido

| Emoções em `analise.emocoes` | `progresso.emocoes_confirmadas` | Significado |
| --- | --- | --- |
| `[]` | `false` | Revisão pendente |
| `[]` | `true` | Escolha explícita de seguir sem categoria |
| Lista preenchida | `true` | Categorias confirmadas pela pessoa |

O formato da sessão permanece o mesmo. A revisão é salva antes da pergunta
sobre o estado desejado; uma interrupção posterior conserva a escolha, UUID,
criação e texto original. Retomar pede apenas as etapas ainda pendentes.
Não há reanálise ou migração de registros legados. Uma lista vazia antiga
sem o marcador de confirmação não passa a representar escolha explícita.

## Terminal

Na confirmação das categorias sugeridas, responda `sim`, `não` para corrigir
ou `sem categoria`. Essa última opção também aparece no refinamento quando
nenhuma categoria foi detectada ou quando a pessoa rejeita as sugestões.
O comando aceita maiúsculas e espaços nas extremidades.

Um refinamento não reconhecido ou Enter não conclui a revisão: o terminal
oferece nova tentativa ou a escolha explícita. Ctrl+C/fim da entrada conserva
as etapas já salvas. No histórico, uma escolha concluída aparece como
`sem categoria (escolha explícita)`, enquanto uma revisão não concluída
continua `pendentes`.

## API

Em `POST /api/registrar-estado`, omitir `emocoes_confirmadas` ou enviar `null`
mantém a revisão pendente, mesmo quando o analisador não detecta categoria.
Enviar `[]` conclui a revisão por escolha explícita:

```json
{
  "texto_atual": "  Não estou triste.\n",
  "emocoes_confirmadas": [],
  "texto_desejado": "calmo"
}
```

Na resposta, `emocoes_atuais` é `[]` e
`progresso.emocoes_confirmadas` é `true`. `emocoes_confirmadas` deixa de
aparecer em `pendencias`. As sugestões do analisador nunca substituem essa
escolha. `texto_desejado` ausente/null continua pendente; `""` registra
explicitamente a decisão de não definir um desejo.

Uma sessão já criada pode concluir a revisão em `POST /api/retomar-sessao`:

```json
{
  "sessao_id": "11111111-1111-4111-8111-111111111111",
  "emocoes_confirmadas": [],
  "texto_desejado": ""
}
```

Use o UUID real retornado na criação. Na retomada, omissão/null preservam
a revisão atual. Reenviar a mesma escolha é permitido; tentar substituir
categorias já confirmadas por `[]` ou o inverso retorna 409. Recomendações
salvas não são recalculadas. Listas com itens vazios, como `[""]` ou
`[" "]`, continuam resultando em 422. Autenticação e isolamento por conta
continuam obrigatórios nas rotas pessoais.

A retomada continua sem permitir correção de categorias ou desejo depois
de concluídas as recomendações, inclusive quando a lista é vazia; mudanças
retornam 409. A edição dessas etapas é uma melhoria separada.

## Sugestões e limites

Sem categorias atuais, o recomendador pode usar as regras já existentes
para o desejo: `calmo`/`relaxar` usam descompressão, `foco` usa foco cognitivo,
`animado`/`disposto` usam ativação. A explicação informa que as sugestões
usam apenas o estado desejado. Pontuação, ordenação e limite de três faixas
dessas estratégias são preservados.

Sem desejo reconhecido ou com desejo sem estratégia aplicável (como `feliz`
nas regras atuais), não há fallback de espelhamento: `estrategia` fica
`null`, `recomendacoes` fica `[]` e a explicação informa o motivo. A etapa
de recomendação fica concluída (`recomendacoes_geradas=true`), sem criar
escolha musical, confirmação de escuta ou feedback. Isso evita atribuir uma
categoria ao relato para preencher uma lacuna do recomendador.

Os padrões não contam uma emoção artificial para essas sessões. Desejos,
estratégias aplicáveis e feedbacks explicitamente informados continuam
sendo contados segundo seus contratos anteriores.

Essa opção pertence à revisão do relato. O cadastro/importação de músicas
mantém as exigências anteriores de classificação; não há ampliação do
catálogo nem integração externa nesta mudança.

## Verificação

Na raiz do projeto, com Python 3.12 e dependências de desenvolvimento:

```bash
.venv-local/bin/python -m pip check
.venv-local/bin/python -B -m unittest tests.test_sem_categoria -v
.venv-local/bin/python -B -m unittest discover -s tests -v
```

Os testes usam relatos, contas e catálogos fictícios em armazenamento temporário.

Validação em 04/11/2026, Python 3.12 no Linux: **206 testes aprovados**
(186 existentes, com a expectativa de rejeição de `[]` atualizada para o novo
contrato, e 20 novos). `pip check` sem conflitos.
