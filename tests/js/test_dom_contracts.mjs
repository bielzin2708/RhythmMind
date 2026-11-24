import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';

const html = readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
const htmlIds = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]));

test('todos os seletores #id estáticos usados em app.js, session.js, home.js e history.js existem em index.html', () => {
  const files = ['app.js', 'session.js', 'home.js', 'history.js'];
  const missing = [];
  for (const file of files) {
    const source = readFileSync(new URL(`../../static/${file}`, import.meta.url), 'utf8');
    for (const match of source.matchAll(/(?:\$|byId)\(\s*['"]#?([a-zA-Z0-9_-]+)['"]\s*\)/g)) {
      const id = match[1];
      if (!htmlIds.has(id)) missing.push(`${file}: #${id}`);
    }
  }
  assert.deepEqual(missing, []);
});

test('novo fluxo na página expõe objetivos, pergunta editável, escolha de diário e estados vazios distintos', () => {
  for (const requiredId of [
    'home-quick-relax', 'home-quick-focus', 'home-quick-energy', 'home-starter-catalog',
    'session-visualizer', 'session-persistence-badge', 'objective-cards', 'state-chips',
    'entry-import-reference', 'entry-submit-button', 'save-draft-button',
    'review-question', 'review-quick-confirm', 'review-toggle-editor', 'review-editor-panel',
    'empty-import-reference', 'empty-change-objective',
    'suggestion-fit-choices', 'diary-save-card', 'save-include-note',
    'save-to-diary-button', 'finish-without-saving', 'diary-saved-banner',
  ]) {
    assert.ok(htmlIds.has(requiredId), `ID ausente em index.html: #${requiredId}`);
  }
  // Relato livre não é mais obrigatório no HTML inicial.
  const narrativeTag = html.match(/<textarea[^>]*\bid="narrative-text"[^>]*>/);
  assert.ok(narrativeTag, 'textarea #narrative-text deve existir');
  assert.ok(!/\brequired\b/.test(narrativeTag[0]), '#narrative-text deve ser opcional');
});
