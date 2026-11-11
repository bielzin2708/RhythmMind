import { el, categoriaLabel, CATEGORIAS } from './ui.js';

const SOURCE_HOSTS = new Set(['music.apple.com', 'open.spotify.com']);

export function safeCatalogSource(value) {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || !SOURCE_HOSTS.has(url.hostname)
      || url.username || url.password || (url.port && url.port !== '443')) return null;
    return url.href;
  } catch { return null; }
}

export function renderCatalogCard(song) {
  const card = el('article', { class: 'music-card' },
    el('h3', {}, song.nome || 'Faixa cadastrada'),
    el('p', { class: 'hint' }, `${song.artista || 'Artista não informado'} · ${song.duracao || 'Duração não informada'}`));
  const source = song.proveniencia;
  if (source && typeof source === 'object') {
    if (source.album) card.append(el('p', { class: 'field-help' }, `Álbum: ${source.album}`));
    const url = safeCatalogSource(source.url);
    const label = typeof source.fonte === 'string' && source.fonte.trim() ? source.fonte : 'Fonte do catálogo';
    card.append(url
      ? el('p', { class: 'field-help' }, 'Fonte: ', el('a', { href: url, target: '_blank', rel: 'noopener noreferrer' }, label))
      : el('p', { class: 'field-help' }, `Fonte: ${label}`));
  }
  if (song.curadoria?.status === 'provisoria') {
    const categories = Array.isArray(song.sentimentos_associados)
      ? song.sentimentos_associados.filter(value => CATEGORIAS.includes(value)).map(categoriaLabel) : [];
    card.append(el('p', { class: 'field-help' }, categories.length
      ? `Associações iniciais provisórias: ${categories.join(', ')}.`
      : 'Associações editoriais iniciais provisórias.'));
  }
  return card;
}

export function createCatalogReference({ api, button, status, count, list, container,
  onImported = async () => {}, onError = () => {}, onStart = () => {}, describeError = error => error?.message || 'Não foi possível concluir agora.' }) {
  let generation = 0;
  let request = 0;
  let importTask = null;
  let previewError = false;
  let importVersion = 0;
  const message = (text, type = 'info') => {
    status.textContent = text;
    status.dataset.type = type;
  };
  const busy = value => {
    button.disabled = value;
    if (value) container.setAttribute('aria-busy', 'true');
    else container.removeAttribute('aria-busy');
  };
  function reset() {
    generation += 1;
    request += 1;
    importTask = null;
    previewError = false;
    busy(false);
    count.textContent = 'Confira as faixas e adicione a seleção ao seu catálogo.';
    list.replaceChildren();
    message('');
  }
  async function load() {
    const version = generation;
    const currentRequest = ++request;
    const noticeVersion = importVersion;
    try {
      const result = await api('/api/catalogo-referencia');
      if (version !== generation || currentRequest !== request) return;
      const songs = Array.isArray(result.musicas) ? result.musicas : [];
      const total = Number.isSafeInteger(result.total) && result.total >= 0 ? result.total : songs.length;
      count.textContent = `${total} músicas reais nesta seleção. Você pode conferir a lista antes de adicionar.`;
      list.replaceChildren(...songs.map(renderCatalogCard));
      if (previewError && !importTask) {
        message('');
        previewError = false;
      }
    } catch (error) {
      if (version !== generation || currentRequest !== request || error?.name === 'StaleRequestError' || error?.name === 'AbortError') return;
      count.textContent = 'A prévia da seleção está indisponível agora. Seu catálogo pessoal continua disponível.';
      if (!importTask && noticeVersion === importVersion) {
        message('Você pode tentar adicionar a seleção novamente quando o serviço estiver disponível.', 'error');
        previewError = true;
      }
    }
  }
  function importAll() {
    if (importTask) return importTask;
    const version = generation;
    importVersion += 1;
    onStart();
    const isCurrent = () => version === generation;
    busy(true);
    previewError = false;
    message('Adicionando a seleção de músicas reais ao seu catálogo…', 'loading');
    const task = (async () => {
      try {
        const result = await api('/api/catalogo-referencia/importar', { method: 'POST', body: {} });
        if (!isCurrent()) return;
        await onImported(isCurrent);
        if (!isCurrent()) return;
        message(`${result.importadas} músicas adicionadas; ${result.ja_existentes} já estavam no seu catálogo. Suas faixas existentes foram preservadas.`, 'success');
      } catch (error) {
        if (!isCurrent() || error?.name === 'StaleRequestError' || error?.name === 'AbortError') return;
        message(describeError(error), 'error');
        onError(error);
      }
    })().finally(() => {
      if (!isCurrent() || importTask !== task) return;
      importTask = null;
      busy(false);
    });
    importTask = task;
    return task;
  }
  button.addEventListener('click', () => void importAll());
  return { load, importAll, reset };
}
