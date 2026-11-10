// O rascunho permanece apenas no formulário e na memória desta página.
export function createNarrativeDraft(form, { confirm }) {
  const capture = (defaults = false) => JSON.stringify(Array.from(form.elements)
    .filter(field => ['INPUT', 'TEXTAREA', 'SELECT'].includes(field.tagName)
      && !['button', 'submit', 'reset', 'image', 'file'].includes(field.type))
    .map((field, index) => {
      let value;
      if (field.type === 'checkbox' || field.type === 'radio') {
        value = defaults ? field.defaultChecked : field.checked;
      } else if (field.tagName === 'SELECT') {
        const options = Array.from(field.options);
        const selected = options.filter(option => defaults ? option.defaultSelected : option.selected);
        value = field.multiple
          ? selected.map(option => option.value)
          : (selected[0] || (defaults ? options[0] : null))?.value || '';
      } else value = defaults ? field.defaultValue : field.value;
      return [field.name || field.id || String(index), field.type, value ?? ''];
    }));

  let baseline = capture(true);
  let pending = null;
  const hasChanges = () => capture() !== baseline;

  return {
    hasChanges,
    capture: () => capture(),
    // Passe o snapshot do início do envio para preservar edições feitas durante a espera.
    markSaved(snapshot = capture()) { baseline = snapshot; },
    // Se a versão salva for excluída, o conteúdo em elaboração volta a ser não enviado.
    reset({ toDefaults = false } = {}) { baseline = capture(toDefaults); },
    confirmDiscard({
      title = 'Começar outro relato?',
      message = 'Há alterações neste relato que ainda não foram enviadas. Você pode continuar escrevendo ou descartar esse texto para começar outro. Seus registros já salvos serão mantidos.',
      label = 'Descartar e começar outro',
      cancelLabel = 'Continuar escrevendo',
    } = {}) {
      if (pending) return pending;
      if (!hasChanges()) return Promise.resolve(true);
      pending = Promise.resolve().then(() => confirm({
        title, message, label, cancelLabel,
      })).then(Boolean).finally(() => { pending = null; });
      return pending;
    },
  };
}
