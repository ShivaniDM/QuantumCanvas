import { api } from './api.js';
import { circuit } from './circuit.js';
import { fetchExplanation, renderExplanation } from './explain.js';
import { renderResults, widthOf } from './results.js';
import { backends } from './run.js';
import { clearRuns, deleteRun, getRun, listRuns } from './runs-store.js';
import { $, $$, download, esc, toast } from './util.js';

const top = counts => {
  const e = Object.entries(counts || {}).sort((a, b) => b[1] - a[1])[0];
  const total = Object.values(counts || {}).reduce((a, b) => a + b, 0) || 1;
  return e ? `|${e[0]}⟩ ${(100 * e[1] / total).toFixed(1)}%` : '—';
};
const shareUrl = recordId => `${location.origin}${location.pathname}#/shared/${recordId}`;

export function renderRuns(main) {
  const runs = listRuns();
  main.innerHTML = `<div class="page">
    <div class="chips" style="margin-bottom:16px"><h1 style="margin:0;font-size:26px">My runs</h1><span style="flex:1"></span>
      <label class="sr-only" for="run-q">Search runs</label><input id="run-q" type="text" placeholder="Search by circuit or backend" style="width:240px">
      ${runs.length ? '<button type="button" class="btn small ghost" data-clear>Clear all</button>' : ''}</div>
    <p class="muted" style="margin:0 0 16px;font-size:14px">Runs are kept in this browser. Runs on the server also get a share link that anyone can open.</p>
    <div class="card" style="overflow-x:auto">${runs.length ? `<table class="runs-table"><thead><tr><th scope="col">Circuit</th><th scope="col">Backend</th><th scope="col">Shots</th><th scope="col">Most frequent</th><th scope="col">Check</th><th scope="col">When</th><th scope="col"><span class="sr-only">Actions</span></th></tr></thead>
      <tbody>${runs.map(r => {
        const rc = r.math?.result_check;
        const check = rc ? (rc.ok === false ? '<span class="pill bad">differs</span>' : rc.ok === null ? '<span class="pill warn">within noise</span>' : '<span class="pill ok">matches</span>') : '<span class="muted">—</span>';
        return `<tr data-row="${esc(r.id)}" data-text="${esc((r.title + ' ' + (r.backend_label || r.backend)).toLowerCase())}">
          <td><b>${esc(r.title)}</b><br><span class="muted" style="font-size:12px">${r.document?.qubits ?? '?'} qubits</span></td>
          <td>${esc(r.backend_label || r.backend)}</td><td class="mono">${r.shots.toLocaleString()}</td><td class="mono">${esc(top(r.counts))}</td><td>${check}</td>
          <td>${new Date(r.at).toLocaleString()}</td>
          <td><div class="acts"><a class="btn small" href="#/runs/${esc(r.id)}">View</a><button type="button" class="btn small" data-open="${esc(r.id)}">Open in Build</button>
            ${r.record_id ? `<button type="button" class="btn small" data-share="${esc(r.record_id)}">Copy link</button>` : ''}
            <button type="button" class="icon-btn" data-del="${esc(r.id)}" aria-label="Delete run ${esc(r.title)}">✕</button></div></td></tr>`;
      }).join('')}</tbody></table>` : '<div class="empty" style="min-height:200px"><h2>No runs yet</h2><p style="margin:0">Run a circuit in Build and it appears here.</p><a class="btn primary" href="#/build">Go to Build</a></div>'}</div></div>`;
  const q = $('#run-q', main);
  q.addEventListener('input', () => $$('[data-row]', main).forEach(tr => { tr.hidden = !tr.dataset.text.includes(q.value.toLowerCase()); }));
  $$('[data-open]', main).forEach(b => b.addEventListener('click', () => openRunInBuild(getRun(b.dataset.open))));
  $$('[data-share]', main).forEach(b => b.addEventListener('click', () => copyLink(b.dataset.share)));
  $$('[data-del]', main).forEach(b => b.addEventListener('click', () => { deleteRun(b.dataset.del); renderRuns(main); toast('Run deleted from this browser.'); }));
  const c = $('[data-clear]', main);
  if (c) c.addEventListener('click', () => { if (confirm('Delete every run stored in this browser?')) { clearRuns(); renderRuns(main); } });
}

async function copyLink(recordId) {
  try { await navigator.clipboard.writeText(shareUrl(recordId)); toast('Share link copied.'); }
  catch (_) { prompt('Copy this link:', shareUrl(recordId)); }
}

function openRunInBuild(run) {
  if (!run?.document) { toast('This run has no circuit saved with it.', { kind: 'bad' }); return; }
  circuit.load(run.document, run.title, 'Open run');
  circuit.setRun({ ...run, docKey: circuit.docKey() });
  location.hash = '#/build';
}

function detail(main, run, { shared }) {
  const w = widthOf(run.counts, run.document?.classical_bits || 1);
  main.innerHTML = `<div class="page" style="max-width:920px">
    <a href="#/runs" class="muted" style="font-size:14px">← My runs</a>
    <h1 style="margin:8px 0 4px;font-size:26px">${esc(run.title)}</h1>
    <div class="muted" style="margin-bottom:18px">${esc(run.backend_label || run.backend)} · ${Number(run.shots).toLocaleString()} shots${run.at ? ` · ${new Date(run.at).toLocaleString()}` : ''}${shared ? ' · shared run' : ''}</div>
    <div class="card" style="padding:18px;display:flex;flex-direction:column;gap:12px">
      <div class="label">Results</div>${renderResults({ counts: run.counts, predicted: null, width: w })}
      <div class="chips"><button type="button" class="btn primary" data-open>Open in Build</button><button type="button" class="btn" data-explain>Explain</button>
        ${run.record_id ? '<button type="button" class="btn" data-share>Copy share link</button>' : ''}<button type="button" class="btn ghost" data-dl>Download (.json)</button></div>
      <div data-ex></div>
      <details><summary class="muted">Run details for developers</summary><pre class="codebox">${esc(JSON.stringify({ record_id: run.record_id, backend: run.backend, shots: run.shots, math: run.math, flags: run.flags, compile_report: run.compile_report }, null, 2))}</pre></details>
    </div></div>`;
  $('[data-open]', main).addEventListener('click', () => openRunInBuild(run));
  const sh = $('[data-share]', main); if (sh) sh.addEventListener('click', () => copyLink(run.record_id));
  $('[data-dl]', main).addEventListener('click', () => download(`${(run.title || 'run').replace(/[^\w-]+/g, '_')}.json`, JSON.stringify(run, null, 2), 'application/json'));
  $('[data-explain]', main).addEventListener('click', async e => {
    const host = $('[data-ex]', main);
    e.target.disabled = true; host.innerHTML = '<div class="muted">Explaining…</div>';
    try {
      const labels = Array.from({ length: run.document?.qubits || 0 }, (_, i) => `q${i}`);
      host.innerHTML = renderExplanation(await fetchExplanation({ recordId: run.record_id, document: run.document, counts: run.counts, labels }));
    } catch (err) { host.innerHTML = `<div class="note bad">${esc(err.message)}</div>`; }
    e.target.disabled = false;
  });
}

export function renderRunDetail(main, id) {
  const run = getRun(id);
  if (!run) { main.innerHTML = `<div class="page"><h1>Run not found</h1><p>It may have been deleted from this browser.</p><a class="btn" href="#/runs">My runs</a></div>`; return; }
  detail(main, run, { shared: false });
}

export async function renderShared(main, recordId) {
  main.innerHTML = `<div class="page"><p class="muted">Loading the shared run…</p></div>`;
  try {
    const rec = await api.get(`/runs/${encodeURIComponent(recordId)}`);
    let doc = rec.input?.ir_migrated || rec.input?.ir_json;
    if (typeof doc === 'string') doc = JSON.parse(doc);
    let canvas = rec.input?.canvas_json;
    if (typeof canvas === 'string') { try { canvas = JSON.parse(canvas); } catch (_) { canvas = null; } }
    const counts = rec.results?.counts || {};
    const requested = rec.execution?.backend_requested;
    const listing = await backends().catch(() => null);
    const known = listing?.backends?.find(b => b.id === requested || b.id === rec.execution?.backend_executed || (requested === 'aer_simulator' && b.id === 'aer'));
    const run = { id: recordId, record_id: recordId, title: canvas?.concepts?.title || 'Shared run',
                  backend: rec.execution?.backend_requested || 'run', backend_label: known?.label || rec.execution?.backend_executed || requested || 'Simulator',
                  shots: rec.execution?.shots || Object.values(counts).reduce((a, b) => a + b, 0), counts,
                  document: doc?.operations ? doc : null, at: rec.identity?.created_at || null,
                  math: rec.results?.result_check ? { result_check: rec.results.result_check } : null };
    detail(main, run, { shared: true });
  } catch (e) {
    main.innerHTML = `<div class="page"><h1>Couldn't open this run</h1><div class="note bad">${esc(e.message)}</div><a class="btn" href="#/">Home</a></div>`;
  }
}
