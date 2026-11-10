// A lista vazia não registra como o catálogo estava quando a sessão foi gerada.
export function recommendationState(record) {
  if (record.recomendacoes?.length) return 'suggestions';
  // Ausência explícita de estratégia é diferente de um campo legado ausente.
  return record.estrategia === null ? 'no-criteria' : 'no-matches';
}

export function currentCatalogState(response) {
  if (!Array.isArray(response?.musicas)) throw new TypeError('Não foi possível conferir as faixas do catálogo.');
  return response.musicas.length ? 'ready' : 'empty';
}
