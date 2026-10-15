export const BACKEND_URL =
  (location.hostname === 'localhost' || location.hostname === '127.0.0.1' || location.protocol === 'file:')
    ? 'http://localhost:8000'
    : 'https://quantumcanvas-backend-f6hphzcrejgjbha8.centralus-01.azurewebsites.net';

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

function detailOf(status, text) {
  try {
    const d = JSON.parse(text).detail;
    if (typeof d === 'string') return d;
    if (Array.isArray(d) && d[0]?.msg) return d[0].msg;
  } catch (_) {}
  return status >= 500 ? `The server had a problem (error ${status}). Try again in a moment.` : `The server couldn't do this (error ${status}).`;
}

async function call(method, path, body) {
  let resp;
  try {
    resp = await fetch(`${BACKEND_URL}${path}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (_) {
    throw new ApiError("Couldn't reach the QuantumCanvas server. If it was asleep it can take about 30 seconds to wake up, so try again.", 0);
  }
  const text = await resp.text();
  if (!resp.ok) throw new ApiError(detailOf(resp.status, text), resp.status);
  return text ? JSON.parse(text) : null;
}

export const api = {
  get: path => call('GET', path),
  post: (path, body) => call('POST', path, body),
};

export const SESSION_ID = (() => {
  try { const k = sessionStorage.getItem('qc_session'); if (k) return k; } catch (_) {}
  const id = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : 's' + Math.random().toString(36).slice(2);
  try { sessionStorage.setItem('qc_session', id); } catch (_) {}
  return id;
})();
