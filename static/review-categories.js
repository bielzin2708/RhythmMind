import { el, categoriaLabel, CATEGORIAS } from './ui.js';

// Keep reviewed options available when collapsing, so a focused checkbox never
// disappears just because the person changed their mind about that category.
export function createCategorySelection(suggested = [], { disabled = false } = {}) {
  const initial = new Set(suggested.filter(value => CATEGORIAS.includes(value)));
  const checked = new Set(initial);
  let surfaced = new Set(initial);
  let expanded = false;
  return {
    get selected() { return CATEGORIAS.filter(value => checked.has(value)); },
    get expanded() { return expanded; },
    isVisible(value) { return expanded || surfaced.has(value); },
    setChecked(value, valueChecked) {
      if (disabled || !CATEGORIAS.includes(value)) return;
      if (valueChecked) { checked.add(value); surfaced.add(value); }
      else checked.delete(value);
    },
    toggleExpanded() { if (!disabled) expanded = !expanded; },
    clear() {
      if (disabled) return;
      checked.clear();
      surfaced = new Set(initial);
    },
  };
}

const controllers = new WeakMap();

export function renderCategories(target, { name, selected = [], disabled = false }) {
  const selection = createCategorySelection(selected, { disabled });
  target.disabled = disabled;
  const desired = name === 'desired';
  const helpId = `${target.id}-help`;
  const gridId = `${target.id}-options`;
  const legend = el('legend', {}, desired ? 'Como desejo me sentir' : 'Como estou agora');
  const help = el('p', { id: helpId, class: 'field-help category-help' }, disabled
    ? 'Categorias já confirmadas nesta sessão.'
    : desired ? 'Estado desejado · intenção. Escolha apenas se fizer sentido para você.'
      : 'Estado atual sugerido. Marque apenas o que você reconhece.');
  target.setAttribute('aria-describedby', helpId);
  const note = el('p', { class: 'category-selection-note' }, disabled
    ? 'Nenhuma categoria confirmada nesta dimensão.'
    : 'Nenhuma sugestão nesta dimensão. Você pode abrir as opções ou deixar sem categoria.');
  const grid = el('div', { class: 'tag-grid', id: gridId });
  const labels = new Map();
  const initiallySelected = new Set(selection.selected);
  const ordered = [...selection.selected, ...CATEGORIAS.filter(value => !initiallySelected.has(value))];
  const toggle = el('button', {
    class: 'button-link category-expand', type: 'button',
    'aria-controls': gridId, 'aria-expanded': 'false', disabled,
  });

  function update() {
    for (const [category, { label, input }] of labels) {
      label.hidden = !selection.isVisible(category);
      input.checked = selection.selected.includes(category);
    }
    note.hidden = initiallySelected.size > 0 || selection.selected.length > 0;
    toggle.setAttribute('aria-expanded', String(selection.expanded));
    toggle.textContent = selection.expanded
      ? 'Recolher opções' : `Ver todas as sensações (${CATEGORIAS.length})`;
    toggle.hidden = disabled;
  }

  for (const category of ordered) {
    const input = el('input', {
      type: 'checkbox', name, value: category, id: `${name}-${category}`,
      checked: initiallySelected.has(category),
    });
    const label = el('label', { class: 'tag-option', for: input.id },
      input, el('span', {}, categoriaLabel(category)));
    input.addEventListener('change', () => {
      selection.setChecked(category, input.checked);
      update();
    });
    labels.set(category, { label, input });
    grid.append(label);
  }
  toggle.addEventListener('click', () => { selection.toggleExpanded(); update(); });
  target.replaceChildren(legend, help, note, grid, toggle);
  controllers.set(target, { selection, update });
  update();
}

export function clearCategories(target) {
  const controller = controllers.get(target);
  if (!controller || target.disabled) return;
  controller.selection.clear();
  controller.update();
}
