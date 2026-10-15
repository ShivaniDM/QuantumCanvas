import { api } from './api.js';
import { circuit, MAX_QUBITS } from './circuit.js';
import { pseudocodeLine } from './describe.js';
import { $, $$, debounce, esc, store, uid } from './util.js';

const PREF = 'qc.dock';
const TABS = [['qiskit', 'Qiskit'], ['qasm', 'OpenQASM 3'], ['pseudocode', 'Pseudocode'], ['math', 'Math']];
const IMPORT_FORMAT = { qiskit: 'qiskit', qasm: 'qasm3' };
const RUN_MARKER = '# ── Run on Aer simulator';
const LINE_PX = 21;
const MIN_H = 120;

const saved = store.get(PREF, {});
const st = {
  tab: TABS.some(t => t[0] === saved.tab) ? saved.tab : 'qiskit',
  height: Number(saved.height) || 260,
  collapsed: !!saved.collapsed,
  dirty: { qiskit: false, qasm: false },
  err: { qiskit: null, qasm: null },
  phase: { qiskit: 'idle', qasm: 'idle' },
  session: null, seq: 0, stale: false,
  qasm: null, qasmKey: null, qasmLoading: false,
  math: null, mathKey: null, mathLoading: false, mathError: null,
  ai: null, aiBusy: false, llm: null,
};
let host = null;
let hooks = { select: () => {}, selected: () => null };

const save = () => store.set(PREF, { tab: st.tab, height: st.height, collapsed: st.collapsed });
const editable = () => st.tab === 'qiskit' || st.tab === 'qasm';
const ta = () => host && $('[data-src]', host);

export function mountDock(el, h) {
  host = el;
  hooks = { ...hooks, ...h };
  render();
  if (st.llm === null) api.get('/health').then(r => { st.llm = (r.llm_configured || 0) > 0; paintStatus(); }).catch(() => { st.llm = false; });
}

export function openDock(tab) {
  st.collapsed = false;
  if (tab) st.tab = tab;
  save();
  render();
}

export function updateDock() {
  if (!host || !document.body.contains(host)) return;
  if (editable()) {
    const fmt = st.tab;
    if (st.dirty[fmt] && !st.applying && st.err[fmt]) st.stale = true;
    if (st.dirty[fmt] && !st.err[fmt] && document.activeElement !== ta()) st.dirty[fmt] = false;
    if (!st.dirty[fmt]) syncText();
    paint();
  } else renderBody();
  paintTabs();
}

function generated(fmt) {
  const r = circuit.compiled;
  if (!r || !r.ok) return null;
  if (fmt === 'qiskit') {
    const lines = r.qiskit_lines;
    const cut = lines.findIndex(l => l.startsWith(RUN_MARKER));
    const body = cut >= 0 ? lines.slice(0, cut) : lines.slice();
    while (body.length && !body[body.length - 1].trim()) body.pop();
    return body.join('\n') + '\n';
  }
  if (st.qasmKey !== circuit.docKey()) { loadQasm(); return null; }
  return st.qasm;
}

async function loadQasm() {
  if (st.qasmLoading) return;
  st.qasmLoading = true;
  const key = circuit.docKey();
  try {
    const r = await api.post('/compile', { document: circuit.toDocument(), qasm: true });
    if (r.ok && key === circuit.docKey()) { st.qasm = r.qasm3; st.qasmKey = key; }
  } catch (_) {}
  st.qasmLoading = false;
  if (st.tab === 'qasm' && key === circuit.docKey()) updateDock();
}

function syncText() {
  const t = ta();
  if (!t) return;
  const gen = generated(st.tab);
  const text = gen ?? (circuit.compiled && !circuit.compiled.ok ? '' : t.value);
  if (gen === null && circuit.compiled && !circuit.compiled.ok) {
    t.value = '';
    t.placeholder = 'Fix the problems in the steps list to see the code.';
    return;
  }
  if (t.value !== text) { t.value = text; t.placeholder = ''; }
}

function render() {
  if (!host) return;
  host.innerHTML = `<div class="dock ${st.collapsed ? 'collapsed' : ''}">
    <div class="dock-handle" role="separator" aria-orientation="horizontal" aria-label="Resize the code panel" tabindex="0" ${st.collapsed ? 'hidden' : ''}></div>
    <div class="dock-bar">
      <div class="tabs" role="tablist" aria-label="Code panel">${TABS.map(([k, l]) => `<button type="button" role="tab" id="dtab-${k}" aria-controls="dpanel" aria-selected="${st.tab === k}" tabindex="${st.tab === k ? 0 : -1}" data-dtab="${k}">${l}<span class="dot-mark" data-mark="${k}"></span></button>`).join('')}</div>
      <span style="flex:1"></span>
      <button type="button" class="btn ghost small" data-dock-toggle aria-expanded="${!st.collapsed}">${st.collapsed ? 'Show code' : 'Hide'}</button>
    </div>
    <div class="dock-body" id="dpanel" role="tabpanel" aria-labelledby="dtab-${st.tab}" data-dock-body style="height:${st.height}px" ${st.collapsed ? 'hidden' : ''}></div>
  </div>`;
  $$('[data-dtab]', host).forEach(b => {
    b.addEventListener('click', () => { st.tab = b.dataset.dtab; st.collapsed = false; st.ai = null; save(); render(); });
    b.addEventListener('keydown', e => {
      if (!['ArrowRight', 'ArrowLeft'].includes(e.key)) return;
      const i = TABS.findIndex(t => t[0] === st.tab);
      st.tab = TABS[(i + (e.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length][0];
      save(); render(); $(`[data-dtab="${st.tab}"]`, host).focus();
    });
  });
  $('[data-dock-toggle]', host).addEventListener('click', () => { st.collapsed = !st.collapsed; save(); render(); });
  bindResize();
  if (!st.collapsed) renderBody();
  paintTabs();
}

function paintTabs() {
  if (!host) return;
  for (const k of ['qiskit', 'qasm']) {
    const m = $(`[data-mark="${k}"]`, host);
    if (m) { m.textContent = st.dirty[k] && st.err[k] ? ' •' : ''; m.title = st.dirty[k] && st.err[k] ? 'Edited, not applied' : ''; }
  }
}

function bindResize() {
  const h = $('.dock-handle', host);
  if (!h) return;
  const clamp = v => {
    const stage = host.closest('.stage');
    const max = stage ? Math.max(MIN_H, stage.clientHeight - 160) : 600;
    return Math.round(Math.min(max, Math.max(MIN_H, v)));
  };
  const set = v => { st.height = clamp(v); const b = $('[data-dock-body]', host); if (b) b.style.height = `${st.height}px`; h.setAttribute('aria-valuenow', st.height); };
  h.addEventListener('pointerdown', e => {
    e.preventDefault();
    const y0 = e.clientY, h0 = st.height;
    h.setPointerCapture(e.pointerId);
    const move = ev => set(h0 + (y0 - ev.clientY));
    const up = () => { h.removeEventListener('pointermove', move); h.removeEventListener('pointerup', up); save(); };
    h.addEventListener('pointermove', move);
    h.addEventListener('pointerup', up);
  });
  h.addEventListener('keydown', e => {
    if (e.key === 'ArrowUp') { e.preventDefault(); set(st.height + 24); save(); }
    if (e.key === 'ArrowDown') { e.preventDefault(); set(st.height - 24); save(); }
  });
}

function renderBody() {
  const body = host && $('[data-dock-body]', host);
  if (!body || st.collapsed) return;
  if (editable()) {
    if (!$('[data-src]', body)) {
      const fmtName = st.tab === 'qiskit' ? 'Qiskit' : 'OpenQASM 3';
      body.innerHTML = `<div class="ed">
        <div class="ed-gutter" aria-hidden="true"><div data-gut></div></div>
        <div class="ed-main"><div class="ed-back" aria-hidden="true"><div data-back></div></div>
          <textarea data-src spellcheck="false" autocapitalize="off" autocomplete="off" wrap="off" aria-label="${fmtName} code. Edits update the canvas." aria-describedby="ed-help"></textarea></div>
      </div>
      <div class="ed-status" data-status role="status" aria-live="polite"></div>
      <span id="ed-help" class="sr-only">Tab inserts spaces. Press Escape to leave the editor. Ctrl+Enter applies now.</span>`;
      bindEditor();
    }
    if (!st.dirty[st.tab]) syncText();
    paint();
    return;
  }
  if (st.tab === 'pseudocode') renderPseudocode(body);
  else renderMath(body);
}

function segmentsOf(lines) {
  const segs = [];
  let cur = null;
  lines.forEach((l, i) => {
    if (/^#\s/.test(l) && !l.startsWith(RUN_MARKER)) { cur = { header: l.trimEnd(), start: i + 1, end: i + 1, body: [] }; segs.push(cur); }
    else if (cur) { cur.body.push(l.trimEnd()); if (l.trim()) cur.end = i + 1; }
  });
  segs.forEach(s => { while (s.body.length && !s.body[s.body.length - 1]) s.body.pop(); s.key = [s.header, ...s.body].join('\n'); });
  return segs;
}

function originalSegments() {
  const gen = generated('qiskit');
  if (gen === null) return null;
  const segs = segmentsOf(gen.split('\n'));
  if (segs.length !== circuit.s.nodes.length) return null;
  segs.forEach((s, k) => { s.node = circuit.s.nodes[k]; });
  return segs;
}

function nodeLines() {
  const segs = originalSegments();
  const map = {};
  (segs || []).forEach(s => { map[s.node.id] = [s.start, s.end]; });
  return map;
}

function bindEditor() {
  const t = ta();
  const apply = debounce(() => applyEdits(), 650);
  t.addEventListener('input', () => {
    const fmt = st.tab;
    if (!st.dirty[fmt]) st.session = uid('code');
    st.dirty[fmt] = true; st.phase[fmt] = 'checking'; st.ai = null;
    paint(); paintTabs();
    apply();
  });
  t.addEventListener('scroll', () => syncScroll());
  t.addEventListener('focus', () => { if (!st.session) st.session = uid('code'); });
  t.addEventListener('blur', () => {
    const fmt = st.tab;
    st.session = null;
    if (st.dirty[fmt] && !st.err[fmt] && st.phase[fmt] !== 'checking') { st.dirty[fmt] = false; st.phase[fmt] = 'idle'; syncText(); paint(); paintTabs(); }
  });
  t.addEventListener('keydown', e => {
    if (e.key === 'Tab' && !e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey) {
      e.preventDefault();
      const s = t.selectionStart, en = t.selectionEnd;
      t.setRangeText('    ', s, en, 'end');
      t.dispatchEvent(new Event('input'));
    } else if (e.key === 'Escape') { e.preventDefault(); t.blur(); $('[data-dtab].active, [data-dtab][aria-selected="true"]', host)?.focus(); }
    else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); applyEdits(); }
  });
  const pick = () => {
    if (st.tab !== 'qiskit' || st.dirty.qiskit) return;
    const line = t.value.slice(0, t.selectionStart).split('\n').length;
    const segs = originalSegments();
    const s = segs && segs.find(x => line >= x.start && line <= Math.max(x.end, x.start));
    if (s && s.node.id !== hooks.selected()) hooks.select(s.node.id);
  };
  t.addEventListener('click', pick);
  t.addEventListener('keyup', e => { if (/Arrow|Page|Home|End/.test(e.key)) pick(); });
}

function syncScroll() {
  const t = ta();
  if (!t) return;
  const back = $('[data-back]', host), gut = $('[data-gut]', host);
  if (back) back.style.transform = `translate(${-t.scrollLeft}px, ${-t.scrollTop}px)`;
  if (gut) gut.style.transform = `translateY(${-t.scrollTop}px)`;
}

function paint() {
  const t = ta();
  if (!t) return;
  const fmt = st.tab;
  const n = Math.max(1, t.value.split('\n').length);
  const err = st.err[fmt];
  const errLines = new Set(st.dirty[fmt] && err ? err.lines || [] : []);
  const hl = new Set();
  if (fmt === 'qiskit' && !st.dirty.qiskit && hooks.selected()) {
    const r = nodeLines()[hooks.selected()];
    if (r) for (let i = r[0]; i <= r[1]; i++) hl.add(i);
  }
  let g = '', bk = '';
  for (let i = 1; i <= n; i++) {
    const cls = errLines.has(i) ? 'err' : hl.has(i) ? 'hl' : '';
    g += `<div class="${cls}">${i}</div>`;
    bk += `<div class="${cls}"></div>`;
  }
  $('[data-gut]', host).innerHTML = g;
  $('[data-back]', host).innerHTML = bk;
  syncScroll();
  paintStatus();
  if (hl.size && document.activeElement !== t) {
    const first = Math.min(...hl);
    const top = (first - 1) * LINE_PX;
    if (top < t.scrollTop || top > t.scrollTop + t.clientHeight - LINE_PX * 2) { t.scrollTop = Math.max(0, top - LINE_PX * 2); syncScroll(); }
  }
}

function paintStatus() {
  const box = host && $('[data-status]', host);
  if (!box || !editable()) return;
  const fmt = st.tab;
  const err = st.err[fmt];
  let h = '';
  if (!st.dirty[fmt]) {
    h = `<span class="muted">${fmt === 'qiskit'
      ? 'Edit the code and the canvas follows. Concept blocks stay as they are for code you don\'t change; changed code becomes individual gates.'
      : 'Edit the code and the canvas follows. Edits here rebuild the circuit as individual gates.'} The run block for the simulator is added when you export.</span>`;
  } else if (st.phase[fmt] === 'checking') {
    h = '<span class="muted">Checking…</span>';
  } else if (err) {
    h = `<div class="ed-error"><b>Not applied.</b> ${esc(err.message)}${(err.items || []).length > 1 ? `<ul>${err.items.map(u => `<li>${u.line ? `Line ${u.line}: ` : ''}${esc(u.message || u.construct || '')}</li>`).join('')}</ul>` : ''}</div>
      <div class="chips">
        ${st.llm ? `<button type="button" class="btn small" data-ai ${st.aiBusy ? 'disabled' : ''}>${st.aiBusy ? 'Asking…' : 'Explain with AI'}</button>` : '<span class="muted" style="font-size:12px">AI help is not set up on this server.</span>'}
        <button type="button" class="btn ghost small" data-discard>Discard edits</button>
        ${st.stale ? '<span class="muted" style="font-size:12px">The canvas changed while this was not applied.</span>' : ''}
      </div>${renderAi()}`;
  } else {
    h = `<span class="ok">✓ Applied to the canvas.</span> <button type="button" class="btn ghost small" data-discard>Show generated code</button>`;
  }
  box.innerHTML = h;
  const d = $('[data-discard]', box);
  if (d) d.addEventListener('click', discard);
  const a = $('[data-ai]', box);
  if (a) a.addEventListener('click', askAi);
  const use = $('[data-ai-use]', box);
  if (use) use.addEventListener('click', () => {
    const t = ta();
    t.value = st.ai.fixed_source;
    st.ai = null;
    t.focus();
    t.dispatchEvent(new Event('input'));
  });
}

function renderAi() {
  const a = st.ai;
  if (!a) return '';
  if (a.status !== 'ok') return `<div class="note warn">${esc(a.message || 'AI help is unavailable right now.')}</div>`;
  const chk = a.fix_check;
  return `<div class="ai-help"><div class="label">AI explanation · not verified</div><p>${esc(a.explanation || '')}</p>
    ${a.fixed_source ? `<div class="label">Suggested code</div><pre class="ai-fix">${esc(a.fixed_source)}</pre>
      <div class="note ${chk?.ok ? 'ok' : 'bad'}">${chk?.ok ? 'Checked: this code imports and compiles.' : `Checked: this code still fails. ${esc(chk?.message || '')}`}</div>
      ${chk?.ok ? '<button type="button" class="btn small primary" data-ai-use>Use this code</button>' : ''}` : ''}</div>`;
}

async function askAi() {
  const fmt = st.tab;
  st.aiBusy = true; paintStatus();
  try {
    st.ai = await api.post('/code-help', { format: IMPORT_FORMAT[fmt], source: ta().value, error: st.err[fmt]?.message || '' });
  } catch (e) {
    st.ai = { status: 'error', message: e.message };
  }
  st.aiBusy = false;
  paintStatus();
}

function discard() {
  const fmt = st.tab;
  st.dirty[fmt] = false; st.err[fmt] = null; st.phase[fmt] = 'idle'; st.session = null; st.stale = false; st.ai = null; st.seq++;
  syncText(); paint(); paintTabs();
}

function blankUnchanged(text) {
  const lines = text.split('\n');
  const orig = originalSegments();
  if (!orig) return { source: text, keep: [] };
  const pool = new Map();
  orig.forEach(o => { if (!pool.has(o.key)) pool.set(o.key, []); pool.get(o.key).push(o.node); });
  const out = lines.slice();
  const keep = [];
  const used = new Set();
  for (const s of segmentsOf(lines)) {
    const q = pool.get(s.key);
    if (q && q.length) {
      const node = q.shift();
      used.add(node.id);
      keep.push({ start: s.start, end: s.end, node });
      for (let i = s.start; i < s.end; i++) out[i] = '';
      continue;
    }
    const prefix = orig.find(o => !used.has(o.node.id) && o.header === s.header && o.body.length < s.body.length
      && o.body.every((l, k) => l === s.body[k]));
    if (!prefix) continue;
    used.add(prefix.node.id);
    (pool.get(prefix.key) || []).splice((pool.get(prefix.key) || []).indexOf(prefix.node), 1);
    const end = s.start + prefix.body.length;
    keep.push({ start: s.start, end, node: prefix.node });
    for (let i = s.start; i < end; i++) out[i] = '';
  }
  return { source: out.join('\n'), keep };
}

function clbitsOf(nodes) {
  let m = -1;
  const visit = n => { (n.classical || []).forEach(c => { m = Math.max(m, c); }); if (n.condition) m = Math.max(m, n.condition.clbit); if (n.body) visit(n.body); };
  nodes.forEach(visit);
  return m + 1;
}

async function applyEdits() {
  const fmt = st.tab;
  const t = ta();
  if (!t || !editable() || !st.dirty[fmt]) return;
  const seq = ++st.seq;
  const { source, keep } = fmt === 'qiskit' ? blankUnchanged(t.value) : { source: t.value, keep: [] };
  const fail = (message, lines = [], items = []) => {
    if (seq !== st.seq) return;
    st.err[fmt] = { message, lines, items }; st.phase[fmt] = 'error';
    paint(); paintTabs();
  };
  let r;
  try { r = await api.post('/import', { format: IMPORT_FORMAT[fmt], source }); }
  catch (e) { fail(e.message); return; }
  if (seq !== st.seq) return;
  if (!r.ok) { fail(r.error || 'This code could not be read.', (r.unsupported || []).map(u => u.line).filter(Boolean), r.unsupported || []); return; }
  const qubits = r.document.qubits;
  if (qubits > MAX_QUBITS) { fail(`The canvas holds up to ${MAX_QUBITS} qubits; this code has ${qubits}.`); return; }
  let nextId = circuit.s.nextId;
  const linesOf = {};
  const items = r.document.operations.map((n, k) => {
    const id = `N${nextId++}`;
    linesOf[id] = n.metadata?.lines || [];
    return { line: (n.metadata?.lines || [0])[0], k, node: { ...n, id, metadata: { source: 'code' } } };
  });
  keep.forEach((s, j) => {
    const ls = [];
    for (let i = s.start; i <= s.end; i++) ls.push(i);
    linesOf[s.node.id] = ls;
    items.push({ line: s.start, k: -1 - j, node: JSON.parse(JSON.stringify(s.node)) });
  });
  items.sort((a, b) => (a.line - b.line) || (a.k - b.k));
  const nodes = items.map(x => x.node);
  const doc = { version: '0.4', qubits, classical_bits: clbitsOf(nodes), operations: nodes };
  let c;
  try { c = await api.post('/compile', { document: doc }); }
  catch (e) { fail(e.message); return; }
  if (seq !== st.seq) return;
  if (!c.ok) {
    const errs = c.errors || [];
    fail(errs.map(e => e.message + (e.hint ? ` ${e.hint}` : '')).join(' '), errs.flatMap(e => linesOf[e.op_id] || []),
         errs.map(e => ({ line: (linesOf[e.op_id] || [])[0], message: e.message })));
    return;
  }
  st.err[fmt] = null; st.phase[fmt] = 'applied'; st.stale = false;
  circuit.s.nextId = nextId;
  st.applying = true;
  circuit.applyCode(qubits, nodes, st.session || uid('code'));
  st.applying = false;
  paint(); paintTabs();
}

function renderPseudocode(body) {
  const r = circuit.compiled;
  const sel = hooks.selected();
  let h = '<div class="muted dock-note">Pseudocode: the circuit\'s steps in structured plain language. It is generated from the circuit, so it can\'t be edited here.</div>';
  if (!r) h += '<div class="muted dock-note">Checking the circuit…</div>';
  else if (!r.ok) h += '<div class="note bad" style="margin:10px">Fix the problems in the steps list to see the pseudocode.</div>';
  else h += `<div class="ro-lines">${r.pseudocode.steps.map((s, i) => `<div class="ln ${s.id && s.id === sel ? 'hl' : ''} ${s.id ? 'clickable' : ''}" ${s.id ? `data-pick="${s.id}"` : ''}><span class="no">${i + 1}</span><span>${esc(pseudocodeLine(s.code))}</span></div>`).join('')}</div>`;
  body.innerHTML = h;
  $$('[data-pick]', body).forEach(l => l.addEventListener('click', () => hooks.select(l.dataset.pick)));
}

async function loadMath() {
  if (st.mathLoading) return;
  st.mathLoading = true;
  const key = circuit.docKey();
  try {
    const labels = Array.from({ length: circuit.s.qubits }, (_, i) => `q${i}`);
    const m = await api.post('/math', { document: circuit.toDocument(), labels });
    if (key === circuit.docKey()) { st.math = m; st.mathKey = key; st.mathError = null; }
  } catch (e) {
    if (key === circuit.docKey()) { st.math = null; st.mathKey = key; st.mathError = e.message; }
  }
  st.mathLoading = false;
  if (st.tab === 'math' && key === circuit.docKey()) renderBody();
}

function stateView(v) {
  if (!v) return '';
  if (v.n_branches > 1 || (v.branches || []).length > 1) {
    return v.branches.map(b => `<div class="ket">${b.bits ? `<span class="muted">if c = ${esc(b.bits)} (${(100 * b.prob).toFixed(1)}%):</span> ` : ''}${esc(b.ket)}</div>`).join('') + (v.truncated ? '<div class="muted">…more branches</div>' : '');
  }
  return `<span class="ket">${esc(v.branches[0].ket)}</span>`;
}

function matrixView(rows, basis) {
  return `<table class="mx"><thead><tr><th></th>${basis.map(b => `<th>|${esc(b)}⟩</th>`).join('')}</tr></thead><tbody>${rows.map((r, i) => `<tr><th>⟨${esc(basis[i])}|</th>${r.map(x => `<td>${esc(x)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
}

function renderMath(body) {
  const r = circuit.compiled;
  if (!circuit.s.nodes.length) { body.innerHTML = '<div class="muted dock-note">Add a step to see the state after each one.</div>'; return; }
  if (r && !r.ok) { body.innerHTML = '<div class="note bad" style="margin:10px">Fix the problems in the steps list to see the maths.</div>'; return; }
  if (st.mathKey !== circuit.docKey()) {
    body.innerHTML = '<div class="muted dock-note">Working out the state after each step…</div>';
    loadMath();
    return;
  }
  if (st.mathError || !st.math) { body.innerHTML = `<div class="note bad" style="margin:10px">${esc(st.mathError || 'The maths could not be worked out.')}</div>`; return; }
  const m = st.math;
  if (m.skipped) { body.innerHTML = `<div class="muted dock-note">${esc(m.skipped)}</div>`; return; }
  const sel = hooks.selected();
  const ps = Object.fromEntries((r?.pseudocode?.steps || []).filter(s => s.id).map(s => [s.id, pseudocodeLine(s.code.split('  →')[0])]));
  const rows = m.steps.map((s, i) => {
    const after = s.after ? stateView(s.after) : '';
    const meas = s.measure ? `<div class="muted">${s.measure.map(q => `${esc(q.qubit)}: P(0) = ${(100 * q.p0).toFixed(1)}%, P(1) = ${(100 * q.p1).toFixed(1)}%`).join(' · ')}</div>` : '';
    const mx = s.matrix ? `<details><summary>Matrix on ${esc((s.local_qubits || []).join(', '))}</summary>${matrixView(s.matrix, s.basis)}</details>` : s.too_large ? `<div class="muted">Matrix is ${s.too_large.dim}×${s.too_large.dim}, too large to show.</div>` : '';
    return `<div class="mstep ${s.id === sel ? 'hl' : ''}" data-pick="${s.id}">
      <div class="mhead"><span class="no">${i + 1}</span><b>${esc(ps[s.id] || s.op)}</b></div>
      ${s.equation ? `<div class="eq">${esc(s.equation)}</div>` : ''}
      ${s.unavailable ? `<div class="muted">${esc(s.unavailable)}</div>` : `<div class="arrow">→ ${after}</div>${meas}`}
      ${mx}</div>`;
  }).join('');
  body.innerHTML = `<div class="mathview"><div class="muted dock-note">${esc(m.order_note)}</div>
    <div class="mstep"><div class="mhead"><span class="no">0</span><b>Start</b></div><div class="arrow">${stateView(m.initial)}</div></div>${rows}</div>`;
  $$('[data-pick]', body).forEach(el => el.addEventListener('click', e => { if (e.target.closest('summary,details')) return; hooks.select(el.dataset.pick); }));
}
