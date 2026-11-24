import { $, el, categoriaLabel, strategyLabel, withBusy, confirmAction, CATEGORIAS } from './ui.js';
import { createNarrativeDraft } from './narrative-draft.js';
import { renderCategories, clearCategories } from './review-categories.js';
import { recommendationState, currentCatalogState } from './listening-state.js';
import { createCatalogReference, renderCatalogCard, safeCatalogSource } from './catalog-reference.js';
import { createCatalogBrowser, createCatalogAssociations } from './catalog-browser.js';

const REFERENCIAS = {
  RM01: 'Estado atual, intenção e atividade são informações distintas.',
  RM02: 'Mais de um sentimento pode coexistir.',
  RM03: 'A escuta durante tarefas de concentração exige atenção ao contexto.',
  RM04: 'A experiência de relaxamento e treino varia entre pessoas e situações.',
  RM05: 'A interpretação é provisória e usa linguagem cotidiana.',
  RM06: 'A pessoa revisa a sugestão e pode seguir sem categoria.',
  RM07: 'Negação, momento e pessoa de quem se fala precisam ser considerados.',
  RM08: 'As faixas vêm do catálogo e das regras de seleção após a revisão.',
};

const FAIXAS_EXEMPLO = [
  { nome: 'Pausa Fictícia', artista: 'Artista de Exemplo', duracao: '3:00', sentimentos_texto: 'calmo cansado reflexivo triste sofrendo amor' },
  { nome: 'Passo Fictício', artista: 'Artista de Exemplo', duracao: '2:30', sentimentos_texto: 'animado disposto feliz raiva explosivo' },
  { nome: 'Horizonte Fictício', artista: 'Artista de Exemplo', duracao: '3:20', sentimentos_texto: 'foco normal ansioso calmo' },
];

const OBJECTIVE_CONFIG = {
  calmo: { desired: ['calmo'], fallbackState: [], purpose: 'Relaxar', mood: 'calm' },
  foco: { desired: ['foco'], fallbackState: [], purpose: 'Focar', mood: 'focus' },
  disposto: { desired: ['disposto'], fallbackState: [], purpose: 'Ganhar energia', mood: 'energy' },
  espelhar: { desired: [], fallbackState: ['reflexivo'], purpose: 'Refletir', mood: 'reflect' },
};

function joinLabelsPt(values) {
  const names = values
    .filter(value => CATEGORIAS.includes(value))
    .map(value => categoriaLabel(value).toLocaleLowerCase('pt-BR'));
  if (!names.length) return '';
  if (names.length === 1) return names[0];
  return `${names.slice(0, -1).join(', ')} e ${names.at(-1)}`;
}

export function buildReviewQuestion(emocoes = [], desejos = []) {
  const current = joinLabelsPt(emocoes);
  const desired = joinLabelsPt(desejos);
  if (current && desired) {
    return `Você quis dizer que está ${current} e busca ficar ${desired}?`;
  }
  if (current) {
    return `Você quis dizer que está ${current}?`;
  }
  if (desired) {
    return `Você quis dizer que busca ficar ${desired}?`;
  }
  return 'Não identificamos uma sensação clara na nota. Quer escolher abaixo ou seguir sem categoria?';
}

export function resolveQuickSelection({ objective = '', states = [] } = {}) {
  const cleanStates = states.filter((item, idx) => CATEGORIAS.includes(item) && states.indexOf(item) === idx);
  const config = OBJECTIVE_CONFIG[objective];
  if (!config) {
    return {
      emocoes_atuais: cleanStates,
      estado_desejado: [],
      finalidadeSugerida: '',
      mood: cleanStates.includes('calmo') ? 'calm'
        : cleanStates.includes('foco') ? 'focus'
          : cleanStates.some(s => ['animado', 'disposto', 'feliz'].includes(s)) ? 'energy'
            : cleanStates.length ? 'reflect' : 'neutral',
    };
  }
  return {
    emocoes_atuais: cleanStates.length ? cleanStates : [...config.fallbackState],
    estado_desejado: [...config.desired],
    finalidadeSugerida: config.purpose,
    mood: config.mood,
  };
}

export function humanizeTrackReason(music = {}, reason = null, estrategia = null) {
  const criteria = Array.isArray(reason?.criterios) ? reason.criterios : [];
  const confirmed = criteria.filter(c => c.tipo === 'emocao_confirmada' && c.valor).map(c => categoriaLabel(c.valor));
  const bridges = criteria.filter(c => c.tipo === 'categoria_ponte' && c.valor).map(c => categoriaLabel(c.valor));
  const hasStrategy = criteria.some(c => c.tipo === 'estrategia');
  const songTags = Array.isArray(music.sentimentos_associados)
    ? music.sentimentos_associados.filter(v => CATEGORIAS.includes(v)).slice(0, 3).map(categoriaLabel)
    : [];
  const parts = [];
  if (confirmed.length) {
    parts.push(`Marcada como ${confirmed.join(', ')} no seu catálogo (confirmada por você)`);
  } else if (bridges.length) {
    parts.push(`Marcada como ${bridges.join(', ')} no seu catálogo para fazer a transição aos poucos`);
  } else if (songTags.length) {
    parts.push(`Marcada como ${songTags.join(', ')} no seu catálogo`);
  }
  if (hasStrategy && estrategia) {
    parts.push(`selecionada para ${strategyLabel(estrategia).toLocaleLowerCase('pt-BR')}`);
  }
  if (parts.length) return `${parts.join(' · ')}.`;
  return reason?.explicacao || 'Faixa presente no seu catálogo e selecionada conforme os critérios escolhidos.';
}

function stale(error) {
  return error?.name === 'StaleRequestError' || error?.name === 'AbortError';
}

function readableError(error) {
  if (error?.status === 409) return 'Esta sessão mudou desde a última leitura. Abra o registro novamente para continuar com a versão salva.';
  if (error?.status === 404) return 'Esta sessão não está mais disponível na sua conta.';
  if (error?.status === 401) return 'Seu acesso terminou. Entre novamente para continuar.';
  return error?.message || 'Não foi possível concluir agora. Sua última etapa salva foi preservada.';
}

export function initSession({ api, notify, onChanged, onHistory, onCatalog }) {
  let epoch = 0;
  let draftsEpoch = 0;
  let catalogEpoch = 0;
  let sessionId = null;
  let record = null;
  let interpretation = null;
  let legacyPartial = false;
  let engine = 'dicionario';
  let fallback = false;
  let guidanceRequest = 0;
  let catalogState = 'unknown';
  let catalogEligibleCount = 0;
  let activeCatalogFilter = 'all';
  let selectedObjective = '';
  let selectedStates = new Set();
  let suggestionFitNote = '';

  const catalogStatus = (message, kind = 'info') => {
    const target = $('#catalog-status');
    if (!target) return;
    target.textContent = message;
    target.dataset.type = kind;
    target.setAttribute('role', kind === 'error' ? 'alert' : 'status');
  };
  const feedbackStatus = (message, kind = 'info') => {
    const target = $('#feedback-status');
    if (!target) return;
    target.textContent = message;
    target.dataset.type = kind;
    target.setAttribute('role', kind === 'error' ? 'alert' : 'status');
  };
  const narrativeDraft = createNarrativeDraft($('#narrative-form'), { confirm: confirmAction });
  const catalogReference = createCatalogReference({
    api, button: $('#catalog-reference-import'), status: $('#catalog-reference-status'),
    count: $('#catalog-reference-count'), list: $('#catalog-reference-list'), container: $('#catalog-reference'),
    search: $('#catalog-reference-search'), pageCount: $('#catalog-reference-page-count'),
    more: $('#catalog-reference-more'), disclosure: $('#catalog-reference-preview'),
    describeError: readableError,
    onStart: () => notify(''),
    onError: error => notify(readableError(error), 'error'),
    onImported: async isCurrent => {
      await loadCatalog({ loadReference: false });
      if (!isCurrent()) return;
      changed();
      void refreshCatalogGuidance();
    },
  });
  const catalogAssociations = createCatalogAssociations({
    api, dialog: $('#catalog-associations-dialog'), form: $('#catalog-associations-form'),
    title: $('#catalog-associations-title'), categories: $('#catalog-associations-categories'),
    status: $('#catalog-associations-status'), save: $('#catalog-associations-save'), cancel: $('#catalog-associations-cancel'),
    describeError: readableError,
    onError: error => notify(readableError(error), 'error'),
    onSaved: async (_song, isCurrent) => {
      await loadCatalog({ loadReference: false, preserveLimit: true });
      if (!isCurrent()) return;
      catalogStatus('Sensações salvas. As faixas com associações participam das próximas sugestões.', 'success');
      changed();
      void refreshCatalogGuidance();
    },
  });
  const catalogBrowser = createCatalogBrowser({
    list: $('#catalog-list'), search: $('#catalog-search'), count: $('#catalog-page-count'), more: $('#catalog-more'),
    emptyMessage: 'Seu catálogo ainda está vazio. Adicione a seleção inicial de músicas reais, cadastre uma faixa ou use os exemplos fictícios para experimentar o fluxo.',
    renderCard: song => renderCatalogCard(song, { onEdit: (item, trigger) => catalogAssociations.open(item, trigger) }),
    onRender: state => syncCatalogFilterBar(state),
  });

  function hasUnsavedNote() {
    return !sessionId && Boolean(($('#narrative-text')?.value || '').trim()) && narrativeDraft.hasChanges();
  }

  window.addEventListener('beforeunload', event => {
    if (!hasUnsavedNote()) return;
    event.preventDefault();
    event.returnValue = '';
  });

  const own = (version) => epoch === version;
  const changed = () => { if (onChanged) onChanged(); };
  const status = (message, kind = 'info') => {
    const target = $('#session-status');
    target.textContent = message;
    target.dataset.type = kind;
    target.hidden = !message;
    target.setAttribute('role', kind === 'error' ? 'alert' : 'status');
  };

  function syncMoodAtmosphere() {
    const { mood } = resolveQuickSelection({ objective: selectedObjective, states: [...selectedStates] });
    document.body.dataset.sessionMood = mood;
  }

  function syncPersistenceUI() {
    const persisted = Boolean(sessionId);
    const badge = $('#session-persistence-badge');
    if (badge) {
      badge.textContent = persisted ? 'Guardado no diário' : 'Não gravado no diário';
      badge.dataset.persisted = String(persisted);
    }
    const saveCard = $('#diary-save-card');
    const savedBanner = $('#diary-saved-banner');
    if (saveCard) saveCard.hidden = persisted;
    if (savedBanner) savedBanner.hidden = !persisted;
    const noteRow = $('#save-include-note-row');
    if (noteRow) {
      const hasText = Boolean((record?.texto_usuario || $('#narrative-text')?.value || '').trim());
      noteRow.hidden = persisted || !hasText;
    }
  }

  async function action(container, callback) {
    const version = epoch;
    notify('');
    try {
      await withBusy(container, () => callback(version));
    } catch (error) {
      if (!own(version) || stale(error)) return;
      const message = readableError(error);
      if (container?.closest?.('#view-catalog') || container?.id === 'view-catalog') {
        catalogStatus(message, 'error');
      } else status(message, 'error');
      notify(message, 'error');
    }
  }

  function canAnimateStage() {
    try {
      return typeof document.startViewTransition === 'function'
        && document.visibilityState !== 'hidden'
        && !document.body.classList.contains('ambient-paused')
        && !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    } catch {
      return false;
    }
  }

  function applyStageDOM(number) {
    $('#session-entry').hidden = number !== 1;
    $('#session-review').hidden = number !== 2;
    $('#session-listening').hidden = number !== 3;
    if (number !== 3) $('#step-escuta').lastChild.textContent = 'Faixas e diário';
    ['relato', 'revisao', 'escuta'].forEach((name, index) => {
      const item = $(`#step-${name}`);
      if (index + 1 === number) item.setAttribute('aria-current', 'step');
      else item.removeAttribute('aria-current');
      item.dataset.complete = String(index + 1 < number);
      item.classList.toggle('current', index + 1 === number);
      item.classList.toggle('complete', index + 1 < number);
    });
  }

  function stage(number, { animate = false, focusTarget = null } = {}) {
    const previous = !$('#session-entry').hidden ? 1 : !$('#session-review').hidden ? 2 : 3;
    const finishFocus = () => {
      if (number !== previous && window.scrollY > 0) {
        window.scrollTo({ top: 0, behavior: 'instant' });
      }
      if (focusTarget && focusTarget.getClientRects?.().length) {
        focusTarget.focus({ preventScroll: true });
      }
    };
    if (animate && number !== previous && canAnimateStage()) {
      try {
        const transition = document.startViewTransition(() => applyStageDOM(number));
        transition.finished.finally(finishFocus);
        return;
      } catch { /* Executa atualização imediata abaixo. */ }
    }
    applyStageDOM(number);
    finishFocus();
  }

  function setReviewEditorOpen(open) {
    const panel = $('#review-editor-panel');
    const toggle = $('#review-toggle-editor');
    if (panel) panel.hidden = !open;
    if (toggle) {
      toggle.setAttribute('aria-expanded', String(open));
      toggle.textContent = open ? 'Ocultar ajustes' : 'Mudar';
    }
  }

  function reset({ preserveNarrative = false } = {}) {
    epoch += 1;
    draftsEpoch += 1;
    catalogEpoch += 1;
    activeCatalogFilter = 'all';
    if (!preserveNarrative) {
      selectedObjective = '';
      selectedStates = new Set();
    }
    suggestionFitNote = '';
    catalogReference.reset();
    catalogAssociations.reset();
    catalogBrowser.reset();
    sessionId = null;
    record = null;
    interpretation = null;
    legacyPartial = false;
    engine = 'dicionario';
    fallback = false;
    guidanceRequest += 1;
    catalogState = 'unknown';
    catalogEligibleCount = 0;
    ['narrative-form', 'review-form', 'listening-form', 'feedback-form', 'catalog-form'].forEach((id) => {
      if (id !== 'narrative-form' || !preserveNarrative) $(`#${id}`).reset();
    });
    if ($('#save-include-note')) $('#save-include-note').checked = true;
    narrativeDraft.reset({ toDefaults: preserveNarrative });
    ['review-original', 'review-reflection', 'review-origin', 'review-references', 'review-clarification', 'strategy-summary', 'recommendation-list', 'draft-list', 'catalog-list'].forEach((id) => $(`#${id}`).replaceChildren());
    $('#current-tags').replaceChildren();
    $('#desired-tags').replaceChildren();
    $('#desired-text').readOnly = false;
    $('#session-heading').textContent = 'O que você busca na sua escuta?';
    if ($('#session-subheading')) {
      $('#session-subheading').textContent = 'Comece por um objetivo rápido ou conte seu momento nas suas palavras. Você decide no final se quer guardar no diário.';
    }
    $('#review-form').hidden = false;
    setReviewEditorOpen(false);
    $('#session-retry').hidden = true;
    $('#fallback-local-button').hidden = true;
    $('#review-clarification').hidden = true;
    $('#llm-options').hidden = $('#interpretation-engine').value !== 'llm';
    $('#draft-count').textContent = '0';
    catalogStatus('');
    feedbackStatus('');
    if (!preserveNarrative && $('#session-extra-options')) $('#session-extra-options').open = false;
    if ($('#feedback-extra-fields')) $('#feedback-extra-fields').open = false;
    syncCatalogFilterChips();
    syncCatalogFilterBar({ query: '', total: 0, matched: 0, error: '', searchMatched: [] });
    syncEntryDynamics();
    syncFeedbackChoices();
    syncSuggestionFitChoices();
    syncCatalogFeelingChips();
    syncMoodAtmosphere();
    syncPersistenceUI();
    status('');
    stage(1);
    renderCatalogGuidance();
  }

  async function confirmLeave(options) {
    const version = epoch;
    if (!hasUnsavedNote()) return true;
    const allowed = await narrativeDraft.confirmDiscard(options);
    return allowed && own(version);
  }

  async function newSession() {
    const version = epoch;
    if (!await confirmLeave() || !own(version)) {
      if ($('#session-entry').getClientRects().length) $('#narrative-text').focus();
      return false;
    }
    reset();
    notify('');
    void loadDrafts();
    void refreshCatalogGuidance();
    if ($('#session-entry').getClientRects().length) {
      const firstObjective = document.querySelector('[data-objective]');
      (firstObjective || $('#narrative-text')).focus({ preventScroll: true });
      window.scrollTo({ top: 0, behavior: 'instant' });
    }
    return true;
  }

  function categories(targetId, name, selected, disabled = false) {
    renderCategories($(`#${targetId}`), { name, selected, disabled });
  }

  function selected(targetId) {
    return [...$(`#${targetId}`).querySelectorAll('input:checked')].map((input) => input.value);
  }

  function clear(targetId) {
    clearCategories($(`#${targetId}`));
    refreshReviewQuestionFromTags();
  }

  function refreshReviewQuestionFromTags() {
    const q = $('#review-question');
    if (!q || $('#session-review').hidden) return;
    q.textContent = buildReviewQuestion(selected('current-tags'), selected('desired-tags'));
  }

  function renderCatalogGuidance() {
    const empty = catalogState === 'empty';
    const failed = catalogState === 'error';
    const checking = catalogState === 'loading';
    const noEligible = catalogState === 'ready' && catalogEligibleCount === 0;
    $('#session-catalog-guidance').hidden = !empty && !failed && !checking && !noEligible;
    $('#session-catalog-message').textContent = empty
      ? 'Sua conta ainda não tem músicas no catálogo. Carregue a seleção inicial (66 faixas já classificadas) em um clique ou adicione suas músicas.'
      : noEligible
        ? 'Suas faixas atuais ainda aguardam classificação de sensações para entrar nas sugestões.'
        : failed
          ? 'Não foi possível conferir seu catálogo agora. Você ainda pode explorar objetivos ou escrever sua nota.'
          : 'Conferindo as faixas do seu catálogo…';
    if ($('#entry-import-reference')) $('#entry-import-reference').hidden = !empty;
    $('#entry-open-catalog').hidden = !empty && !noEligible;
    $('#entry-retry-catalog').hidden = !failed;

    const hasNoMatches = Boolean(record) && recommendationState(record) === 'no-matches';
    $('#listening-catalog-message').hidden = !hasNoMatches;
    $('#listening-catalog-message').textContent = empty
      ? 'Motivo: seu catálogo pessoal está vazio no momento.'
      : noEligible
        ? 'Motivo: seu catálogo tem faixas importadas, mas nenhuma possui sensações associadas ainda.'
        : failed
          ? 'Não foi possível consultar o catálogo agora.'
          : checking
            ? 'Conferindo seu catálogo atual…'
            : catalogState === 'ready'
              ? 'Seu catálogo possui faixas, mas nenhuma correspondeu à combinação escolhida.'
              : '';
    $('#listening-retry-catalog').hidden = !hasNoMatches || !failed;
    if ($('#empty-import-reference')) {
      $('#empty-import-reference').hidden = !(Boolean(record) && empty && recommendationState(record) !== 'suggestions');
    }
    if ($('#empty-change-objective')) {
      $('#empty-change-objective').hidden = !(Boolean(record) && !empty && recommendationState(record) !== 'suggestions');
    }
  }

  async function refreshCatalogGuidance() {
    const request = ++guidanceRequest;
    const version = epoch;
    catalogState = 'loading';
    renderCatalogGuidance();
    try {
      const response = await api('/api/musicas');
      if (!own(version) || request !== guidanceRequest) return;
      catalogState = currentCatalogState(response);
      const songs = Array.isArray(response.musicas) ? response.musicas : [];
      catalogEligibleCount = songs.filter(song => !isPendingCatalogSong(song)).length;
    } catch (error) {
      if (!own(version) || request !== guidanceRequest || stale(error)) return;
      catalogState = 'error';
    }
    renderCatalogGuidance();
  }

  function referenceList(ids) {
    const target = $('#review-references');
    target.hidden = !ids?.length;
    if (!ids?.length) { target.replaceChildren(); return; }
    const list = el('ul', { class: 'reference-list' });
    ids.forEach((id) => list.append(el('li', {}, `${id} · ${REFERENCIAS[id] || 'Regra da base de conhecimento utilizada nesta sugestão.'}`)));
    target.replaceChildren(el('summary', {}, 'O que orientou esta sugestão'), list);
  }

  function showPending(message = 'Escolha como continuar a interpretação.') {
    stage(2, { animate: true, focusTarget: $('#session-heading') });
    syncPersistenceUI();
    $('#session-heading').textContent = 'Vamos revisar a interpretação';
    $('#review-back-entry').hidden = Boolean(sessionId);
    $('#review-new-session').hidden = !sessionId;
    $('#review-original-box').hidden = !record?.texto_usuario;
    $('#review-original').textContent = record?.texto_usuario || '';
    $('#review-question').textContent = 'Interpretação pendente';
    $('#review-reflection').textContent = message;
    $('#review-origin').textContent = 'Interpretação ainda não concluída.';
    $('#review-quick-actions').hidden = true;
    $('#review-form').hidden = true;
    $('#review-clarification').hidden = true;
    $('#review-references').hidden = true;
    $('#session-retry').textContent = engine === 'llm' ? 'Tentar interpretação com LLM' : 'Interpretar com dicionário local';
    $('#session-retry').hidden = false;
    $('#fallback-local-button').hidden = engine !== 'llm';
  }

  function showInterpretation(result) {
    interpretation = result;
    legacyPartial = false;
    const proposal = result.proposta;
    const quick = resolveQuickSelection({ objective: selectedObjective, states: [...selectedStates] });
    const suggestedCurrent = [...new Set([
      ...(proposal.estado_atual?.sugestoes || []).map((item) => item.categoria),
      ...(!sessionId ? quick.emocoes_atuais : []),
    ])].filter(c => CATEGORIAS.includes(c));
    const closedDesire = record?.texto_desejado === '';
    const suggestedDesired = closedDesire ? [] : [...new Set([
      ...(!sessionId ? quick.estado_desejado : []),
      ...(proposal.estado_desejado?.sugestoes || []).map((item) => item.categoria),
    ])].filter(c => CATEGORIAS.includes(c));

    stage(2, { animate: true, focusTarget: $('#review-heading') });
    syncPersistenceUI();
    $('#session-heading').textContent = 'Revise nossa leitura da sua nota';
    $('#review-back-entry').hidden = Boolean(sessionId);
    $('#review-new-session').hidden = !sessionId;
    $('#review-form').hidden = false;
    $('#review-quick-actions').hidden = false;
    $('#review-original-box').hidden = !record?.texto_usuario;
    $('#review-original').textContent = record?.texto_usuario || '';
    $('#review-question').textContent = buildReviewQuestion(suggestedCurrent, suggestedDesired);
    $('#review-reflection').textContent = proposal.resumo_reflexivo || 'Confira se a pergunta acima representa bem o seu momento.';
    $('#review-clarification').hidden = !proposal.precisa_esclarecimento;
    if (proposal.precisa_esclarecimento) {
      const doubts = [...(proposal.estado_atual?.ambiguidades || []), ...(proposal.estado_desejado?.ambiguidades || [])];
      $('#review-clarification').textContent = doubts.length
        ? `A nota deixa mais de uma leitura possível: ${doubts.join(' ')}`
        : 'Sua nota deixa dúvidas. Confirme apenas o que reconhecer, clique em “Mudar” para escolher manualmente ou siga sem categoria.';
    }
    const source = result.motor_utilizado === 'llm'
      ? `Leitura sugerida por LLM${result.modelo ? ` (${result.modelo})` : ''}.`
      : 'Leitura sugerida pelo dicionário local.';
    $('#review-origin').textContent = source
      + (result.fallback_motivo ? ' Alternativa local usada porque o serviço externo não respondeu.' : '')
      + (!sessionId ? ' Nada foi salvo no diário ainda.' : '');
    referenceList(proposal.referencias_base);
    categories('current-tags', 'current', suggestedCurrent);
    categories('desired-tags', 'desired', suggestedDesired, closedDesire);
    $('#desired-text').value = record?.texto_desejado !== null && record?.texto_desejado !== undefined
      ? record.texto_desejado
      : (proposal.texto_intencao || (suggestedDesired[0] ? categoriaLabel(suggestedDesired[0]).toLocaleLowerCase('pt-BR') : ''));
    $('#desired-text').readOnly = Boolean(sessionId) && record?.texto_desejado !== null && record?.texto_desejado !== undefined;
    $('#review-without-category').disabled = false;
    $('#clear-current-tags').disabled = false;
    $('#clear-desired-tags').disabled = closedDesire;
    $('#session-retry').hidden = true;
    $('#fallback-local-button').hidden = true;
    setReviewEditorOpen(!suggestedCurrent.length && !suggestedDesired.length);
    status(!sessionId
      ? 'Confirme a pergunta, mude as categorias ou siga sem categoria. Nada foi gravado no diário.'
      : 'Interpretação sugerida para revisão.');
  }

  function showLegacyPartial() {
    interpretation = null;
    legacyPartial = true;
    stage(2, { animate: true, focusTarget: $('#review-heading') });
    syncPersistenceUI();
    $('#session-heading').textContent = 'Continue de onde parou';
    $('#review-back-entry').hidden = true;
    $('#review-new-session').hidden = false;
    $('#review-form').hidden = false;
    $('#review-quick-actions').hidden = true;
    setReviewEditorOpen(true);
    $('#review-original-box').hidden = !record.texto_usuario;
    $('#review-original').textContent = record.texto_usuario || '';
    $('#review-question').textContent = buildReviewQuestion(record.analise?.emocoes || [], record.analise?.estado_desejado || []);
    $('#review-reflection').textContent = 'O estado atual desta sessão já foi confirmado. Você pode completar a intenção pendente para continuar.';
    $('#review-origin').textContent = 'Categorias já confirmadas por você, preservadas nesta retomada.';
    $('#review-clarification').hidden = true;
    referenceList([]);
    categories('current-tags', 'current', record.analise?.emocoes || [], true);
    categories('desired-tags', 'desired', record.analise?.estado_desejado || [], true);
    $('#desired-text').value = record.texto_desejado || '';
    $('#desired-text').readOnly = record.texto_desejado !== null && record.texto_desejado !== undefined;
    $('#review-without-category').disabled = true;
    $('#clear-current-tags').disabled = true;
    $('#clear-desired-tags').disabled = true;
    $('#session-retry').hidden = true;
    $('#fallback-local-button').hidden = true;
    status('As decisões já salvas serão mantidas. Para revê-las em outro momento, você pode criar uma nova sessão.');
  }

  async function generatePreviewInterpretation(version, motor = engine) {
    if (!record || !own(version)) return;
    engine = motor;
    status(motor === 'llm' ? 'Interpretando sua nota com o serviço configurado…' : 'Lendo sua nota localmente…', 'loading');
    $('#session-retry').hidden = true;
    $('#fallback-local-button').hidden = true;
    try {
      const quick = resolveQuickSelection({ objective: selectedObjective, states: [...selectedStates] });
      const result = await api('/api/explorar-interpretacao', {
        method: 'POST',
        body: {
          texto_atual: record.texto_usuario,
          texto_desejado: quick.estado_desejado[0] || null,
          motor,
          permitir_fallback_dicionario: motor === 'llm' && fallback,
        },
      });
      if (!own(version)) return;
      showInterpretation(result);
    } catch (error) {
      if (!own(version) || stale(error)) return;
      showPending('Não foi possível concluir a leitura agora. Nada foi gravado; você pode tentar novamente ou usar o dicionário local.');
      status(readableError(error), 'error');
      $('#fallback-local-button').hidden = motor !== 'llm';
    }
  }

  async function generate(version, motor = engine) {
    if (!sessionId) {
      await generatePreviewInterpretation(version, motor);
      return;
    }
    if (!record || !own(version)) return;
    engine = motor;
    status(motor === 'llm' ? 'Interpretando seu relato com o serviço configurado…' : 'Preparando a interpretação local…', 'loading');
    $('#session-retry').hidden = true;
    $('#fallback-local-button').hidden = true;
    try {
      const result = await api('/api/interpretacoes', { method: 'POST', body: {
        sessao_id: sessionId, motor,
        permitir_fallback_dicionario: motor === 'llm' && fallback,
        regenerar: false,
      } });
      if (!own(version)) return;
      engine = motor;
      showInterpretation(result);
      changed();
    } catch (error) {
      if (!own(version) || stale(error)) return;
      showPending();
      if (error.status === 503 && motor === 'llm') {
        status('O serviço de interpretação está indisponível ou não concluiu uma resposta válida. Seu relato está salvo. Você pode tentar de novo ou escolher o dicionário local.', 'error');
      } else {
        status(readableError(error), 'error');
      }
      $('#fallback-local-button').hidden = motor !== 'llm';
    }
  }

  async function exploreRecommendations(version, { emocoes = [], desejos = [], textoDesejado = '' } = {}) {
    const limit = Number($('#session-limit')?.value || record?.limite_recomendacoes || 3);
    status('Buscando até ' + limit + (limit === 1 ? ' faixa compatível…' : ' faixas compatíveis…'), 'loading');
    const result = await api('/api/explorar-escuta', {
      method: 'POST',
      body: {
        emocoes_atuais: emocoes,
        estado_desejado: desejos,
        texto_desejado: textoDesejado || null,
        limite_recomendacoes: limit,
      },
    });
    if (!own(version)) return;
    if (result.catalogo) {
      catalogState = result.catalogo.total === 0 ? 'empty' : 'ready';
      catalogEligibleCount = Number(result.catalogo.elegiveis) || 0;
    }
    record = {
      sessao_id: null,
      persistido: false,
      texto_usuario: $('#narrative-text')?.value || '',
      finalidade: $('#session-purpose')?.value?.trim() || resolveQuickSelection({ objective: selectedObjective, states: [...selectedStates] }).finalidadeSugerida || null,
      contexto: $('#session-context')?.value?.trim() || null,
      analise: {
        emocoes: result.emocoes_atuais || emocoes,
        estado_desejado: result.estado_desejado || desejos,
      },
      texto_desejado: textoDesejado,
      estrategia: result.estrategia,
      explicacao: result.explicacao,
      recomendacoes: result.recomendacoes || [],
      motivos_recomendacoes: result.motivos_recomendacoes || [],
      limite_recomendacoes: result.limite_recomendacoes || limit,
      escuta: record?.escuta || null,
      feedback: record?.feedback || null,
      progresso: {
        emocoes_confirmadas: true,
        estado_desejado_informado: true,
        recomendacoes_geradas: true,
      },
    };
    showListening();
  }

  async function fetchRecord(id, version) {
    const response = await api('/api/historico/sessao', { query: { sessao_id: id } });
    if (!own(version)) return null;
    record = response.registro;
    return record;
  }

  async function open(id) {
    const previousVersion = epoch;
    if (!await confirmLeave({
      title: 'Abrir outro registro?',
      message: 'Há uma nota escrita que ainda não foi guardada. Deseja descartar esse rascunho para abrir o registro salvo?',
      label: 'Descartar rascunho e abrir',
    }) || !own(previousVersion)) return false;
    reset();
    notify('');
    sessionId = id;
    syncPersistenceUI();
    const version = epoch;
    showPending('Carregando a última etapa salva…');
    status('Abrindo sua sessão…', 'loading');
    try {
      const loaded = await fetchRecord(id, version);
      if (!loaded || !own(version)) return;
      if (!loaded.progresso || loaded.progresso.recomendacoes_geradas) {
        showListening();
      } else if (loaded.progresso.emocoes_confirmadas) {
        showLegacyPartial();
      } else {
        try {
          const saved = await api(`/api/interpretacoes/${encodeURIComponent(id)}`);
          if (!own(version)) return;
          engine = saved.motor_solicitado || 'dicionario';
          if (saved.estado_revisao === 'pendente') showInterpretation(saved);
          else showPending();
        } catch (error) {
          if (!own(version) || stale(error)) return;
          if (error.status !== 404 && error.status !== 409) throw error;
          showPending('Seu rascunho foi salvo antes da interpretação. Use o botão abaixo para continuar.');
          status('Rascunho retomado. A interpretação só será executada quando você escolher continuar.');
        }
      }
    } catch (error) {
      if (!own(version) || stale(error)) return;
      showPending('Não foi possível abrir esta sessão agora.');
      $('#session-retry').hidden = true;
      $('#fallback-local-button').hidden = true;
      status(readableError(error), 'error');
    }
  }

  async function loadDrafts() {
    const requestVersion = ++draftsEpoch;
    const list = $('#draft-list');
    list?.setAttribute('aria-busy', 'true');
    try {
      const history = await api('/api/historico');
      if (requestVersion !== draftsEpoch) return;
      const drafts = Object.entries(history.registros || {}).filter(([, item]) => item.progresso && !item.progresso.recomendacoes_geradas).reverse();
      $('#draft-count').textContent = String(drafts.length);
      list.replaceChildren();
      if (!drafts.length) list.append(el('p', { class: 'hint' }, 'Nenhum rascunho pendente no diário.'));
      drafts.forEach(([id, item]) => {
        const text = item.finalidade || item.texto_usuario || 'Rascunho salvo';
        const button = el('button', { type: 'button', class: 'draft-card' },
          el('span', { class: 'eyebrow' }, item.data_hora || 'Rascunho salvo'),
          el('strong', {}, text.length > 90 ? `${text.slice(0, 90)}…` : text),
          el('span', { class: 'hint' }, 'Retomar etapa pendente'));
        button.addEventListener('click', () => open(id));
        list.append(button);
      });
    } catch (error) {
      if (requestVersion !== draftsEpoch || stale(error)) return;
      list.replaceChildren(el('p', { class: 'hint' }, 'Não foi possível carregar os rascunhos agora. Use “Atualizar” para tentar novamente.'));
    } finally {
      if (requestVersion === draftsEpoch) list?.removeAttribute('aria-busy');
    }
  }

  function showListening() {
    stage(3, { animate: true, focusTarget: $('#listening-heading') });
    legacyPartial = false;
    syncPersistenceUI();
    const state = recommendationState(record);
    const hasSuggestions = state === 'suggestions';
    const emptyCatalog = catalogState === 'empty';
    const noEligible = catalogState === 'ready' && catalogEligibleCount === 0;

    $('#listening-change-objective').hidden = Boolean(sessionId);
    $('#step-escuta').lastChild.textContent = hasSuggestions ? 'Faixas e diário' : 'Resultado e diário';
    $('#session-heading').textContent = hasSuggestions
      ? 'Sugestões para o seu momento'
      : emptyCatalog ? 'Falta preparar seu catálogo musical' : 'Nenhuma faixa combinou com este filtro';
    $('#listening-heading').textContent = hasSuggestions ? 'Escolha o que faz sentido ouvir.' : 'Próximo passo sugerido.';
    $('#listening-intro').textContent = hasSuggestions
      ? 'Veja o motivo verificável de cada sugestão e abra a faixa quando houver link.'
      : 'Cada situação abaixo tem uma saída direta para você continuar.';
    $('#session-retry').hidden = true;
    $('#fallback-local-button').hidden = true;

    $('#strategy-summary').replaceChildren(
      el('strong', {}, record.estrategia ? strategyLabel(record.estrategia) : 'Sem estratégia aplicável'),
      el('p', {}, record.explicacao || 'As escolhas atuais não definiram uma estratégia de busca.'),
      el('p', { class: 'hint' }, record.estrategia === 'foco_cognitivo'
        ? 'Músicas em tarefas de concentração funcionam de forma diferente para cada pessoa. Observe sua experiência.'
        : 'Sugestão baseada nas etiquetas do seu catálogo — sem análise acústica ou promessa clínica.'),
    );
    $('#strategy-summary').hidden = !hasSuggestions;

    const musicas = record.recomendacoes || [];
    const choices = new Map((record.escuta?.faixas || []).map((choice) => [choice.indice_recomendacao, choice]));
    const list = $('#recommendation-list');
    list.replaceChildren();
    $('#recommendation-empty').hidden = hasSuggestions;
    if (!hasSuggestions) {
      if (emptyCatalog) {
        $('#recommendation-empty-title').textContent = 'Seu catálogo ainda está vazio.';
        $('#recommendation-empty-message').textContent = 'O RhythmMind sugere faixas do seu próprio catálogo. Carregue agora a seleção inicial com 66 músicas classificadas em um clique ou cadastre uma faixa sua.';
      } else if (state === 'no-criteria') {
        $('#recommendation-empty-title').textContent = 'Sem objetivo ou sensação selecionada.';
        $('#recommendation-empty-message').textContent = 'Você optou por seguir sem categorias e sem objetivo. Escolha um objetivo (como Relaxar, Focar ou Ganhar energia) para receber faixas.';
      } else if (noEligible) {
        $('#recommendation-empty-title').textContent = 'Suas músicas aguardam classificação.';
        $('#recommendation-empty-message').textContent = 'Há faixas no seu catálogo, mas nenhuma tem sensações indicadas ainda. Classifique algumas faixas em Catálogo para ativar as sugestões.';
      } else {
        $('#recommendation-empty-title').textContent = 'Nenhuma faixa do catálogo combinou com este objetivo.';
        $('#recommendation-empty-message').textContent = 'Seu catálogo já tem músicas, mas nenhuma está marcada para esta combinação. Experimente mudar o objetivo ou classificar novas faixas.';
      }
    }
    $('#open-catalog-button').textContent = emptyCatalog ? 'Cadastrar uma faixa minha' : 'Abrir meu catálogo';
    $('#listening-actions').hidden = !hasSuggestions;
    $('#listening-help').hidden = !hasSuggestions;
    $('#feedback-card').hidden = !hasSuggestions && !record.feedback;
    renderCatalogGuidance();
    if (state === 'no-matches' && catalogState === 'unknown') void refreshCatalogGuidance();
    $('#save-listening').disabled = !musicas.length;

    musicas.forEach((music, index) => {
      const number = index + 1;
      const existing = choices.get(number);
      const check = el('input', { type: 'checkbox', id: `track-select-${number}`, value: String(number), name: 'faixa' });
      check.checked = Boolean(existing);
      const heard = el('select', { id: `track-heard-${number}`, 'aria-label': `Escuta de ${music.nome || `faixa ${number}`}` },
        el('option', { value: '' }, 'Ainda não ouvi / não informar'),
        el('option', { value: 'true' }, 'Ouvi esta faixa'),
        el('option', { value: 'false' }, 'Optei por não ouvir'));
      heard.value = existing?.ouvida === true ? 'true' : existing?.ouvida === false ? 'false' : '';
      heard.disabled = !check.checked;
      check.addEventListener('change', () => { heard.disabled = !check.checked; });

      const reason = (record.motivos_recomendacoes || []).find((item) => item.indice_recomendacao === number);
      const sourceUrl = safeCatalogSource(music.proveniencia?.url);
      const albumText = music.proveniencia?.album ? ` · ${music.proveniencia.album}` : '';
      const headerRow = el('div', { class: 'music-card-header' },
        el('div', { class: 'music-card-titles' },
          el('span', { class: 'track-rank-badge', 'aria-hidden': 'true' }, `0${number}`),
          el('div', {},
            el('h3', {}, music.nome || 'Faixa cadastrada'),
            el('p', { class: 'music-meta' }, `${music.artista || 'Artista não informado'} · ${music.duracao || 'Duração não informada'}${albumText}`))),
        sourceUrl
          ? el('a', {
            class: 'button button-secondary track-open-link',
            href: sourceUrl,
            target: '_blank',
            rel: 'noopener noreferrer',
          }, 'Abrir faixa', el('span', { class: 'sr-only' }, ' (abre em nova aba)'))
          : el('span', { class: 'music-duration-pill', 'aria-hidden': 'true' }, music.duracao || '—'));

      list.append(el('article', { class: 'music-card recommendation-track-card' },
        headerRow,
        el('p', { class: 'music-reason' }, humanizeTrackReason(music, reason, record.estrategia)),
        el('div', { class: 'choice-control' },
          el('label', { for: check.id }, check, ' Escolher faixa'),
          el('label', { for: heard.id }, 'Escuta:', heard))));
    });

    const feedback = record.feedback;
    let comment = feedback?.motivo || '';
    const noChange = feedback?.ajudou === false && comment.startsWith('Não percebi mudança.');
    if (noChange) comment = comment.slice('Não percebi mudança.'.length).trim();
    $('#feedback-answer').value = feedback?.ajudou === true ? 'ajudou' : noChange ? 'sem_mudanca' : feedback?.ajudou === false ? 'nao_ajudou' : '';
    $('#feedback-comment').value = comment;
    $('#feedback-improvement').value = feedback?.melhoria || '';
    syncFeedbackChoices();
    syncSuggestionFitChoices();
    if ($('#feedback-extra-fields')) {
      $('#feedback-extra-fields').open = Boolean(comment || feedback?.melhoria);
    }
    $('#feedback-later').textContent = typeof feedback?.ajudou === 'boolean' ? 'Manter retorno atual' : 'Pular retorno';
    feedbackStatus(typeof feedback?.ajudou === 'boolean'
      ? 'Retorno aplicado nesta sessão.'
      : 'O retorno é opcional — você pode responder ou pular.');
    status(!sessionId
      ? 'Modo rápido: nada foi gravado no diário ainda. Use “Guardar no meu diário” abaixo se quiser registrar.'
      : !hasSuggestions
        ? 'Sessão salva no diário sem sugestões pendentes.'
        : record.escuta?.faixas?.length === 0
          ? 'Você registrou a decisão de não escolher nenhuma faixa.'
          : record.escuta
            ? 'Escolha de faixa e informação de escuta salvas.'
            : 'Escolha uma faixa se quiser e registre a escuta separadamente.');
  }

  async function submitReview(version, noCategories = false) {
    if (!record) return;
    if (!sessionId) {
      const currentConfirmed = noCategories ? [] : selected('current-tags');
      const desiredConfirmed = noCategories ? [] : selected('desired-tags');
      const desireText = noCategories ? '' : ($('#desired-text')?.value || '');
      await exploreRecommendations(version, {
        emocoes: currentConfirmed,
        desejos: desiredConfirmed,
        textoDesejado: desireText,
      });
      return;
    }
    const desireText = record.texto_desejado !== null && record.texto_desejado !== undefined
      ? record.texto_desejado : $('#desired-text').value;
    if (legacyPartial) {
      await api('/api/retomar-sessao', { method: 'POST', body: { sessao_id: sessionId, texto_desejado: desireText } });
    } else {
      if (!interpretation) return;
      const wanted = noCategories ? [] : selected('desired-tags');
      const effectiveDesireText = wanted.length && !desireText.trim()
        ? wanted.map(categoriaLabel).join(', ')
        : desireText;
      await api('/api/revisoes-interpretacao', { method: 'POST', body: {
        sessao_id: sessionId, interpretacao_id: interpretation.interpretacao_id,
        emocoes_confirmadas: noCategories ? [] : selected('current-tags'),
        estado_desejado_confirmado: wanted, texto_desejado: effectiveDesireText,
      } });
    }
    if (!own(version)) return;
    if (!await fetchRecord(sessionId, version)) return;
    showListening();
    changed();
  }

  function collectCurrentListeningFromDOM(none = false) {
    if (none) return [];
    const container = $('#recommendation-list');
    if (!container) return null;
    const checked = [...container.querySelectorAll('input[name="faixa"]:checked')];
    if (!checked.length) return null;
    return checked.map((input) => {
      const heard = $(`#track-heard-${input.value}`)?.value || '';
      return { indice_recomendacao: Number(input.value), ouvida: heard === '' ? null : heard === 'true' };
    });
  }

  function collectCurrentFeedbackFromDOM() {
    const answer = $('#feedback-answer')?.value || '';
    if (!answer) return null;
    const rawComment = ($('#feedback-comment')?.value || '').trim();
    const fitPrefix = suggestionFitNote && !rawComment.includes(suggestionFitNote) ? `${suggestionFitNote} ` : '';
    const combinedComment = `${fitPrefix}${rawComment}`.trim();
    const motive = answer === 'sem_mudanca'
      ? `Não percebi mudança.${combinedComment ? ` ${combinedComment}` : ''}`
      : combinedComment;
    return {
      ajudou: answer === 'ajudou',
      motivo: motive,
      melhoria: ($('#feedback-improvement')?.value || '').trim(),
    };
  }

  async function saveSessionToDiary(version) {
    if (sessionId || !record) return;
    const domListening = collectCurrentListeningFromDOM(false);
    const effectiveListening = domListening !== null ? domListening : (record.escuta?.faixas ?? null);
    const domFeedback = collectCurrentFeedbackFromDOM();
    const effectiveFeedback = domFeedback || record.feedback || null;
    const includeNote = $('#save-include-note') ? $('#save-include-note').checked : true;
    const noteText = record.texto_usuario || $('#narrative-text')?.value || '';

    status('Guardando esta sessão no seu diário…', 'loading');
    const saved = await api('/api/diario/sessoes', {
      method: 'POST',
      body: {
        texto_atual: noteText,
        guardar_relato: includeNote,
        finalidade: record.finalidade || $('#session-purpose')?.value?.trim() || null,
        contexto: record.contexto || $('#session-context')?.value?.trim() || null,
        emocoes_confirmadas: record.analise?.emocoes || [],
        estado_desejado_confirmado: record.analise?.estado_desejado || [],
        texto_desejado: record.texto_desejado || '',
        limite_recomendacoes: Number(record.limite_recomendacoes || 3),
        faixas_escuta: effectiveListening,
        feedback_ajudou: typeof effectiveFeedback?.ajudou === 'boolean' ? effectiveFeedback.ajudou : null,
        feedback_motivo: effectiveFeedback?.motivo || '',
        feedback_melhoria: effectiveFeedback?.melhoria || '',
      },
    });
    if (!own(version)) return;
    narrativeDraft.markSaved();
    sessionId = saved.sessao_id;
    await fetchRecord(sessionId, version);
    if (!own(version)) return;
    showListening();
    status('Sessão guardada no seu diário com sucesso.', 'success');
    notify('Sessão guardada no diário.', 'success');
    changed();
  }

  async function importStarterCatalog(triggerContainer = $('#view-session'), { rerunListening = false } = {}) {
    await action(triggerContainer, async (version) => {
      status('Carregando seleção inicial de músicas reais no seu catálogo…', 'loading');
      const result = await api('/api/catalogo-referencia/importar', { method: 'POST', body: {} });
      if (!own(version)) return;
      await refreshCatalogGuidance();
      if (!own(version)) return;
      changed();
      const added = Number(result.importadas) || 0;
      notify(added
        ? `${added} músicas adicionadas ao seu catálogo.`
        : 'A seleção inicial já está no seu catálogo.', 'success');
      if (rerunListening && record && !sessionId) {
        await exploreRecommendations(version, {
          emocoes: record.analise?.emocoes || [],
          desejos: record.analise?.estado_desejado || [],
          textoDesejado: record.texto_desejado || '',
        });
      } else {
        status('Seleção inicial pronta! Escolha seu objetivo para ver até 3 faixas.', 'success');
      }
    });
  }

  function syncEntryDynamics() {
    const text = $('#narrative-text')?.value || '';
    const hasNote = text.trim().length > 0;
    const counter = $('#narrative-counter');
    if (counter) {
      const len = text.trim().length;
      if (len === 0) {
        counter.textContent = 'Opcional · só seu';
        delete counter.dataset.state;
      } else if (text.length >= 4000) {
        counter.textContent = '4000 / 4000 · limite atingido';
        counter.dataset.state = 'near-limit';
      } else if (text.length >= 3600) {
        counter.textContent = `${text.length} / 4000 · restam ${4000 - text.length}`;
        counter.dataset.state = 'near-limit';
      } else {
        counter.textContent = `${text.length} / 4000 caracteres`;
        counter.dataset.state = 'ready';
      }
      counter.classList.toggle('active', len > 0);
    }

    document.querySelectorAll('[data-objective]').forEach((card) => {
      const active = card.dataset.objective === selectedObjective;
      card.classList.toggle('active', active);
      card.setAttribute('aria-pressed', String(active));
    });
    document.querySelectorAll('[data-state-chip]').forEach((chip) => {
      const active = selectedStates.has(chip.dataset.stateChip);
      chip.classList.toggle('active', active);
      chip.setAttribute('aria-pressed', String(active));
    });

    const submitBtn = $('#entry-submit-button');
    if (submitBtn) {
      const limit = Number($('#session-limit')?.value || 3);
      const label = hasNote
        ? 'Revisar leitura da nota '
        : `Ver até ${limit} ${limit === 1 ? 'faixa' : 'faixas'} para agora `;
      submitBtn.replaceChildren(document.createTextNode(label), el('span', { 'aria-hidden': 'true' }, '→'));
    }
    const draftBtn = $('#save-draft-button');
    if (draftBtn) draftBtn.hidden = !hasNote;

    const purposeVal = ($('#session-purpose')?.value || '').trim().toLowerCase();
    document.querySelectorAll('[data-purpose-chip]').forEach((chip) => {
      const match = chip.dataset.purposeChip.toLowerCase() === purposeVal && purposeVal.length > 0;
      chip.classList.toggle('active', match);
      chip.setAttribute('aria-pressed', String(match));
    });
    const contextVal = ($('#session-context')?.value || '').trim().toLowerCase();
    const contextTokens = contextVal.length > 0
      ? contextVal.split(/[,;·]+/).map((s) => s.trim()).filter(Boolean) : [];
    document.querySelectorAll('[data-context-chip]').forEach((chip) => {
      const target = chip.dataset.contextChip.toLowerCase();
      const match = contextVal === target || contextTokens.includes(target);
      chip.classList.toggle('active', match);
      chip.setAttribute('aria-pressed', String(match));
    });
    const badge = $('#session-options-badge');
    if (badge) {
      const limit = $('#session-limit')?.value || '3';
      const motor = $('#interpretation-engine')?.value === 'llm' ? 'LLM externo' : 'Dicionário local';
      const ctx = ($('#session-context')?.value || '').trim();
      badge.textContent = `${ctx ? 'Com contexto · ' : ''}Até ${limit} ${Number(limit) === 1 ? 'faixa' : 'faixas'} · ${motor}`;
    }
    syncMoodAtmosphere();
  }

  function syncFeedbackChoices() {
    const val = $('#feedback-answer')?.value || '';
    document.querySelectorAll('[data-feedback-choice]').forEach((btn) => {
      const active = btn.dataset.feedbackChoice === val && val.length > 0;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-pressed', String(active));
    });
  }

  function syncSuggestionFitChoices() {
    document.querySelectorAll('[data-suggestion-fit]').forEach((chip) => {
      const active = chip.dataset.suggestionFit === suggestionFitNote && Boolean(suggestionFitNote);
      chip.classList.toggle('active', active);
      chip.setAttribute('aria-pressed', String(active));
    });
  }

  function syncCatalogFeelingChips() {
    const raw = ($('#catalog-feelings')?.value || '').toLowerCase();
    const tokens = new Set(raw.split(/[\s,;]+/).filter(Boolean));
    document.querySelectorAll('[data-feeling-chip]').forEach((chip) => {
      const active = tokens.has(chip.dataset.feelingChip.toLowerCase());
      chip.classList.toggle('active', active);
      chip.setAttribute('aria-pressed', String(active));
    });
  }

  function isPendingCatalogSong(song) {
    return !Array.isArray(song.sentimentos_associados)
      || !song.sentimentos_associados.some(value => CATEGORIAS.includes(value));
  }

  function catalogFilterPredicate(filter) {
    if (filter === 'all') return null;
    if (filter === 'pending') return isPendingCatalogSong;
    return song => Array.isArray(song.sentimentos_associados) && song.sentimentos_associados.includes(filter);
  }

  function syncCatalogFilterChips() {
    document.querySelectorAll('[data-catalog-filter]').forEach((chip) => {
      const active = chip.dataset.catalogFilter === activeCatalogFilter;
      chip.classList.toggle('active', active);
      chip.setAttribute('aria-pressed', String(active));
    });
  }

  function syncCatalogFilterBar({ total = 0, matched = 0, query = '', error = '', searchMatched = [] } = {}) {
    const bar = $('#catalog-filter-bar');
    const chips = document.querySelectorAll('[data-catalog-filter]');
    const show = total > 0 && !error;
    if (bar) bar.hidden = !show;
    const pool = Array.isArray(searchMatched) ? searchMatched : [];
    const counts = { all: pool.length, pending: 0 };
    if (show) {
      for (const song of pool) {
        if (isPendingCatalogSong(song)) counts.pending += 1;
        if (Array.isArray(song.sentimentos_associados)) {
          for (const tag of song.sentimentos_associados) {
            if (CATEGORIAS.includes(tag)) counts[tag] = (counts[tag] || 0) + 1;
          }
        }
      }
    }
    chips.forEach((chip) => {
      const base = chip.dataset.baseLabel || chip.textContent.trim();
      chip.dataset.baseLabel = base;
      const filter = chip.dataset.catalogFilter;
      const count = show ? (counts[filter] || 0) : 0;
      chip.textContent = count > 0 ? `${base} (${count})` : base;
    });
    const badge = $('#catalog-total-badge');
    if (!badge) return;
    if (!show) {
      badge.textContent = '0';
      return;
    }
    const filtered = activeCatalogFilter !== 'all' || Boolean(query);
    badge.textContent = filtered ? `${matched}/${total}` : String(total);
  }

  function applyCatalogFilter(filter = activeCatalogFilter) {
    activeCatalogFilter = filter;
    syncCatalogFilterChips();
    catalogBrowser.setFilter(catalogFilterPredicate(filter));
  }

  async function loadCatalog({ loadReference = true, preserveLimit = false } = {}) {
    const version = ++catalogEpoch;
    if (loadReference) void catalogReference.load();
    catalogBrowser.setBusy(true);
    try {
      const result = await api('/api/musicas');
      if (version !== catalogEpoch) return;
      const songs = result.musicas || [];
      catalogBrowser.setSongs(songs, { preserveLimit });
      if ($('#catalog-status').dataset.type === 'error') catalogStatus('');
    } catch (error) {
      if (version !== catalogEpoch || stale(error)) return;
      catalogStatus(readableError(error), 'error');
      catalogBrowser.setError('Não foi possível carregar suas faixas. Abra Catálogo novamente para tentar.');
    } finally {
      if (version === catalogEpoch) catalogBrowser.setBusy(false);
    }
  }

  document.querySelectorAll('[data-objective]').forEach((card) => {
    card.addEventListener('click', () => {
      const next = card.dataset.objective;
      const prevPurpose = OBJECTIVE_CONFIG[selectedObjective]?.purpose || '';
      selectedObjective = selectedObjective === next ? '' : next;
      const purposeInput = $('#session-purpose');
      if (purposeInput && (!purposeInput.value.trim() || purposeInput.value.trim() === prevPurpose)) {
        purposeInput.value = OBJECTIVE_CONFIG[selectedObjective]?.purpose || '';
      }
      if ($('#session-status')?.dataset.type === 'error') status('');
      syncEntryDynamics();
    });
  });

  document.querySelectorAll('[data-state-chip]').forEach((chip) => {
    chip.addEventListener('click', () => {
      const value = chip.dataset.stateChip;
      if (selectedStates.has(value)) selectedStates.delete(value);
      else selectedStates.add(value);
      if ($('#session-status')?.dataset.type === 'error') status('');
      syncEntryDynamics();
    });
  });

  $('#current-tags')?.addEventListener('change', refreshReviewQuestionFromTags);
  $('#desired-tags')?.addEventListener('change', refreshReviewQuestionFromTags);

  $('#narrative-text')?.addEventListener('input', syncEntryDynamics);
  $('#narrative-text')?.addEventListener('change', syncEntryDynamics);
  $('#session-purpose')?.addEventListener('input', syncEntryDynamics);
  $('#session-purpose')?.addEventListener('change', syncEntryDynamics);
  $('#session-context')?.addEventListener('input', syncEntryDynamics);
  $('#session-context')?.addEventListener('change', syncEntryDynamics);
  $('#session-limit')?.addEventListener('change', syncEntryDynamics);
  $('#narrative-form')?.addEventListener('reset', () => queueMicrotask(syncEntryDynamics));
  window.addEventListener('pageshow', (event) => {
    if (!event.persisted) return;
    syncEntryDynamics();
    syncFeedbackChoices();
    syncSuggestionFitChoices();
    syncCatalogFeelingChips();
  });
  document.querySelectorAll('[data-purpose-chip]').forEach((chip) => {
    chip.addEventListener('click', () => {
      const input = $('#session-purpose');
      if (!input) return;
      const value = chip.dataset.purposeChip;
      input.value = input.value.trim().toLowerCase() === value.toLowerCase() ? '' : value;
      syncEntryDynamics();
    });
  });
  document.querySelectorAll('[data-context-chip]').forEach((chip) => {
    chip.addEventListener('click', () => {
      const input = $('#session-context');
      if (!input) return;
      const value = chip.dataset.contextChip;
      const parts = input.value.split(/[,;·]+/).map((s) => s.trim()).filter(Boolean);
      const exists = parts.some((p) => p.toLowerCase() === value.toLowerCase());
      const next = exists ? parts.filter((p) => p.toLowerCase() !== value.toLowerCase()) : [...parts, value];
      input.value = next.join(', ');
      syncEntryDynamics();
    });
  });
  document.querySelectorAll('[data-suggestion-fit]').forEach((chip) => {
    chip.addEventListener('click', () => {
      const value = chip.dataset.suggestionFit;
      suggestionFitNote = suggestionFitNote === value ? '' : value;
      syncSuggestionFitChoices();
    });
  });

  const handleFeedbackSelection = () => {
    syncFeedbackChoices();
    if ($('#feedback-answer')?.value && $('#feedback-extra-fields')) $('#feedback-extra-fields').open = true;
    if ($('#feedback-status')?.dataset.type === 'error' && $('#feedback-answer')?.value) {
      feedbackStatus('Escolha pronta. Aplique ou guarde no diário quando quiser.');
    }
  };
  document.querySelectorAll('[data-feedback-choice]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const select = $('#feedback-answer');
      if (!select) return;
      select.value = btn.dataset.feedbackChoice;
      handleFeedbackSelection();
    });
  });
  $('#feedback-answer')?.addEventListener('change', handleFeedbackSelection);
  document.querySelectorAll('[data-feeling-chip]').forEach((chip) => {
    chip.addEventListener('click', () => {
      const input = $('#catalog-feelings');
      if (!input) return;
      const target = chip.dataset.feelingChip.toLowerCase();
      const parts = input.value.split(/[\s,;]+/).filter(Boolean);
      const exists = parts.some((p) => p.toLowerCase() === target);
      const next = exists ? parts.filter((p) => p.toLowerCase() !== target) : [...parts, target];
      input.value = next.join(', ');
      syncCatalogFeelingChips();
    });
  });
  $('#catalog-feelings')?.addEventListener('input', syncCatalogFeelingChips);
  $('#catalog-feelings')?.addEventListener('change', syncCatalogFeelingChips);
  $('#catalog-form')?.addEventListener('reset', () => queueMicrotask(syncCatalogFeelingChips));
  document.querySelectorAll('[data-catalog-filter]').forEach((chip) => {
    chip.addEventListener('click', () => applyCatalogFilter(chip.dataset.catalogFilter));
  });

  $('#interpretation-engine').addEventListener('change', () => {
    $('#llm-options').hidden = $('#interpretation-engine').value !== 'llm';
    syncEntryDynamics();
  });

  $('#narrative-form').addEventListener('submit', (event) => {
    event.preventDefault();
    action($('#narrative-form'), async (version) => {
      const note = ($('#narrative-text')?.value || '').trim();
      engine = $('#interpretation-engine').value;
      fallback = $('#allow-fallback').checked;
      if (note) {
        record = {
          sessao_id: null,
          persistido: false,
          texto_usuario: $('#narrative-text').value,
          texto_desejado: null,
          finalidade: $('#session-purpose').value || null,
          contexto: $('#session-context').value || null,
          limite_recomendacoes: Number($('#session-limit').value || 3),
        };
        await generatePreviewInterpretation(version, engine);
        return;
      }
      const quick = resolveQuickSelection({ objective: selectedObjective, states: [...selectedStates] });
      if (!quick.emocoes_atuais.length && !quick.estado_desejado.length) {
        status('Escolha um objetivo acima (Relaxar, Focar, Ganhar energia ou Acolher o momento), marque como está agora ou escreva uma nota opcional.', 'error');
        document.querySelector('[data-objective]')?.focus();
        return;
      }
      await exploreRecommendations(version, {
        emocoes: quick.emocoes_atuais,
        desejos: quick.estado_desejado,
        textoDesejado: quick.estado_desejado[0] || '',
      });
    });
  });

  $('#save-draft-button')?.addEventListener('click', () => {
    action($('#narrative-form'), async (version) => {
      const note = ($('#narrative-text')?.value || '').trim();
      if (!note) {
        status('Escreva uma nota se quiser salvar um rascunho para retomar depois.', 'error');
        $('#narrative-text')?.focus();
        return;
      }
      const submitted = narrativeDraft.capture();
      engine = $('#interpretation-engine').value;
      fallback = $('#allow-fallback').checked;
      status('Salvando rascunho no seu diário…', 'loading');
      const response = await api('/api/registrar-estado', { method: 'POST', body: {
        texto_atual: $('#narrative-text').value,
        finalidade: $('#session-purpose').value || null,
        contexto: $('#session-context').value || null,
        limite_recomendacoes: Number($('#session-limit').value),
      } });
      if (!own(version)) return;
      narrativeDraft.markSaved(submitted);
      sessionId = response.sessao_id;
      record = { ...response, texto_desejado: null };
      syncPersistenceUI();
      changed();
      await fetchRecord(sessionId, version);
      if (own(version)) await generate(version);
    });
  });

  $('#review-back-entry')?.addEventListener('click', () => {
    status('');
    stage(1, { animate: true, focusTarget: $('#narrative-heading') });
  });
  $('#listening-change-objective')?.addEventListener('click', () => {
    status('');
    stage(1, { animate: true, focusTarget: $('#narrative-heading') });
  });
  $('#empty-change-objective')?.addEventListener('click', () => {
    status('');
    stage(1, { animate: true, focusTarget: $('#narrative-heading') });
  });
  $('#entry-import-reference')?.addEventListener('click', () => {
    void importStarterCatalog($('#session-entry'), { rerunListening: false });
  });
  $('#empty-import-reference')?.addEventListener('click', () => {
    void importStarterCatalog($('#session-listening'), { rerunListening: true });
  });

  $('#review-toggle-editor')?.addEventListener('click', () => {
    const panel = $('#review-editor-panel');
    const willOpen = panel ? panel.hidden : true;
    setReviewEditorOpen(willOpen);
    if (willOpen) panel?.querySelector('input, textarea, button')?.focus();
  });
  $('#review-quick-confirm')?.addEventListener('click', () => {
    action($('#session-review'), (version) => submitReview(version, false));
  });

  $('#session-retry').addEventListener('click', () => action($('#session-review'), (version) => generate(version)));
  $('#fallback-local-button').addEventListener('click', () => action($('#session-review'), (version) => generate(version, 'dicionario')));
  $('#review-form').addEventListener('submit', (event) => { event.preventDefault(); action($('#review-form'), (version) => submitReview(version)); });
  $('#review-without-category').addEventListener('click', () => action($('#session-review'), (version) => submitReview(version, true)));
  $('#clear-current-tags').addEventListener('click', () => clear('current-tags'));
  $('#clear-desired-tags').addEventListener('click', () => clear('desired-tags'));
  $('#refresh-drafts').addEventListener('click', () => loadDrafts());
  $('#open-catalog-button').addEventListener('click', () => onCatalog());
  $('#entry-open-catalog').addEventListener('click', () => onCatalog());
  $('#entry-retry-catalog').addEventListener('click', () => void refreshCatalogGuidance());
  $('#listening-retry-catalog').addEventListener('click', () => void refreshCatalogGuidance());
  $('#session-to-history').addEventListener('click', () => onHistory());
  $('#start-another').addEventListener('click', () => newSession());
  $('#new-session-button')?.addEventListener('click', () => newSession());
  $('#review-new-session')?.addEventListener('click', () => newSession());

  $('#save-to-diary-button')?.addEventListener('click', () => {
    action($('#diary-save-card'), (version) => saveSessionToDiary(version));
  });
  $('#finish-without-saving')?.addEventListener('click', () => {
    reset();
    notify('Sessão concluída sem gravar nada no diário.', 'info');
    void refreshCatalogGuidance();
  });

  async function saveListening(version, none = false) {
    if (!record) return;
    const faixas = collectCurrentListeningFromDOM(none);
    if (!none && (!faixas || !faixas.length)) {
      status('Marque ao menos uma faixa ou use “Não escolher nenhuma faixa”.', 'error');
      return;
    }
    if (!sessionId) {
      record.escuta = { faixas };
      status(none
        ? 'Decisão anotada nesta sessão. Clique em “Guardar no meu diário” abaixo se quiser salvar.'
        : 'Escolha anotada nesta sessão. Clique em “Guardar no meu diário” abaixo se quiser salvar.', 'success');
      if (none) showListening();
      return;
    }
    const response = await api('/api/escuta', { method: 'POST', body: { sessao_id: sessionId, faixas } });
    if (!own(version)) return;
    record.escuta = response.escuta;
    status(none ? 'Sua decisão de não escolher uma faixa foi salva. O retorno continua opcional.' : 'Escolha e informação de escuta salvas. Você pode registrar seu retorno quando quiser.', 'success');
    if (none) showListening();
    changed();
  }
  $('#listening-form').addEventListener('submit', (event) => { event.preventDefault(); action($('#listening-form'), (version) => saveListening(version)); });
  $('#choose-none').addEventListener('click', () => action($('#listening-form'), (version) => saveListening(version, true)));

  $('#feedback-form').addEventListener('submit', (event) => {
    event.preventDefault();
    action($('#feedback-form'), async (version) => {
      const feedback = collectCurrentFeedbackFromDOM();
      if (!feedback) {
        feedbackStatus('Escolha uma resposta ou use “Pular retorno”.', 'error');
        $('#feedback-answer').focus();
        return;
      }
      if (!sessionId) {
        record.feedback = feedback;
        feedbackStatus('Percepção anotada nesta sessão temporária. Use “Guardar no meu diário” abaixo se quiser persistir.', 'success');
        return;
      }
      await api('/api/feedback', { method: 'POST', body: { sessao_id: sessionId, ...feedback } });
      if (!own(version)) return;
      record.feedback = feedback;
      feedbackStatus('Seu retorno foi salvo para esta sessão, sem atribuir o resultado a uma faixa específica.', 'success');
      $('#feedback-later').textContent = 'Manter retorno atual';
      notify('Retorno salvo.', 'success');
      changed();
    });
  });
  $('#feedback-later').addEventListener('click', () => {
    if (!sessionId && record) record.feedback = null;
    feedbackStatus(typeof record?.feedback?.ajudou === 'boolean'
      ? 'O retorno já salvo foi mantido.'
      : 'Retorno pulado. Nada é obrigatório nesta etapa.');
  });

  $('#catalog-form').addEventListener('submit', (event) => {
    event.preventDefault();
    action($('#catalog-form'), async (version) => {
      catalogStatus('Adicionando a faixa ao seu catálogo…', 'loading');
      await api('/api/musicas', { method: 'POST', body: {
        nome: $('#catalog-name').value, artista: $('#catalog-artist').value,
        duracao: $('#catalog-duration').value, sentimentos_texto: $('#catalog-feelings').value,
      } });
      if (!own(version)) return;
      $('#catalog-form').reset();
      syncCatalogFeelingChips();
      catalogStatus('Faixa adicionada ao seu catálogo. Ela estará disponível nas próximas sessões.', 'success');
      await loadCatalog({ loadReference: false });
      if (!own(version)) return;
      changed();
      void refreshCatalogGuidance();
    });
  });
  $('#catalog-demo').addEventListener('click', () => action($('#view-catalog'), async (version) => {
    catalogStatus('Preparando as faixas fictícias do seu catálogo…', 'loading');
    const current = await api('/api/musicas');
    if (!own(version)) return;
    const existing = new Set((current.musicas || []).map((song) => `${song.nome}|${song.artista}`));
    let added = 0;
    for (const song of FAIXAS_EXEMPLO) {
      if (existing.has(`${song.nome}|${song.artista}`)) continue;
      await api('/api/musicas', { method: 'POST', body: song });
      if (!own(version)) return;
      added += 1;
    }
    catalogStatus(added
      ? 'Faixas fictícias adicionadas ao seu catálogo para experimentar as próximas sessões.'
      : 'As faixas fictícias de exemplo já estão no seu catálogo.', 'success');
    await loadCatalog({ loadReference: false });
    if (!own(version)) return;
    changed();
    void refreshCatalogGuidance();
  }));

  async function startWithObjective(objective) {
    const version = epoch;
    if (!await confirmLeave() || !own(version)) return false;
    reset();
    notify('');
    selectedObjective = OBJECTIVE_CONFIG[objective] ? objective : '';
    const purpose = OBJECTIVE_CONFIG[selectedObjective]?.purpose || '';
    if ($('#session-purpose') && purpose) $('#session-purpose').value = purpose;
    syncEntryDynamics();
    void loadDrafts();
    const quick = resolveQuickSelection({ objective: selectedObjective, states: [] });
    await action($('#view-session'), async (runVersion) => {
      await exploreRecommendations(runVersion, {
        emocoes: quick.emocoes_atuais,
        desejos: quick.estado_desejado,
        textoDesejado: quick.estado_desejado[0] || '',
      });
    });
    return true;
  }

  reset();
  return {
    open, reset, newSession, startWithObjective, importStarterCatalog,
    loadDrafts, loadCatalog, refreshCatalogGuidance, confirmLeave,
    invalidateDeleted(ids) {
      if (!sessionId || !Array.isArray(ids) || !ids.includes(sessionId)) return;
      const preserveNarrative = narrativeDraft.hasChanges();
      reset({ preserveNarrative });
      if (preserveNarrative) status('O registro salvo foi excluído. Suas alterações ainda não enviadas continuam neste formulário.');
    },
  };
}
