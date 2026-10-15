import { api } from './api.js';
import { circuit } from './circuit.js';
import { $, $$, esc, store, toast } from './util.js';

const DRAFT_KEY = 'qc.import.draft';
const SAMPLE = {
  qiskit: `from qiskit import QuantumCircuit
import numpy as np

qc = QuantumCircuit(2, 2)
qc.h([0, 1])
qc.x(1)
qc.cz(0, 1)
qc.x(1)
for q in range(2):
    qc.h(q)
qc.x([0, 1])
qc.cz(0, 1)
qc.x([0, 1])
qc.h([0, 1])
qc.measure([0, 1], [0, 1])
`,
  qasm3: `OPENQASM 3.0;
include "stdgates.inc";
qubit[2] q;
bit[2] c;
h q[0];
cx q[0], q[1];
c[0] = measure q[0];
c[1] = measure q[1];
`,
  qasm2: `OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
creg c[2];
h q[0];
cx q[0],q[1];
measure q[0] -> c[0];
measure q[1] -> c[1];
`,
};
const NAMES = { qiskit: 'Qiskit', qasm3: 'OpenQASM 3', qasm2: 'OpenQASM 2' };

const st = { format: 'qiskit', source: '', result: null, accepted: new Set(), busy: false };

function detect(src) {
  if (/OPENQASM\s+3/.test(src)) return 'qasm3';
  if (/OPENQASM\s+2/.test(src)) return 'qasm2';
  if (/QuantumCircuit/.test(src)) return 'qiskit';
  return null;
}

let cameFrom = null;

export function renderImport(main, query) {
  if (query.get('from')) cameFrom = query.get('from');
  const saved = store.get(DRAFT_KEY, null);
  if (query.get('from') === 'circuit' && circuit.compiled?.ok) {
    st.format = 'qiskit';
    const lines = circuit.compiled.qiskit_lines;
    const cut = lines.findIndex(l => l.startsWith('# ── Run on Aer simulator'));
    st.source = (cut > 0 ? lines.slice(0, cut) : lines).join('\n').trimEnd() + '\n';
    st.result = null;
  } else if (!st.source && saved) { st.format = saved.format; st.source = saved.source; }
  main.innerHTML = `<div class="page" style="max-width:1280px">
    <h1 style="margin:0 0 6px;font-size:26px">Bring code</h1>
    <p class="muted" style="margin:0 0 20px">Paste OpenQASM or Qiskit. The import keeps every gate exactly as written; concepts are only offered as suggestions.</p>
    <div class="importer">
      <div class="card" style="padding:14px;display:flex;flex-direction:column;gap:10px">
        <div class="chips"><div class="seg" role="group" aria-label="Format">${Object.entries(NAMES).map(([k, v]) => `<button type="button" data-fmt="${k}" aria-pressed="${st.format === k}">${v}</button>`).join('')}</div>
          <span style="flex:1"></span>
          <label class="btn small" style="cursor:pointer">Upload file<input type="file" accept=".qasm,.py,.txt" data-file hidden></label>
          <button type="button" class="btn small ghost" data-sample>Load example</button></div>
        <label class="sr-only" for="src">Code to import</label>
        <textarea id="src" spellcheck="false" placeholder="Paste ${NAMES[st.format]} here">${esc(st.source)}</textarea>
        <div class="muted" style="font-size:12px" data-help></div>
        <div class="chips"><button type="button" class="btn primary" data-go>Import</button><button type="button" class="btn ghost" data-cancel>Cancel</button><span class="muted" style="font-size:13px" data-status role="status"></span></div>
      </div>
      <div class="card" style="padding:16px;display:flex;flex-direction:column;gap:12px" data-report aria-live="polite"></div>
    </div></div>`;
  const ta = $('#src', main);
  const help = $('[data-help]', main);
  const setHelp = () => {
    help.textContent = st.format === 'qiskit'
      ? 'Supported Qiskit: qc = QuantumCircuit(n, m), calls like qc.h(0), qc.cx(0, 1), qc.rz(np.pi/4, 2), qc.measure(...), and for loops over range(...). Anything else is named with its line number. Your code is read, never run.'
      : 'OpenQASM gates from the standard library are supported. Anything else is named with its line number.';
  };
  setHelp();
  ta.addEventListener('input', () => {
    st.source = ta.value; store.set(DRAFT_KEY, { format: st.format, source: st.source });
    const d = detect(st.source);
    if (d && d !== st.format) { st.format = d; $$('[data-fmt]', main).forEach(b => b.setAttribute('aria-pressed', String(b.dataset.fmt === d))); setHelp(); }
  });
  $$('[data-fmt]', main).forEach(b => b.addEventListener('click', () => {
    st.format = b.dataset.fmt; $$('[data-fmt]', main).forEach(x => x.setAttribute('aria-pressed', String(x === b))); setHelp();
    ta.placeholder = `Paste ${NAMES[st.format]} here`;
  }));
  $('[data-sample]', main).addEventListener('click', () => { ta.value = st.source = SAMPLE[st.format]; ta.focus(); });
  $('[data-file]', main).addEventListener('change', async e => {
    const f = e.target.files[0]; e.target.value = '';
    if (!f) return;
    if (f.size > 200000) { toast('That file is larger than 200 KB.', { kind: 'bad' }); return; }
    ta.value = st.source = await f.text();
    const d = detect(st.source); if (d) { st.format = d; renderImport(main, new URLSearchParams()); }
  });
  $('[data-go]', main).addEventListener('click', () => doImport(main));
  $('[data-cancel]', main).addEventListener('click', () => {
    const saved = store.get(DRAFT_KEY, null);
    st.source = saved?.source || ''; st.format = saved?.format || 'qiskit'; st.result = null; st.accepted = new Set();
    location.hash = cameFrom === 'circuit' || circuit.s.nodes.length ? '#/build' : '#/';
  });
  renderReport(main);
}

async function doImport(main) {
  if (!st.source.trim()) { toast('Paste some code first.'); return; }
  const status = $('[data-status]', main);
  st.busy = true; status.textContent = 'Reading the code…';
  try {
    st.result = await api.post('/import', { format: st.format, source: st.source });
    st.accepted = new Set();
    status.textContent = '';
  } catch (e) {
    st.result = { ok: false, error: e.message, unsupported: [] };
    status.textContent = '';
  }
  st.busy = false;
  renderReport(main);
}

function renderReport(main) {
  const host = $('[data-report]', main);
  const r = st.result;
  if (!r) {
    host.innerHTML = `<div class="label">Import report</div><p class="muted" style="margin:0">After you import, this shows what was kept exactly, which concepts were recognised, and anything that couldn't be imported.</p>`;
    return;
  }
  if (!r.ok) {
    host.innerHTML = `<div class="label">Import report</div><div class="note bad">${esc(r.error)}</div>
      ${(r.unsupported || []).map(u => `<div class="check-row"><span class="pill bad">${u.line ? `line ${u.line}` : 'code'}</span><span>${esc(u.message)}</span></div>`).join('')}
      <p class="muted" style="margin:0;font-size:13px">Nothing was imported, so nothing was dropped silently. Change those lines and import again.</p>`;
    highlightLines(main, (r.unsupported || []).map(u => u.line).filter(Boolean));
    return;
  }
  const rep = r.report;
  const checks = rep.checks.map(c => `<div class="check-row"><span class="pill ${c.ok === true ? 'ok' : c.ok === false ? 'bad' : 'warn'}">${c.ok === true ? '✓' : c.ok === false ? '✗' : 'not checked'}</span><span>${esc(c.check)}<br><span class="muted">${esc(c.detail || '')}</span></span></div>`).join('');
  const sugg = r.suggestions.length ? r.suggestions.map(s => `<div class="sugg">
      <span class="what"><b>${esc(s.title)}</b><br><span class="muted" style="font-size:12px">${s.lines.length ? `line${s.lines.length > 1 ? 's' : ''} ${esc(formatLines(s.lines))} · ` : ''}${s.node_ids.length} gate${s.node_ids.length > 1 ? 's' : ''} · ${esc(s.check.detail)}</span></span>
      <label class="chips" style="font-size:14px"><input type="checkbox" data-accept="${s.id}" ${st.accepted.has(s.id) ? 'checked' : ''}> Group</label></div>`).join('')
    : '<p class="muted" style="margin:0;font-size:14px">No familiar patterns found. The circuit opens as gates.</p>';
  host.innerHTML = `<div class="label">Import report</div>
    <div class="note ok"><b>Imported exactly.</b> ${rep.qubits} qubit${rep.qubits > 1 ? 's' : ''} · ${rep.gates} gate${rep.gates === 1 ? '' : 's'} · ${rep.measurements} measurement${rep.measurements === 1 ? '' : 's'}. Order and parameters are kept as written${rep.loops.length ? `; loops over ${esc(rep.loops.join(', '))} were unrolled` : ''}.</div>
    ${checks}
    ${rep.notes.map(n => `<div class="note info">${esc(n)}</div>`).join('')}
    ${rep.line_numbers ? '' : '<div class="muted" style="font-size:12px">Line numbers aren\'t available for this file (some statements apply to several qubits at once).</div>'}
    <div class="label" style="margin-top:6px">Suggested concepts · optional</div>
    ${sugg}
    ${r.suggestions.length ? '<p class="muted" style="margin:0;font-size:12px">Each suggestion was checked to be the same operation as the gates it replaces. Your gates stay the source of truth, and any group can be undone from Build.</p>' : ''}
    <div class="chips" style="margin-top:6px"><button type="button" class="btn primary" data-open>Open in Build</button>
      <span class="muted" style="font-size:12px">This replaces the circuit in Build. You can undo it there.</span></div>`;
  $$('[data-accept]', host).forEach(cb => cb.addEventListener('change', () => { if (cb.checked) st.accepted.add(cb.dataset.accept); else st.accepted.delete(cb.dataset.accept); }));
  $('[data-open]', host).addEventListener('click', () => openInBuild());
  highlightLines(main, []);
}

function formatLines(ls) {
  if (ls.length > 1 && ls[ls.length - 1] - ls[0] === ls.length - 1) return `${ls[0]}–${ls[ls.length - 1]}`;
  return ls.join(', ');
}

function highlightLines(main, lines) {
  const ta = $('#src', main);
  if (!lines.length || !ta) return;
  const all = ta.value.split('\n');
  const ln = lines[0];
  const start = all.slice(0, ln - 1).join('\n').length + (ln > 1 ? 1 : 0);
  ta.focus();
  ta.setSelectionRange(start, start + (all[ln - 1] || '').length);
}

export function applySuggestions(document, suggestions, accepted) {
  const doc = JSON.parse(JSON.stringify(document));
  const chosen = suggestions.filter(s => accepted.has(s.id));
  for (const s of chosen) {
    const first = doc.operations.findIndex(n => n.id === s.node_ids[0]);
    if (first < 0) continue;
    const originals = doc.operations.filter(n => s.node_ids.includes(n.id));
    const lines = [...new Set(originals.flatMap(n => n.metadata?.lines || []))].sort((a, b) => a - b);
    const node = { id: `L${s.id}`, op: s.concept.op, targets: s.concept.targets, controls: [], ancillas: [], classical: [], params: s.concept.params,
                   condition: null, body: null, ref: null, repeat: 1,
                   metadata: { source: 'import', ...(lines.length ? { lines } : {}), lifted_from: originals, verified: { level: 'unitary', ok: true } } };
    doc.operations = [...doc.operations.slice(0, first), node, ...doc.operations.filter((n, i) => i >= first && !s.node_ids.includes(n.id))];
  }
  return doc;
}

function openInBuild() {
  const r = st.result;
  const doc = applySuggestions(r.document, r.suggestions, st.accepted);
  circuit.load(doc, 'Imported circuit', 'Import code');
  toast(`Imported ${r.report.gates} gates${st.accepted.size ? `, ${st.accepted.size} grouped as concepts` : ''}.`);
  location.hash = '#/build/code';
}
