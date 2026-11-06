import assert from 'node:assert/strict';
import test from 'node:test';
import { recordsForHome, sessionPending } from '../../static/home.js';

const complete = () => ({
  progresso: { emocoes_confirmadas: true, estado_desejado_informado: true, recomendacoes_geradas: true },
  recomendacoes: [{ nome: 'Faixa fictícia' }],
  escuta: { faixas: [{ indice_recomendacao: 1, ouvida: true }] },
  feedback: { ajudou: true },
});

test('retoma a primeira etapa ainda não salva sem confundir categorias vazias com revisão pendente', () => {
  const record = complete();
  record.analise = { emocoes: [] };
  assert.equal(sessionPending(record), null);
  record.progresso.recomendacoes_geradas = false;
  assert.equal(sessionPending(record).kind, 'sugestoes');
  record.progresso.estado_desejado_informado = false;
  assert.equal(sessionPending(record).kind, 'intencao');
  record.progresso.emocoes_confirmadas = false;
  assert.equal(sessionPending(record).kind, 'revisao');
});

test('distingue escolha ausente, nenhuma faixa explícita, escuta não informada e escuta negativa', () => {
  const record = complete();
  record.escuta = null;
  assert.equal(sessionPending(record).kind, 'escuta');
  record.escuta = { faixas: [] };
  assert.equal(sessionPending(record), null);
  record.escuta.faixas = [{ indice_recomendacao: 1, ouvida: null }];
  assert.equal(sessionPending(record).kind, 'escuta');
  record.escuta.faixas[0].ouvida = false;
  assert.equal(sessionPending(record), null);
});

test('retorno negativo é resposta; retorno ausente ou coleta parcial continua opcional', () => {
  const record = complete();
  record.feedback.ajudou = false;
  assert.equal(sessionPending(record), null);
  record.feedback.coleta_concluida = false;
  assert.equal(sessionPending(record).kind, 'retorno');
  for (const feedback of [null, {}, { ajudou: null }, { ajudou: 'false' }]) {
    record.feedback = feedback;
    assert.equal(sessionPending(record).kind, 'retorno');
  }
});

test('sessão sem sugestões não cria pendência de escuta ou retorno, inclusive em legados', () => {
  const record = complete();
  record.recomendacoes = [];
  record.escuta = null;
  record.feedback = null;
  assert.equal(sessionPending(record), null);
  delete record.progresso;
  assert.equal(sessionPending(record), null);
  record.recomendacoes = [{ nome: 'Faixa fictícia legada' }];
  assert.equal(sessionPending(record).kind, 'escuta');
});

test('datas locais e ISO são ordenadas pelo instante e datas inválidas ficam ao final', () => {
  const records = {
    setembro: { ...complete(), data_hora: '30/09/2026 23:00:00' },
    dezembro: { ...complete(), data_hora: '01/12/2026 10:00:00' },
    novembro: { ...complete(), data_hora: new Date(2026, 10, 6, 19).toISOString() },
    invalida: { ...complete(), data_hora: '31/02/2026 10:00:00' },
  };
  const before = structuredClone(records);
  const result = recordsForHome(records);
  assert.deepEqual(result.recent.map(item => item.id), ['dezembro', 'novembro', 'setembro', 'invalida']);
  assert.equal(result.recent[3].date, 'Data não informada');
  assert.equal(recordsForHome({ invalida: { data_hora: '2026-02-31T12:00:00Z' } }).recent[0].date, 'Data não informada');
  assert.deepEqual(records, before);
});

test('usa a chave de data legada somente quando ela contém uma data válida', () => {
  const records = {
    '01/11/2026 09:00:00': { ...complete() },
    'uuid-sem-data': { ...complete() },
  };
  const result = recordsForHome(records);
  assert.equal(result.recent[0].date, '01/11/2026 09:00:00');
  assert.equal(result.recent[1].date, 'Data não informada');
});

test('limita recentes e pendências independentemente, incluindo uma pendência mais antiga', () => {
  const records = {};
  for (let day = 1; day <= 8; day += 1) {
    records[`sessao-${day}`] = { ...complete(), data_hora: `0${day}/11/2026 10:00:00` };
    if (day <= 4) records[`sessao-${day}`].feedback = null;
  }
  const result = recordsForHome(records);
  assert.deepEqual(result.recent.map(item => item.id), ['sessao-8', 'sessao-7', 'sessao-6', 'sessao-5']);
  assert.deepEqual(result.pending.map(item => item.id), ['sessao-4', 'sessao-3', 'sessao-2']);
});

test('títulos usam dados reais com resumo de até 80 caracteres e preservam Unicode', () => {
  const result = recordsForHome({
    finalidade: { ...complete(), finalidade: '  Estudar  ', texto_usuario: 'Relato fictício' },
    texto: { ...complete(), texto_usuario: `  ${'😌'.repeat(120)}  ` },
    vazio: { ...complete(), texto_usuario: '   ' },
  });
  assert.equal(result.recent[0].title, 'Estudar');
  assert.equal(Array.from(result.recent[1].title).length, 80);
  assert.ok(result.recent[1].title.endsWith('…'));
  assert.equal(result.recent[2].title, 'Sessão de escuta');
});

test('histórico vazio é distinto de uma estrutura inválida', () => {
  assert.deepEqual(recordsForHome({}), { pending: [], recent: [] });
  for (const invalid of [null, [], 'registros inválidos', { quebrado: null }]) {
    assert.throws(() => recordsForHome(invalid), TypeError);
  }
});
