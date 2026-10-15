import { esc, pct } from './util.js';

const MAX_ALL = 4;
const MAX_ROWS = 16;

export function normaliseCounts(counts, width) {
  const out = {};
  for (const [k, v] of Object.entries(counts || {})) {
    const n = Number(v);
    if (!Number.isFinite(n) || k === 'circuit_hash') continue;
    const key = /^[01]+$/.test(k) ? k.replace(/\s/g, '') : parseInt(k, 10).toString(2);
    const bitsKey = key.padStart(width, '0');
    out[bitsKey] = (out[bitsKey] || 0) + n;
  }
  return out;
}

export function widthOf(counts, fallback) {
  const keys = Object.keys(counts || {}).filter(k => /^[01 ]+$/.test(k));
  return keys.length ? Math.max(...keys.map(k => k.replace(/\s/g, '').length)) : fallback;
}

export function legend(width) {
  if (width <= 1) return 'Each outcome is the value of c0.';
  const order = Array.from({ length: width }, (_, i) => `c${width - 1 - i}`).join(' ');
  return `Bits read right to left, as in Qiskit: an outcome lists ${order}, so the rightmost bit is c0.`;
}

export function renderProbabilities({ predicted, width }) {
  const probs = {};
  for (const [k, v] of Object.entries(predicted || {})) probs[k.padStart(width, '0')] = Number(v) || 0;
  let keys;
  let truncated = false;
  if (width <= MAX_ALL) keys = Array.from({ length: 2 ** width }, (_, i) => i.toString(2).padStart(width, '0'));
  else {
    keys = Object.keys(probs).filter(k => probs[k] > 0).sort((a, b) => probs[b] - probs[a]).slice(0, MAX_ROWS);
    truncated = Object.keys(probs).filter(k => probs[k] > 0).length > MAX_ROWS;
  }
  const rows = keys.map(k => {
    const p = probs[k] || 0;
    const label = k.split('').map((b, i) => `c${k.length - 1 - i}=${b}`).join(' ');
    return `<div class="rrow" role="listitem" aria-label="Outcome ${k}: probability ${pct(p)}">
      <span class="k">|${k}⟩<small>${esc(label)}</small></span>
      <span class="track">${p ? `<span class="fill calc" style="width:${(100 * p).toFixed(2)}%"></span>` : ''}</span>
      <span class="v">${pct(p)}</span></div>`;
  }).join('');
  return `<div class="results-chart" role="list">${rows}</div>
    <div class="muted" style="font-size:12px">${esc(legend(width))} The bars are exact probabilities calculated from the circuit, not measured shots.${truncated ? ` Showing the ${MAX_ROWS} most likely outcomes.` : ''}</div>`;
}

export function renderResults({ counts, predicted, width }) {
  const clean = normaliseCounts(counts, width);
  const total = Object.values(clean).reduce((a, b) => a + b, 0) || 1;
  let keys;
  let truncated = false;
  if (width <= MAX_ALL) keys = Array.from({ length: 2 ** width }, (_, i) => i.toString(2).padStart(width, '0'));
  else {
    keys = Object.keys(clean).sort((a, b) => clean[b] - clean[a]).slice(0, MAX_ROWS);
    truncated = Object.keys(clean).length > MAX_ROWS;
  }
  const rows = keys.map(k => {
    const c = clean[k] || 0, f = c / total;
    const p = predicted ? predicted[k] : null;
    const label = k.split('').map((b, i) => `c${k.length - 1 - i}=${b}`).join(' ');
    return `<div class="rrow" role="listitem" aria-label="Outcome ${k}: ${c} shots, ${pct(f)}${p != null ? `, predicted ${pct(p)}` : ''}">
      <span class="k">|${k}⟩<small>${esc(label)}</small></span>
      <span class="track">${c ? `<span class="fill" style="width:${(100 * f).toFixed(2)}%"></span>` : ''}${p != null ? `<span class="pred" style="left:calc(${(100 * p).toFixed(2)}% - 1px)" title="Predicted ${pct(p)}"></span>` : ''}</span>
      <span class="v">${c} · ${pct(f)}</span></div>`;
  }).join('');
  return `<div class="results-chart" role="list">${rows}</div>
    <div class="muted" style="font-size:12px">${esc(legend(width))}${predicted ? ' The thin orange mark is the predicted probability; the bar is the measured frequency.' : ''}${truncated ? ` Showing the ${MAX_ROWS} most frequent outcomes.` : ''}</div>`;
}
