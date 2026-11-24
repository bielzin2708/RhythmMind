import assert from 'node:assert/strict';
import test from 'node:test';
import { initHome, recordsForHome, sessionPending, summarizeHome, catalogTotal } from '../../static/home.js';

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

test('sessões criadas no mesmo segundo usam a inclusão mais recente para desempatar', () => {
  const records = {
    anterior: { ...complete(), data_hora: '09/11/2026 20:00:00', finalidade: 'Primeira', analise: { emocoes: ['calmo'] } },
    recente: { ...complete(), data_hora: '09/11/2026 20:00:00', finalidade: 'Segunda', analise: { emocoes: ['cansado'] } },
  };
  assert.deepEqual(recordsForHome(records).recent.map(item => item.id), ['recente', 'anterior']);
  assert.equal(summarizeHome(records).lastPurpose, 'Segunda');
  assert.equal(summarizeHome(records).lastState, 'Cansado');
});

test('indicadores vazios mostram zero e não inventam um estado confirmado', () => {
  assert.deepEqual(summarizeHome({}), {
    totalSessions: 0, totalListens: 0, lastPurpose: 'Não informado',
    lastState: 'Não informado', lastStateDate: '—', lastStateCategories: [],
  });
});

test('último estado usa confirmação humana e ignora a sugestão de uma sessão mais recente', () => {
  const records = {
    anterior: { ...complete(), data_hora: '01/11/2026 10:00:00', analise: { emocoes: ['calmo'] } },
    recente: {
      ...complete(), data_hora: '02/11/2026 10:00:00',
      progresso: { emocoes_confirmadas: false, recomendacoes_geradas: false },
      analise: { emocoes: ['triste'], estado_desejado: ['foco'] },
      interpretacao: { proposta: { estado_atual: { sugestoes: [{ categoria: 'triste' }] } } },
    },
  };
  const result = summarizeHome(records);
  assert.equal(result.totalSessions, 2);
  assert.equal(result.lastState, 'Calmo');
  assert.equal(result.lastStateDate, '01/11/2026 10:00:00');
  assert.deepEqual(result.lastStateCategories, ['calmo']);
});

test('seguir sem categoria é uma confirmação explícita; lista legada vazia não basta', () => {
  const records = {
    anterior: { ...complete(), data_hora: '01/11/2026 10:00:00', analise: { emocoes: ['triste'] } },
    recente: { ...complete(), data_hora: '02/11/2026 10:00:00', analise: { emocoes: [] } },
  };
  assert.equal(summarizeHome(records).lastState, 'Sem categoria');
  delete records.recente.progresso;
  assert.equal(summarizeHome(records).lastState, 'Triste');
});

test('legados só apresentam categorias conhecidas, sem transformar intenções em estado atual', () => {
  const records = {
    legado: { data_hora: '01/11/2026 10:00:00', analise: { emocoes: ['cansado'] } },
    invalido: { ...complete(), data_hora: '03/11/2026 10:00:00', analise: { emocoes: ['diagnostico_inventado'] } },
    intencao: { ...complete(), data_hora: '02/11/2026 10:00:00', analise: { estado_desejado: ['calmo'] } },
  };
  assert.equal(summarizeHome(records).lastState, 'Cansado');
  assert.equal(summarizeHome({ invalido: records.invalido, intencao: records.intencao }).lastState, 'Não informado');
});

test('sentimentos coexistentes são preservados, com resumo curto e sem duplicatas', () => {
  const record = { ...complete(), analise: { emocoes: ['calmo', 'reflexivo', 'amor', 'calmo'] } };
  const result = summarizeHome({ sessao: record });
  assert.equal(result.lastState, 'Calmo, Reflexivo +1');
  assert.deepEqual(result.lastStateCategories, ['calmo', 'reflexivo', 'amor']);
  assert.equal(result.lastStateDate, 'Data não informada');
});

test('escutas contam ocorrências informadas como true, inclusive a mesma faixa em duas sessões', () => {
  const records = {
    primeira: { ...complete(), escuta: { faixas: [
      { indice_recomendacao: 1, ouvida: true }, { indice_recomendacao: 2, ouvida: false },
      { indice_recomendacao: 3, ouvida: null }, { indice_recomendacao: 4, ouvida: 'true' }, null,
    ] } },
    segunda: { ...complete(), escuta: { faixas: [{ indice_recomendacao: 1, ouvida: true }] } },
    nenhuma: { ...complete(), escuta: { faixas: [] } },
    ausente: { ...complete(), escuta: null },
  };
  assert.equal(summarizeHome(records).totalListens, 2);
  assert.equal(summarizeHome(records).totalSessions, 4);
});

test('última finalidade usa a mais recente que foi informada e não assume gênero ou emoção', () => {
  const records = {
    primeira: { ...complete(), data_hora: '01/11/2026 10:00:00', finalidade: 'Treinar' },
    segunda: { ...complete(), data_hora: '02/11/2026 10:00:00', finalidade: '  Estudar  ' },
    terceira: { ...complete(), data_hora: '03/11/2026 10:00:00', finalidade: null, analise: { emocoes: ['calmo'] } },
  };
  const before = structuredClone(records);
  assert.equal(summarizeHome(records).lastPurpose, 'Estudar');
  assert.deepEqual(records, before);
});

test('catálogo usa total válido e distingue ausência de dados de catálogo vazio', () => {
  assert.equal(catalogTotal({ total: 0, musicas: [] }), 0);
  assert.equal(catalogTotal({ total: 18, musicas: [] }), 18);
  assert.equal(catalogTotal({ musicas: [{ nome: 'Uma faixa fictícia' }] }), 1);
  for (const total of [null, '18', -1, NaN, Infinity, 1.5]) {
    assert.equal(catalogTotal({ total, musicas: [{ nome: 'Uma faixa fictícia' }] }), 1);
  }
  for (const invalid of [null, [], {}, { total: '18' }, { total: -1 }, { musicas: null }]) {
    assert.throws(() => catalogTotal(invalid), TypeError);
  }
});

test('initHome destaca ações de navegação com nav-destination e seta decorativa', async t => {
  const prev = { document: globalThis.document, Node: globalThis.Node };
  const elements = new Map();
  class MockNode {
    constructor(tag = '', text = '') {
      this.tagName = tag.toUpperCase();
      this.children = [];
      this.attributes = {};
      this.dataset = {};
      this.listeners = new Map();
      this.className = '';
      this.hidden = false;
      this._text = text;
    }
    set textContent(value) { this._text = String(value); this.children = []; }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = []; this._text = ''; this.append(...children); }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    removeAttribute(name) { delete this.attributes[name]; }
    addEventListener(type, fn) { this.listeners.set(type, fn); }
  }
  const byId = id => {
    if (!elements.has(id)) {
      const el = new MockNode('div');
      el.id = id;
      elements.set(id, el);
    }
    return elements.get(id);
  };
  globalThis.Node = MockNode;
  globalThis.document = {
    createElement: tag => new MockNode(tag),
    createTextNode: text => new MockNode('', text),
    querySelector: sel => byId(sel.replace(/^#/, '')),
  };
  t.after(() => {
    for (const [k, v] of Object.entries(prev)) {
      if (v === undefined) delete globalThis[k];
      else globalThis[k] = v;
    }
  });
  const home = initHome({
    api: async path => path === '/api/historico'
      ? { registros: { 'sessao-1': { ...complete(), data_hora: '12/11/2026 10:00:00', finalidade: 'Relaxar' } } }
      : { total: 2, musicas: [{}, {}] },
    onNew: () => {}, onResume: () => {}, onRecord: () => {}, onHistory: () => {}, onCatalog: () => {},
  });
  home.setUser({ nome_usuario: 'Teste' });
  await home.load();
  const recentBtn = byId('home-recent-list').children[0].children.find(child => child.tagName === 'BUTTON');
  assert.ok(recentBtn.className.split(/\s+/).includes('button-link'));
  assert.ok(recentBtn.className.split(/\s+/).includes('home-card-action'));
  assert.ok(recentBtn.className.split(/\s+/).includes('nav-destination'));
  assert.equal(recentBtn.textContent, 'Ver registro →');
  const arrow = recentBtn.children.find(child => child.tagName === 'SPAN');
  assert.equal(arrow.attributes['aria-hidden'], 'true');
  assert.equal(arrow.textContent, '→');
  const catalogBtn = byId('home-open-catalog');
  assert.equal(catalogBtn.textContent, 'Explorar músicas →');
  assert.equal(catalogBtn.children.find(child => child.tagName === 'SPAN')?.attributes['aria-hidden'], 'true');
});
