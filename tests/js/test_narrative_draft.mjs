import assert from 'node:assert/strict';
import test from 'node:test';
import { createNarrativeDraft } from '../../static/narrative-draft.js';
import { confirmAction } from '../../static/ui.js';

function fixture(confirm = async () => false) {
  const text = { tagName: 'TEXTAREA', type: 'textarea', name: 'texto_atual', defaultValue: '', value: '' };
  const purpose = { tagName: 'INPUT', type: 'text', name: 'finalidade', defaultValue: '', value: '' };
  const context = { tagName: 'TEXTAREA', type: 'textarea', name: 'contexto', defaultValue: '', value: '' };
  const options = [1, 3, 5].map(value => ({ value: String(value), defaultSelected: value === 3, selected: value === 3 }));
  const limit = { tagName: 'SELECT', type: 'select-one', name: 'limite', options };
  const fallback = { tagName: 'INPUT', type: 'checkbox', id: 'allow-fallback', defaultChecked: false, checked: false };
  const form = { elements: [text, purpose, context, limit, fallback] };
  return { text, purpose, context, options, fallback, guard: createNarrativeDraft(form, { confirm }) };
}

test('formulário padrão não pede confirmação; reverter o texto remove a alteração', async () => {
  let calls = 0;
  const { guard, text } = fixture(async () => { calls += 1; return false; });
  assert.equal(guard.hasChanges(), false);
  assert.equal(await guard.confirmDiscard(), true);
  text.value = 'Relato fictício 😌';
  assert.equal(guard.hasChanges(), true);
  text.value = '';
  assert.equal(guard.hasChanges(), false);
  assert.equal(await guard.confirmDiscard(), true);
  assert.equal(calls, 0);
});

test('cancelar o descarte preserva texto e alterações; a mensagem diferencia os dados salvos', async () => {
  let question;
  const { guard, text } = fixture(async options => { question = options; return false; });
  text.value = 'Quero preservar este relato fictício.';
  assert.equal(await guard.confirmDiscard(), false);
  assert.equal(text.value, 'Quero preservar este relato fictício.');
  assert.equal(guard.hasChanges(), true);
  assert.equal(question.cancelLabel, 'Continuar escrevendo');
  assert.equal(question.label, 'Descartar e começar outro');
  assert.match(question.message, /registros já salvos serão mantidos/);
});

test('confirmar libera a limpeza pelo chamador e só reset redefine a referência', async () => {
  const { guard, text } = fixture(async () => true);
  text.value = 'Rascunho fictício';
  assert.equal(await guard.confirmDiscard(), true);
  assert.equal(text.value, 'Rascunho fictício');
  assert.equal(guard.hasChanges(), true);
  text.value = '';
  guard.reset();
  assert.equal(guard.hasChanges(), false);
});

test('finalidade, contexto, limite e checkbox sem name também são protegidos', () => {
  const { guard, purpose, context, options, fallback } = fixture();
  for (const field of [purpose, context]) {
    field.value = 'Conteúdo fictício';
    assert.equal(guard.hasChanges(), true);
    field.value = '';
    assert.equal(guard.hasChanges(), false);
  }
  options[1].selected = false;
  options[2].selected = true;
  assert.equal(guard.hasChanges(), true);
  options[2].selected = false;
  options[1].selected = true;
  assert.equal(guard.hasChanges(), false);
  fallback.checked = true;
  assert.equal(guard.hasChanges(), true);
  fallback.checked = false;
  assert.equal(guard.hasChanges(), false);
});

test('envio com erro preserva o estado não enviado; sucesso passa a reconhecer o texto salvo', async () => {
  let calls = 0;
  const { guard, text } = fixture(async () => { calls += 1; return false; });
  text.value = 'Relato fictício a enviar';
  const sent = guard.capture();
  // O chamador não marca sucesso quando o POST falha.
  assert.equal(await guard.confirmDiscard(), false);
  guard.markSaved(sent);
  assert.equal(guard.hasChanges(), false);
  assert.equal(await guard.confirmDiscard(), true);
  assert.equal(calls, 1);
  text.value += ' — ajuste posterior';
  assert.equal(guard.hasChanges(), true);
});

test('sucesso de um envio anterior não apaga a proteção de uma edição feita durante a espera', () => {
  const { guard, text } = fixture();
  text.value = 'Versão enviada';
  const sent = guard.capture();
  text.value = 'Versão ajustada durante o envio';
  guard.markSaved(sent);
  assert.equal(guard.hasChanges(), true);
  text.value = 'Versão enviada';
  assert.equal(guard.hasChanges(), false);
});

test('excluir a versão salva invalida a referência sem descartar o texto em elaboração', async () => {
  const { guard, text } = fixture(async () => false);
  text.value = 'Versão salva fictícia';
  guard.markSaved();
  text.value = 'Versão mais recente ainda não enviada';
  guard.reset({ toDefaults: true });
  assert.equal(text.value, 'Versão mais recente ainda não enviada');
  assert.equal(await guard.confirmDiscard(), false);
  // Voltar ao texto do registro excluído também não equivale a salvá-lo novamente.
  text.value = 'Versão salva fictícia';
  assert.equal(guard.hasChanges(), true);
});

test('dois pedidos simultâneos compartilham uma confirmação e uma decisão', async () => {
  let calls = 0;
  let decide;
  const { guard, text } = fixture(() => {
    calls += 1;
    return new Promise(resolve => { decide = resolve; });
  });
  text.value = 'Relato em elaboração';
  const first = guard.confirmDiscard();
  const second = guard.confirmDiscard();
  assert.equal(first, second);
  await Promise.resolve();
  assert.equal(calls, 1);
  decide(false);
  assert.deepEqual(await Promise.all([first, second]), [false, false]);
  assert.equal(guard.hasChanges(), true);
});

test('erro ao abrir confirmação não descarta conteúdo e permite nova tentativa', async () => {
  let calls = 0;
  const { guard, text } = fixture(async () => {
    calls += 1;
    if (calls === 1) throw new Error('Falha de interface simulada');
    return false;
  });
  text.value = 'Relato preservado';
  await assert.rejects(guard.confirmDiscard(), /Falha de interface/);
  assert.equal(guard.hasChanges(), true);
  assert.equal(await guard.confirmDiscard(), false);
  assert.equal(calls, 2);
});

test('abertura de registro e saída podem explicar a ação correta sem mudar o rascunho', async () => {
  let question;
  const { guard, text } = fixture(async options => { question = options; return false; });
  text.value = 'Rascunho fictício em elaboração';
  assert.equal(await guard.confirmDiscard({
    title: 'Abrir o registro salvo?',
    message: 'O texto ainda não enviado será descartado se você abrir outro registro.',
    label: 'Descartar e abrir registro',
  }), false);
  assert.equal(question.title, 'Abrir o registro salvo?');
  assert.equal(question.label, 'Descartar e abrir registro');
  assert.equal(question.cancelLabel, 'Continuar escrevendo');
  assert.equal(text.value, 'Rascunho fictício em elaboração');
});

test('valor preenchido antes da inicialização é tratado como diferente do padrão vazio', () => {
  const text = { tagName: 'TEXTAREA', type: 'textarea', name: 'texto_atual', defaultValue: '', value: 'Texto pré-preenchido' };
  const guard = createNarrativeDraft({ elements: [text] }, { confirm: async () => false });
  assert.equal(guard.hasChanges(), true);
  guard.markSaved();
  assert.equal(guard.hasChanges(), false);
});

test('rótulo de cancelamento personalizado não vaza para a próxima confirmação comum', async () => {
  const previousDocument = globalThis.document;
  const nodes = new Map();
  function node(id) {
    const listeners = new Map();
    const value = {
      textContent: '', open: false,
      addEventListener(type, handler) { listeners.set(type, handler); },
      removeEventListener(type) { listeners.delete(type); },
      focus() {},
      showModal() { this.open = true; },
      close() { this.open = false; },
      cancel() { listeners.get('click')?.({ preventDefault() {} }); },
    };
    nodes.set(id, value);
    return value;
  }
  for (const id of ['confirm-dialog', 'confirm-form', 'confirm-cancel', 'confirm-submit', 'confirm-title', 'confirm-text']) node(id);
  globalThis.document = { querySelector: selector => nodes.get(selector.slice(1)), activeElement: null };
  try {
    const discard = confirmAction({ title: 'Descartar?', message: 'Texto fictício.', cancelLabel: 'Continuar escrevendo' });
    assert.equal(nodes.get('confirm-cancel').textContent, 'Continuar escrevendo');
    nodes.get('confirm-cancel').cancel();
    assert.equal(await discard, false);
    const deletion = confirmAction({ title: 'Excluir registro?', message: 'Operação fictícia.' });
    assert.equal(nodes.get('confirm-cancel').textContent, 'Cancelar');
    nodes.get('confirm-cancel').cancel();
    assert.equal(await deletion, false);
  } finally {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  }
});
