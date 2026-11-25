// Camada visual reativa em Canvas 2D: ondas harmônicas suaves que respondem
// ao cursor, ao ritmo de digitação e ao objetivo escolhido, sem estilos inline (CSP 'self').
(() => {
  'use strict';

  const PALETTES = {
    dark: {
      neutral: ['#38bdf8', '#4cc9c0', '#5ec2a6'],
      calm: ['#38bdf8', '#4cc9c0', '#67d5b5'],
      focus: ['#60a5fa', '#7c9cf8', '#4cc9c0'],
      energy: ['#4cc9c0', '#5ec2a6', '#84dcc6'],
      reflect: ['#7c9cf8', '#5bb8d4', '#6bc4b8'],
    },
    light: {
      neutral: ['#135d66', '#1e7874', '#2a8576'],
      calm: ['#0f6270', '#1b7a78', '#2d8a7b'],
      focus: ['#255c7a', '#1b6d7a', '#2c7a7b'],
      energy: ['#166963', '#1f7d6e', '#2e8b70'],
      reflect: ['#2b5f75', '#1d7278', '#357e77'],
    },
  };

  const SPEEDS = {
    neutral: 1.0,
    calm: 0.62,
    focus: 0.88,
    energy: 1.48,
    reflect: 0.74,
  };

  let reducedMotion = null;
  try {
    if (typeof window.matchMedia === 'function') {
      reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    }
  } catch { /* Mantém quadro estático caso indisponível. */ }

  let previewMood = '';
  let typingEnergy = 0;
  let pointerX = 0.5;
  let pointerEnergy = 0;
  let rafId = 0;
  let lastTime = 0;
  let phase = 0;

  function hexToRgb(hex) {
    const clean = hex.replace('#', '');
    const num = Number.parseInt(clean, 16);
    return [(num >> 16) & 255, (num >> 8) & 255, num & 255];
  }

  function lerpColor(a, b, t) {
    return [
      Math.round(a[0] + (b[0] - a[0]) * t),
      Math.round(a[1] + (b[1] - a[1]) * t),
      Math.round(a[2] + (b[2] - a[2]) * t),
    ];
  }

  let currentColors = PALETTES.dark.neutral.map(hexToRgb);

  function activeMood() {
    if (previewMood) return previewMood;
    const mood = document.body?.dataset?.sessionMood;
    return mood && SPEEDS[mood] ? mood : 'neutral';
  }

  function activeTheme() {
    return document.documentElement?.dataset?.theme === 'light' ? 'light' : 'dark';
  }

  function shouldAnimate() {
    if (document.visibilityState === 'hidden') return false;
    if (reducedMotion?.matches) return false;
    if (document.body?.classList?.contains('ambient-paused')) return false;
    return true;
  }

  function syncCanvasSize(canvas) {
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.max(1, Math.round(rect.width * dpr));
    const height = Math.max(1, Math.round(rect.height * dpr));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    return { width, height, dpr };
  }

  function drawWaveCanvas(canvas, colors, mood, soft) {
    const dims = syncCanvasSize(canvas);
    if (!dims) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const { width, height } = dims;
    ctx.clearRect(0, 0, width, height);

    const kind = canvas.dataset.waveCanvas || 'home';
    const centerY = height * 0.52;
    const baseAmp = height * (kind === 'session' ? 0.28 : kind === 'auth' ? 0.30 : 0.33);
    const boost = 1 + typingEnergy * 0.45 + pointerEnergy * 0.25;
    const alphaScale = soft ? 0.55 : 1;

    const grad = ctx.createLinearGradient(0, 0, width, 0);
    const [c0, c1, c2] = colors;
    grad.addColorStop(0, `rgba(${c0[0]}, ${c0[1]}, ${c0[2]}, 0)`);
    grad.addColorStop(0.18, `rgba(${c0[0]}, ${c0[1]}, ${c0[2]}, ${0.78 * alphaScale})`);
    grad.addColorStop(0.52, `rgba(${c1[0]}, ${c1[1]}, ${c1[2]}, ${0.92 * alphaScale})`);
    grad.addColorStop(0.84, `rgba(${c2[0]}, ${c2[1]}, ${c2[2]}, ${0.78 * alphaScale})`);
    grad.addColorStop(1, `rgba(${c2[0]}, ${c2[1]}, ${c2[2]}, 0)`);

    const fillGrad = ctx.createLinearGradient(0, centerY - baseAmp, 0, centerY + baseAmp);
    fillGrad.addColorStop(0, `rgba(${c1[0]}, ${c1[1]}, ${c1[2]}, ${0.22 * alphaScale})`);
    fillGrad.addColorStop(0.5, `rgba(${c0[0]}, ${c0[1]}, ${c0[2]}, ${0.07 * alphaScale})`);
    fillGrad.addColorStop(1, `rgba(${c2[0]}, ${c2[1]}, ${c2[2]}, ${0.18 * alphaScale})`);

    const freq = mood === 'energy' ? 3.2 : mood === 'focus' ? 2.6 : 2.1;
    const layers = [
      { ratio: 1.0, phaseOffset: 0, lineWidth: 2.4, fill: true, opacity: 1 },
      { ratio: 0.68, phaseOffset: 1.35, lineWidth: 1.6, fill: false, opacity: 0.72 },
      { ratio: 0.42, phaseOffset: 2.7, lineWidth: 1.15, fill: false, opacity: 0.48 },
    ];

    const steps = Math.max(48, Math.min(110, Math.round(width / 8)));
    for (const layer of layers) {
      ctx.save();
      ctx.globalAlpha = layer.opacity;
      ctx.beginPath();
      for (let i = 0; i <= steps; i += 1) {
        const u = i / steps;
        const x = u * width;
        const envelope = Math.sin(u * Math.PI);
        const pointerBell = Math.exp(-((u - pointerX) ** 2) / 0.045) * pointerEnergy * 0.35;
        const wave1 = Math.sin(u * Math.PI * 2 * freq + phase + layer.phaseOffset);
        const wave2 = Math.sin(u * Math.PI * 2 * (freq * 1.65) - phase * 0.72 + layer.phaseOffset * 1.4) * 0.42;
        const y = centerY + (wave1 + wave2) * baseAmp * layer.ratio * (envelope + pointerBell) * boost;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      if (layer.fill) {
        for (let i = steps; i >= 0; i -= 1) {
          const u = i / steps;
          const x = u * width;
          const envelope = Math.sin(u * Math.PI);
          const wave1 = Math.cos(u * Math.PI * 2 * (freq * 0.85) - phase * 0.6);
          const y = centerY - wave1 * baseAmp * 0.38 * envelope * boost;
          ctx.lineTo(x, y);
        }
        ctx.closePath();
        ctx.fillStyle = fillGrad;
        ctx.fill();
        ctx.beginPath();
        for (let i = 0; i <= steps; i += 1) {
          const u = i / steps;
          const x = u * width;
          const envelope = Math.sin(u * Math.PI);
          const pointerBell = Math.exp(-((u - pointerX) ** 2) / 0.045) * pointerEnergy * 0.35;
          const wave1 = Math.sin(u * Math.PI * 2 * freq + phase + layer.phaseOffset);
          const wave2 = Math.sin(u * Math.PI * 2 * (freq * 1.65) - phase * 0.72 + layer.phaseOffset * 1.4) * 0.42;
          const y = centerY + (wave1 + wave2) * baseAmp * layer.ratio * (envelope + pointerBell) * boost;
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
      }
      ctx.strokeStyle = grad;
      ctx.lineWidth = layer.lineWidth * Math.min(window.devicePixelRatio || 1, 2);
      ctx.lineCap = 'round';
      ctx.stroke();
      ctx.restore();
    }
  }

  function renderFrame(now) {
    const dt = lastTime ? Math.min(0.05, (now - lastTime) / 1000) : 0.016;
    lastTime = now;
    const mood = activeMood();
    const theme = activeTheme();
    const targetPalette = (PALETTES[theme][mood] || PALETTES[theme].neutral).map(hexToRgb);
    const blend = Math.min(1, dt * 6);
    currentColors = currentColors.map((col, idx) => lerpColor(col, targetPalette[idx], blend));

    if (shouldAnimate()) {
      phase += dt * 1.85 * (SPEEDS[mood] || 1);
      typingEnergy = Math.max(0, typingEnergy - dt * 1.9);
      pointerEnergy = Math.max(0, pointerEnergy - dt * 1.4);
    } else {
      typingEnergy = 0;
      pointerEnergy = 0;
    }

    const soft = document.documentElement?.dataset?.softEffects === 'true';
    const canvases = document.querySelectorAll('canvas[data-wave-canvas]');
    canvases.forEach((canvas) => {
      if (canvas.closest('[hidden]')) return;
      drawWaveCanvas(canvas, currentColors, mood, soft);
    });

    if (shouldAnimate()) {
      rafId = window.requestAnimationFrame(renderFrame);
    } else {
      rafId = 0;
    }
  }

  function kickLoop() {
    if (rafId) return;
    lastTime = 0;
    if (shouldAnimate()) {
      rafId = window.requestAnimationFrame(renderFrame);
    } else {
      renderFrame(performance.now());
    }
  }

  function bindInteractions() {
    const moodFromButton = (el) => {
      if (!el) return '';
      if (el.dataset.mood) return el.dataset.mood;
      const obj = el.dataset.homeObjective || el.dataset.objective;
      return obj === 'calmo' ? 'calm' : obj === 'foco' ? 'focus' : obj === 'disposto' ? 'energy' : obj === 'espelhar' ? 'reflect' : '';
    };

    document.addEventListener('pointerover', (event) => {
      const btn = event.target?.closest?.('[data-objective], [data-home-objective]');
      const mood = moodFromButton(btn);
      if (mood && mood !== previewMood) {
        previewMood = mood;
        document.body.dataset.previewMood = mood;
        kickLoop();
      }
    });
    document.addEventListener('pointerout', (event) => {
      const btn = event.target?.closest?.('[data-objective], [data-home-objective]');
      if (btn && previewMood) {
        previewMood = '';
        delete document.body.dataset.previewMood;
        kickLoop();
      }
    });

    document.addEventListener('pointermove', (event) => {
      if (!shouldAnimate()) return;
      const width = window.innerWidth || 1;
      pointerX = Math.max(0.05, Math.min(0.95, event.clientX / width));
      pointerEnergy = Math.min(1, pointerEnergy + 0.18);
      kickLoop();
    }, { passive: true });

    const narrative = document.getElementById('narrative-text');
    narrative?.addEventListener('input', () => {
      if (!shouldAnimate()) return;
      typingEnergy = Math.min(1, typingEnergy + 0.35);
      kickLoop();
    });

    document.getElementById('ambient-toggle')?.addEventListener('change', () => {
      queueMicrotask(kickLoop);
    });
    window.addEventListener('resize', () => kickLoop(), { passive: true });
    document.addEventListener('visibilitychange', () => kickLoop());
    reducedMotion?.addEventListener?.('change', () => kickLoop());

    const observer = new MutationObserver(() => kickLoop());
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'data-soft-effects'] });
    if (document.body) {
      observer.observe(document.body, { attributes: true, attributeFilter: ['class', 'data-session-mood'] });
    }
    kickLoop();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindInteractions, { once: true });
  } else {
    bindInteractions();
  }
})();
