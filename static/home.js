import { $, el, formatDate } from './ui.js';

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

export function recordsForHome(records) {
  if (!records || typeof records !== 'object' || Array.isArray(records)) throw new TypeError('Histórico inválido.');
  const entries = Object.entries(records).map(([id, record]) => {
    if (!record || typeof record !== 'object' || Array.isArray(record)) throw new TypeError('Registro inválido.');
    const savedDate = timestamp(record.data_hora) !== null ? record.data_hora : timestamp(id) !== null ? id : null;
    return {
      id,
      title: summary(record.finalidade) || summary(record.texto_usuario) || 'Sessão de escuta',
      date: savedDate ? formatDate(savedDate) : 'Data não informada',
      instant: timestamp(savedDate),
      stage: sessionPending(record),
    };
  });
  entries.sort((a, b) => (b.instant ?? -Infinity) - (a.instant ?? -Infinity));
  return { pending: entries.filter(entry => entry.stage).slice(0, 3), recent: entries.slice(0, 4) };
}

export function initHome({ api, onNew, onResume, onRecord, onHistory, onCatalog }) {
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
  }

  function clear() {
    pendingList.replaceChildren();
    recentList.replaceChildren();
    $('#home-pending-empty').hidden = true;
    $('#home-recent-empty').hidden = true;
    $('#home-retry').hidden = true;
  }

  function reset() {
    version += 1;
    activeUser = false;
    clear();
    status();
    loading(false);
    $('#home-greeting').textContent = 'Seu espaço';
  }

  function setUser(profile) {
    reset();
    activeUser = Boolean(profile);
    const name = summary(profile?.nome_usuario);
    $('#home-greeting').textContent = name ? `Olá, ${name}.` : 'Bem-vindo ao seu espaço.';
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
    const button = el('button', { type: 'button', class: 'button-link home-card-action', 'aria-label': `Ver registro: ${entry.title}` }, 'Ver registro →');
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
    status('Buscando seus registros…');
    try {
      const response = await api('/api/historico');
      if (requestVersion !== version || !activeUser) return;
      const records = recordsForHome(response.registros);
      records.pending.forEach(entry => pendingList.append(pendingCard(entry, requestVersion)));
      records.recent.forEach(entry => recentList.append(recentRow(entry, requestVersion)));
      $('#home-pending-empty').hidden = records.pending.length > 0;
      $('#home-recent-empty').hidden = records.recent.length > 0;
      status();
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
  $('#home-open-history').addEventListener('click', () => { if (activeUser) onHistory(); });
  $('#home-open-catalog').addEventListener('click', () => { if (activeUser) onCatalog(); });
  $('#home-retry').addEventListener('click', () => { void load(); });
  reset();
  return { load, reset, setUser };
}
