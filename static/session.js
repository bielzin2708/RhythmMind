import { $, el, categoriaLabel, strategyLabel, CATEGORIAS, withBusy } from './ui.js';

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

  const own = (version) => epoch === version;
  const changed = () => { if (onChanged) onChanged(); };
  const status = (message, kind = 'info') => {
    const target = $('#session-status');
    target.textContent = message;
    target.dataset.type = kind;
    target.hidden = !message;
    target.setAttribute('role', kind === 'error' ? 'alert' : 'status');
  };

  async function action(container, callback) {
    const version = epoch;
    try {
      await withBusy(container, () => callback(version));
    } catch (error) {
      if (!own(version) || stale(error)) return;
      const message = readableError(error);
      if (container?.closest('#view-catalog') || container?.id === 'view-catalog') {
        $('#catalog-status').textContent = message;
        $('#catalog-status').dataset.type = 'error';
      } else status(message, 'error');
      notify(message, 'error');
    }
  }

  function stage(number) {
    $('#session-entry').hidden = number !== 1;
    $('#session-review').hidden = number !== 2;
    $('#session-listening').hidden = number !== 3;
    ['relato', 'revisao', 'escuta'].forEach((name, index) => {
      const item = $(`#step-${name}`);
      if (index + 1 === number) item.setAttribute('aria-current', 'step');
      else item.removeAttribute('aria-current');
      item.dataset.complete = String(index + 1 < number);
      item.classList.toggle('current', index + 1 === number);
      item.classList.toggle('complete', index + 1 < number);
    });
  }

  function reset() {
    epoch += 1;
    draftsEpoch += 1;
    catalogEpoch += 1;
    sessionId = null;
    record = null;
    interpretation = null;
    legacyPartial = false;
    engine = 'dicionario';
    fallback = false;
    ['narrative-form', 'review-form', 'listening-form', 'feedback-form', 'catalog-form'].forEach((id) => $(`#${id}`).reset());
    ['review-original', 'review-reflection', 'review-origin', 'review-references', 'review-clarification', 'strategy-summary', 'recommendation-list', 'draft-list', 'catalog-list'].forEach((id) => $(`#${id}`).replaceChildren());
    $('#current-tags').replaceChildren();
    $('#desired-tags').replaceChildren();
    $('#desired-text').readOnly = false;
    $('#session-heading').textContent = 'Seu momento, nas suas palavras';
    $('#review-form').hidden = false;
    $('#session-retry').hidden = true;
    $('#fallback-local-button').hidden = true;
    $('#review-clarification').hidden = true;
    $('#llm-options').hidden = true;
    $('#draft-count').textContent = '0';
    $('#catalog-status').textContent = '';
    $('#feedback-status').textContent = '';
    status('');
    stage(1);
  }

  function newSession() {
    reset();
    loadDrafts();
    $('#narrative-text').focus();
  }

  function categories(targetId, name, selected, disabled = false) {
    const target = $(`#${targetId}`);
    target.disabled = disabled;
    const legend = el('legend', {}, name === 'current' ? 'Estado atual' : 'Estado desejado · intenção');
    const grid = el('div', { class: 'tag-grid' });
    CATEGORIAS.forEach((category) => {
      const input = el('input', { type: 'checkbox', name, value: category, id: `${name}-${category}` });
      input.checked = selected.includes(category);
      grid.append(el('label', { class: 'tag-option', for: input.id }, input, el('span', {}, categoriaLabel(category))));
    });
    target.replaceChildren(legend, grid);
  }

  function selected(targetId) {
    return [...$(`#${targetId}`).querySelectorAll('input:checked')].map((input) => input.value);
  }

  function clear(targetId) {
    $(`#${targetId}`).querySelectorAll('input').forEach((input) => { if (!input.disabled) input.checked = false; });
  }

  function referenceList(ids) {
    const target = $('#review-references');
    target.hidden = !ids?.length;
    if (!ids?.length) { target.replaceChildren(); return; }
    const list = el('ul', { class: 'reference-list' });
    ids.forEach((id) => list.append(el('li', {}, `${id} · ${REFERENCIAS[id] || 'Regra da base de conhecimento utilizada nesta sugestão.'}`)));
    target.replaceChildren(el('summary', {}, 'O que orientou esta sugestão'), list);
  }

  function showPending(message = 'Seu relato está salvo. Escolha como continuar a interpretação.') {
    stage(2);
    $('#session-heading').textContent = 'Vamos revisar a interpretação';
    $('#review-original').textContent = record?.texto_usuario || '';
    $('#review-reflection').textContent = message;
    $('#review-origin').textContent = 'Interpretação ainda não concluída.';
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
    stage(2);
    $('#session-heading').textContent = 'A interpretação é sua para revisar';
    $('#review-form').hidden = false;
    $('#review-original').textContent = record.texto_usuario;
    $('#review-reflection').textContent = proposal.resumo_reflexivo || 'Com base no seu relato, estas são sugestões para você revisar.';
    $('#review-clarification').hidden = !proposal.precisa_esclarecimento;
    if (proposal.precisa_esclarecimento) {
      const doubts = [...(proposal.estado_atual?.ambiguidades || []), ...(proposal.estado_desejado?.ambiguidades || [])];
      $('#review-clarification').textContent = doubts.length
        ? `Falta um pouco de contexto para esta leitura. ${doubts.join(' ')}`
        : 'Seu relato ainda deixa dúvidas. Revise apenas o que reconhece ou siga sem categoria; você também pode iniciar um novo relato com mais contexto.';
    }
    const source = result.motor_utilizado === 'llm'
      ? `Interpretação sugerida por LLM${result.modelo ? ` (${result.modelo})` : ''}.`
      : 'Interpretação sugerida pelo dicionário local.';
    $('#review-origin').textContent = source + (result.fallback_motivo ? ' A alternativa local que você autorizou foi usada porque o serviço externo não concluiu a leitura.' : '');
    referenceList(proposal.referencias_base);
    categories('current-tags', 'current', (proposal.estado_atual?.sugestoes || []).map((item) => item.categoria));
    const closedDesire = record.texto_desejado === '';
    categories('desired-tags', 'desired', closedDesire ? [] : (proposal.estado_desejado?.sugestoes || []).map((item) => item.categoria), closedDesire);
    $('#desired-text').value = record.texto_desejado !== null && record.texto_desejado !== undefined
      ? record.texto_desejado : (proposal.texto_intencao || '');
    $('#desired-text').readOnly = record.texto_desejado !== null && record.texto_desejado !== undefined;
    $('#review-without-category').disabled = false;
    $('#clear-current-tags').disabled = false;
    $('#clear-desired-tags').disabled = closedDesire;
    $('#session-retry').hidden = true;
    $('#fallback-local-button').hidden = true;
    status('Interpretação sugerida para revisão. Nada foi confirmado por você ainda.');
  }

  function showLegacyPartial() {
    interpretation = null;
    legacyPartial = true;
    stage(2);
    $('#session-heading').textContent = 'Continue de onde parou';
    $('#review-form').hidden = false;
    $('#review-original').textContent = record.texto_usuario || '';
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

  async function generate(version, motor = engine) {
    if (!sessionId || !record || !own(version)) return;
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

  async function fetchRecord(id, version) {
    const response = await api('/api/historico/sessao', { query: { sessao_id: id } });
    if (!own(version)) return null;
    record = response.registro;
    return record;
  }

  async function open(id) {
    reset();
    sessionId = id;
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
          showPending('Seu relato foi salvo antes da interpretação. Use o botão abaixo para continuar.');
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
    try {
      const history = await api('/api/historico');
      if (requestVersion !== draftsEpoch) return;
      const drafts = Object.entries(history.registros || {}).filter(([, item]) => item.progresso && !item.progresso.recomendacoes_geradas).reverse();
      $('#draft-count').textContent = String(drafts.length);
      const list = $('#draft-list');
      list.replaceChildren();
      if (!drafts.length) list.append(el('p', { class: 'hint' }, 'Nenhum rascunho pendente. Você pode começar uma nova sessão.'));
      drafts.forEach(([id, item]) => {
        const text = item.texto_usuario || 'Relato salvo';
        const button = el('button', { type: 'button', class: 'draft-card' },
          el('span', { class: 'eyebrow' }, item.data_hora || 'Rascunho salvo'),
          el('strong', {}, text.length > 90 ? `${text.slice(0, 90)}…` : text),
          el('span', { class: 'hint' }, 'Retomar a última etapa salva'));
        button.addEventListener('click', () => open(id));
        list.append(button);
      });
    } catch (error) {
      if (requestVersion !== draftsEpoch || stale(error)) return;
      $('#draft-list').replaceChildren(el('p', { class: 'hint' }, 'Não foi possível carregar os rascunhos agora. Use “Atualizar” para tentar novamente.'));
    }
  }

  function showListening() {
    stage(3);
    legacyPartial = false;
    $('#session-heading').textContent = 'Uma proposta de escuta para o seu momento';
    $('#session-retry').hidden = true;
    $('#fallback-local-button').hidden = true;
    $('#strategy-summary').replaceChildren(
      el('strong', {}, record.estrategia ? strategyLabel(record.estrategia) : 'Sem uma estratégia definida'),
      el('p', {}, record.explicacao || 'As escolhas confirmadas não forneceram um critério para sugerir faixas nesta sessão.'),
      el('p', { class: 'hint' }, record.estrategia === 'foco_cognitivo'
        ? 'A escuta também pode distrair, dependendo da tarefa. Observe como ela funciona para você.'
        : 'Esta é uma possibilidade de escuta, sem garantia de mudança. Sua percepção pode ser diferente.'),
    );
    const musicas = record.recomendacoes || [];
    const choices = new Map((record.escuta?.faixas || []).map((choice) => [choice.indice_recomendacao, choice]));
    const list = $('#recommendation-list');
    list.replaceChildren();
    $('#recommendation-empty').hidden = musicas.length > 0;
    $('#save-listening').disabled = !musicas.length;
    musicas.forEach((music, index) => {
      const number = index + 1;
      const existing = choices.get(number);
      const check = el('input', { type: 'checkbox', id: `track-select-${number}`, value: String(number), name: 'faixa' });
      check.checked = Boolean(existing);
      const heard = el('select', { id: `track-heard-${number}`, 'aria-label': `Escuta de ${music.nome || `faixa ${number}`}` },
        el('option', { value: '' }, 'Escuta ainda não informada'),
        el('option', { value: 'true' }, 'Ouvi'),
        el('option', { value: 'false' }, 'Não ouvi'));
      heard.value = existing?.ouvida === true ? 'true' : existing?.ouvida === false ? 'false' : '';
      heard.disabled = !check.checked;
      check.addEventListener('change', () => { heard.disabled = !check.checked; });
      const reason = (record.motivos_recomendacoes || []).find((item) => item.indice_recomendacao === number);
      list.append(el('article', { class: 'music-card' },
        el('div', { class: 'music-meta' }, el('h3', {}, music.nome || 'Faixa cadastrada'),
          el('p', {}, `${music.artista || 'Artista não informado'} · ${music.duracao || 'Duração não informada'}`)),
        el('p', { class: 'music-reason' }, reason?.explicacao || 'Faixa presente no seu catálogo e selecionada conforme as categorias confirmadas.'),
        el('div', { class: 'choice-control' }, el('label', { for: check.id }, check, ' Escolher esta faixa'),
          el('label', { for: heard.id }, 'Sobre a escuta', heard))));
    });
    const feedback = record.feedback;
    let comment = feedback?.motivo || '';
    const noChange = feedback?.ajudou === false && comment.startsWith('Não percebi mudança.');
    if (noChange) comment = comment.slice('Não percebi mudança.'.length).trim();
    $('#feedback-answer').value = feedback?.ajudou === true ? 'ajudou' : noChange ? 'sem_mudanca' : feedback?.ajudou === false ? 'nao_ajudou' : '';
    $('#feedback-comment').value = comment;
    $('#feedback-improvement').value = feedback?.melhoria || '';
    $('#feedback-later').textContent = typeof feedback?.ajudou === 'boolean' ? 'Manter retorno atual' : 'Responder depois';
    $('#feedback-status').textContent = typeof feedback?.ajudou === 'boolean' ? 'Esta sessão já tem um retorno registrado. Você pode mantê-lo ou atualizá-lo.' : 'O retorno ainda não foi informado.';
    status(record.escuta?.faixas?.length === 0
      ? 'Você registrou a decisão de não escolher uma faixa nesta sessão.'
      : record.escuta ? 'Sua escolha de faixa e a informação de escuta estão salvas.'
        : 'Escolher uma faixa e informar que a ouviu são decisões separadas.');
  }

  async function submitReview(version, noCategories = false) {
    if (!record || !sessionId) return;
    const desireText = record.texto_desejado !== null && record.texto_desejado !== undefined
      ? record.texto_desejado : $('#desired-text').value;
    if (legacyPartial) {
      await api('/api/retomar-sessao', { method: 'POST', body: { sessao_id: sessionId, texto_desejado: desireText } });
    } else {
      if (!interpretation) return;
      const wanted = noCategories ? [] : selected('desired-tags');
      if (wanted.length && !desireText.trim()) {
        status('Descreva a intenção que deseja confirmar, ou limpe as etiquetas de estado desejado.', 'error');
        $('#desired-text').focus();
        return;
      }
      await api('/api/revisoes-interpretacao', { method: 'POST', body: {
        sessao_id: sessionId, interpretacao_id: interpretation.interpretacao_id,
        emocoes_confirmadas: noCategories ? [] : selected('current-tags'),
        estado_desejado_confirmado: wanted, texto_desejado: desireText,
      } });
    }
    if (!own(version)) return;
    if (!await fetchRecord(sessionId, version)) return;
    showListening();
    changed();
  }

  async function loadCatalog() {
    const version = ++catalogEpoch;
    try {
      const result = await api('/api/musicas');
      if (version !== catalogEpoch) return;
      const list = $('#catalog-list');
      list.replaceChildren();
      const songs = result.musicas || [];
      if (!songs.length) list.append(el('p', { class: 'empty-state' }, 'Seu catálogo ainda está vazio. Adicione uma faixa ou use as faixas fictícias para experimentar o fluxo.'));
      songs.forEach((song) => list.append(el('article', { class: 'music-card' },
        el('h3', {}, song.nome || 'Faixa cadastrada'),
        el('p', { class: 'hint' }, `${song.artista || 'Artista não informado'} · ${song.duracao || 'Duração não informada'}`))));
    } catch (error) {
      if (version !== catalogEpoch || stale(error)) return;
      $('#catalog-status').textContent = readableError(error);
    }
  }

  $('#interpretation-engine').addEventListener('change', () => {
    $('#llm-options').hidden = $('#interpretation-engine').value !== 'llm';
  });
  $('#narrative-form').addEventListener('submit', (event) => {
    event.preventDefault();
    action($('#narrative-form'), async (version) => {
      engine = $('#interpretation-engine').value;
      fallback = $('#allow-fallback').checked;
      status('Salvando seu relato…', 'loading');
      const response = await api('/api/registrar-estado', { method: 'POST', body: {
        texto_atual: $('#narrative-text').value,
        finalidade: $('#session-purpose').value || null,
        contexto: $('#session-context').value || null,
        limite_recomendacoes: Number($('#session-limit').value),
      } });
      if (!own(version)) return;
      sessionId = response.sessao_id;
      record = { ...response, texto_desejado: null };
      showPending();
      changed();
      await fetchRecord(sessionId, version);
      if (own(version)) await generate(version);
    });
  });
  $('#session-retry').addEventListener('click', () => action($('#session-review'), (version) => generate(version)));
  $('#fallback-local-button').addEventListener('click', () => action($('#session-review'), (version) => generate(version, 'dicionario')));
  $('#review-form').addEventListener('submit', (event) => { event.preventDefault(); action($('#review-form'), (version) => submitReview(version)); });
  $('#review-without-category').addEventListener('click', () => action($('#review-form'), (version) => submitReview(version, true)));
  $('#review-adjust').addEventListener('click', () => $('#current-tags').querySelector('input:not(:disabled)')?.focus());
  $('#clear-current-tags').addEventListener('click', () => clear('current-tags'));
  $('#clear-desired-tags').addEventListener('click', () => clear('desired-tags'));
  $('#refresh-drafts').addEventListener('click', () => loadDrafts());
  $('#open-catalog-button').addEventListener('click', () => onCatalog());
  $('#session-to-history').addEventListener('click', () => onHistory());
  $('#start-another').addEventListener('click', () => newSession());
  $('#new-session-button')?.addEventListener('click', () => newSession());

  async function saveListening(version, none = false) {
    if (!sessionId || !record) return;
    const faixas = none ? [] : [...$('#recommendation-list').querySelectorAll('input[name="faixa"]:checked')].map((input) => {
      const heard = $(`#track-heard-${input.value}`).value;
      return { indice_recomendacao: Number(input.value), ouvida: heard === '' ? null : heard === 'true' };
    });
    if (!none && !faixas.length) {
      status('Escolha uma faixa ou use “Não escolher uma faixa agora” para registrar essa decisão.', 'error');
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
      if (!sessionId) return;
      const answer = $('#feedback-answer').value;
      if (!answer) {
        $('#feedback-status').textContent = 'Escolha uma resposta ou use “Responder depois” para manter o retorno pendente.';
        $('#feedback-answer').focus();
        return;
      }
      const comment = $('#feedback-comment').value.trim();
      const motive = answer === 'sem_mudanca' ? `Não percebi mudança.${comment ? ` ${comment}` : ''}` : comment;
      const feedback = { ajudou: answer === 'ajudou', motivo: motive, melhoria: $('#feedback-improvement').value.trim() };
      await api('/api/feedback', { method: 'POST', body: { sessao_id: sessionId, ...feedback } });
      if (!own(version)) return;
      record.feedback = feedback;
      $('#feedback-status').textContent = 'Seu retorno foi salvo para esta sessão, sem atribuir o resultado a uma faixa específica.';
      $('#feedback-later').textContent = 'Manter retorno atual';
      notify('Retorno salvo.', 'success');
      changed();
    });
  });
  $('#feedback-later').addEventListener('click', () => {
    $('#feedback-status').textContent = typeof record?.feedback?.ajudou === 'boolean'
      ? 'O retorno já salvo foi mantido.'
      : 'O retorno permanece pendente. Você pode voltar a esta sessão pelo histórico.';
  });

  $('#catalog-form').addEventListener('submit', (event) => {
    event.preventDefault();
    action($('#catalog-form'), async (version) => {
      $('#catalog-status').textContent = 'Adicionando a faixa ao seu catálogo…';
      $('#catalog-status').dataset.type = 'loading';
      await api('/api/musicas', { method: 'POST', body: {
        nome: $('#catalog-name').value, artista: $('#catalog-artist').value,
        duracao: $('#catalog-duration').value, sentimentos_texto: $('#catalog-feelings').value,
      } });
      if (!own(version)) return;
      $('#catalog-form').reset();
      $('#catalog-status').textContent = 'Faixa adicionada ao seu catálogo. Ela estará disponível nas próximas sessões.';
      $('#catalog-status').dataset.type = 'success';
      await loadCatalog();
      changed();
    });
  });
  $('#catalog-demo').addEventListener('click', () => action($('#view-catalog'), async (version) => {
    $('#catalog-status').textContent = 'Preparando as faixas fictícias do seu catálogo…';
    $('#catalog-status').dataset.type = 'loading';
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
    $('#catalog-status').textContent = added
      ? 'Faixas fictícias adicionadas ao seu catálogo para experimentar as próximas sessões.'
      : 'As faixas fictícias de exemplo já estão no seu catálogo.';
    $('#catalog-status').dataset.type = 'success';
    await loadCatalog();
    changed();
  }));

  reset();
  return {
    open, reset, newSession, loadDrafts, loadCatalog,
    invalidateDeleted(ids) {
      if (sessionId && Array.isArray(ids) && ids.includes(sessionId)) reset();
    },
  };
}
