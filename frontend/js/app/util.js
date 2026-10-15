export const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function toast(message, { kind = 'info', action = null, ms = 4200 } = {}) {
  const host = document.getElementById('toasts');
  const el = document.createElement('div');
  el.className = `toast ${kind === 'bad' ? 'bad' : ''}`;
  el.textContent = message;
  if (action) {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = action.label;
    b.addEventListener('click', () => { action.run(); el.remove(); });
    el.appendChild(b);
  }
  host.appendChild(el);
  setTimeout(() => el.remove(), ms);
}

export function openDialog({ title, body, footer, onClose, labelledBy = 'dlg-title', wide = false }) {
  const host = document.getElementById('dialogs');
  const back = document.createElement('div');
  back.className = 'backdrop';
  back.innerHTML = `<div class="dialog" role="dialog" aria-modal="true" aria-labelledby="${labelledBy}" ${wide ? 'style="max-width:880px"' : ''}>
    <header><h2 id="${labelledBy}">${esc(title)}</h2><span style="flex:1"></span>
    <button class="icon-btn" type="button" data-close aria-label="Close">✕</button></header>
    <div class="body"></div><footer></footer></div>`;
  const dlg = back.querySelector('.dialog');
  const bodyEl = back.querySelector('.body');
  const footEl = back.querySelector('footer');
  if (typeof body === 'string') bodyEl.innerHTML = body; else if (body) bodyEl.appendChild(body);
  if (typeof footer === 'string') footEl.innerHTML = footer; else if (footer) footEl.appendChild(footer); else footEl.remove();
  const prev = document.activeElement;
  const close = () => {
    back.remove();
    document.removeEventListener('keydown', onKey, true);
    if (onClose) onClose();
    if (prev && prev.focus) prev.focus();
  };
  const onKey = e => {
    if (e.key === 'Escape') { e.preventDefault(); close(); return; }
    if (e.key !== 'Tab') return;
    const f = [...dlg.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')].filter(x => !x.disabled && x.offsetParent !== null);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  };
  back.addEventListener('mousedown', e => { if (e.target === back) close(); });
  back.querySelector('[data-close]').addEventListener('click', close);
  document.addEventListener('keydown', onKey, true);
  host.appendChild(back);
  const focusable = dlg.querySelector('[autofocus]') || dlg.querySelector('.body button, .body input, .body select, footer button.primary') || dlg.querySelector('[data-close]');
  focusable.focus();
  return { el: dlg, body: bodyEl, footer: footEl, close };
}

export const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch (_) { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch (_) { return false; }
  },
  remove(key) { try { localStorage.removeItem(key); } catch (_) {} },
};

export function ket(bits) { return `|${bits}⟩`; }

export function bitLabel(bits) {
  const n = bits.length;
  return bits.split('').map((b, i) => `q${n - 1 - i}=${b}`).join(' ');
}

export function pct(x, digits = 1) { return `${(100 * x).toFixed(digits)}%`; }

export function debounce(fn, ms) {
  let t = null;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

export function uid(prefix = '') {
  const r = (window.crypto && crypto.randomUUID) ? crypto.randomUUID().replace(/-/g, '').slice(0, 10) : Math.random().toString(36).slice(2, 12);
  return prefix + r;
}

export function fmtAngle(a) {
  if (!a) return '';
  if (a.pi) {
    const [n, d] = a.pi;
    if (n === 0) return '0';
    const s = (Math.abs(n) === 1 ? '' : Math.abs(n)) + 'π' + (d === 1 ? '' : '/' + d);
    return n < 0 ? '−' + s : s;
  }
  return `${Number(a.rad).toFixed(3)} rad`;
}

export function download(name, text, type = 'text/plain') {
  const blob = new Blob([text], { type });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 0);
}
