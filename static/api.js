// Credencial apenas em memória. Nenhum relato ou token é persistido no navegador.
let token = null;
let epoch = 0;
let unauthorized = () => {};
const pending = new Set();

export class ApiError extends Error {
  constructor(status, detail) {
    super(errorMessage(status, detail));
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

export class StaleRequestError extends Error {
  constructor() { super('Solicitação de um acesso anterior encerrada.'); this.name = 'StaleRequestError'; }
}

function errorMessage(status, detail) {
  if (status === 401) return token ? 'Seu acesso terminou. Entre novamente para continuar.' : 'Confira o nome de usuário e a senha para entrar.';
  if (status === 403) return 'Este ambiente está disponível apenas no acesso local autorizado.';
  if (status === 409) return 'Este registro mudou desde sua última leitura. Abra a versão atual antes de continuar.';
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return 'Confira os campos informados e seus limites antes de tentar novamente.';
  if (detail && typeof detail.mensagem === 'string') return detail.mensagem;
  return status >= 500 ? 'O serviço está indisponível neste momento. O último registro salvo foi preservado.' : 'Não foi possível concluir. Confira os campos e tente novamente.';
}

export function setToken(value) {
  epoch += 1;
  token = value || null;
  for (const controller of pending) controller.abort();
  pending.clear();
}

export function onUnauthorized(callback) { unauthorized = callback; }

export async function api(path, { method = 'GET', body, query } = {}) {
  if (!path.startsWith('/api/') || path.startsWith('//') || path.includes('?') || path.includes('#')) {
    throw new Error('Endereço da API inválido.');
  }
  const url = new URL(path, window.location.origin);
  if (query) for (const [name, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== '') url.searchParams.set(name, String(value));
  }
  const requestEpoch = epoch;
  const controller = new AbortController();
  pending.add(controller);
  const headers = { Accept: 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  try {
    const response = await fetch(url, {
      method, headers, body: body === undefined ? undefined : JSON.stringify(body),
      // Somente a conclusão OAuth troca o cookie HttpOnly por uma credencial local.
      signal: controller.signal, credentials: path === '/api/auth/google/concluir' ? 'same-origin' : 'omit',
      cache: 'no-store', redirect: 'error',
    });
    if (requestEpoch !== epoch) throw new StaleRequestError();
    if (response.status === 204) return null;
    const data = await response.json().catch(() => null);
    if (requestEpoch !== epoch) throw new StaleRequestError();
    if (!response.ok) {
      const error = new ApiError(response.status, data?.detail);
      if (response.status === 401 && token) unauthorized();
      throw error;
    }
    if (data === null) throw new ApiError(502, 'O serviço devolveu uma resposta inesperada. Tente novamente.');
    return data;
  } catch (error) {
    if (requestEpoch !== epoch || error.name === 'AbortError' || error.name === 'StaleRequestError') throw new StaleRequestError();
    if (error instanceof ApiError) throw error;
    throw new ApiError(0, 'Não foi possível conectar. Confira se o servidor está em execução e tente novamente.');
  } finally {
    pending.delete(controller);
  }
}
