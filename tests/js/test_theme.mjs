import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../../static/theme.js', import.meta.url), 'utf8');
const key = 'rhythmmind.theme';
const softKey = 'rhythmmind.softEffects';

function fixture({ stored = null, softStored = null, darkSystem = false, storageDenied = false, writeDenied = false,
  mediaMissing = false, legacyMedia = false, ready = 'loading',
  reducedMotion = null, withTimers = false, withViewTransition = false } = {}) {
  const storageValues = new Map([[key, stored], [softKey, softStored]].filter(([, value]) => value !== null));
  const writes = [];
  const windowListeners = new Map();
  const documentListeners = new Map();
  const mediaListeners = [];
  const elements = [];
  const timers = [];
  const viewTransitions = [];
  let nextTimerId = 1;
  const document = { documentElement: { dataset: {} }, readyState: ready };
  const metas = {
    'meta[name="color-scheme"]': { content: 'dark' },
    'meta[name="theme-color"]': { content: '#08131c' },
  };
  const status = { textContent: '' };

  function element(type) {
    const listeners = new Map();
    const node = {
      type, attributes: new Map(), title: '', value: '', checked: false,
      setAttribute(name, value) { this.attributes.set(name, value); },
      removeAttribute(name) { this.attributes.delete(name); },
      addEventListener(name, listener) { listeners.set(name, listener); },
      dispatch(name) { listeners.get(name)?.({ currentTarget: this }); },
    };
    elements.push(node);
    return node;
  }
  const accessToggle = element('toggle');
  const workspaceToggle = element('toggle');
  const select = element('select');
  const softToggle = element('soft');
  const ambient = { checked: true };
  document.querySelector = selector => metas[selector] || null;
  const selectorTypes = {
    'button[data-theme-toggle]': 'toggle',
    'select[data-theme-preference]': 'select',
    'input[data-soft-effects-toggle]': 'soft',
  };
  document.querySelectorAll = selector => elements.filter(node => node.type === selectorTypes[selector]);
  document.getElementById = id => id === 'theme-status' ? status : id === 'ambient-toggle' ? ambient : null;
  document.addEventListener = (name, listener) => documentListeners.set(name, listener);
  if (withViewTransition) {
    document.visibilityState = 'visible';
    document.startViewTransition = callback => {
      if (withViewTransition === 'throw') throw new Error('startViewTransition indisponível');
      const entry = { ran: false };
      viewTransitions.push(entry);
      callback();
      entry.ran = true;
      return { ready: Promise.resolve(), finished: Promise.resolve() };
    };
  }
  const storage = {
    getItem(name) {
      if (storageDenied) throw new Error('Storage indisponível');
      return storageValues.get(name) ?? null;
    },
    setItem(name, value) {
      if (storageDenied || writeDenied) throw new Error('Storage indisponível');
      writes.push([name, value]);
      storageValues.set(name, value);
    },
  };
  const media = { matches: darkSystem };
  if (legacyMedia) media.addListener = listener => mediaListeners.push(listener);
  else media.addEventListener = (name, listener) => { if (name === 'change') mediaListeners.push(listener); };
  const window = { localStorage: storage, addEventListener: (name, listener) => windowListeners.set(name, listener) };
  if (withTimers) {
    window.setTimeout = (fn, delay) => {
      const entry = { id: nextTimerId++, fn, delay, cleared: false, ran: false };
      timers.push(entry);
      return entry.id;
    };
    window.clearTimeout = id => {
      const entry = timers.find(item => item.id === id);
      if (entry) entry.cleared = true;
    };
  }
  if (!mediaMissing) window.matchMedia = query => {
    if (reducedMotion !== null || withTimers || withViewTransition) {
      if (query === '(prefers-reduced-motion: reduce)') return { matches: Boolean(reducedMotion) };
    }
    assert.equal(query, '(prefers-color-scheme: dark)');
    return media;
  };
  vm.runInNewContext(source, { window, document, Set });
  return {
    document, metas, status, accessToggle, workspaceToggle, select, softToggle, ambient, writes, storageValues,
    timers, viewTransitions,
    flushTimers() {
      for (const entry of timers) {
        if (!entry.cleared && !entry.ran) {
          entry.ran = true;
          entry.fn();
        }
      }
    },
    ready() { documentListeners.get('DOMContentLoaded')?.(); },
    choose(value) { select.value = value; select.dispatch('change'); },
    soften(value) { softToggle.checked = value; softToggle.dispatch('change'); },
    system(value) { media.matches = value; mediaListeners.forEach(listener => listener({ matches: value })); },
    crossTab(value, { clear = false, otherStorage = false, unrelated = false, soft = false } = {}) {
      const eventKey = unrelated ? 'outra.preferencia' : soft ? softKey : key;
      if (clear) storageValues.clear();
      else storageValues.set(eventKey, value);
      windowListeners.get('storage')?.({
        key: clear ? null : eventKey,
        newValue: clear ? null : value,
        storageArea: otherStorage ? {} : storage,
      });
    },
  };
}

test('primeira pintura preserva o escuro atual sem escrever storage ou depender do DOM pronto', () => {
  const f = fixture({ darkSystem: false });
  assert.equal(f.document.documentElement.dataset.theme, 'dark');
  assert.equal(f.document.documentElement.dataset.themePreference, 'dark');
  assert.equal(f.document.documentElement.dataset.softEffects, 'false');
  assert.equal(f.metas['meta[name="color-scheme"]'].content, 'dark');
  assert.equal(f.metas['meta[name="theme-color"]'].content, '#08131c');
  assert.deepEqual(f.writes, []);
});

test('preferência clara salva é aplicada no bootstrap e atualiza metadados', () => {
  const f = fixture({ stored: 'light', darkSystem: true });
  assert.equal(f.document.documentElement.dataset.theme, 'light');
  assert.equal(f.metas['meta[name="color-scheme"]'].content, 'only light');
  assert.equal(f.metas['meta[name="theme-color"]'].content, '#d7e8e6');
  f.ready();
  assert.equal(f.select.value, 'light');
});

test('valor inválido salvo não é aplicado como tema nem interpretado como conteúdo', () => {
  const f = fixture({ stored: '<script>alert(1)</script>' });
  assert.equal(f.document.documentElement.dataset.theme, 'dark');
  assert.equal(f.document.documentElement.dataset.themePreference, 'dark');
  assert.deepEqual(f.writes, []);
});

test('sistema acompanha a preferência do dispositivo e suas mudanças', () => {
  const f = fixture({ stored: 'system', darkSystem: false });
  f.ready();
  assert.equal(f.document.documentElement.dataset.theme, 'light');
  assert.match(f.status.textContent, /Seguindo o sistema: modo claro/);
  f.system(true);
  assert.equal(f.document.documentElement.dataset.theme, 'dark');
  assert.equal(f.select.value, 'system');
  assert.match(f.status.textContent, /Seguindo o sistema: modo escuro/);
  assert.deepEqual(f.writes, []);
});

test('escolha explícita prevalece sobre mudanças do dispositivo', () => {
  const f = fixture({ stored: 'system' });
  f.ready();
  f.choose('light');
  f.system(true);
  assert.equal(f.document.documentElement.dataset.theme, 'light');
  assert.equal(f.document.documentElement.dataset.themePreference, 'light');
  assert.deepEqual(f.writes, [[key, 'light']]);
});

test('controles de acesso e área autenticada sincronizam e alternam o tema efetivo', () => {
  const f = fixture({ stored: 'system', darkSystem: true });
  f.ready();
  assert.equal(f.accessToggle.attributes.get('aria-label'), 'Ativar modo claro');
  f.accessToggle.dispatch('click');
  assert.equal(f.document.documentElement.dataset.theme, 'light');
  assert.equal(f.select.value, 'light');
  assert.equal(f.workspaceToggle.title, 'Ativar modo escuro');
  f.workspaceToggle.dispatch('click');
  assert.equal(f.document.documentElement.dataset.theme, 'dark');
  assert.equal(f.accessToggle.title, 'Ativar modo claro');
  assert.deepEqual(f.writes, [[key, 'light'], [key, 'dark']]);
});

test('somente o enum do tema é persistido e a ambientação não é alterada', () => {
  const f = fixture();
  f.ready();
  f.choose('system');
  assert.deepEqual(f.writes, [[key, 'system']]);
  assert.equal(f.ambient.checked, true);
  f.choose('inexistente');
  assert.equal(f.select.value, 'system');
  assert.deepEqual(f.writes, [[key, 'system']]);
});

test('storage bloqueado mantém a escolha nesta aba e informa o limite de persistência', () => {
  const f = fixture({ storageDenied: true });
  f.ready();
  f.choose('light');
  assert.equal(f.document.documentElement.dataset.theme, 'light');
  assert.equal(f.select.value, 'light');
  assert.match(f.status.textContent, /Suas preferências valem nesta aba/);
  assert.deepEqual(f.writes, []);
});

test('falha somente na gravação não invalida a preferência aplicada', () => {
  const f = fixture({ stored: 'dark', writeDenied: true });
  f.ready();
  f.choose('light');
  assert.equal(f.document.documentElement.dataset.themePreference, 'light');
  assert.match(f.status.textContent, /não foi possível salvá-las/);
});

test('ausência de matchMedia mantém sistema com alternativa escura e escolhas manuais funcionam', () => {
  const f = fixture({ stored: 'system', mediaMissing: true });
  f.ready();
  assert.equal(f.document.documentElement.dataset.theme, 'dark');
  assert.match(f.status.textContent, /não está disponível/);
  f.choose('light');
  assert.equal(f.document.documentElement.dataset.theme, 'light');
});

test('matchMedia legado também acompanha alterações do sistema', () => {
  const f = fixture({ stored: 'system', legacyMedia: true });
  f.ready();
  f.system(true);
  assert.equal(f.document.documentElement.dataset.theme, 'dark');
});

test('mudança em outra aba sincroniza tema/controles sem regravar a preferência', () => {
  const f = fixture();
  f.ready();
  f.crossTab('light');
  assert.equal(f.document.documentElement.dataset.theme, 'light');
  assert.equal(f.select.value, 'light');
  f.crossTab('system');
  f.system(true);
  assert.equal(f.document.documentElement.dataset.theme, 'dark');
  assert.equal(f.select.value, 'system');
  assert.deepEqual(f.writes, []);
});

test('limpar storage ou receber um valor inválido restaura o padrão escuro', () => {
  const f = fixture({ stored: 'light' });
  f.ready();
  f.crossTab('light', { clear: true });
  assert.equal(f.document.documentElement.dataset.themePreference, 'dark');
  f.crossTab('light');
  f.crossTab('corrompido');
  assert.equal(f.select.value, 'dark');
});

test('eventos de outro storage ou de outra chave são ignorados', () => {
  const f = fixture();
  f.ready();
  f.crossTab('light', { unrelated: true });
  assert.equal(f.select.value, 'dark');
  f.crossTab('light', { otherStorage: true });
  assert.equal(f.select.value, 'dark');
});

test('script carregado após o DOM pronto conecta os controles imediatamente', () => {
  const f = fixture({ ready: 'complete' });
  f.accessToggle.dispatch('click');
  assert.equal(f.document.documentElement.dataset.theme, 'light');
});

test('suavização salva é aplicada antes da primeira pintura sem mudar o tema', () => {
  const f = fixture({ stored: 'light', softStored: 'true' });
  assert.equal(f.document.documentElement.dataset.softEffects, 'true');
  assert.equal(f.document.documentElement.dataset.theme, 'light');
  f.ready();
  assert.equal(f.softToggle.checked, true);
  assert.deepEqual(f.writes, []);
  for (const value of ['false', '1', 'TRUE', '<script>']) {
    const invalid = fixture({ softStored: value });
    assert.equal(invalid.document.documentElement.dataset.softEffects, 'false');
  }
});

test('suavizar brilhos persiste só o booleano e preserva tema e ambientação', () => {
  const f = fixture({ stored: 'system', darkSystem: true });
  f.ready();
  f.soften(true);
  assert.equal(f.document.documentElement.dataset.softEffects, 'true');
  assert.equal(f.select.value, 'system');
  assert.equal(f.document.documentElement.dataset.theme, 'dark');
  assert.equal(f.ambient.checked, true);
  assert.deepEqual(f.writes, [[softKey, 'true']]);
  f.soften(false);
  assert.equal(f.document.documentElement.dataset.softEffects, 'false');
  assert.deepEqual(f.writes, [[softKey, 'true'], [softKey, 'false']]);
});

test('mudar tema ou receber mudança do sistema não desfaz a suavização escolhida', () => {
  const f = fixture({ stored: 'system' });
  f.ready();
  f.soften(true);
  f.system(true);
  assert.equal(f.softToggle.checked, true);
  f.choose('light');
  assert.equal(f.document.documentElement.dataset.softEffects, 'true');
  assert.equal(f.document.documentElement.dataset.theme, 'light');
  assert.deepEqual(f.writes, [[softKey, 'true'], [key, 'light']]);
});

test('suavização recebida de outra aba sincroniza sem alterar o tema nem regravar storage', () => {
  const f = fixture({ stored: 'light' });
  f.ready();
  f.crossTab('true', { soft: true });
  assert.equal(f.softToggle.checked, true);
  assert.equal(f.document.documentElement.dataset.theme, 'light');
  f.crossTab(null, { soft: true });
  assert.equal(f.softToggle.checked, false);
  f.crossTab('true', { soft: true });
  f.crossTab('inválido', { soft: true });
  assert.equal(f.document.documentElement.dataset.softEffects, 'false');
  assert.deepEqual(f.writes, []);
});

test('limpar as preferências entre abas restaura separadamente tema escuro e brilhos normais', () => {
  const f = fixture({ stored: 'light', softStored: 'true' });
  f.ready();
  f.crossTab(null, { clear: true });
  assert.equal(f.document.documentElement.dataset.themePreference, 'dark');
  assert.equal(f.document.documentElement.dataset.softEffects, 'false');
  assert.equal(f.softToggle.checked, false);
  assert.deepEqual(f.writes, []);
});

test('storage bloqueado não impede suavizar brilhos nesta aba', () => {
  const f = fixture({ stored: 'light', writeDenied: true });
  f.ready();
  f.soften(true);
  assert.equal(f.document.documentElement.dataset.softEffects, 'true');
  assert.equal(f.softToggle.checked, true);
  assert.equal(f.document.documentElement.dataset.theme, 'light');
  assert.equal(f.ambient.checked, true);
  assert.match(f.status.textContent, /Suas preferências valem nesta aba/);
  assert.deepEqual(f.writes, []);
});

test('transição visual via startViewTransition ocorre apenas em trocas interativas que mudam o tema efetivo', () => {
  const f = fixture({ stored: 'system', darkSystem: true, withTimers: true, withViewTransition: true });
  assert.equal(f.viewTransitions.length, 0);
  assert.equal(f.document.documentElement.dataset.themeSwitching, undefined);
  f.ready();
  assert.equal(f.viewTransitions.length, 0);

  // Selecionar explicitamente 'dark' quando o sistema já estava em 'dark' não anima.
  f.choose('dark');
  assert.equal(f.viewTransitions.length, 0);
  assert.equal(f.document.documentElement.dataset.theme, 'dark');

  // Mudança via outra aba ou sistema não dispara transição interativa.
  f.crossTab('light');
  assert.equal(f.viewTransitions.length, 0);
  f.crossTab('system');
  f.system(false);
  assert.equal(f.viewTransitions.length, 0);
  assert.equal(f.document.documentElement.dataset.theme, 'light');

  // Clique interativo no botão e troca no select disparam startViewTransition sem acionar fallback.
  f.accessToggle.dispatch('click');
  assert.equal(f.viewTransitions.length, 1);
  assert.equal(f.viewTransitions[0].ran, true);
  assert.equal(f.document.documentElement.dataset.theme, 'dark');
  assert.equal(f.document.documentElement.dataset.themeSwitching, undefined);

  f.choose('light');
  assert.equal(f.viewTransitions.length, 2);
  assert.equal(f.document.documentElement.dataset.theme, 'light');
  assert.equal(f.timers.length, 0);
});

test('fallback por dataset.themeSwitching anima apenas em troca interativa e limpa após 480ms', () => {
  const f = fixture({ stored: 'dark', withTimers: true, withViewTransition: 'throw' });
  f.ready();
  assert.equal(f.document.documentElement.dataset.themeSwitching, undefined);

  f.workspaceToggle.dispatch('click');
  assert.equal(f.document.documentElement.dataset.theme, 'light');
  assert.equal(f.document.documentElement.dataset.themeSwitching, 'true');
  assert.equal(f.timers.length, 1);
  assert.equal(f.timers[0].delay, 480);

  // Segundo clique rápido cancela o timer anterior e mantém themeSwitching até o novo prazo.
  f.workspaceToggle.dispatch('click');
  assert.equal(f.document.documentElement.dataset.theme, 'dark');
  assert.equal(f.document.documentElement.dataset.themeSwitching, 'true');
  assert.equal(f.timers.length, 2);
  assert.equal(f.timers[0].cleared, true);
  assert.equal(f.timers[1].cleared, false);

  f.flushTimers();
  assert.equal(f.document.documentElement.dataset.themeSwitching, undefined);
});

test('movimento reduzido suprime startViewTransition e dataset.themeSwitching mantendo a troca imediata', () => {
  const f = fixture({ stored: 'dark', reducedMotion: true, withTimers: true, withViewTransition: true });
  f.ready();
  f.accessToggle.dispatch('click');
  assert.equal(f.document.documentElement.dataset.theme, 'light');
  assert.equal(f.viewTransitions.length, 0);
  assert.equal(f.document.documentElement.dataset.themeSwitching, undefined);
  assert.equal(f.timers.length, 0);

  f.choose('dark');
  assert.equal(f.document.documentElement.dataset.theme, 'dark');
  assert.equal(f.viewTransitions.length, 0);
  assert.equal(f.document.documentElement.dataset.themeSwitching, undefined);
  assert.equal(f.timers.length, 0);
});
