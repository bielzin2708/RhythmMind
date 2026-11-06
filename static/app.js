import { api, setToken, onUnauthorized, StaleRequestError } from './api.js';
import { $, notify, withBusy, dismissConfirmation } from './ui.js';
import { initSession } from './session.js';
import { initHistory } from './history.js';

let user = null;
let accessEpoch = 0;
let history;
let session;

function isStale(error) { return error instanceof StaleRequestError || error.name === 'StaleRequestError'; }

function setAccessAppearance(access) {
  document.body.classList.toggle('auth-screen', access);
  document.querySelector('meta[name="color-scheme"]').content = access ? 'dark' : 'light';
  document.querySelector('meta[name="theme-color"]').content = access ? '#0B1329' : '#193440';
}

function resetPasswordVisibility(form) {
  const input = form.elements.namedItem('senha');
  if (input) input.type = 'password';
  const button = form.querySelector('[data-toggle-password]');
  if (!button) return;
  button.setAttribute('aria-pressed', 'false');
  button.setAttribute('aria-label', 'Mostrar senha');
  button.querySelector('[data-password-label]').textContent = 'Mostrar';
}

function clearPasswords() {
  for (const id of ['auth-login-form', 'auth-register-form']) {
    const form = $(id);
    form.elements.namedItem('senha').value = '';
    resetPasswordVisibility(form);
  }
}

for (const button of document.querySelectorAll('[data-toggle-password]')) {
  button.addEventListener('click', () => {
    const input = document.getElementById(button.dataset.togglePassword);
    const visible = input.type === 'password';
    input.type = visible ? 'text' : 'password';
    button.setAttribute('aria-pressed', String(visible));
    button.setAttribute('aria-label', visible ? 'Ocultar senha' : 'Mostrar senha');
    button.querySelector('[data-password-label]').textContent = visible ? 'Ocultar' : 'Mostrar';
  });
}

function showView(next) {
  if (!user) return;
  for (const name of ['session', 'history', 'catalog']) {
    $(`#view-${name}`).hidden = name !== next;
    const navigation = $(`#nav-${name}`);
    navigation.classList.toggle('active', name === next);
    if (name === next) navigation.setAttribute('aria-current', 'page');
    else navigation.removeAttribute('aria-current');
  }
  if (next === 'history') void history.load();
  if (next === 'catalog') void session.loadCatalog();
  if (next === 'session') void session.loadDrafts();
}

function onChanged(change = {}) {
  if (!user) return;
  if (change.deletedIds?.length) session.invalidateDeleted(change.deletedIds);
  void session.loadDrafts();
}

function clearIdentity() {
  accessEpoch += 1;
  user = null;
  setToken(null);
  dismissConfirmation();
  session.reset();
  history.reset();
  $('#account-name').textContent = '';
  $('#app-shell').hidden = true;
  $('#auth-shell').hidden = false;
  setAccessAppearance(true);
  $('#auth-login-form').hidden = false;
  $('#auth-register-form').hidden = true;
  $('#auth-login-form').reset();
  $('#auth-register-form').reset();
  clearPasswords();
  $('#auth-status').textContent = '';
  notify('');
  $('#login-name').focus();
}

session = initSession({ api, notify, onChanged,
  onHistory: () => showView('history'), onCatalog: () => showView('catalog'),
});
history = initHistory({ api, notify, onChanged,
  onResume: async id => { showView('session'); await session.open(id); },
});

onUnauthorized(() => {
  clearIdentity();
  notify('Seu acesso terminou. Entre novamente; seus registros salvos permanecem no servidor.', 'error');
});

for (const name of ['session', 'history', 'catalog']) {
  $(`#nav-${name}`).addEventListener('click', () => showView(name));
}

$('#show-register').addEventListener('click', () => {
  clearPasswords();
  $('#auth-login-form').hidden = true;
  $('#auth-register-form').hidden = false;
  $('#auth-status').textContent = '';
  $('#register-name').focus();
});
$('#show-login').addEventListener('click', () => {
  clearPasswords();
  $('#auth-register-form').hidden = true;
  $('#auth-login-form').hidden = false;
  $('#auth-status').textContent = '';
  $('#login-name').focus();
});

async function authenticate(form, register) {
  const attempt = ++accessEpoch;
  const fields = new FormData(form);
  const credentials = { nome_usuario: String(fields.get('nome_usuario')).trim(), senha: String(fields.get('senha')) };
  await withBusy(form, async () => {
    $('#auth-status').textContent = register ? 'Criando seu espaço…' : 'Conferindo seu acesso…';
    $('#auth-status').setAttribute('role', 'status');
    try {
      if (register) await api('/api/auth/registrar', { method: 'POST', body: credentials });
      const access = await api('/api/auth/entrar', { method: 'POST', body: credentials });
      if (attempt !== accessEpoch) return;
      setToken(access.token_acesso);
      const profile = await api('/api/auth/eu');
      if (attempt !== accessEpoch) return;
      user = profile;
      $('#account-name').textContent = profile.nome_usuario;
      $('#auth-shell').hidden = true;
      $('#app-shell').hidden = false;
      setAccessAppearance(false);
      $('#auth-status').textContent = '';
      form.reset();
      session.newSession();
      showView('session');
      notify(register ? 'Seu espaço está pronto. Comece um relato ou adicione faixas ao catálogo.' : 'Acesso confirmado. Você pode começar ou retomar uma sessão.', 'success');
    } catch (error) {
      if (!isStale(error) && attempt === accessEpoch) {
        $('#auth-status').textContent = error.message;
        $('#auth-status').setAttribute('role', 'alert');
        if (register && error.status !== 409) notify('Se a conta já foi criada, use Entrar para continuar.', 'info');
      }
    } finally {
      // Senhas não ficam no formulário depois de uma tentativa.
      form.elements.namedItem('senha').value = '';
      resetPasswordVisibility(form);
      credentials.senha = '';
    }
  });
}

for (const [id, register] of [['auth-login-form', false], ['auth-register-form', true]]) {
  $(id).addEventListener('submit', event => { event.preventDefault(); void authenticate(event.currentTarget, register); });
}

$('#logout-button').addEventListener('click', () => {
  void withBusy($('#logout-button').parentElement, async () => {
    let confirmed = false;
    try { await api('/api/auth/sair', { method: 'POST' }); confirmed = true; }
    catch (error) { if (isStale(error)) return; }
    clearIdentity();
    notify(confirmed ? 'Você saiu do seu espaço.' : 'Acesso encerrado neste navegador. O servidor não confirmou a saída; tente entrar novamente se precisar continuar.', confirmed ? 'info' : 'error');
  });
});

// A sessão é retomada após autenticação, sempre a partir do servidor.
$('#global-status').hidden = true;
