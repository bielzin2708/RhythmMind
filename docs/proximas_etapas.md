# Próximas rodadas

A base de contas, autenticação e isolamento está preservada. A interpretação
usa [negação e expressões compostas por regras locais](negacao_expressoes.md),
com limitações documentadas. A revisão agora permite a
[escolha explícita de seguir sem categoria](seguir_sem_categoria.md).
A sessão agora também aceita
[finalidade, contexto e filtros do histórico](finalidade_contexto_historico.md).
A próxima etapa é ampliar a escolha musical e explicar o motivo das sugestões.
O fluxo aprovado permanece:

**Relato e finalidade → Revisar interpretação → Escolha musical → Retorno após a escuta → Histórico.**

A ordem das melhorias posteriores é:

1. Melhorar a interpretação do relato, incluindo negação: base lexical local entregue; limitações documentadas.
2. Permitir revisão com a opção de seguir sem categoria: entregue na CLI e API.
3. Completar finalidade, contexto e filtros do histórico: entregue na CLI e API.
4. Ampliar a escolha musical e explicar o motivo das sugestões.
5. Implementar a decisão explícita “sem avaliação”.
6. Completar correção, exportação e exclusão dos registros.
7. Avaliar personalização com evidências.

As etapas 4 a 7 continuam separadas; não foram implementadas nesta rodada.

## Ampliação via Spotify em rodada separada

Quando essa atividade começar, conferir quais ferramentas do plugin e
campos estão realmente disponíveis no ambiente em uso. A presença do
plugin em uma conversa não implica disponibilidade no VS Code.

Preservar identificadores, links e procedência quando fornecidos.
Não inventar BPM, valência, ativação ou outros atributos ausentes; não
deduzir sentimentos pelo título, artista ou BPM. Sem fonte documentada,
as anotações emocionais permanecem pendentes.

Candidatos sem classificação devem ficar separados das músicas prontas
para recomendar. Não encaminhar conteúdo do Spotify a modelos de IA nem
usá-lo para treinamento. Esta entrega apenas registra essa atividade;
não consulta o plugin, não obtém faixas e não altera o catálogo por ele.

Autenticação, autorização e isolamento continuam sendo condições
obrigatórias, com dados fictícios durante o desenvolvimento.
