# Validação do salvamento progressivo

A cópia importada já trazia salvamento progressivo e 70 testes. Esta etapa
corrige perdas durante a edição de respostas e reforça a verificação de
retomada após encerrar o processo Python.

## Comportamento preservado

1. Um relato não vazio recebe UUID e data/hora e é gravado antes da análise.
2. Categorias confirmadas, texto desejado e recomendações são gravados por etapa.
3. A seleção é salva antes das perguntas de escuta; cada resposta é persistida.
4. Cada resposta de feedback é salva antes da pergunta seguinte.
5. A retomada usa a chave exata, conservando UUID, criação, relato e respostas.
   Registros legados continuam acessíveis por suas chaves, sem migração.

Ausência de recomendação não descarta o relato. Escolha/escuta/feedback não
informados continuam pendentes; não viram respostas negativas.
`recomendacoes_geradas=true` com lista vazia indica busca concluída sem
sugestões. `false` indica que essa etapa ainda não terminou.

## Correções desta etapa

- Na opção 8 do terminal, editar a seleção conserva a escuta das faixas
  mantidas até uma nova resposta sim/não. Enter conserva respostas anteriores;
  faixas novas ficam com escuta pendente. Uma seleção explícita continua
  substituindo a lista; `nenhuma` remove todas as faixas escolhidas.
- Na opção 9, responder a uma pergunta de feedback conserva os outros
  detalhes já registrados. Interrupção deixa a coleta parcial. Enter mantém
  valores anteriores disponíveis, e campos adicionais legados são preservados.
  Responder explicitamente que não há melhorias remove o detalhe anterior.
- Na API, se o texto desejado foi salvo mas sua análise falhou, retomar com
  outro texto retorna 409. Omitir o campo ou reenviar o mesmo valor permite
  continuar sem descartar o texto já persistido.
- A opção 10 conserva seu comportamento: pede apenas respostas pendentes.
  O contrato de substituição completa de `POST /api/escuta` foi mantido.

## Verificações

Validação final em 03/11/2026: **85 testes aprovados** (70 recebidos e 15 novos)
em Python 3.12.6, Windows; `pip check` sem conflitos. A suíte completa rodou
em cópia temporária exportada do índice Git, contendo somente os arquivos
publicáveis, sem catálogo/CSV pessoais, histórico ou ambientes virtuais.

Os 70 testes recebidos foram executados e passaram antes do primeiro commit.
Foram adicionadas regressões de edição interrompida, preservação de detalhes
e escuta, conflito no desejo já salvo e retomada com dados anteriores.

Os testes de reinício executam a CLI em processos Python distintos, usando
entrada real e fim da entrada. Todos os arquivos são fictícios e temporários.
Verificam o relato salvo antes da confirmação, retomada pelo mesmo UUID,
preservação de data/hora e legado, escuta/feedback após outro encerramento e
reabertura sem recomendações. Nenhum histórico pessoal é usado.

Para reproduzir na raiz do projeto:

```powershell
.\.venv-local\Scripts\python.exe -m pip check
.\.venv-local\Scripts\python.exe -B -m unittest discover -s tests -v
```

## Limites

A retomada exige o mesmo arquivo JSON. O inicializador
`python -m api.desenvolvimento` continua usando uma base fictícia descartável,
apagada ao encerrar. Reiniciar esse inicializador cria outra base; isso não
é persistência entre execuções do servidor.

A escrita atômica protege o último JSON contra falhas de escrita antes da
substituição. Não cobre múltiplos gravadores concorrentes ou falha do
dispositivo. Não houve publicação de servidor. Autenticação, autorização
por registro e isolamento entre contas continuam obrigatórios antes de uso real.
