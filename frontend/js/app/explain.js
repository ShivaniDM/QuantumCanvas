import { api } from './api.js';
import { pseudocodeLine } from './describe.js';
import { esc } from './util.js';

export async function fetchExplanation({ recordId, document, counts, labels }) {
  const body = recordId ? { record_id: recordId, labels, use_llm: true } : { document, counts, labels, use_llm: true };
  return api.post('/explain', body);
}

function stepCard(s, aiText, aiPrinciple) {
  const p = s.principle;
  const text = aiText || s.text;
  return `<article class="explain-step ${s.claim_ok === false ? 'warn' : ''}" data-step="${esc(s.id)}">
    <h4><span class="label">Pseudocode</span><br>${esc(pseudocodeLine(s.title || s.id))}</h4>
    ${p ? `<p><b>Principle: ${esc(p.name)}.</b> ${esc(aiPrinciple || p.idea)}</p>` : ''}
    <p>${esc(text)}</p>
    ${s.math ? `<details><summary>Math</summary><pre>${esc(s.math)}</pre></details>` : ''}
    ${s.code ? `<details><summary>Code</summary><pre>${esc(s.code)}</pre></details>` : ''}
  </article>`;
}

export function renderExplanation(r) {
  const L = r.llm || {}, T = r.template || { steps: [], summary: '' };
  let h = '';
  if (L.status === 'ok' && L.text) {
    const by = Object.fromEntries((L.text.steps || []).map(s => [s.id, s.text]));
    const pr = Object.fromEntries((L.text.steps || []).filter(s => typeof s.principle === 'string').map(s => [s.id, s.principle]));
    h += `<div class="chips"><span class="pill ok">AI explanation · checked</span>${L.cache_hit ? '<span class="pill">cached</span>' : ''}</div>
      <p style="margin:0">${esc(L.text.summary || '')}</p>
      <div class="muted" style="font-size:12px">Every number and direction in this text was checked against the exact simulation.</div>
      ${T.steps.map(s => stepCard(s, by[s.id], pr[s.id])).join('')}
      <details><summary class="muted">Explanation without AI</summary><p>${esc(T.summary)}</p>${T.steps.map(s => stepCard(s)).join('')}</details>`;
  } else {
    h += `<div class="chips"><span class="pill">Explanation · from the simulation</span></div><p style="margin:0">${esc(T.summary)}</p>${T.steps.map(s => stepCard(s)).join('')}`;
    const why = {
      rejected: 'An AI explanation was written, but it said something the simulation contradicts, so it was not shown.',
      unavailable: 'The AI explanation is unavailable right now, so this one comes straight from the simulation.',
      budget: "Today's AI explanation allowance is used up, so this one comes straight from the simulation.",
    }[L.status];
    if (why) h += `<div class="note info">${esc(why)}</div>`;
  }
  if (r.save_error) h += `<div class="note bad">${esc(r.save_error)}</div>`;
  return h;
}
