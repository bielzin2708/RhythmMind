import { api, setToken, onUnauthorized, StaleRequestError } from './api.js';
import { $, notify, withBusy, dismissConfirmation } from './ui.js';
import { initSession } from './session.js';
import { initHistory } from './history.js';

let user = null;
let accessEpoch = 0;
let history;
let session;
let accessBusy = false;
let googleAvailable = false;

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

function updateGoogleButton() {
  $('#google-login-button').disabled = accessBusy || !googleAvailable;
  $('#google-login-label').textContent = 'Continuar com Google';
}

async function withAccessBusy(task) {
  if (accessBusy) return;
  accessBusy = true;
  try { await withBusy($('#access-card'), task); }
  finally { accessBusy = false; updateGoogleButton(); }
}

function accessStatus(message, error = false) {
  $('#auth-status').textContent = message;
  $('#auth-status').setAttribute('role', error ? 'alert' : 'status');
}

async function configureGoogle() {
  try {
    const config = await api('/api/auth/google/config');
    const persistent = config.armazenamento === 'persistente';
    $('#environment-label').textContent = persistent ? 'Protótipo · dados locais' : 'Protótipo · dados fictícios';
    $('#development-note-text').textContent = persistent
      ? 'Seus registros ficam salvos neste computador. Use dados fictícios durante os testes.'
      : 'Use dados fictícios. Seus registros são temporários neste protótipo.';
    googleAvailable = config.disponivel === true && config.inicio_url === '/api/auth/google/iniciar';
    $('#google-access-help').textContent = googleAvailable
      ? 'Use uma guia do Chrome ou Edge para confirmar seu acesso no Google.'
      : 'O acesso com Google ainda não está disponível neste ambiente.';
  } catch (error) {
    if (isStale(error)) return;
    googleAvailable = false;
    $('#development-note-text').textContent = 'Ambiente local de desenvolvimento. Use dados fictícios.';
    $('#google-access-help').textContent = 'Não foi possível conferir o acesso com Google. Você pode entrar com sua senha.';
  } finally { updateGoogleButton(); }
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
  void configureGoogle();
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

async function activateAccess(access, attempt, message) {
  if (attempt !== accessEpoch) return;
  setToken(access.token_acesso);
  const profile = await api('/api/auth/eu');
  if (attempt !== accessEpoch) return;
  user = profile;
  $('#account-name').textContent = profile.nome_usuario;
  $('#auth-shell').hidden = true;
  $('#app-shell').hidden = false;
  setAccessAppearance(false);
  accessStatus('');
  $('#auth-login-form').reset();
  $('#auth-register-form').reset();
  clearPasswords();
  session.newSession();
  showView('session');
  notify(message, 'success');
}

async function authenticate(form, register) {
  if (accessBusy) return;
  const attempt = ++accessEpoch;
  const fields = new FormData(form);
  const credentials = { nome_usuario: String(fields.get('nome_usuario')).trim(), senha: String(fields.get('senha')) };
  await withAccessBusy(async () => {
    accessStatus(register ? 'Criando seu espaço…' : 'Conferindo seu acesso…');
    try {
      if (register) await api('/api/auth/registrar', { method: 'POST', body: credentials });
      const access = await api('/api/auth/entrar', { method: 'POST', body: credentials });
      await activateAccess(access, attempt, register
        ? 'Seu espaço está pronto. Comece um relato ou adicione faixas ao catálogo.'
        : 'Acesso confirmado. Você pode começar ou retomar uma sessão.');
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

$('#google-login-button').addEventListener('click', () => {
  if (accessBusy || !googleAvailable || user) return;
  void withAccessBusy(async () => {
    accessEpoch += 1;
    clearPasswords();
    accessStatus('Abrindo o Google para confirmar seu acesso…');
    $('#google-login-label').textContent = 'Abrindo o Google…';
    // A navegação completa mantém a autenticação fora de frames e dispensa SDK externo.
    window.location.assign('/api/auth/google/iniciar');
  });
});

async function completeGoogle() {
  if (accessBusy || user) return;
  const attempt = ++accessEpoch;
  await withAccessBusy(async () => {
    clearPasswords();
    accessStatus('Concluindo seu acesso com Google…');
    try {
      const access = await api('/api/auth/google/concluir', { method: 'POST' });
      await activateAccess(access, attempt, 'Acesso com Google confirmado. Você pode começar ou retomar uma sessão.');
    } catch (error) {
      if (!isStale(error) && attempt === accessEpoch) {
        accessStatus(error.status === 401
          ? 'O retorno do Google expirou. Tente entrar com Google novamente.'
          : 'Não foi possível concluir o acesso com Google. Tente novamente ou entre com sua senha.', true);
      }
    }
  });
}

async function initializeGoogle() {
  const current = new URL(window.location.href);
  const returned = current.searchParams.get('google');
  if (current.searchParams.has('google')) {
    current.searchParams.delete('google');
    window.history.replaceState(null, '', `${current.pathname}${current.search}${current.hash}`);
    if (returned === 'concluir') await completeGoogle();
    else if (returned === 'cancelado') accessStatus('Você cancelou o acesso com Google. Pode tentar novamente quando quiser.');
    else if (returned === 'indisponivel') accessStatus('O acesso com Google está indisponível neste momento. Você pode entrar com sua senha.', true);
    else accessStatus('Não foi possível confirmar o acesso com Google. Tente novamente ou entre com sua senha.', true);
  }
  await configureGoogle();
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
void initializeGoogle();
