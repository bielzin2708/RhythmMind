# Escolha musical e motivos das sugestões

A pessoa pode escolher a quantidade máxima de sugestões da sessão, entre
1 e 10, com padrão 3. O catálogo pessoal e os critérios atuais continuam
sendo a fonte das faixas: a ampliação não inventa músicas nem completa
atributos ausentes. Se houver menos candidatas com pontuação positiva,
o sistema devolve apenas as que encontrou.

## Terminal

O menu **1** salva o relato e os metadados opcionais, depois pergunta a
quantidade de sugestões antes da revisão emocional. Enter mantém três;
valores fora de 1 a 10 são recusados. A quantidade é salva antes de avançar,
e uma interrupção conserva as respostas anteriores.

O menu **13** permite alterar a quantidade de uma sessão ainda pendente.
Depois que a lista foi salva, aumentar ou diminuir a quantidade não pode
substituir as sugestões existentes. Para outra busca, crie uma nova sessão.
A retomada usa a quantidade salva, sem perguntar novamente por ela.

Os motivos por faixa aparecem ao mostrar as recomendações, na opção de
escolha/escuta e no histórico. Os números usados na escolha continuam
referindo-se à posição na lista salva, inclusive posições acima de três.
Escolha, confirmação de escuta e retorno continuam independentes.

Chamadas Python existentes de `opcao_registar_estado()` mantêm a sequência
anterior de perguntas. Elas podem fornecer `limite_recomendacoes` como
argumento; o menu interativo oferece a pergunta de quantidade.

## API

Na criação, `POST /api/registrar-estado` aceita, por exemplo:

```json
{
  "texto_atual": "Relato fictício: estou cansado.",
  "emocoes_confirmadas": ["cansado"],
  "texto_desejado": "calmo",
  "limite_recomendacoes": 5
}
```

O campo é um inteiro estrito de 1 a 10. Ausência usa 3; `null`, booleanos,
strings, decimais ou valores fora desse intervalo retornam 422 antes de
salvar o relato. As demais regras de criação e salvamento progressivo
permanecem.

Na retomada, `POST /api/retomar-sessao` aceita a quantidade junto do UUID:

```json
{
  "sessao_id": "11111111-1111-4111-8111-111111111111",
  "limite_recomendacoes": 5
}
```

Use o UUID real da sessão. Aqui, ausência ou `null` preservam a quantidade.
Uma mudança só é permitida antes de concluir as recomendações; o valor é
salvo antes da análise/seleção, para permitir retomar após falha.
Depois da geração, reenviar o mesmo valor é permitido; outro valor retorna
409, sem alterar a sessão, inclusive quando a lista de músicas está vazia.

As respostas de estado expõem `limite_recomendacoes` e
`motivos_recomendacoes`. O segundo é uma lista alinhada à lista de músicas
pelo campo `indice_recomendacao`, começando em 1. Cada elemento contém:

- `pontuacao`: soma dos componentes usados na ordenação.
- `criterios`: componentes com `tipo`, `valor` quando aplicável, e `pontos`.
- `explicacao`: descrição em texto dos componentes observados.

As músicas em `recomendacoes` mantêm seus campos originais; as explicações
não são acrescentadas ao catálogo nem aos objetos de música. Consultas e
retomadas devolvem os motivos que foram salvos com a sessão.

## Critérios e interpretação

A mesma função calcula os componentes para ordenar e explicar:

| Critério | Pontos |
| --- | --- |
| Estratégia da sessão presente no cadastro da faixa | 3 |
| Categoria atual confirmada presente nas anotações da faixa | 2 por ocorrência |
| Categoria intermediária da regra de transição presente no cadastro | 2 por categoria |
| Estratégia intermediária de ativação gradual, na transição | 2 |
| Ajuste explicitamente fornecido pela chamada Python | Valor recebido |

Empates mantêm a ordem do catálogo. O aumento do limite conserva o prefixo
da ordenação anterior. A quantidade padrão, os pesos, as regras de escolha
de estratégia e as restrições de seguir sem categoria permanecem.
Os motivos não usam título, artista, BPM ou caracterização acústica para
inferir emoções. Relatam associações cadastradas e critérios locais.

A pontuação não é probabilidade, confiança estatística ou medida clínica;
não demonstra eficácia de uma faixa. Anotações do catálogo podem ter
procedência desconhecida, conforme a caracterização musical existente.
Não há novo aprendizado nem leitura automática de feedback para ajustar
o ranking. O parâmetro Python de ajuste anterior continua disponível,
explicitamente identificado nos motivos quando contribui com valor não zero.

Sem categoria atual, sugestões baseadas no desejo não recebem motivos
de correspondência com uma emoção atual. Sem estratégia aplicável, lista
de músicas e motivos ficam vazias. Sem dados suficientes para justificar
um componente, a explicação não inventa uma associação.

## Persistência e legado

Músicas, motivos, estratégia, quantidade e conclusão da etapa são salvos
juntos na mesma atualização atômica. Se a explicação ou a escrita falhar,
a etapa permanece pendente e conserva as respostas já gravadas. Use o ID
retornado no erro para retomar, sem criar outra sessão.

Um registro legado sem motivos permanece sem eles; a API expõe `null`
quando o campo não existe. Não há explicação retroativa com o catálogo
atual. Uma lista vazia numa etapa concluída sem faixas representa a busca
concluída sem sugestões, e não um erro de explicação.

Uma quantidade ausente no legado não é inferida como uma escolha da pessoa.
Sessões antigas já concluídas não aceitam mudar a quantidade; sessões
antigas ainda pendentes usam o padrão três se não houver uma quantidade
salva. Os demais campos, UUID, data/hora, relato, escuta e feedback são
preservados. Autenticação, isolamento por conta e restrição local continuam
valendo para as rotas pessoais.

## Verificação

Os testes usam dados fictícios em diretórios temporários:

```bash
.venv-local/bin/python -m pip check
.venv-local/bin/python -B -m unittest tests.test_recomendacoes_motivos tests.test_escolha_musical_api tests.test_escolha_musical_cli -v
.venv-local/bin/python -B -m unittest discover -s tests -v
```

Validação em 04/11/2026, Python 3.12 no Linux: **293 testes aprovados**
(250 anteriores e 43 novos), `pip check` sem conflitos. Os testes anteriores
de coleta completa receberam apenas o Enter da nova pergunta de quantidade,
preservando suas verificações. Os novos testes cobrem pontuação e motivos,
limites estritos, seleção além da terceira faixa, falhas de escrita/explicação,
retomada, índices estáveis, ausência de migração e isolamento por conta.
