import assert from 'node:assert/strict';
import test from 'node:test';
import { initHistory, listeningText, feedbackText, historyFilterSummary, historyRecordTitle, historyEntries } from '../../static/history.js';

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

test('voltar à lista do diário limpa o detalhe e devolve foco ao gatilho ou ao cabeçalho da lista', async t => {
  const prev = { document: globalThis.document, window: globalThis.window };
  const elements = new Map();
  const doc = { activeElement: null };
  class MockClassList {
    constructor(node) { this.node = node; this.set = new Set(); }
    add(...names) { names.forEach(n => this.set.add(n)); }
    toggle(name, force) {
      if (force === undefined) this.set[this.set.has(name) ? 'delete' : 'add'](name);
      else if (force) this.set.add(name);
      else this.set.delete(name);
    }
    contains(name) { return this.set.has(name); }
  }
  class MockNode {
    constructor(tag = 'div', id = '') {
      this.tagName = tag.toUpperCase();
      this.id = id;
      this.children = [];
      this.attributes = {};
      this.dataset = {};
      this.listeners = new Map();
      this.classList = new MockClassList(this);
      this.className = '';
      this.hidden = false;
      this.disabled = false;
      this.open = false;
      this.isConnected = true;
      this.value = '';
      this.elements = { namedItem: () => null };
      this._text = '';
    }
    set textContent(value) { this._text = String(value); this.children = []; }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
    append(...children) {
      for (const child of children) {
        if (typeof child === 'object' && child) {
          child.isConnected = this.isConnected;
          this.children.push(child);
        }
      }
    }
    replaceChildren(...children) {
      for (const old of this.children) old.isConnected = false;
      this.children = [];
      this._text = '';
      this.append(...children);
    }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    removeAttribute(name) { delete this.attributes[name]; }
    addEventListener(type, fn) { this.listeners.set(type, fn); }
    dispatch(type) { return this.listeners.get(type)?.({ preventDefault() {}, currentTarget: this }); }
    reset() {}
    focus() { if (!this.disabled && this.isConnected) doc.activeElement = this; }
    scrollIntoView() {}
    matches() { return false; }
    querySelector(selector) {
      if (selector === 'button[data-session-id]') {
        return this.children.find(child => child.tagName === 'BUTTON' && child.dataset.sessionId) || null;
      }
      return null;
    }
    querySelectorAll(selector) {
      if (selector === '.history-card') return this.children.filter(child => child.className.includes('history-card'));
      return [];
    }
  }
  const byId = id => {
    if (!elements.has(id)) elements.set(id, new MockNode(id === 'history-filter-form' || id === 'history-correction-form' ? 'form' : 'div', id));
    return elements.get(id);
  };
  for (const id of ['history-list-heading', 'history-heading', 'history-detail-back', 'history-detail-title', 'history-detail']) byId(id);
  doc.getElementById = id => byId(id);
  doc.createElement = tag => new MockNode(tag);
  doc.querySelector = sel => sel.startsWith('#') ? byId(sel.slice(1)) : null;
  globalThis.document = doc;
  globalThis.window = { innerWidth: 1280, scrollTo() {} };
  t.after(() => {
    for (const [k, v] of Object.entries(prev)) {
      if (v === undefined) delete globalThis[k];
      else globalThis[k] = v;
    }
  });

  const record = complete({ data_hora: '12/11/2026 10:00:00', texto_usuario: 'Relato fictício' });
  const history = initHistory({
    api: async path => path === '/api/historico'
      ? { registros: { s1: record } }
      : path === '/api/padroes'
        ? { avaliacoes_sessoes: { sessoes_totais: 1 } }
        : { registro: record },
    notify: () => {}, onResume: () => {}, onChanged: () => {},
  });

  await history.load();
  const cardBtn = byId('history-list').children[0].querySelector('button[data-session-id]');
  await cardBtn.dispatch('click');
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(byId('history-detail').hidden, false);
  assert.equal(doc.activeElement, byId('history-detail-title'));

  byId('history-detail-back').dispatch('click');
  assert.equal(byId('history-detail').hidden, true);
  assert.equal(doc.activeElement, cardBtn);

  await history.open('s1', true);
  assert.equal(byId('history-detail').hidden, false);
  byId('history-detail-back').dispatch('click');
  assert.equal(byId('history-detail').hidden, true);
  assert.equal(doc.activeElement, byId('history-list-heading'));
});
