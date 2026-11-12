import { el, CATEGORIAS } from './ui.js';
import { renderCategories } from './review-categories.js';

export function normalizeCatalogSearch(value) {
  return String(value ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR').trim();
}

// Both catalog views keep their full data in memory, but create only the page
// requested by the person. A closed reference preview creates no song cards.
export function createCatalogBrowser({ list, search, count, more, renderCard,
  pageSize = 25, emptyMessage = 'Nenhuma faixa cadastrada.', isVisible = () => true }) {
  let songs = [];
  let query = '';
  let limit = pageSize;
  let busy = false;
  let error = '';
  let matched = [];
  let visible = 0;
  function render() {
    const terms = query.split(/\s+/).filter(Boolean);
    matched = songs.filter(song => {
      const text = normalizeCatalogSearch([song.nome, song.artista, song.album, song.proveniencia?.album].filter(Boolean).join(' '));
      return terms.every(term => text.includes(term));
    });
    visible = !error && isVisible() ? Math.min(limit, matched.length) : 0;
    list.replaceChildren();
    if (error) list.append(el('p', { class: 'empty-copy', role: 'alert' }, error));
    else if (isVisible()) {
      if (!matched.length) list.append(el('p', { class: 'empty-copy' }, query
        ? 'Nenhuma faixa encontrada. Tente outro nome, artista ou álbum.' : emptyMessage));
      else list.append(...matched.slice(0, visible).map(renderCard));
    }
    count.textContent = `Mostrando ${visible} de ${matched.length} faixas${query ? ` (${songs.length} no catálogo)` : ''}.`;
    more.hidden = Boolean(error) || !isVisible() || visible >= matched.length;
    more.disabled = busy;
    for (const button of list.querySelectorAll('button, input[type="submit"]')) button.disabled = busy;
    if (busy) list.setAttribute('aria-busy', 'true');
    else list.removeAttribute('aria-busy');
  }
  search.addEventListener('input', () => {
    query = normalizeCatalogSearch(search.value);
    limit = pageSize;
    render();
  });
  more.addEventListener('click', () => {
    if (busy) return;
    limit += pageSize;
    render();
  });
  return {
    render,
    setSongs(value) { songs = Array.isArray(value) ? value : []; error = ''; limit = pageSize; render(); },
    setBusy(value) { busy = Boolean(value); render(); },
    setError(message) { error = message; songs = []; render(); },
    reset() {
      songs = []; query = ''; limit = pageSize; busy = false; error = ''; search.value = '';
      render();
      list.replaceChildren();
      count.textContent = '';
    },
    get state() { return { query, total: songs.length, matched: matched.length, visible, busy, error }; },
  };
}

export function createCatalogAssociations({ api, dialog, form, title, categories,
  status, save, cancel, onSaved = async () => {}, onError = () => {},
  describeError = error => error?.message || 'Não foi possível salvar. Tente novamente.' }) {
  let generation = 0;
  let displayVersion = 0;
  let currentSong = null;
  let previousFocus = null;
  let pending = null;
  function busy(value) {
    save.disabled = value;
    categories.disabled = value;
    for (const button of categories.querySelectorAll('button')) button.disabled = value;
    if (value) form.setAttribute('aria-busy', 'true');
    else form.removeAttribute('aria-busy');
  }
  function close({ restoreFocus = true } = {}) {
    displayVersion += 1;
    currentSong = null;
    if (dialog.open) dialog.close();
    if (restoreFocus) {
      const target = previousFocus?.isConnected ? previousFocus : document.querySelector('#catalog-list-heading');
      target?.focus({ preventScroll: true });
    }
    previousFocus = null;
  }
  function open(song, trigger) {
    displayVersion += 1;
    currentSong = song;
    previousFocus = trigger || document.activeElement;
    title.textContent = `${song.nome || 'Faixa cadastrada'} · ${song.artista || 'Artista não informado'}`;
    status.textContent = '';
    renderCategories(categories, { name: 'catalog-associations', selected: song.sentimentos_associados || [] });
    categories.querySelector('legend').textContent = 'Que sensações você associa à faixa?';
    categories.querySelector('.category-help').textContent = 'Escolha apenas as sensações que fazem sentido para você.';
    categories.querySelector('.category-selection-note').textContent = 'Você ainda não indicou sensações. Abra as opções para escolher ou salve sem categoria.';
    busy(Boolean(pending));
    if (!dialog.open) dialog.showModal();
    cancel.focus();
  }
  function submit() {
    if (pending) return pending.promise;
    if (!currentSong) return Promise.resolve();
    const version = generation;
    const view = displayVersion;
    const song = currentSong;
    const selected = [...categories.querySelectorAll('input:checked')].map(input => input.value).filter(value => CATEGORIAS.includes(value));
    const isCurrent = () => version === generation;
    busy(true);
    status.textContent = 'Salvando suas sensações…';
    status.dataset.type = 'loading';
    const task = {};
    task.promise = (async () => {
      try {
        const result = await api(`/api/musicas/${encodeURIComponent(song.id)}/associacoes`, {
          method: 'PATCH', body: { sentimentos_associados: selected },
        });
        if (!isCurrent()) return;
        await onSaved(result.musica, isCurrent);
        if (isCurrent() && view === displayVersion) close();
      } catch (error) {
        if (!isCurrent() || error?.name === 'StaleRequestError' || error?.name === 'AbortError') return;
        if (view === displayVersion) {
          status.textContent = describeError(error);
          status.dataset.type = 'error';
        }
        onError(error);
      }
    })().finally(() => {
      if (!isCurrent() || pending !== task) return;
      pending = null;
      busy(false);
    });
    pending = task;
    return task.promise;
  }
  form.addEventListener('submit', event => { event.preventDefault(); void submit(); });
  cancel.addEventListener('click', () => close());
  dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
  return { open, submit, close, reset() {
    generation += 1;
    pending = null;
    close({ restoreFocus: false });
    busy(false);
    status.textContent = '';
    title.textContent = '';
    categories.replaceChildren();
  } };
}
