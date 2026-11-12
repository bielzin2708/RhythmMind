import assert from 'node:assert/strict';
import test from 'node:test';
import { createCatalogBrowser, createCatalogAssociations, normalizeCatalogSearch } from '../../static/catalog-browser.js';

function fixture(t, options = {}) {
  const previous = { document: globalThis.document, Node: globalThis.Node };
  class MockNode {
    constructor(tag = '', text = '') {
      this.tagName = tag.toUpperCase();
      this.children = [];
      this.attributes = {};
      this.listeners = new Map();
      this.dataset = {};
      this.value = '';
      this.disabled = false;
      this.hidden = false;
      this.isConnected = true;
      this._text = text;
    }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
    set textContent(value) { this._text = String(value); this.children = []; }
    set innerHTML(_value) { throw new Error('Use nós de texto para conteúdo de catálogo.'); }
    append(...children) {
      for (const child of children) {
        assert.ok(child instanceof MockNode);
        this.children.push(child);
      }
    }
    replaceChildren(...children) { this.children = []; this._text = ''; this.append(...children); }
    setAttribute(name, value) { this.attributes[name] = String(value); if (name === 'id') this.id = String(value); }
    getAttribute(name) { return this.attributes[name] ?? null; }
    removeAttribute(name) { delete this.attributes[name]; }
    addEventListener(name, callback) { this.listeners.set(name, callback); }
    dispatch(name) { return this.listeners.get(name)?.({ preventDefault() {}, target: this }); }
    focus() { globalThis.document.activeElement = this; }
    showModal() { this.open = true; }
    close() { this.open = false; }
    querySelectorAll(selector) {
      const matches = node => selector.split(',').some(part => {
        const value = part.trim();
        if (value === 'input:checked') return node.tagName === 'INPUT' && node.checked;
        if (value === 'input[type="submit"]') return node.tagName === 'INPUT' && node.getAttribute('type') === 'submit';
        if (value.startsWith('.')) return (node.className || '').split(/\s+/).includes(value.slice(1));
        return node.tagName === value.toUpperCase();
      });
      return this.children.flatMap(child => [
        ...(matches(child) ? [child] : []),
        ...child.querySelectorAll(selector),
      ]);
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }
  }
  globalThis.Node = MockNode;
  globalThis.document = {
    createElement: tag => new MockNode(tag),
    createTextNode: text => new MockNode('', String(text)),
  };
  t.after(() => {
    for (const [name, value] of Object.entries(previous)) {
      if (value === undefined) delete globalThis[name];
      else globalThis[name] = value;
    }
  });
  const list = new MockNode('div');
  const search = new MockNode('input');
  const count = new MockNode('p');
  const more = new MockNode('button');
  const rendered = [];
  const browser = createCatalogBrowser({
    list, search, count, more,
    renderCard: song => {
      rendered.push(song.id);
      const card = new MockNode('article', song.nome);
      card.song = song;
      return card;
    },
    ...options,
  });
  const query = value => { search.value = value; search.dispatch('input'); };
  return { browser, list, search, count, more, rendered, query, MockNode };
}

const songs = (length = 700) => Array.from({ length }, (_, index) => ({
  id: `faixa-${index}`, nome: `Canção ${index}`, artista: 'Artista de teste',
  proveniencia: { album: 'Álbum de teste' },
}));

test('busca normaliza caixa, espaços e acentos de texto português', () => {
  assert.equal(normalizeCatalogSearch('  CANÇÃO À NOITE  '), 'cancao a noite');
  assert.equal(normalizeCatalogSearch('João'), normalizeCatalogSearch('JOAO'));
  assert.equal(normalizeCatalogSearch(null), '');
});

test('700 faixas geram somente a página inicial e carregar mais respeita o limite', t => {
  const { browser, list, more, count, rendered } = fixture(t);
  browser.setSongs(songs());
  assert.equal(browser.state.total, 700);
  assert.equal(browser.state.matched, 700);
  assert.equal(browser.state.visible, 25);
  assert.equal(list.children.length, 25);
  assert.equal(rendered.length, 25, 'nem sequer deve construir cards fora da página');
  assert.match(count.textContent, /25/);
  assert.match(count.textContent, /700/);
  assert.equal(more.hidden, false);
  more.dispatch('click');
  assert.equal(list.children.length, 50);
  assert.equal(browser.state.visible, 50);
  assert.equal(list.children[49].song.id, 'faixa-49');
});

test('pesquisa nome, artista e ambos os campos de álbum sem acentos, reiniciando a página', t => {
  const { browser, list, more, query } = fixture(t);
  const data = songs(70);
  data[55] = { id: 'nome', nome: 'Coração Azul', artista: 'Pessoa' };
  data[56] = { id: 'artista', nome: 'Outra', artista: 'João Gilberto' };
  data[57] = { id: 'fonte-album', nome: 'Terceira', artista: 'Pessoa', proveniencia: { album: 'Órbita' } };
  data[58] = { id: 'album', nome: 'Quarta', artista: 'Pessoa', album: 'Memórias' };
  browser.setSongs(data);
  more.dispatch('click');
  assert.equal(browser.state.visible, 50);
  for (const [term, expected] of [['coracao', 'nome'], ['JOAO', 'artista'], ['orbita', 'fonte-album'], ['memorias', 'album']]) {
    query(term);
    assert.equal(browser.state.matched, 1);
    assert.equal(list.children.length, 1);
    assert.equal(list.children[0].song.id, expected);
    assert.equal(more.hidden, true);
  }
  query('');
  assert.equal(browser.state.visible, 25);
  assert.equal(list.children.length, 25);
});

test('prévia fechada não constrói cards e pode renderizar a primeira página ao abrir', t => {
  let visible = false;
  const { browser, list, rendered } = fixture(t, { isVisible: () => visible });
  browser.setSongs(songs());
  assert.equal(list.children.length, 0);
  assert.equal(rendered.length, 0);
  visible = true;
  browser.render();
  assert.equal(list.children.length, 25);
  assert.equal(rendered.length, 25);
});

test('busca sem resultado mostra estado vazio e permite pesquisar novamente', t => {
  const { browser, list, query, more, count } = fixture(t);
  browser.setSongs(songs(30));
  query('nenhuma-faixa-correspondente');
  assert.equal(browser.state.matched, 0);
  assert.equal(browser.state.visible, 0);
  assert.ok(list.textContent.trim().length || count.textContent.trim().length, 'ausência de resultados precisa ser comunicada');
  assert.ok(list.children.every(node => node.tagName !== 'ARTICLE'));
  assert.equal(more.hidden, true);
  query('canção');
  assert.equal(browser.state.matched, 30);
  assert.equal(list.children.length, 25);
});

test('busy continua ativo após atualizar faixas, filtrar e renderizar novamente', t => {
  const { browser, list, more, query } = fixture(t);
  browser.setSongs(songs());
  browser.setBusy(true);
  browser.setSongs(songs(50));
  query('canção');
  browser.render();
  assert.equal(browser.state.busy, true);
  assert.equal(more.disabled, true);
  assert.equal(list.getAttribute('aria-busy'), 'true');
  browser.setBusy(false);
  assert.equal(browser.state.busy, false);
  assert.equal(more.disabled, false);
  assert.notEqual(list.getAttribute('aria-busy'), 'true');
});

test('falha de leitura não conserva cards antigos e uma nova leitura recupera o catálogo', t => {
  const { browser, list, count } = fixture(t);
  browser.setSongs(songs());
  browser.setError('Não foi possível consultar seu catálogo.');
  assert.ok(list.children.every(node => node.tagName !== 'ARTICLE'));
  assert.match(list.textContent + count.textContent, /Não foi possível consultar seu catálogo/);
  browser.setSongs(songs(4));
  assert.equal(browser.state.error, '');
  assert.equal(list.children.length, 4);
});

test('reset apaga busca, resultados, estado de erro e bloqueio da conta anterior', t => {
  const { browser, list, search, query } = fixture(t);
  browser.setSongs(songs());
  query('canção 6');
  browser.setBusy(true);
  browser.setError('Erro anterior');
  browser.reset();
  assert.equal(search.value, '');
  assert.equal(browser.state.query, '');
  assert.equal(browser.state.total, 0);
  assert.equal(browser.state.matched, 0);
  assert.equal(browser.state.visible, 0);
  assert.equal(browser.state.error, '');
  assert.equal(browser.state.busy, false);
  assert.equal(list.children.length, 0);
  browser.setSongs(songs(2));
  assert.equal(list.children.length, 2);
});

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function associations(t, api, options = {}) {
  const { MockNode } = fixture(t);
  const dialog = new MockNode('dialog');
  const form = new MockNode('form');
  const title = new MockNode('h2');
  const categories = new MockNode('fieldset');
  categories.id = 'catalog-associations-categories';
  const status = new MockNode('p');
  const save = new MockNode('button');
  const cancel = new MockNode('button');
  const trigger = new MockNode('button');
  const editor = createCatalogAssociations({ api, dialog, form, title, categories, status, save, cancel, ...options });
  return { editor, dialog, form, title, categories, status, save, cancel, trigger };
}

test('editor usa um PATCH com ID codificado e todas as sensações marcadas, inclusive ocultas', async t => {
  const pending = deferred();
  const requests = [];
  const saved = [];
  const { editor, dialog, title, categories, save, form, trigger } = associations(t, (path, options) => {
    requests.push([path, options]);
    return pending.promise;
  }, { onSaved: song => saved.push(song) });
  const music = { id: 'abc/ç?', nome: 'Canção de teste', artista: 'João', sentimentos_associados: ['calmo', 'foco'] };
  editor.open(music, trigger);
  assert.equal(dialog.open, true);
  assert.match(title.textContent, /Canção de teste.*João/);
  const inputs = categories.querySelectorAll('input');
  assert.equal(inputs.length, 14);
  assert.deepEqual(inputs.filter(input => input.checked).map(input => input.value).sort(), ['calmo', 'foco']);
  // Saving must read checked inputs even when their option is hidden.
  const extra = inputs.find(input => input.value === 'reflexivo');
  extra.checked = true;
  assert.equal(categories.querySelectorAll('label').find(label => label.children.includes(extra)).hidden, true);
  const first = editor.submit();
  const second = editor.submit();
  assert.equal(first, second);
  assert.equal(requests.length, 1);
  assert.equal(requests[0][0], '/api/musicas/abc%2F%C3%A7%3F/associacoes');
  assert.equal(requests[0][1].method, 'PATCH');
  assert.deepEqual([...requests[0][1].body.sentimentos_associados].sort(), ['calmo', 'foco', 'reflexivo']);
  assert.deepEqual(Object.keys(requests[0][1].body), ['sentimentos_associados']);
  assert.equal(save.disabled, true);
  assert.equal(categories.disabled, true);
  assert.equal(form.getAttribute('aria-busy'), 'true');
  const updated = { ...music, sentimentos_associados: ['calmo', 'foco', 'reflexivo'] };
  pending.resolve({ musica: updated });
  await first;
  assert.deepEqual(saved, [updated]);
  assert.equal(dialog.open, false);
  assert.equal(save.disabled, false);
  assert.equal(globalThis.document.activeElement, trigger);
});

test('salvar sem sensações envia lista vazia e permite remover associações sem excluir faixa', async t => {
  let request;
  const { editor, categories } = associations(t, async (path, options) => {
    request = [path, options];
    return { musica: { id: 'existente', sentimentos_associados: [] } };
  });
  editor.open({ id: 'existente', nome: 'Faixa existente', sentimentos_associados: ['calmo'] });
  for (const input of categories.querySelectorAll('input')) input.checked = false;
  await editor.submit();
  assert.equal(request[0], '/api/musicas/existente/associacoes');
  assert.deepEqual(request[1], { method: 'PATCH', body: { sentimentos_associados: [] } });
});

test('falha de PATCH mantém escolhas e diálogo aberto para tentar novamente', async t => {
  let calls = 0;
  const failures = [];
  const { editor, dialog, categories, status, save } = associations(t, async () => {
    calls += 1;
    if (calls === 1) throw new Error('Falha temporária');
    return { musica: { id: 'retry', sentimentos_associados: ['amor'] } };
  }, { onError: error => failures.push(error) });
  editor.open({ id: 'retry', sentimentos_associados: ['amor'] });
  await editor.submit();
  assert.equal(dialog.open, true);
  assert.match(status.textContent, /Falha temporária/);
  assert.equal(status.dataset.type, 'error');
  assert.equal(save.disabled, false);
  assert.equal(categories.disabled, false);
  assert.equal(categories.querySelectorAll('input:checked')[0].value, 'amor');
  assert.equal(failures.length, 1);
  await editor.submit();
  assert.equal(calls, 2);
  assert.equal(dialog.open, false);
});

test('reset ignora PATCH antigo e sua conclusão não libera bloqueio da nova conta', async t => {
  const older = deferred();
  const newer = deferred();
  let calls = 0;
  const saved = [];
  const { editor, dialog, form, save, status, trigger } = associations(t, () => {
    calls += 1;
    return calls === 1 ? older.promise : newer.promise;
  }, { onSaved: song => saved.push(song) });
  editor.open({ id: 'antiga', sentimentos_associados: [] }, trigger);
  const oldSave = editor.submit();
  editor.reset();
  assert.equal(dialog.open, false);
  assert.equal(save.disabled, false);
  editor.open({ id: 'nova', sentimentos_associados: [] }, trigger);
  const newSave = editor.submit();
  older.resolve({ musica: { id: 'antiga' } });
  await oldSave;
  assert.deepEqual(saved, []);
  assert.equal(dialog.open, true);
  assert.equal(save.disabled, true);
  assert.equal(form.getAttribute('aria-busy'), 'true');
  assert.doesNotMatch(status.textContent, /antiga/);
  newer.resolve({ musica: { id: 'nova' } });
  await newSave;
  assert.deepEqual(saved, [{ id: 'nova' }]);
  assert.equal(save.disabled, false);
});

for (const cancellation of ['button', 'escape']) {
  test(`cancelar por ${cancellation} fecha diálogo sem PATCH e retorna foco`, t => {
    let requests = 0;
    const { editor, dialog, cancel, trigger } = associations(t, async () => { requests += 1; });
    editor.open({ id: 'cancelar', sentimentos_associados: [] }, trigger);
    if (cancellation === 'button') cancel.dispatch('click');
    else dialog.dispatch('cancel');
    assert.equal(dialog.open, false);
    assert.equal(globalThis.document.activeElement, trigger);
    assert.equal(requests, 0);
  });
}
