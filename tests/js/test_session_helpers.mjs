import assert from 'node:assert/strict';
import test from 'node:test';
import { buildReviewQuestion, resolveQuickSelection, humanizeTrackReason } from '../../static/session.js';

test('buildReviewQuestion formula perguntas editáveis em português claro', () => {
  assert.equal(
    buildReviewQuestion(['cansado'], ['calmo']),
    'Você quis dizer que está cansado e busca ficar calmo?',
  );
  assert.equal(
    buildReviewQuestion(['cansado', 'ansioso'], []),
    'Você quis dizer que está cansado e ansioso?',
  );
  assert.equal(
    buildReviewQuestion([], ['foco']),
    'Você quis dizer que busca ficar foco?',
  );
  assert.match(
    buildReviewQuestion([], []),
    /Não identificamos uma sensação clara/,
  );
});

test('resolveQuickSelection traduz objetivos rápidos sem inventar categorias inválidas', () => {
  assert.deepEqual(resolveQuickSelection({ objective: 'calmo', states: [] }), {
    emocoes_atuais: [],
    estado_desejado: ['calmo'],
    finalidadeSugerida: 'Relaxar',
    mood: 'calm',
  });
  assert.deepEqual(resolveQuickSelection({ objective: 'disposto', states: ['cansado', 'cansado', 'invalida'] }), {
    emocoes_atuais: ['cansado'],
    estado_desejado: ['disposto'],
    finalidadeSugerida: 'Ganhar energia',
    mood: 'energy',
  });
  assert.deepEqual(resolveQuickSelection({ objective: 'espelhar', states: [] }), {
    emocoes_atuais: ['reflexivo'],
    estado_desejado: [],
    finalidadeSugerida: 'Refletir',
    mood: 'reflect',
  });
});

test('humanizeTrackReason explica a faixa com base verificável no catálogo', () => {
  const texto = humanizeTrackReason(
    { sentimentos_associados: ['calmo', 'reflexivo'] },
    { criterios: [{ tipo: 'estrategia', valor: 'descompressao', pontos: 3 }] },
    'descompressao',
  );
  assert.equal(texto, 'Marcada como Calmo, Reflexivo no seu catálogo · selecionada para descompressão.');

  const confirmada = humanizeTrackReason(
    { sentimentos_associados: ['cansado'] },
    { criterios: [{ tipo: 'emocao_confirmada', valor: 'cansado', pontos: 2 }] },
    'espelhamento',
  );
  assert.equal(confirmada, 'Marcada como Cansado no seu catálogo (confirmada por você).');
});
