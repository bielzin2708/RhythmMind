import assert from 'node:assert/strict';
import test from 'node:test';
import { createCategorySelection } from '../../static/review-categories.js';
import { CATEGORIAS } from '../../static/ui.js';

test('começa somente pelas sugestões conhecidas, sem misturar outras categorias', () => {
  const current = createCategorySelection(['cansado', 'ansioso', 'cansado', 'inventada']);
  assert.deepEqual(current.selected, ['cansado', 'ansioso']);
  assert.equal(current.expanded, false);
  assert.equal(current.isVisible('cansado'), true);
  assert.equal(current.isVisible('triste'), false);
});

test('expandir oferece as 14 categorias e recolher preserva múltiplas escolhas manuais', () => {
  const current = createCategorySelection(['cansado']);
  current.toggleExpanded();
  assert.equal(current.expanded, true);
  assert.ok(CATEGORIAS.every(category => current.isVisible(category)));
  current.setChecked('ansioso', true);
  current.setChecked('reflexivo', true);
  current.toggleExpanded();
  assert.equal(current.expanded, false);
  assert.deepEqual(current.selected, ['reflexivo', 'cansado', 'ansioso']);
  for (const category of current.selected) assert.equal(current.isVisible(category), true);
  assert.equal(current.isVisible('triste'), false);
});

test('desmarcar uma opção acessível não a faz desaparecer enquanto a pessoa a revisa', () => {
  const current = createCategorySelection(['calmo']);
  current.toggleExpanded();
  current.setChecked('ansioso', true);
  current.toggleExpanded();
  current.setChecked('ansioso', false);
  assert.equal(current.isVisible('ansioso'), true);
  assert.deepEqual(current.selected, ['calmo']);
  current.setChecked('ansioso', true);
  assert.deepEqual(current.selected, ['calmo', 'ansioso']);
});

test('limpar remove escolhas, mantém sugestões acessíveis e permite recomeçar', () => {
  const desired = createCategorySelection(['calmo']);
  desired.toggleExpanded();
  desired.setChecked('foco', true);
  desired.toggleExpanded();
  desired.clear();
  assert.deepEqual(desired.selected, []);
  assert.equal(desired.isVisible('calmo'), true);
  assert.equal(desired.isVisible('foco'), false);
  desired.setChecked('calmo', true);
  assert.deepEqual(desired.selected, ['calmo']);
});

test('nenhuma sugestão não obriga uma categoria e todas permanecem disponíveis', () => {
  const current = createCategorySelection();
  assert.deepEqual(current.selected, []);
  assert.ok(CATEGORIAS.every(category => !current.isVisible(category)));
  current.toggleExpanded();
  assert.ok(CATEGORIAS.every(category => current.isVisible(category)));
  current.setChecked('amor', true);
  current.toggleExpanded();
  assert.equal(current.isVisible('amor'), true);
  assert.deepEqual(current.selected, ['amor']);
});

test('atual e desejado têm seleções e expansões independentes', () => {
  const current = createCategorySelection(['ansioso']);
  const desired = createCategorySelection(['calmo']);
  current.toggleExpanded();
  current.setChecked('cansado', true);
  assert.equal(desired.expanded, false);
  assert.deepEqual(desired.selected, ['calmo']);
  desired.clear();
  assert.deepEqual(current.selected, ['cansado', 'ansioso']);
});

test('retomada de categorias já confirmadas conserva decisões e bloqueia alterações', () => {
  const saved = createCategorySelection(['calmo', 'foco'], { disabled: true });
  saved.setChecked('calmo', false);
  saved.setChecked('triste', true);
  saved.toggleExpanded();
  saved.clear();
  assert.deepEqual(saved.selected, ['foco', 'calmo']);
  assert.equal(saved.expanded, false);
  assert.equal(saved.isVisible('foco'), true);
  assert.equal(saved.isVisible('triste'), false);
});
