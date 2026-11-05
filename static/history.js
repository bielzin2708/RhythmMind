import {
  categoriaLabel, strategyLabel, confirmAction, downloadJSON, formatDate, withBusy,
} from './ui.js';

const byId = (id) => document.getElementById(id);
const textNode = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
};
const present = (value) => typeof value === 'string' && value.trim() ? value : 'Não informado';
const fieldLabels = { finalidade: 'Finalidade', contexto: 'Contexto', observacoes: 'Observações' };

function categoryGroup(title, categories, empty) {
  const group = textNode('div', 'history-category-group');
  group.append(textNode('h4', '', title));
  if (!Array.isArray(categories) || categories.length === 0) {
    group.append(textNode('p', 'muted', empty));
    return group;
  }
  const tags = textNode('div', 'tag-list');
  for (const category of categories) tags.append(textNode('span', 'tag', categoriaLabel(category)));
  group.append(tags);
  return group;
}

function listeningText(record) {
  if (!record.escuta || !Array.isArray(record.escuta.faixas)) return 'Escolha ainda não registrada';
  if (!record.escuta.faixas.length) return 'Você optou por não escolher uma faixa';
  const selected = record.escuta.faixas.length;
  const heard = record.escuta.faixas.filter((track) => track.ouvida === true).length;
  const notHeard = record.escuta.faixas.filter((track) => track.ouvida === false).length;
  const unknown = selected - heard - notHeard;
  const detail = [];
  if (heard) detail.push(`${heard} com escuta informada`);
  if (notHeard) detail.push(`${notHeard} ${notHeard === 1 ? 'não ouvida' : 'não ouvidas'}`);
  if (unknown) detail.push(`escuta não informada em ${unknown}`);
  return `${selected} ${selected === 1 ? 'faixa escolhida' : 'faixas escolhidas'} · ${detail.join('; ')}`;
}

function feedbackText(record) {
  if (record.feedback?.ajudou === true) return 'Ajuda percebida relatada';
  if (record.feedback?.ajudou === false) return 'Sem ajuda relatada';
  return 'Retorno ainda não registrado';
}

function completed(record) {
  return !record.progresso || record.progresso.recomendacoes_geradas === true;
}

function sessionState(record) {
  if (completed(record)) return 'Sessão registrada';
  if (record.progresso?.emocoes_confirmadas) return 'Etapa pendente';
  return 'Rascunho · revisão pendente';
}

function dateSort(record) {
  const value = record.data_hora;
  if (typeof value !== 'string') return 0;
  const local = /^(\d{2})\/(\d{2})\/(\d{4}) (\d{2}):(\d{2}):(\d{2})$/.exec(value);
  if (local) return Date.UTC(+local[3], +local[2] - 1, +local[1], +local[4], +local[5], +local[6]);
  return Date.parse(value) || 0;
}

export function initHistory({ api, notify, onResume, onChanged }) {
  let epoch = 0;
  let listVersion = 0;
  let detailVersion = 0;
  let records = {};
  let selected = null;
  let totalRecords = 0;

  const status = (message = '', kind = 'info') => {
    const box = byId('history-status');
    box.textContent = message;
    box.className = 'notice';
    box.dataset.type = kind;
    box.hidden = !message;
    box.setAttribute('role', kind === 'error' ? 'alert' : 'status');
  };

  const quietError = (error) => error?.name === 'StaleRequestError'
    || error?.name === 'AbortError' || error?.stale === true;
  const showError = (error, fallback) => {
    if (!quietError(error)) status(error?.message || fallback, 'error');
  };

  function detailButtons() {
    for (const id of ['history-resume', 'history-export-one', 'history-delete-one', 'save-correction']) {
      byId(id).disabled = !selected;
    }
  }

  function clearDetail() {
    detailVersion += 1;
    selected = null;
    byId('history-detail').hidden = true;
    byId('history-detail-content').replaceChildren();
    byId('history-detail-title').textContent = 'Seu registro';
    byId('history-correction-form').reset();
    detailButtons();
  }

  function filterQuery() {
    const form = byId('history-filter-form');
    const query = {};
    for (const name of ['data_inicio', 'data_fim', 'finalidade', 'contexto', 'avaliacao']) {
      const value = form.elements.namedItem(name)?.value?.trim();
      if (value) query[name] = value;
    }
    return query;
  }

  function renderList() {
    const list = byId('history-list');
    list.replaceChildren();
    const entries = Object.entries(records).sort((a, b) => dateSort(b[1]) - dateSort(a[1]));
    byId('history-summary').textContent = `${entries.length} ${entries.length === 1 ? 'registro encontrado' : 'registros encontrados'}`;
    byId('history-empty').hidden = entries.length > 0;
    for (const [id, record] of entries) {
      const card = textNode('article', 'history-card card');
      const heading = textNode('div', 'history-card-heading');
      const title = textNode('h3', '', present(record.finalidade) === 'Não informado' ? 'Sessão de escuta' : record.finalidade);
      const stamp = textNode('p', 'muted small', formatDate(record.data_hora));
      heading.append(title, textNode('span', 'badge', sessionState(record)));
      card.append(heading, stamp);
      if (record.contexto) card.append(textNode('p', 'muted', record.contexto));
      card.append(textNode('p', 'small', listeningText(record)), textNode('p', 'small', feedbackText(record)));
      const button = textNode('button', 'button button-secondary', 'Ver registro');
      button.type = 'button';
      button.dataset.sessionId = id;
      button.addEventListener('click', () => { void openRecord(id); });
      card.append(button);
      list.append(card);
    }
  }

  function renderPatterns(data) {
    const target = byId('patterns-summary');
    target.replaceChildren();
    const counts = data.avaliacoes_sessoes || {};
    totalRecords = Number(counts.sessoes_totais) || 0;
    target.append(textNode('p', 'muted', 'Este resumo considera todas as suas sessões, mesmo quando o histórico está filtrado.'));
    const grid = textNode('div', 'stats-grid');
    const items = [
      [counts.sessoes_totais, 'Sessões registradas'],
      [counts.retornos_positivos, 'Com ajuda percebida relatada'],
      [counts.retornos_negativos, 'Sem ajuda relatada'],
      [counts.retornos_nao_registrados, 'Sem retorno registrado'],
    ];
    for (const [count, label] of items) {
      const tile = textNode('div', 'stat-card');
      tile.append(textNode('strong', 'stat-value', Number(count) || 0), textNode('span', 'muted', label));
      grid.append(tile);
    }
    target.append(grid);
    for (const [key, title, formatter] of [
      ['emocoes_frequentes', 'Categorias atuais mais confirmadas', categoriaLabel],
      ['desejos_frequentes', 'Intenções mais confirmadas', categoriaLabel],
      ['estrategias_frequentes', 'Estratégias mais sugeridas', strategyLabel],
    ]) {
      if (!Array.isArray(data[key]) || !data[key].length) continue;
      target.append(textNode('h3', '', title));
      const values = textNode('ul', 'plain-list');
      for (const [label, count] of data[key]) values.append(textNode('li', '', `${formatter(label)} · ${count} ${count === 1 ? 'registro' : 'registros'}`));
      target.append(values);
    }
    if (data.mensagem) target.append(textNode('p', 'muted', data.mensagem));
    target.append(textNode('p', 'hint', 'Essas associações descrevem seus registros. Elas não demonstram que uma faixa causou uma mudança, e a ausência de retorno não significa uma avaliação negativa.'));
  }

  async function load() {
    const ownEpoch = epoch;
    const version = ++listVersion;
    const list = byId('history-list');
    list.setAttribute('aria-busy', 'true');
    list.replaceChildren(textNode('p', 'muted', 'Carregando seus registros…'));
    byId('history-empty').hidden = true;
    status('Consultando o seu histórico…');
    const [history, patterns] = await Promise.allSettled([
      api('/api/historico', { query: filterQuery() }), api('/api/padroes'),
    ]);
    if (epoch !== ownEpoch || version !== listVersion) return;
    list.setAttribute('aria-busy', 'false');
    if (history.status === 'fulfilled') {
      records = history.value.registros || {};
      renderList();
      if (selected && !Object.hasOwn(records, selected.id)) clearDetail();
      status('');
    } else {
      records = {};
      list.replaceChildren();
      byId('history-summary').textContent = 'Histórico indisponível';
      showError(history.reason, 'Não foi possível consultar o histórico. Tente novamente.');
    }
    if (patterns.status === 'fulfilled') renderPatterns(patterns.value);
    else byId('patterns-summary').replaceChildren(textNode('p', 'muted', 'O resumo de padrões está indisponível. Seus registros não foram alterados.'));
  }

  function readSection(title, value, className = '') {
    const section = textNode('section', `record-section ${className}`.trim());
    section.append(textNode('h3', '', title), textNode('p', 'preserve-lines', present(value)));
    return section;
  }

  function renderDetail() {
    const { id, record } = selected;
    const target = byId('history-detail-content');
    target.replaceChildren();
    byId('history-detail-title').textContent = `Registro de ${formatDate(record.data_hora)}`;
    target.append(readSection('Seu relato original', record.texto_usuario, 'original-record'));
    const metadata = textNode('section', 'record-section');
    metadata.append(textNode('h3', '', 'Finalidade e contexto registrados'));
    metadata.append(textNode('p', '', `Finalidade: ${present(record.finalidade)}`), textNode('p', '', `Contexto: ${present(record.contexto)}`));
    if (record.observacoes) metadata.append(textNode('p', 'preserve-lines', `Observações: ${record.observacoes}`));
    target.append(metadata);

    const interpretation = record.interpretacao;
    const proposal = interpretation?.proposta;
    const suggested = textNode('section', 'record-section');
    suggested.append(textNode('h3', '', 'Interpretação sugerida para revisão'));
    if (proposal) {
      suggested.append(textNode('p', 'preserve-lines', proposal.resumo_reflexivo || 'Sugestões registradas para você revisar.'));
      suggested.append(categoryGroup('Estado atual sugerido', proposal.estado_atual?.sugestoes?.map((item) => item.categoria), 'Nenhuma categoria atual sugerida.'));
      suggested.append(categoryGroup('Estado desejado sugerido', proposal.estado_desejado?.sugestoes?.map((item) => item.categoria), 'Nenhuma categoria desejada sugerida.'));
      if (proposal.texto_intencao) suggested.append(textNode('p', 'preserve-lines muted', `Trecho de intenção sugerido: “${proposal.texto_intencao}”`));
      if (proposal.precisa_esclarecimento) suggested.append(textNode('p', 'notice', 'A interpretação indicou falta de contexto ou ambiguidade. As categorias sugeridas precisam da sua revisão.'));
      if (proposal.referencias_base?.length) suggested.append(textNode('p', 'small muted', `Referências da base: ${proposal.referencias_base.join(', ')}`));
      suggested.append(textNode('p', 'small muted', interpretation.motor_utilizado === 'llm' ? 'Origem: interpretação por LLM.' : 'Origem: interpretação pelo dicionário local.'));
    } else suggested.append(textNode('p', 'muted', 'Não há uma interpretação sugerida salva para esta sessão.'));
    target.append(suggested);

    const confirmed = textNode('section', 'record-section');
    confirmed.append(textNode('h3', '', 'O que você confirmou'));
    const currentConfirmed = !record.progresso || record.progresso.emocoes_confirmadas === true;
    const desiredConfirmed = !record.progresso || record.progresso.estado_desejado_informado === true;
    confirmed.append(categoryGroup('Estado atual confirmado', currentConfirmed ? record.analise?.emocoes : [],
      currentConfirmed ? 'Você seguiu sem categoria atual.' : 'O estado atual ainda não foi confirmado.'));
    confirmed.append(categoryGroup('Estado desejado confirmado', desiredConfirmed ? record.analise?.estado_desejado : [],
      desiredConfirmed ? 'Sem categoria desejada confirmada.' : 'O estado desejado ainda não foi confirmado.'));
    if (record.texto_desejado) confirmed.append(textNode('p', 'preserve-lines', `Sua intenção informada: “${record.texto_desejado}”`));
    target.append(confirmed);

    const listening = textNode('section', 'record-section');
    listening.append(textNode('h3', '', 'Escolha e escuta'), textNode('p', '', listeningText(record)));
    if (record.estrategia) listening.append(textNode('p', 'muted', `Estratégia registrada: ${strategyLabel(record.estrategia)}.`));
    const chosen = Array.isArray(record.escuta?.faixas) ? record.escuta.faixas : [];
    const selections = new Map(chosen.map((track) => [track.indice_recomendacao, track]));
    const songs = textNode('ul', 'plain-list');
    const recommendations = Array.isArray(record.recomendacoes) ? record.recomendacoes : [];
    const reasons = Array.isArray(record.motivos_recomendacoes) ? record.motivos_recomendacoes : [];
    for (const [index, song] of recommendations.entries()) {
      const row = textNode('li', 'record-song');
      row.append(textNode('strong', '', song.nome || 'Faixa sem título'), textNode('span', 'muted', ` ${song.artista || 'Artista não informado'}${song.duracao ? ` · ${song.duracao}` : ''}`));
      const selection = selections.get(index + 1);
      if (selection) row.append(textNode('p', 'small', `Escolhida · ${selection.ouvida === true ? 'escuta informada' : selection.ouvida === false ? 'você informou que não ouviu' : 'escuta ainda não informada'}`));
      const reason = reasons.find((item) => item.indice_recomendacao === index + 1);
      if (reason?.explicacao) row.append(textNode('p', 'small muted', reason.explicacao));
      songs.append(row);
    }
    if (songs.childElementCount) listening.append(songs);
    else listening.append(textNode('p', 'muted', 'Nenhuma faixa sugerida nesta sessão.'));
    target.append(listening);

    const feedback = textNode('section', 'record-section');
    feedback.append(textNode('h3', '', 'Retorno sobre a experiência'), textNode('p', '', feedbackText(record)));
    if (record.feedback?.motivo) feedback.append(textNode('p', 'preserve-lines', record.feedback.motivo));
    if (record.feedback?.melhoria) feedback.append(textNode('p', 'preserve-lines', `Para uma próxima escuta: ${record.feedback.melhoria}`));
    feedback.append(textNode('p', 'small muted', 'O retorno se refere à sessão; não permite atribuir um efeito a uma faixa individual.'));
    target.append(feedback);

    if (Array.isArray(record.correcoes) && record.correcoes.length) {
      const trail = textNode('details', 'record-section');
      trail.append(textNode('summary', '', `Correções registradas (${record.correcoes.length})`));
      for (const correction of record.correcoes) {
        const event = textNode('div', 'correction-entry');
        event.append(textNode('p', 'small muted', formatDate(correction.registrada_em)));
        for (const [field, change] of Object.entries(correction.campos || {})) {
          event.append(textNode('p', 'preserve-lines', `${fieldLabels[field] || field}: ${present(change.anterior)} → ${present(change.novo)}`));
        }
        if (correction.motivo) event.append(textNode('p', 'small', `Motivo: ${correction.motivo}`));
        trail.append(event);
      }
      target.append(trail);
    }
    byId('correction-purpose').value = record.finalidade || '';
    byId('correction-context').value = record.contexto || '';
    byId('correction-notes').value = record.observacoes || '';
    byId('correction-reason').value = '';
    byId('history-resume').textContent = completed(record) ? 'Ver escolha e retorno' : 'Retomar rascunho';
    byId('history-detail').hidden = false;
    detailButtons();
    return id;
  }

  async function openRecord(id, focus = true) {
    const ownEpoch = epoch;
    const version = ++detailVersion;
    selected = null;
    detailButtons();
    byId('history-detail').hidden = false;
    byId('history-detail-title').textContent = 'Carregando seu registro…';
    byId('history-detail-content').replaceChildren();
    try {
      const response = await api('/api/historico/sessao', { query: { sessao_id: id } });
      if (ownEpoch !== epoch || version !== detailVersion) return;
      selected = { id, record: response.registro };
      renderDetail();
      if (focus) {
        const heading = byId('history-detail-title');
        heading.tabIndex = -1;
        heading.focus({ preventScroll: true });
        byId('history-detail').scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    } catch (error) {
      if (ownEpoch !== epoch || version !== detailVersion) return;
      clearDetail();
      showError(error, 'Não foi possível abrir este registro. Atualize o histórico.');
    }
  }

  async function action(control, callback) {
    const ownEpoch = epoch;
    try { await withBusy(control, callback); }
    catch (error) {
      if (ownEpoch === epoch) showError(error, 'A operação não foi concluída. Tente novamente.');
    } finally {
      if (ownEpoch === epoch) detailButtons();
    }
  }

  byId('history-filter-form').addEventListener('submit', (event) => {
    event.preventDefault();
    void load();
  });
  byId('history-clear-filters').addEventListener('click', () => {
    byId('history-filter-form').reset();
    void load();
  });
  byId('history-resume').addEventListener('click', () => {
    if (!selected) return;
    const id = selected.id;
    void action(byId('history-resume'), () => onResume(id));
  });

  byId('history-correction-form').addEventListener('submit', (event) => {
    event.preventDefault();
    if (!selected || !event.currentTarget.reportValidity()) return;
    const snapshot = selected;
    const ownEpoch = epoch;
    const alteracoes = {};
    for (const [field, id] of [['finalidade', 'correction-purpose'], ['contexto', 'correction-context'], ['observacoes', 'correction-notes']]) {
      const value = byId(id).value.trim() || null;
      if ((snapshot.record[field] ?? null) !== value) alteracoes[field] = value;
    }
    if (!Object.keys(alteracoes).length) {
      status('Nenhuma alteração para salvar. O relato original continua preservado.');
      return;
    }
    const motivo = byId('correction-reason').value.trim() || null;
    void action(event.currentTarget, async () => {
      status('Salvando sua correção…');
      try {
        const result = await api('/api/historico/sessao', { method: 'PATCH', body: {
          sessao_id: snapshot.id, alteracoes, motivo,
          revisao_esperada: snapshot.record.revisao_registro || 0,
        } });
        if (ownEpoch !== epoch) return;
        if (selected?.id === snapshot.id) {
          selected = { id: snapshot.id, record: result.registro };
          renderDetail();
        }
        await load();
        if (ownEpoch !== epoch) return;
        status('Correção salva com o histórico das alterações.', 'success');
        notify('Registro corrigido. O relato original foi preservado.', 'success');
        onChanged?.();
      } catch (error) {
        if (ownEpoch !== epoch) return;
        if (error?.status === 409) {
          if (selected?.id === snapshot.id) await openRecord(snapshot.id, false);
          status('Este registro mudou desde sua leitura. Carregamos a versão atual; confira os campos antes de corrigir novamente.', 'error');
          return;
        }
        throw error;
      }
    });
  });

  async function exportData(single) {
    const ownEpoch = epoch;
    const id = single ? selected?.id : null;
    if (single && !id) return;
    const control = byId(single ? 'history-export-one' : 'history-export');
    await action(control, async () => {
      status(single ? 'Preparando a exportação desta sessão…' : 'Preparando todos os seus registros para exportação…');
      const data = await api('/api/historico/exportacao', { query: id ? { sessao_id: id } : {} });
      if (ownEpoch !== epoch) return;
      downloadJSON(data, single ? 'rhythmmind-sessao.json' : 'rhythmmind-registros.json');
      status(single ? 'Exportação desta sessão preparada.' : 'Exportação de todos os seus registros preparada, independentemente dos filtros.', 'success');
    });
  }
  byId('history-export').addEventListener('click', () => { void exportData(false); });
  byId('history-export-one').addEventListener('click', () => { void exportData(true); });

  byId('history-delete-one').addEventListener('click', () => {
    if (!selected) return;
    const ownEpoch = epoch;
    const snapshot = selected;
    void action(byId('history-delete-one'), async () => {
      const accepted = await confirmAction({
        title: 'Excluir esta sessão?', label: 'Excluir sessão',
        message: 'A sessão, suas correções, interpretação, escolhas e retorno serão removidos do histórico. Os outros registros serão preservados. Arquivos já exportados continuam sob seu controle.',
      });
      if (!accepted || ownEpoch !== epoch) return;
      status('Excluindo esta sessão…');
      const response = await api('/api/historico/sessao', { method: 'DELETE', query: { sessao_id: snapshot.id } });
      if (ownEpoch !== epoch) return;
      delete records[snapshot.id];
      if (selected?.id === snapshot.id) clearDetail();
      renderList();
      onChanged?.({ deletedIds: response.registros_excluidos });
      await load();
      if (ownEpoch !== epoch) return;
      status('Sessão excluída do histórico.', 'success');
      notify('Sessão excluída.', 'success');
    });
  });

  byId('history-delete-all').addEventListener('click', () => {
    const ownEpoch = epoch;
    void action(byId('history-delete-all'), async () => {
      const summary = await api('/api/padroes');
      if (ownEpoch !== epoch) return;
      totalRecords = Number(summary.avaliacoes_sessoes?.sessoes_totais) || 0;
      if (!totalRecords) {
        status('Seu histórico já está vazio.');
        return;
      }
      const accepted = await confirmAction({
        title: 'Excluir todo o seu histórico?', label: 'Excluir todo o histórico',
        message: `Todos os seus registros serão removidos (${totalRecords} nesta consulta), incluindo sessões fora dos filtros, correções, interpretações, escolhas e retornos. Sua conta e catálogo serão preservados. Arquivos já exportados continuam sob seu controle.`,
      });
      if (!accepted || ownEpoch !== epoch) return;
      status('Excluindo todos os seus registros…');
      const response = await api('/api/historico', { method: 'DELETE', query: { confirmar: true } });
      if (ownEpoch !== epoch) return;
      records = {};
      totalRecords = 0;
      clearDetail();
      renderList();
      byId('patterns-summary').replaceChildren();
      onChanged?.({ deletedIds: response.registros_excluidos });
      await load();
      if (ownEpoch !== epoch) return;
      status('Todos os registros do seu histórico foram excluídos.', 'success');
      notify('Histórico excluído. Sua conta e catálogo foram preservados.', 'success');
    });
  });

  function reset() {
    epoch += 1;
    listVersion += 1;
    records = {};
    totalRecords = 0;
    clearDetail();
    byId('history-filter-form').reset();
    byId('history-list').replaceChildren();
    byId('patterns-summary').replaceChildren();
    byId('history-summary').textContent = '';
    byId('history-empty').hidden = true;
    byId('history-list').setAttribute('aria-busy', 'false');
    status('');
  }

  reset();
  return { load, reset };
}
