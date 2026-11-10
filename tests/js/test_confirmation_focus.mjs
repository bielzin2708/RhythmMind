import assert from 'node:assert/strict';
import test from 'node:test';
import { confirmAction, withBusy } from '../../static/ui.js';

function fixture(t) {
  const originalDocument = globalThis.document;
  const originalFrame = globalThis.requestAnimationFrame;
  const frames = [];
  const nodes = new Map();
  const doc = { activeElement: null };

  function node(id, tagName = 'DIV', parent = null) {
    const listeners = new Map();
    const element = {
      id, tagName, parentElement: parent, children: [], isConnected: true,
      hidden: false, inert: false, disabled: false, open: false, textContent: '',
      addEventListener(type, listener) { listeners.set(type, listener); },
      removeEventListener(type) { listeners.delete(type); },
      dispatch(type) { listeners.get(type)?.({ preventDefault() {} }); },
      setAttribute() {}, removeAttribute() {},
      contains(other) {
        for (let current = other; current; current = current.parentElement) {
          if (current === this) return true;
        }
        return false;
      },
      matches(selector) {
        if (selector === ':disabled') return this.disabled;
        return selector === 'button, input[type="submit"]' && this.tagName === 'BUTTON';
      },
      closest(selector) {
        for (let current = this; current; current = current.parentElement) {
          if (selector === '[hidden], [inert]' && (current.hidden || current.inert)) return current;
          if (selector === 'details:not([open])' && current.tagName === 'DETAILS' && !current.open) return current;
        }
        return null;
      },
      querySelector(selector) {
        if (selector === ':scope > summary') return this.children.find(child => child.tagName === 'SUMMARY') || null;
        return null;
      },
      querySelectorAll() { return []; },
      getClientRects() {
        if (!this.isConnected || this.closest('[hidden], [inert]')) return [];
        for (let current = this; current; current = current.parentElement) {
          if (current.tagName === 'DIALOG' && !current.open) return [];
          if (current.tagName === 'DETAILS' && !current.open
            && !current.querySelector(':scope > summary')?.contains(this)) return [];
        }
        return [{}];
      },
      focus() {
        if (!this.disabled && this.getClientRects().length) doc.activeElement = this;
      },
      showModal() { this.returnFocus = doc.activeElement; this.open = true; doc.activeElement = this; },
      close() {
        this.open = false;
        doc.activeElement = doc.body;
        this.returnFocus?.focus();
      },
    };
    parent?.children.push(element);
    nodes.set(id, element);
    return element;
  }

  doc.documentElement = node('html', 'HTML');
  doc.body = node('body', 'BODY', doc.documentElement);
  const view = node('view-session', 'SECTION', doc.body);
  const heading = node('session-heading', 'H1', view);
  const trigger = node('trigger', 'BUTTON', view);
  const dialog = node('confirm-dialog', 'DIALOG', doc.body);
  const form = node('confirm-form', 'FORM', dialog);
  node('confirm-cancel', 'BUTTON', form);
  node('confirm-submit', 'BUTTON', form);
  node('confirm-title', 'H2', dialog);
  node('confirm-text', 'P', dialog);
  doc.querySelector = selector => {
    if (selector.startsWith('#')) return nodes.get(selector.slice(1));
    if (selector === 'dialog[open]') return [...nodes.values()].find(value => value.tagName === 'DIALOG' && value.open) || null;
    if (selector === '.workspace-view:not([hidden]) h1[tabindex="-1"]') return heading;
    return null;
  };
  doc.activeElement = trigger;
  globalThis.document = doc;
  globalThis.requestAnimationFrame = callback => frames.push(callback);
  t.after(() => {
    if (originalDocument === undefined) delete globalThis.document;
    else globalThis.document = originalDocument;
    if (originalFrame === undefined) delete globalThis.requestAnimationFrame;
    else globalThis.requestAnimationFrame = originalFrame;
  });
  return {
    doc, node, trigger, dialog, heading,
    frame() { while (frames.length) frames.shift()(); },
    cancel() { dialog.dispatch('cancel'); },
    confirm() { form.dispatch('submit'); },
  };
}

test('Escape devolve foco ao disparador depois que withBusy o reabilita', async t => {
  const { doc, trigger, cancel, frame } = fixture(t);
  const result = withBusy(trigger, () => confirmAction({ title: 'Excluir?', message: 'Sessão fictícia.' }));
  assert.equal(trigger.disabled, true);
  cancel();
  assert.equal(doc.activeElement, doc.body);
  assert.equal(await result, false);
  assert.equal(trigger.disabled, false);
  frame();
  assert.equal(doc.activeElement, trigger);
});

test('fechar o menu da conta devolve o foco ao summary visível', async t => {
  const { doc, node, cancel, frame } = fixture(t);
  const menu = node('account-menu', 'DETAILS', doc.body);
  const summary = node('account-menu-toggle', 'SUMMARY', menu);
  const logout = node('logout-button', 'BUTTON', menu);
  menu.open = true;
  logout.focus();
  const result = confirmAction({ title: 'Sair?', message: 'Texto fictício.' });
  cancel();
  assert.equal(await result, false);
  menu.open = false;
  frame();
  assert.equal(doc.activeElement, summary);
});

test('cancelar novo relato conserva o foco que o chamador levou ao texto', async t => {
  const { doc, node, cancel, frame } = fixture(t);
  const text = node('narrative-text', 'TEXTAREA', doc.body);
  const result = confirmAction({ title: 'Novo relato?', message: 'Texto fictício.' });
  cancel();
  await result;
  text.focus();
  frame();
  assert.equal(doc.activeElement, text);
});

test('disparador removido recupera foco no heading da view visível', async t => {
  const { doc, trigger, heading, confirm, frame } = fixture(t);
  const result = confirmAction({ title: 'Excluir?', message: 'Sessão fictícia.' });
  confirm();
  assert.equal(await result, true);
  trigger.isConnected = false;
  doc.activeElement = doc.body;
  frame();
  assert.equal(doc.activeElement, heading);
});

test('restauração pendente respeita outro dialog aberto', async t => {
  const { doc, node, cancel, frame } = fixture(t);
  const result = confirmAction({ title: 'Excluir?', message: 'Sessão fictícia.' });
  cancel();
  await result;
  const about = node('about-dialog', 'DIALOG', doc.body);
  about.showModal();
  frame();
  assert.equal(doc.activeElement, about);
});

test('confirmações consecutivas ignoram a restauração da pergunta anterior', async t => {
  const { doc, node, trigger, cancel, frame } = fixture(t);
  trigger.disabled = true;
  const first = confirmAction({ title: 'Primeira?', message: 'Texto fictício.' });
  cancel();
  await first;
  const latestTrigger = node('latest-trigger', 'BUTTON', doc.body);
  latestTrigger.focus();
  latestTrigger.disabled = true;
  const second = confirmAction({ title: 'Segunda?', message: 'Texto fictício.' });
  cancel();
  await second;
  trigger.disabled = false;
  latestTrigger.disabled = false;
  frame();
  assert.equal(doc.activeElement, latestTrigger);
});
