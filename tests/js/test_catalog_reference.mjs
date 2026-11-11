import assert from 'node:assert/strict';
import test from 'node:test';
import { safeCatalogSource, renderCatalogCard, createCatalogReference } from '../../static/catalog-reference.js';

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function domFixture(t) {
  const previous = { document: globalThis.document, Node: globalThis.Node };
  const nodes = new Map();
  class MockNode {
    constructor(tag = '', text = '') {
      this.tagName = tag.toUpperCase();
      this.children = [];
      this.attributes = {};
      this.dataset = {};
      this.listeners = new Map();
      this.disabled = false;
      this.hidden = false;
      this._text = text;
    }
    set textContent(value) { this._text = String(value); this.children = []; }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
    set innerHTML(_value) { throw new Error('A renderização deve usar nós de texto.'); }
    append(...children) {
      for (const child of children) {
        assert.ok(child instanceof MockNode, 'append deve receber nós DOM');
        this.children.push(child);
      }
    }
    replaceChildren(...children) { this.children = []; this._text = ''; this.append(...children); }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    getAttribute(name) { return this.attributes[name] ?? null; }
    removeAttribute(name) { delete this.attributes[name]; }
    addEventListener(name, callback) { this.listeners.set(name, callback); }
    dispatch(name) { return this.listeners.get(name)?.({ preventDefault() {} }); }
    matches(selector) {
      return selector === 'button, input[type="submit"]' && this.tagName === 'BUTTON';
    }
    querySelectorAll(selector) {
      const result = [];
      for (const child of this.children) {
        if (selector === 'a' && child.tagName === 'A') result.push(child);
        else if (selector === 'button, input[type="submit"]' && child.tagName === 'BUTTON') result.push(child);
        result.push(...child.querySelectorAll(selector));
      }
      return result;
    }
  }
  function node(id, tag = 'div') {
    const value = new MockNode(tag);
    value.id = id;
    nodes.set(id, value);
    return value;
  }
  globalThis.Node = MockNode;
  globalThis.document = {
    createElement: tag => new MockNode(tag),
    createTextNode: text => new MockNode('', text),
    querySelector: selector => nodes.get(selector.replace(/^#/, '')) ?? null,
  };
  t.after(() => {
    for (const [name, value] of Object.entries(previous)) {
      if (value === undefined) delete globalThis[name];
      else globalThis[name] = value;
    }
  });
  return { node, nodes };
}

const song = () => ({
  id: 'referencia-ficticia-1', nome: 'Canção <img src=x onerror=alert(1)>',
  artista: 'Artista Fictício', duracao: '3:00',
  sentimentos_associados: ['calmo', 'reflexivo'],
  proveniencia: { fonte: 'Fonte Fictícia', album: 'Álbum Fictício',
    url: 'https://open.spotify.com/track/0000000000000000000000', consultado_em: '2026-11-11' },
  curadoria: { status: 'provisoria' },
});

function controller(t, api, options = {}) {
  const { node } = domFixture(t);
  const button = node('catalog-reference-import', 'button');
  const status = node('catalog-reference-status', 'p');
  const count = node('catalog-reference-count', 'span');
  const list = node('catalog-reference-list');
  const container = node('catalog-reference');
  container.append(button, status, count, list);
  const reference = createCatalogReference({ api, button, status, count, list, container, ...options });
  return { reference, button, status, count, list, container };
}

const response = () => ({ versao: 'ficticia-1', total: 3, descricao: 'Seleção fictícia.',
  musicas: [song(), { ...song(), id: 'referencia-ficticia-2' }, { ...song(), id: 'referencia-ficticia-3' }] });

function descendants(node) { return node.children.flatMap(child => [child, ...descendants(child)]); }

test('fonte externa permite apenas HTTPS nos hosts exatos e recusa credenciais e portas extras', () => {
  for (const url of ['https://music.apple.com/br/album/ficticio/123?i=456',
    'https://open.spotify.com/track/0000000000000000000000']) {
    assert.equal(safeCatalogSource(url), url);
  }
  for (const unsafe of [null, undefined, 12, '', 'não é uma URL',
    'http://music.apple.com/faixa', 'javascript:alert(1)', '//open.spotify.com/faixa',
    'https://music.apple.com.evil.invalid/faixa', 'https://evil.invalid/open.spotify.com',
    'https://senha@music.apple.com/faixa', 'https://user:senha@open.spotify.com/faixa',
    'https://open.spotify.com:444/faixa', 'https://music.apple.com:80/faixa']) {
    assert.equal(safeCatalogSource(unsafe), null, String(unsafe));
  }
});

test('card mostra texto literal, proveniência e categorias provisórias sem medidas inventadas', t => {
  domFixture(t);
  const fixture = song();
  fixture.bpm = 120;
  fixture.valencia = 'alta';
  const card = renderCatalogCard(fixture);
  const nodes = descendants(card);
  assert.equal(card.tagName, 'ARTICLE');
  assert.equal(nodes.find(node => node.tagName === 'H3').textContent, fixture.nome);
  assert.ok(!nodes.some(node => node.tagName === 'IMG'));
  assert.ok(card.textContent.includes(fixture.artista));
  assert.ok(card.textContent.includes(fixture.proveniencia.album));
  assert.ok(card.textContent.includes(fixture.proveniencia.fonte));
  assert.match(card.textContent, /provisóri/i);
  assert.match(card.textContent, /calmo/i);
  assert.match(card.textContent, /reflexivo/i);
  assert.doesNotMatch(card.textContent, /120|bpm|valência|valencia/i);
  const links = card.querySelectorAll('a');
  assert.equal(links.length, 1);
  assert.equal(links[0].getAttribute('href'), fixture.proveniencia.url);
  assert.equal(links[0].getAttribute('target'), '_blank');
  assert.ok(links[0].getAttribute('rel').split(/\s+/).includes('noreferrer'));
  assert.ok(links[0].getAttribute('rel').split(/\s+/).includes('noopener'));
});

test('fonte inválida não vira link e cadastro pessoal não ganha rótulo de curadoria', t => {
  domFixture(t);
  const fixture = song();
  fixture.proveniencia.url = 'https://music.apple.com.evil.invalid/faixa';
  assert.equal(renderCatalogCard(fixture).querySelectorAll('a').length, 0);
  delete fixture.curadoria;
  delete fixture.proveniencia;
  assert.doesNotMatch(renderCatalogCard(fixture).textContent, /provisóri/i);
});

test('consulta usa total recebido e renderiza músicas sem escrever catálogo pessoal', async t => {
  const requests = [];
  const { reference, count, list } = controller(t, async (path, options) => {
    requests.push([path, options]);
    return response();
  });
  await reference.load();
  assert.deepEqual(requests.map(([path]) => path), ['/api/catalogo-referencia']);
  assert.equal(requests[0][1]?.method ?? 'GET', 'GET');
  assert.match(count.textContent, /3/);
  assert.equal(list.children.length, 3);
});

test('cliques repetidos compartilham um POST e concluem uma única atualização', async t => {
  const pending = deferred();
  const requests = [];
  let imported = 0;
  const { reference, button, container, status } = controller(t, (path, options) => {
    requests.push([path, options]);
    return pending.promise;
  }, { onImported: async () => { imported += 1; } });
  const first = reference.importAll();
  const duplicate = reference.importAll();
  assert.equal(duplicate, first, 'as duas ações devem compartilhar a mesma operação');
  assert.equal(requests.length, 1);
  assert.equal(requests[0][0], '/api/catalogo-referencia/importar');
  assert.equal(requests[0][1].method, 'POST');
  assert.deepEqual(requests[0][1].body, {});
  assert.equal(button.disabled, true);
  assert.equal(container.getAttribute('aria-busy'), 'true');
  pending.resolve({ versao: 'ficticia-1', importadas: 2, ja_existentes: 1, total: 3 });
  await Promise.all([first, duplicate]);
  assert.equal(imported, 1);
  assert.equal(button.disabled, false);
  assert.equal(container.getAttribute('aria-busy'), null);
  assert.match(status.textContent, /2/);
  assert.match(status.textContent, /1/);
});

test('reset descarta GET atrasado sem expor faixas da conta anterior', async t => {
  const pending = deferred();
  const { reference, list, count } = controller(t, () => pending.promise);
  const loading = reference.load();
  reference.reset();
  pending.resolve(response());
  await loading;
  assert.equal(list.children.length, 0);
  assert.doesNotMatch(count.textContent, /3/);
});

test('importação anterior ao reset não altera novo ciclo nem retira seu busy', async t => {
  const oldRequest = deferred();
  const newRequest = deferred();
  let calls = 0;
  let imported = 0;
  const { reference, button, container, status } = controller(t, () => {
    calls += 1;
    return calls === 1 ? oldRequest.promise : newRequest.promise;
  }, { onImported: async () => { imported += 1; } });
  const oldImport = reference.importAll();
  reference.reset();
  assert.equal(button.disabled, false);
  const newImport = reference.importAll();
  assert.equal(calls, 2);
  oldRequest.resolve({ versao: 'antiga', importadas: 99, ja_existentes: 0, total: 99 });
  await oldImport;
  assert.equal(imported, 0);
  assert.equal(button.disabled, true);
  assert.equal(container.getAttribute('aria-busy'), 'true');
  assert.doesNotMatch(status.textContent, /99/);
  newRequest.resolve({ versao: 'nova', importadas: 1, ja_existentes: 2, total: 3 });
  await newImport;
  assert.equal(imported, 1);
  assert.equal(button.disabled, false);
  assert.match(status.textContent, /1/);
});

test('falha ao importar restaura ação e permite tentativa posterior', async t => {
  let calls = 0;
  let imported = 0;
  const errors = [];
  const failure = new Error('Falha fictícia temporária.');
  const { reference, button, status } = controller(t, async () => {
    calls += 1;
    if (calls === 1) throw failure;
    return { versao: 'ficticia-1', importadas: 0, ja_existentes: 3, total: 3 };
  }, { onImported: async () => { imported += 1; }, onError: error => errors.push(error) });
  await reference.importAll();
  assert.equal(button.disabled, false);
  assert.equal(imported, 0);
  assert.equal(errors.length, 1);
  assert.match(status.textContent, /Falha fictícia/);
  await reference.importAll();
  assert.equal(calls, 2);
  assert.equal(imported, 1);
  assert.equal(button.disabled, false);
});

test('falha da prévia não bloqueia uma importação posterior', async t => {
  const requests = [];
  let imported = 0;
  const { reference, list, count, button, status } = controller(t, async (path, options) => {
    requests.push([path, options]);
    if (path === '/api/catalogo-referencia') throw new Error('Prévia fictícia indisponível.');
    return { versao: 'ficticia-1', importadas: 3, ja_existentes: 0, total: 3 };
  }, { onImported: async () => { imported += 1; } });
  await reference.load();
  assert.equal(list.children.length, 0);
  assert.match(count.textContent, /indisponível/i);
  assert.equal(button.disabled, false);
  await reference.importAll();
  assert.deepEqual(requests.map(([path]) => path), ['/api/catalogo-referencia', '/api/catalogo-referencia/importar']);
  assert.equal(imported, 1);
  assert.match(status.textContent, /3/);
});

test('GET mais antigo não substitui uma seleção recebida por consulta mais recente', async t => {
  const older = deferred();
  const newer = deferred();
  let calls = 0;
  const { reference, count, list } = controller(t, () => {
    calls += 1;
    return calls === 1 ? older.promise : newer.promise;
  });
  const oldLoad = reference.load();
  const newLoad = reference.load();
  newer.resolve({ ...response(), total: 1, musicas: [{ ...song(), nome: 'Seleção Fictícia Nova' }] });
  await newLoad;
  assert.match(count.textContent, /^1 /);
  assert.equal(list.children.length, 1);
  assert.match(list.textContent, /Seleção Fictícia Nova/);
  older.resolve(response());
  await oldLoad;
  assert.match(count.textContent, /^1 /);
  assert.equal(list.children.length, 1);
  assert.match(list.textContent, /Seleção Fictícia Nova/);
});

for (const outcome of ['sucesso', 'falha']) {
  test(`prévia tardia com ${outcome} conserva confirmação da importação`, async t => {
    const preview = deferred();
    const { reference, status } = controller(t, async path => {
      if (path === '/api/catalogo-referencia') return preview.promise;
      return { versao: 'ficticia-1', importadas: 2, ja_existentes: 1, total: 3 };
    });
    const loading = reference.load();
    await reference.importAll();
    const confirmation = status.textContent;
    assert.equal(status.dataset.type, 'success');
    assert.match(confirmation, /2/);
    if (outcome === 'sucesso') preview.resolve(response());
    else preview.reject(new Error('Falha fictícia tardia.'));
    await loading;
    assert.equal(status.textContent, confirmation);
    assert.equal(status.dataset.type, 'success');
  });
}
