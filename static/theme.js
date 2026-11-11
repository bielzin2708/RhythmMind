// Executado no head para aplicar a preferência antes da primeira pintura.
(() => {
  'use strict';

  const storageKey = 'rhythmmind.theme';
  const softEffectsKey = 'rhythmmind.softEffects';
  const choices = new Set(['dark', 'light', 'system']);
  const normalize = value => choices.has(value) ? value : 'dark';
  const storageAvailable = { theme: true, softEffects: true };
  let systemMedia = null;

  try {
    if (typeof window.matchMedia === 'function') {
      systemMedia = window.matchMedia('(prefers-color-scheme: dark)');
    }
  } catch { /* O modo escolhido continua disponível sem consulta ao sistema. */ }

  function readPreference() {
    try {
      const value = window.localStorage.getItem(storageKey);
      storageAvailable.theme = true;
      return normalize(value);
    } catch {
      storageAvailable.theme = false;
      return 'dark';
    }
  }

  function readSoftEffects() {
    try {
      const value = window.localStorage.getItem(softEffectsKey);
      storageAvailable.softEffects = true;
      return value === 'true';
    } catch {
      storageAvailable.softEffects = false;
      return false;
    }
  }

  let preference = readPreference();
  let softEffects = readSoftEffects();
  const resolvedTheme = () => preference === 'system'
    ? systemMedia ? systemMedia.matches ? 'dark' : 'light' : 'dark'
    : preference;

  function apply() {
    const theme = resolvedTheme();
    const root = document.documentElement;
    root.dataset.theme = theme;
    root.dataset.themePreference = preference;
    root.dataset.softEffects = String(softEffects);

    const colorScheme = document.querySelector('meta[name="color-scheme"]');
    const themeColor = document.querySelector('meta[name="theme-color"]');
    // O claro já foi desenhado pela aplicação; não deve sofrer a inversão do navegador.
    if (colorScheme) colorScheme.content = theme === 'light' ? 'only light' : 'dark';
    if (themeColor) themeColor.content = theme === 'dark' ? '#11100f' : '#f4f7fb';

    const action = theme === 'dark' ? 'Ativar modo claro' : 'Ativar modo escuro';
    document.querySelectorAll('button[data-theme-toggle]').forEach(button => {
      button.setAttribute('aria-label', action);
      button.title = action;
      button.removeAttribute('aria-pressed');
    });
    document.querySelectorAll('select[data-theme-preference]').forEach(select => {
      select.value = preference;
    });
    document.querySelectorAll('input[data-soft-effects-toggle]').forEach(checkbox => {
      checkbox.checked = softEffects;
    });

    const status = document.getElementById('theme-status');
    if (status) {
      const name = theme === 'dark' ? 'escuro' : 'claro';
      const message = preference === 'system'
        ? systemMedia ? `Seguindo o sistema: modo ${name}.`
          : 'Modo escuro em uso. A preferência de tema do sistema não está disponível neste navegador.'
        : `Modo ${name} selecionado.`;
      status.textContent = message + (storageAvailable.theme && storageAvailable.softEffects ? ''
        : ' Suas preferências valem nesta aba; não foi possível salvá-las neste navegador.');
    }
  }

  function setPreference(value) {
    if (!choices.has(value)) {
      apply();
      return;
    }
    preference = value;
    try {
      // Apenas o nome do tema é armazenado, sem dados da conta ou dos relatos.
      window.localStorage.setItem(storageKey, preference);
      storageAvailable.theme = true;
    } catch { storageAvailable.theme = false; }
    apply();
  }

  function setSoftEffects(value) {
    softEffects = value === true;
    try {
      window.localStorage.setItem(softEffectsKey, String(softEffects));
      storageAvailable.softEffects = true;
    } catch { storageAvailable.softEffects = false; }
    apply();
  }

  function bindControls() {
    document.querySelectorAll('button[data-theme-toggle]').forEach(button => {
      button.addEventListener('click', () => setPreference(resolvedTheme() === 'dark' ? 'light' : 'dark'));
    });
    document.querySelectorAll('select[data-theme-preference]').forEach(select => {
      select.addEventListener('change', () => setPreference(select.value));
    });
    document.querySelectorAll('input[data-soft-effects-toggle]').forEach(checkbox => {
      checkbox.addEventListener('change', () => setSoftEffects(checkbox.checked));
    });
    apply();
  }

  if (systemMedia) {
    const updateFromSystem = () => { if (preference === 'system') apply(); };
    if (typeof systemMedia.addEventListener === 'function') systemMedia.addEventListener('change', updateFromSystem);
    else if (typeof systemMedia.addListener === 'function') systemMedia.addListener(updateFromSystem);
  }

  window.addEventListener('storage', event => {
    if (event.key !== storageKey && event.key !== softEffectsKey && event.key !== null) return;
    // Ignora eventos de sessionStorage, quando a origem do evento estiver disponível.
    try {
      if (event.storageArea && event.storageArea !== window.localStorage) return;
    } catch { /* A preferência recebida ainda pode ser aplicada à aba atual. */ }
    if (event.key === null) {
      preference = readPreference();
      softEffects = readSoftEffects();
    } else if (event.key === storageKey) preference = normalize(event.newValue);
    else softEffects = event.newValue === 'true';
    apply();
  });

  apply();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindControls, { once: true });
  } else bindControls();
})();
