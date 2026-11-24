import assert from 'node:assert/strict';
import test from 'node:test';
import {
  accountIdentity,
  isGeneratedGoogleUsername,
  readStoredDisplayName,
  sanitizeDisplayName,
  saveStoredDisplayName,
} from '../../static/ui.js';
import { initHome } from '../../static/home.js';

function memoryStorage({ throwOnRead = false, throwOnWrite = false } = {}) {
  const values = new Map();
  return {
    getItem(key) {
      if (throwOnRead) throw new Error('storage bloqueado');
      return values.has(key) ? values.get(key) : null;
    },
    setItem(key, value) {
      if (throwOnWrite) throw new Error('quota excedida');
      values.set(key, String(value));
    },
    removeItem(key) {
      if (throwOnWrite) throw new Error('storage bloqueado');
      values.delete(key);
    },
  };
}

function withMockStorage(t, storageValue) {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    writable: true,
    value: storageValue,
  });
  t.after(() => {
    if (descriptor) Object.defineProperty(globalThis, 'localStorage', descriptor);
    else delete globalThis.localStorage;
  });
}

function mockHomeDom(t) {
  const originalDocument = globalThis.document;
  const originalNode = globalThis.Node;
  const elements = new Map();
  class MockNode {
    constructor(tag = '', text = '') {
      this.tagName = tag.toUpperCase();
      this.children = [];
      this.dataset = {};
      this.textContent = text;
      this.title = '';
      this.hidden = false;
      this.className = '';
    }
    replaceChildren(...items) { this.children = []; this.append(...items); }
    append(...items) { this.children.push(...items); }
    addEventListener() {}
    setAttribute() {}
    removeAttribute() {}
  }
  const node = id => {
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
    querySelector: sel => node(sel.replace(/^#/, '')),
  };
  t.after(() => {
    if (originalDocument === undefined) delete globalThis.document;
    else globalThis.document = originalDocument;
    if (originalNode === undefined) delete globalThis.Node;
    else globalThis.Node = originalNode;
  });
  return node;
}

test('identifica apenas contas geradas google_<32hex> sem confundir nomes locais', () => {
  assert.equal(isGeneratedGoogleUsername('google_0123456789abcdef0123456789abcdef'), true);
  assert.equal(isGeneratedGoogleUsername('google_ficticio'), false);
  assert.equal(isGeneratedGoogleUsername('conta_local'), false);
  assert.equal(isGeneratedGoogleUsername(null), false);
});

test('formata conta Google gerada como Conta Google e preserva contas locais', t => {
  withMockStorage(t, undefined);
  const googleProfile = {
    usuario_id: '11111111-1111-4111-8111-111111111111',
    nome_usuario: 'google_0123456789abcdef0123456789abcdef',
  };
  assert.deepEqual(accountIdentity(googleProfile), {
    displayName: 'Conta Google',
    avatar: 'G',
    greetingName: '',
    providerLabel: 'Conectado com Google · seu espaço pessoal',
    customName: '',
    isCustom: false,
    isGeneratedGoogle: true,
  });
  assert.deepEqual(accountIdentity({ usuario_id: '2', nome_usuario: 'maria_silva' }), {
    displayName: 'maria_silva',
    avatar: 'M',
    greetingName: 'maria_silva',
    providerLabel: 'Seu espaço pessoal',
    customName: '',
    isCustom: false,
    isGeneratedGoogle: false,
  });
});

test('apelido personalizado normaliza espaços, respeita limite, persiste por usuário e pode ser restaurado', t => {
  withMockStorage(t, memoryStorage());

  const googleUser = {
    usuario_id: 'aaaa-bbbb',
    nome_usuario: 'google_0123456789abcdef0123456789abcdef',
  };
  const otherUser = {
    usuario_id: 'cccc-dddd',
    nome_usuario: 'google_fedcba9876543210fedcba9876543210',
  };

  assert.equal(sanitizeDisplayName(`  ${'Á'.repeat(55)}  `), 'Á'.repeat(40));
  assert.equal(saveStoredDisplayName(googleUser.usuario_id, '   João   Gabriel  '), true);
  assert.equal(readStoredDisplayName(googleUser.usuario_id), 'João Gabriel');
  assert.equal(readStoredDisplayName(otherUser.usuario_id), '');

  assert.deepEqual(accountIdentity(googleUser), {
    displayName: 'João Gabriel',
    avatar: 'J',
    greetingName: 'João Gabriel',
    providerLabel: 'Conta Google · seu espaço pessoal',
    customName: 'João Gabriel',
    isCustom: true,
    isGeneratedGoogle: true,
  });

  assert.equal(saveStoredDisplayName(googleUser.usuario_id, '   '), true);
  assert.equal(accountIdentity(googleUser).displayName, 'Conta Google');
});

test('falha ao ler ou gravar storage não quebra identidade nem home', t => {
  withMockStorage(t, memoryStorage({ throwOnRead: true, throwOnWrite: true }));

  const node = mockHomeDom(t);
  const home = initHome({
    api: async () => ({}),
    onNew: () => {}, onResume: () => {}, onRecord: () => {}, onHistory: () => {}, onCatalog: () => {},
  });
  const googleUser = {
    usuario_id: 'id-sem-storage',
    nome_usuario: 'google_0123456789abcdef0123456789abcdef',
  };
  assert.equal(saveStoredDisplayName(googleUser.usuario_id, 'João'), false);
  assert.equal(readStoredDisplayName(googleUser.usuario_id), '');
  home.setUser(googleUser);
  assert.equal(node('home-greeting').textContent, 'Bem-vindo ao seu espaço.');
});

test('updateGreeting atualiza saudação da home sem apagar métricas já carregadas', t => {
  withMockStorage(t, memoryStorage());

  const node = mockHomeDom(t);
  const home = initHome({
    api: async () => ({}),
    onNew: () => {}, onResume: () => {}, onRecord: () => {}, onHistory: () => {}, onCatalog: () => {},
  });
  const googleUser = {
    usuario_id: 'user-home-update',
    nome_usuario: 'google_0123456789abcdef0123456789abcdef',
  };
  home.setUser(googleUser);
  assert.equal(node('home-greeting').textContent, 'Bem-vindo ao seu espaço.');
  node('home-total-sessions').textContent = '3';

  saveStoredDisplayName(googleUser.usuario_id, 'João');
  home.updateGreeting(googleUser);
  assert.equal(node('home-greeting').textContent, 'Olá, João.');
  assert.equal(node('home-total-sessions').textContent, '3');
});
