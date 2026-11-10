export const $ = (selector) => document.querySelector(selector.startsWith('#') || selector.startsWith('.') || selector.includes(' ') || selector.includes('[') ? selector : `#${selector}`);

export const CATEGORIAS = ['feliz', 'animado', 'foco', 'calmo', 'disposto', 'reflexivo', 'triste', 'cansado', 'sofrendo', 'ansioso', 'raiva', 'explosivo', 'amor', 'normal'];
const categories = { feliz: 'Feliz', animado: 'Animado', foco: 'Foco', calmo: 'Calmo', disposto: 'Disposto', reflexivo: 'Reflexivo', triste: 'Triste', cansado: 'Cansado', sofrendo: 'Sofrendo', ansioso: 'Ansioso', raiva: 'Raiva', explosivo: 'No limite', amor: 'Amor / saudade', normal: 'Neutro / normal' };
const strategies = { transicao_emocional: 'Transição entre estados', foco_cognitivo: 'Concentração', catarse: 'Expressão do momento', ativacao_gradual: 'Ativação gradual', descompressao: 'Descompressão', ativacao: 'Disposição', espelhamento: 'Acolhimento do momento' };
export const categoriaLabel = (value) => categories[value] || String(value);
export const strategyLabel = (value) => strategies[value] || 'Sugestões a partir da sua revisão';

export function el(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes || {})) {
    if (value === undefined || value === null) continue;
    if (name === 'class' || name === 'className') node.className = value;
    else if (name === 'dataset') Object.assign(node.dataset, value);
    else if (name.startsWith('on') && typeof value === 'function') node.addEventListener(name.slice(2).toLowerCase(), value);
    else if (name.startsWith('on') || name === 'innerHTML' || name === 'style') throw new Error('Atributo de apresentação não permitido.');
    else if (['checked', 'disabled', 'hidden', 'value', 'textContent', 'htmlFor'].includes(name)) node[name] = value;
    else node.setAttribute(name, value === true ? '' : String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child !== undefined && child !== null) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function notify(message, type = 'info') {
  const target = $('#global-status');
  target.textContent = message;
  target.dataset.type = type;
  target.hidden = !message;
  target.setAttribute('role', type === 'error' ? 'alert' : 'status');
}

export async function withBusy(container, task) {
  const target = typeof container === 'string' ? $(container) : container;
  const buttons = target ? [
    ...(target.matches('button, input[type="submit"]') ? [target] : []),
    ...target.querySelectorAll('button, input[type="submit"]'),
  ] : [];
  const states = buttons.map(button => button.disabled);
  if (target) target.setAttribute('aria-busy', 'true');
  buttons.forEach(button => { button.disabled = true; });
  try { return await task(); }
  finally {
    buttons.forEach((button, index) => { button.disabled = states[index]; });
    if (target) target.removeAttribute('aria-busy');
  }
}

export function formatDate(value) {
  if (!value) return 'Data não informada';
  if (/^\d{2}\/\d{2}\/\d{4}/.test(value)) return value;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : new Intl.DateTimeFormat('pt-BR', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

let closeConfirmation = null;
let confirmationVersion = 0;
export function dismissConfirmation() { if (closeConfirmation) closeConfirmation(false); }
export function confirmAction({ title, message, label = 'Confirmar', cancelLabel = 'Cancelar' }) {
  const version = ++confirmationVersion;
  dismissConfirmation();
  const dialog = $('#confirm-dialog');
  const form = $('#confirm-form');
  const cancel = $('#confirm-cancel');
  const button = $('#confirm-submit');
  const previousFocus = document.activeElement;
  $('#confirm-title').textContent = title;
  $('#confirm-text').textContent = message;
  button.textContent = label;
  cancel.textContent = cancelLabel;
  const restoreFocus = () => {
    if (version !== confirmationVersion || document.querySelector('dialog[open]')) return;
    const available = node => {
      if (!node?.isConnected || node === document.body || node === document.documentElement
        || node.matches(':disabled') || node.closest('[hidden], [inert]') || !node.getClientRects().length) return false;
      const disclosure = node.closest('details:not([open])');
      return !disclosure || disclosure.querySelector(':scope > summary')?.contains(node);
    };
    const active = document.activeElement;
    // The caller may have moved focus after closing, for example back to its draft.
    if (!dialog.contains(active) && available(active)) return;
    const disclosure = previousFocus.closest('details:not([open])');
    const target = [previousFocus, disclosure?.querySelector(':scope > summary'),
      document.querySelector('.workspace-view:not([hidden]) h1[tabindex="-1"]')].find(available);
    target?.focus({ preventScroll: true });
  };
  return new Promise(resolve => {
    const finish = value => {
      form.removeEventListener('submit', submit);
      cancel.removeEventListener('click', cancellation);
      dialog.removeEventListener('cancel', cancellation);
      if (dialog.open) dialog.close();
      closeConfirmation = null;
      resolve(value);
      // Let withBusy re-enable its trigger before attempting to restore focus.
      if (previousFocus) {
        if (typeof requestAnimationFrame === 'function') requestAnimationFrame(restoreFocus);
        else setTimeout(restoreFocus, 0);
      }
    };
    const submit = event => { event.preventDefault(); finish(true); };
    const cancellation = event => { event.preventDefault(); finish(false); };
    closeConfirmation = finish;
    form.addEventListener('submit', submit);
    cancel.addEventListener('click', cancellation);
    dialog.addEventListener('cancel', cancellation);
    dialog.showModal();
    cancel.focus();
  });
}

export function downloadJSON(data, filename = 'rhythmmind-registros.json') {
  const objectURL = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = objectURL;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(objectURL), 1000);
}
