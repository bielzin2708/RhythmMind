import assert from 'node:assert/strict';
import test from 'node:test';
import { recommendationState, currentCatalogState } from '../../static/listening-state.js';

test('lista vazia com estratégia registrada não é confundida com falta de critério', () => {
  assert.equal(recommendationState({ estrategia: 'descompressao', recomendacoes: [] }), 'no-matches');
  assert.equal(recommendationState({ estrategia: null, recomendacoes: [] }), 'no-criteria');
});

test('categoria atual vazia não elimina um critério de intenção confirmado', () => {
  assert.equal(recommendationState({
    estrategia: 'foco_cognitivo', analise: { emocoes: [], estado_desejado: ['foco'] },
    recomendacoes: [{ nome: 'Faixa fictícia' }],
  }), 'suggestions');
});

test('registro legado sem estratégia não recebe uma causa inventada', () => {
  assert.equal(recommendationState({ recomendacoes: [] }), 'no-matches');
  assert.equal(recommendationState({ recomendacoes: [{ nome: 'Faixa legada' }] }), 'suggestions');
});

test('catálogo consultado agora não muda a causa registrada numa sessão anterior', () => {
  const record = { estrategia: 'descompressao', recomendacoes: [] };
  assert.equal(currentCatalogState({ musicas: [] }), 'empty');
  assert.equal(recommendationState(record), 'no-matches');
  assert.equal(currentCatalogState({ musicas: [{ nome: 'Nova faixa' }] }), 'ready');
  assert.equal(recommendationState(record), 'no-matches');
});

test('resposta inválida ou desconhecida não significa catálogo vazio', () => {
  for (const response of [null, {}, { total: 0 }, { musicas: null }]) {
    assert.throws(() => currentCatalogState(response), TypeError);
  }
});
