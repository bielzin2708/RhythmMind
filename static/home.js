import { $, el, formatDate, CATEGORIAS, categoriaLabel, accountIdentity } from './ui.js';

const STAGES = {
  revisao: { kind: 'revisao', label: 'Revisão pendente', action: 'Continuar sessão' },
  intencao: { kind: 'intencao', label: 'Intenção pendente', action: 'Continuar sessão' },
  sugestoes: { kind: 'sugestoes', label: 'Sugestões pendentes', action: 'Continuar sessão' },
  escuta: { kind: 'escuta', label: 'Escuta pendente', action: 'Registrar minha escuta' },
  retorno: { kind: 'retorno', label: 'Retorno opcional', action: 'Registrar meu retorno' },
};

export function sessionPending(record) {
  const progress = record.progresso;
  if (progress && progress.recomendacoes_geradas !== true) {
    if (progress.emocoes_confirmadas !== true) return STAGES.revisao;
    if (progress.estado_desejado_informado !== true) return STAGES.intencao;
    return STAGES.sugestoes;
  }
  // Uma sessão salva sem sugestões não exige escolha, escuta ou avaliação.
  if (!Array.isArray(record.recomendacoes) || record.recomendacoes.length === 0) return null;
  const listening = record.escuta;
  if (!listening || !Array.isArray(listening.faixas)) return STAGES.escuta;
  if (listening.faixas.some(track => typeof track?.ouvida !== 'boolean')) return STAGES.escuta;
  // [] registra explicitamente nenhuma faixa; false registra escuta negativa.
  // Nenhum desses valores é confundido com uma resposta ainda não informada.
  if (typeof record.feedback?.ajudou !== 'boolean' || record.feedback.coleta_concluida === false) return STAGES.retorno;
  return null;
}

function timestamp(value) {
  if (typeof value !== 'string') return null;
  const local = /^(\d{2})\/(\d{2})\/(\d{4})(?: (\d{2}):(\d{2})(?::(\d{2}))?)?$/.exec(value);
  if (local) {
    const [, day, month, year, hour = '0', minute = '0', second = '0'] = local;
    const date = new Date(+year, +month - 1, +day, +hour, +minute, +second);
    if (date.getFullYear() !== +year || date.getMonth() !== +month - 1 || date.getDate() !== +day
      || date.getHours() !== +hour || date.getMinutes() !== +minute || date.getSeconds() !== +second) return null;
    return date.getTime();
  }
  const iso = /^(\d{4})-(\d{2})-(\d{2})T/.exec(value);
  if (!iso) return null;
  const year = +iso[1], month = +iso[2], day = +iso[3];
  const february = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 29 : 28;
  const days = [31, february, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (month < 1 || month > 12 || day < 1 || day > days[month - 1]) return null;
  const instant = Date.parse(value);
  return Number.isNaN(instant) ? null : instant;
}

function summary(value) {
  const text = typeof value === 'string' ? value.trim().replace(/\s+/g, ' ') : '';
  const characters = Array.from(text);
  return characters.length > 80 ? `${characters.slice(0, 79).join('')}…` : text;
}

function orderedRecords(records) {
  if (!records || typeof records !== 'object' || Array.isArray(records)) throw new TypeError('Histórico inválido.');
  const entries = Object.entries(records).map(([id, record], order) => {
    if (!record || typeof record !== 'object' || Array.isArray(record)) throw new TypeError('Registro inválido.');
    const savedDate = timestamp(record.data_hora) !== null ? record.data_hora : timestamp(id) !== null ? id : null;
    return {
      id,
      record,
      date: savedDate ? formatDate(savedDate) : 'Data não informada',
      instant: timestamp(savedDate),
      order,
    };
  });
  entries.sort((a, b) => a.instant !== null && a.instant === b.instant
    ? b.order - a.order
    : (b.instant ?? -Infinity) - (a.instant ?? -Infinity));
  return entries;
}

export function recordsForHome(records) {
  const entries = orderedRecords(records).map(({ id, record, date, instant }) => ({
    id, date, instant,
    title: summary(record.finalidade) || summary(record.texto_usuario) || 'Sessão de escuta',
    stage: sessionPending(record),
  }));
  return { pending: entries.filter(entry => entry.stage).slice(0, 3), recent: entries.slice(0, 4) };
}

export function summarizeHome(records) {
  const entries = orderedRecords(records);
  const confirmed = entries.find(({ record }) => {
    const categories = record.analise?.emocoes;
    if (!Array.isArray(categories) || !categories.every(category => CATEGORIAS.includes(category))) return false;
    if (record.progresso == null) return categories.length > 0;
    return record.progresso.emocoes_confirmadas === true;
  });
  const categories = confirmed ? [...new Set(confirmed.record.analise.emocoes)] : [];
  const lastState = !confirmed ? 'Não informado' : categories.length === 0 ? 'Sem categoria'
    : categories.slice(0, 2).map(categoriaLabel).join(', ') + (categories.length > 2 ? ` +${categories.length - 2}` : '');
  const purpose = entries.find(({ record }) => summary(record.finalidade));
  const totalListens = entries.reduce((total, { record }) => {
    const tracks = record.escuta?.faixas;
    return total + (Array.isArray(tracks) ? tracks.filter(track => track?.ouvida === true).length : 0);
  }, 0);
  return {
    totalSessions: entries.length,
    totalListens,
    lastPurpose: purpose ? summary(purpose.record.finalidade) : 'Não informado',
    lastState,
    lastStateDate: confirmed ? confirmed.date : '—',
    lastStateCategories: categories,
  };
}

export function catalogTotal(response) {
  if (!response || typeof response !== 'object' || Array.isArray(response)) throw new TypeError('Catálogo inválido.');
  if (Number.isSafeInteger(response.total) && response.total >= 0) return response.total;
  if (Array.isArray(response.musicas)) return response.musicas.length;
  throw new TypeError('Catálogo inválido.');
}

export function initHome({ api, onNew, onQuickObjective = () => {}, onStarterCatalog = null, onResume, onRecord, onHistory, onCatalog }) {
  let version = 0;
  let activeUser = false;
  const pendingList = $('#home-pending-list');
  const recentList = $('#home-recent-list');

  function status(message = '', error = false) {
    const target = $('#home-status');
    target.textContent = message;
    target.hidden = !message;
    target.dataset.type = error ? 'error' : 'info';
    target.setAttribute('role', error ? 'alert' : 'status');
  }

  function loading(busy) {
    for (const list of [pendingList, recentList]) list.setAttribute('aria-busy', String(busy));
    for (const id of ['profile-sessions', 'profile-last-purpose', 'profile-catalog', 'home-total-sessions',
      'home-last-state', 'home-last-state-date', 'home-total-listens', 'home-total-tracks']) {
      $(`#${id}`).setAttribute('aria-busy', String(busy));
    }
  }

  function clearHistoryMetrics() {
    for (const id of ['profile-sessions', 'profile-last-purpose', 'home-total-sessions',
      'home-last-state-date', 'home-total-listens']) $(`#${id}`).textContent = '—';
    $('#home-last-state').textContent = 'Não informado';
    $('#home-last-state').removeAttribute('title');
  }

  function setCatalogLinkLabel(label) {
    $('#home-open-catalog').replaceChildren(
      document.createTextNode(`${label} `),
      el('span', { 'aria-hidden': 'true' }, '→'),
    );
  }

  function clearCatalogMetrics() {
    $('#profile-catalog').textContent = '—';
    $('#home-total-tracks').textContent = '—';
    $('#home-catalog-description').textContent = 'Organize as faixas disponíveis para suas próximas escutas.';
    $('#home-starter-catalog').hidden = true;
    setCatalogLinkLabel('Explorar músicas');
  }

  function renderHistoryMetrics(records) {
    const result = summarizeHome(records);
    const sessions = result.totalSessions.toLocaleString('pt-BR');
    $('#profile-sessions').textContent = sessions;
    $('#home-total-sessions').textContent = sessions;
    $('#profile-last-purpose').textContent = result.lastPurpose;
    $('#home-total-listens').textContent = result.totalListens.toLocaleString('pt-BR');
    $('#home-last-state').textContent = result.lastState;
    $('#home-last-state-date').textContent = result.lastStateDate;
    $('#home-last-state').title = result.lastStateCategories.length
      ? `${result.lastStateCategories.map(categoriaLabel).join(', ')} · ${result.lastStateDate}`
      : `${result.lastState} · ${result.lastStateDate}`;
  }

  function renderCatalogMetrics(response) {
    const total = catalogTotal(response);
    $('#home-total-tracks').textContent = total.toLocaleString('pt-BR');
    $('#profile-catalog').textContent = `${total.toLocaleString('pt-BR')} ${total === 1 ? 'faixa' : 'faixas'}`;
    $('#home-catalog-description').textContent = total === 0
      ? 'Conta nova sem músicas ainda. Carregue a seleção inicial em um clique ou adicione suas faixas.'
      : 'Organize as faixas disponíveis para suas próximas escutas.';
    $('#home-starter-catalog').hidden = total !== 0 || typeof onStarterCatalog !== 'function';
    setCatalogLinkLabel(total === 0 ? 'Adicionar músicas' : 'Explorar músicas');
  }

  function clear() {
    pendingList.replaceChildren();
    recentList.replaceChildren();
    $('#home-pending-empty').hidden = true;
    $('#home-recent-empty').hidden = true;
    $('#home-retry').hidden = true;
    clearHistoryMetrics();
    clearCatalogMetrics();
  }

  function reset() {
    version += 1;
    activeUser = false;
    clear();
    status();
    loading(false);
    $('#home-greeting').textContent = 'Seu espaço';
  }

  function updateGreeting(profile) {
    const name = summary(accountIdentity(profile).greetingName);
    $('#home-greeting').textContent = name ? `Olá, ${name}.` : 'Bem-vindo ao seu espaço.';
  }

  function setUser(profile) {
    reset();
    activeUser = Boolean(profile);
    updateGreeting(profile);
  }

  function pendingCard(entry, renderedVersion) {
    const button = el('button', { type: 'button', class: 'button button-secondary home-card-action' }, entry.stage.action);
    button.addEventListener('click', () => {
      if (activeUser && version === renderedVersion) onResume(entry.id, entry.stage.kind);
    });
    return el('article', { class: 'home-card home-pending-card' },
      el('div', { class: 'home-card-header' },
        el('h3', { class: 'home-card-title' }, entry.title),
        el('span', { class: 'home-status-badge' }, entry.stage.label)),
      el('p', { class: 'home-card-meta' }, entry.date), button);
  }

  function recentRow(entry, renderedVersion) {
    const button = el('button', {
      type: 'button',
      class: 'button-link home-card-action nav-destination',
      'aria-label': `Ver registro: ${entry.title}`,
    }, 'Ver registro ', el('span', { 'aria-hidden': 'true' }, '→'));
    button.addEventListener('click', () => {
      if (activeUser && version === renderedVersion) onRecord(entry.id);
    });
    return el('article', { class: 'home-record-row' },
      el('div', { class: 'home-record-copy' }, el('h3', { class: 'home-card-title' }, entry.title),
        el('p', { class: 'home-card-meta' }, entry.date)), button);
  }

  async function load() {
    if (!activeUser) return;
    const requestVersion = ++version;
    clear();
    loading(true);
    status('Buscando seus registros e catálogo…');
    try {
      const [history, catalog] = await Promise.allSettled([api('/api/historico'), api('/api/musicas')]);
      if (requestVersion !== version || !activeUser) return;
      const unavailable = [];
      if (history.status === 'fulfilled') {
        try {
          const records = recordsForHome(history.value.registros);
          renderHistoryMetrics(history.value.registros);
          records.pending.forEach(entry => pendingList.append(pendingCard(entry, requestVersion)));
          records.recent.forEach(entry => recentList.append(recentRow(entry, requestVersion)));
          $('#home-pending-empty').hidden = records.pending.length > 0;
          $('#home-recent-empty').hidden = records.recent.length > 0;
        } catch { unavailable.push('histórico'); }
      } else if (!['StaleRequestError', 'AbortError'].includes(history.reason?.name)) unavailable.push('histórico');
      if (catalog.status === 'fulfilled') {
        try { renderCatalogMetrics(catalog.value); }
        catch { unavailable.push('catálogo'); }
      } else if (!['StaleRequestError', 'AbortError'].includes(catalog.reason?.name)) unavailable.push('catálogo');
      if (unavailable.length) {
        status(unavailable.length === 2
          ? 'Não foi possível carregar seu histórico e catálogo agora. Tente novamente.'
          : `Não foi possível carregar seu ${unavailable[0]} agora. As outras informações disponíveis foram preservadas.`, true);
        $('#home-retry').hidden = false;
      } else status();
    } catch (error) {
      if (requestVersion !== version || !activeUser || ['StaleRequestError', 'AbortError'].includes(error?.name)) return;
      clear();
      status('Não foi possível carregar seus registros agora. Tente novamente.', true);
      $('#home-retry').hidden = false;
    } finally {
      if (requestVersion === version) loading(false);
    }
  }

  $('#home-new-session').addEventListener('click', () => { if (activeUser) onNew(); });
  for (const [id, objective] of [
    ['home-quick-relax', 'calmo'],
    ['home-quick-focus', 'foco'],
    ['home-quick-energy', 'disposto'],
  ]) {
    $(`#${id}`).addEventListener('click', () => { if (activeUser) onQuickObjective(objective); });
  }
  $('#home-starter-catalog').addEventListener('click', () => {
    if (activeUser && typeof onStarterCatalog === 'function') void onStarterCatalog($('#home-starter-catalog'));
  });
  $('#home-open-history').addEventListener('click', () => { if (activeUser) onHistory(); });
  $('#home-explore-history').addEventListener('click', () => { if (activeUser) onHistory(); });
  $('#home-open-catalog').addEventListener('click', () => { if (activeUser) onCatalog(); });
  $('#home-retry').addEventListener('click', () => { void load(); });
  reset();
  return { load, reset, setUser, updateGreeting };
}
