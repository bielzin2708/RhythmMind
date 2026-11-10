import assert from 'node:assert/strict';
import test from 'node:test';
import { listeningText, feedbackText, historyFilterSummary, historyRecordTitle, historyEntries } from '../../static/history.js';

const complete = overrides => ({
  progresso: { recomendacoes_geradas: true }, recomendacoes: [], ...overrides,
});

test('registros do mesmo segundo colocam a inclusão mais recente primeiro', () => {
  const records = {
    primeiro: { data_hora: '10/11/2026 16:30:00', texto_usuario: 'Primeiro relato fictício' },
    segundo: { data_hora: '10/11/2026 16:30:00', texto_usuario: 'Segundo relato fictício' },
    terceiro: { data_hora: '10/11/2026 16:30:00', texto_usuario: 'Terceiro relato fictício' },
  };
  assert.deepEqual(historyEntries(records).map(([id]) => id), ['terceiro', 'segundo', 'primeiro']);
});

test('data registrada continua prioritária e a ordenação não inventa ou altera datas', () => {
  const records = {
    recente: { data_hora: '11/11/2026 10:00:00' },
    anterior: { data_hora: '10/11/2026 10:00:00' },
    sem_data: { texto_usuario: 'Relato fictício sem data' },
    data_invalida: { data_hora: 'sem data válida' },
  };
  const before = structuredClone(records);
  const result = historyEntries(records);
  assert.deepEqual(result.map(([id]) => id), ['recente', 'anterior', 'data_invalida', 'sem_data']);
  assert.deepEqual(records, before);
  assert.equal(result.find(([id]) => id === 'sem_data')[1].data_hora, undefined);
});

test('registro concluído sem sugestões não apresenta uma escolha pendente', () => {
  assert.equal(listeningText(complete()), 'Nenhuma faixa sugerida nesta sessão');
  assert.equal(listeningText({ recomendacoes: [] }), 'Nenhuma faixa sugerida nesta sessão');
  assert.equal(listeningText(complete({
    progresso: { recomendacoes_geradas: false },
  })), 'Sessão ainda em andamento');
});

test('intenção sem categoria atual pode oferecer faixas e mantém escolha disponível', () => {
  const record = complete({
    analise: { emocoes: [], estado_desejado: ['foco'] },
    recomendacoes: [{ nome: 'Faixa fictícia' }],
  });
  assert.equal(listeningText(record), 'Escolha ainda não registrada');
});

test('decisão explícita de nenhuma faixa e estados de escuta distintos são preservados', () => {
  assert.equal(listeningText(complete({ escuta: { faixas: [] } })), 'Você optou por não escolher uma faixa');
  const text = listeningText(complete({ escuta: { faixas: [
    { ouvida: true }, { ouvida: false }, { ouvida: null },
  ] } }));
  assert.match(text, /1 com escuta informada/);
  assert.match(text, /1 não ouvida/);
  assert.match(text, /escuta não informada em 1/);
});

test('resumo do diário preserva a resposta Não percebi mudança', () => {
  assert.equal(feedbackText({ feedback: { ajudou: false, motivo: 'Não percebi mudança. Relato fictício.' } }), 'Não percebi mudança');
  assert.equal(feedbackText({ feedback: { ajudou: false, motivo: 'A experiência não me ajudou.' } }), 'Sem ajuda relatada');
  assert.equal(feedbackText({ feedback: { ajudou: true } }), 'Ajuda percebida relatada');
  assert.equal(feedbackText({}), 'Retorno opcional não registrado');
  assert.equal(feedbackText({ feedback: { ajudou: false, motivo: null } }), 'Sem ajuda relatada');
});

test('resumo de filtros descreve valores reais sem converter ausência em filtro ativo', () => {
  const query = { data_inicio: '2026-11-10', finalidade: '  Estudar  ', contexto: 'Em casa', avaliacao: 'negativo' };
  const before = structuredClone(query);
  assert.deepEqual(historyFilterSummary(query), [
    'De: 10/11/2026', 'Finalidade: Estudar', 'Contexto: Em casa', 'Retorno: Sem ajuda ou sem mudança',
  ]);
  assert.deepEqual(query, before);
  assert.deepEqual(historyFilterSummary({ finalidade: ' ', avaliacao: '', extra: 'ignorado' }), []);
  assert.deepEqual(historyFilterSummary(), []);
});

test('título prioriza finalidade e depois o relato sem fabricar um nome de experiência', () => {
  assert.equal(historyRecordTitle({ finalidade: '  Uma pausa  ', texto_usuario: 'Relato fictício' }), 'Uma pausa');
  assert.equal(historyRecordTitle({ texto_usuario: '  Meu relato\n  fictício  ' }), 'Meu relato fictício');
  assert.equal(historyRecordTitle({}), 'Relato registrado');
  const long = historyRecordTitle({ texto_usuario: '😌'.repeat(120) });
  assert.equal(Array.from(long).length, 90);
  assert.ok(long.endsWith('…'));
});
