import { api } from './api.js';
import { CONCEPTS, FAMILIES, GATES, GATE_FAMILIES, WRAPPABLE, colorOf } from './catalog.js';
import { circuit, layout, MAX_QUBITS } from './circuit.js';
import { blockLabel, blockSub, pseudocodeLine } from './describe.js';
import { bindEditor, bitsMeasuredBefore, buildNode, conditionable, draftFromNode, hasMeasure, newDraft, renderEditor, toggleQubit } from './editor.js';
import { fetchExplanation, renderExplanation } from './explain.js';
import { renderProbabilities, renderResults, widthOf } from './results.js';
import { mountDock, openDock, updateDock } from './dock.js';
import { openRunDialog } from './run.js';
import { $, $$, download, esc, store, toast } from './util.js';

const ui = {
  tab: 'steps', palette: store.get('qc.palette', 'concepts'), draft: null, selected: null, zoomed: null,
  openFams: store.get('qc.fams', { basics: true }), explain: null, explainKey: null, explaining: false,
};
let root = null;
let unsub = null;

const labels = () => Array.from({ length: circuit.s.qubits }, (_, i) => `q${i}`);

export function renderBuild(main, view) {
  main.innerHTML = `<div class="build" data-build>
    <div class="build-bar" data-bar></div>
    <aside class="palette" aria-label="Steps you can add" data-palette></aside>
    <section class="stage" aria-label="Circuit and code" data-stage>
      <div class="canvas-scroll" data-canvas></div>
      <div class="stage-foot" data-foot aria-live="polite"></div>
      <div class="dock-host" data-dock></div>
    </section>
    <aside class="inspector" aria-label="Inspector" data-inspector></aside>
  </div>`;
  root = main.querySelector('[data-build]');
  mountDock($('[data-dock]', root), { select: id => { ui.selected = id; ui.tab = 'steps'; if (ui.draft && !ui.draft.editing) ui.draft = null; renderAll(); }, selected: () => ui.selected });
  if (view === 'code') openDock('qiskit');
  if (unsub) unsub();
  unsub = circuit.on(kind => {
    if (!root || !document.body.contains(root)) return;
    if (kind === 'title') return;
    if (kind === 'compiling') { renderFoot(); return; }
    if (ui.selected && !circuit.nodeById(ui.selected)) ui.selected = null;
    if (ui.zoomed && !circuit.nodeById(ui.zoomed)) ui.zoomed = null;
    renderAll();
  });
  bindGlobalKeys();
  renderAll();
  if (!circuit.compiled) circuit.compileNow();
}

function renderAll() {
  const focusKey = document.activeElement?.dataset?.fk;
  renderBar(); renderPalette(); renderStage(); renderInspector(); updateDock();
  if (focusKey) { const el = root.querySelector(`[data-fk="${CSS.escape(focusKey)}"]`); if (el) el.focus(); }
}

function renderBar() {
  const bar = $('[data-bar]', root);
  bar.innerHTML = `
    <label class="sr-only" for="circuit-title">Circuit name</label>
    <input id="circuit-title" class="title" value="${esc(circuit.s.title)}" data-fk="title">
    <span class="chips" style="font-size:13px" aria-label="Number of qubits">
      <button type="button" class="icon-btn" data-qminus data-fk="qminus" aria-label="Remove a qubit" ${circuit.s.qubits <= 1 ? 'disabled' : ''}>−</button>
      <span class="mono">${circuit.s.qubits} qubit${circuit.s.qubits === 1 ? '' : 's'}</span>
      <button type="button" class="icon-btn" data-qplus data-fk="qplus" aria-label="Add a qubit" ${circuit.s.qubits >= MAX_QUBITS ? 'disabled' : ''}>+</button></span>
    <span style="flex:1"></span>
    <button type="button" class="btn ghost small" data-undo data-fk="undo" ${circuit.canUndo() ? '' : 'disabled'} title="Undo (Ctrl+Z)">Undo</button>
    <button type="button" class="btn ghost small" data-redo data-fk="redo" ${circuit.canRedo() ? '' : 'disabled'} title="Redo (Ctrl+Shift+Z)">Redo</button>
    <button type="button" class="btn ghost small" data-clear ${circuit.s.nodes.length ? '' : 'disabled'}>Clear</button>
    <button type="button" class="btn small" data-export aria-haspopup="menu">Export</button>
    <button type="button" class="btn primary" data-run>Run</button>`;
  const t = $('#circuit-title', bar);
  t.addEventListener('change', () => circuit.setTitle(t.value.trim()));
  $('[data-qminus]', bar).addEventListener('click', () => { const e = circuit.setQubits(circuit.s.qubits - 1); if (e) toast(e); });
  $('[data-qplus]', bar).addEventListener('click', () => { const e = circuit.setQubits(circuit.s.qubits + 1); if (e) toast(e); });
  $('[data-undo]', bar).addEventListener('click', doUndo);
  $('[data-redo]', bar).addEventListener('click', doRedo);
  $('[data-clear]', bar).addEventListener('click', () => {
    if (!confirm('Clear every step from this circuit? You can undo this.')) return;
    circuit.clear(); ui.draft = null; toast('Circuit cleared.', { action: { label: 'Undo', run: doUndo } });
  });
  $('[data-export]', bar).addEventListener('click', e => exportMenu(e.currentTarget));
  $('[data-run]', bar).addEventListener('click', () => openRunDialog({ onDone: () => { ui.tab = 'results'; renderInspector(); } }));
}

function doUndo() { const l = circuit.undo(); if (l) toast(`Undid: ${l}`); }
function doRedo() { const l = circuit.redo(); if (l) toast(`Redid: ${l}`); }

function renderPalette() {
  const pal = $('[data-palette]', root);
  const seg = `<div class="seg" role="group" aria-label="Palette"><button type="button" aria-pressed="${ui.palette === 'concepts'}" data-pal="concepts">Concepts</button><button type="button" aria-pressed="${ui.palette === 'gates'}" data-pal="gates">Gates</button></div>`;
  let body = '';
  if (ui.palette === 'concepts') {
    body = FAMILIES.map(f => {
      const open = ui.openFams[f.id] ?? f.open ?? false;
      return `<div class="fam"><button type="button" aria-expanded="${open}" data-fam="${f.id}">${esc(f.name)}<span aria-hidden="true">${open ? '▾' : '▸'}</span></button>
        ${open ? f.ops.map(op => {
          const c = CONCEPTS[op];
          const on = ui.draft && ui.draft.op === op && !ui.draft.editing;
          const blocked = c.needsMeasure && !hasMeasure();
          return `<button type="button" class="tool" data-concept="${op}" data-fk="c-${op}" aria-pressed="${!!on}" ${blocked ? 'aria-disabled="true"' : ''} title="${esc(blocked ? 'Add a Measure step first. ' + c.desc : c.desc)}">
            <span class="dot" style="background:var(--c-${c.color}-dot)" aria-hidden="true"></span><span>${esc(c.name)}</span></button>`;
        }).join('') : ''}</div>`;
    }).join('');
  } else {
    body = GATE_FAMILIES.map(f => `<div class="fam"><div class="label" style="padding:8px">${esc(f.name)}</div>${f.ids.map(id => {
      const g = GATES.find(x => x.id === id);
      const needs = g.controls + g.targets;
      const on = ui.draft && ui.draft.op === 'gate' && ui.draft.gate.id === id && !ui.draft.editing;
      return `<button type="button" class="tool" data-gate="${id}" data-fk="g-${id}" aria-pressed="${!!on}" ${needs > circuit.s.qubits ? 'disabled' : ''} title="${esc(g.desc)}">
        <span class="dot" style="background:var(--c-gate-dot)" aria-hidden="true"></span><span class="mono">${esc(g.label)}</span><small style="margin-left:auto">${esc(g.desc)}</small></button>`;
    }).join('')}</div>`).join('') + `<div class="fam"><div class="label" style="padding:8px">Measurement</div><button type="button" class="tool" data-concept="measure" data-fk="g-measure"><span class="dot" style="background:var(--c-gray-dot)" aria-hidden="true"></span><span>Measure</span></button>
      <button type="button" class="tool" data-concept="reset"><span class="dot" style="background:var(--c-gray-dot)" aria-hidden="true"></span><span>Reset</span></button></div>`;
  }
  pal.innerHTML = seg + body + `<div class="muted" style="font-size:12px;padding:10px 8px">Concepts are groups of gates. Open any block on the canvas to see its exact gates.</div>`;
  $$('[data-pal]', pal).forEach(b => b.addEventListener('click', () => { ui.palette = b.dataset.pal; store.set('qc.palette', ui.palette); renderPalette(); }));
  $$('[data-fam]', pal).forEach(b => b.addEventListener('click', () => {
    const id = b.dataset.fam; ui.openFams[id] = !(ui.openFams[id] ?? FAMILIES.find(f => f.id === id).open ?? false);
    store.set('qc.fams', ui.openFams); renderPalette(); $(`[data-fam="${id}"]`, pal).focus();
  }));
  $$('[data-concept]', pal).forEach(b => b.addEventListener('click', () => startDraft(newDraft(b.dataset.concept))));
  $$('[data-gate]', pal).forEach(b => b.addEventListener('click', () => startDraft(newDraft('gate', b.dataset.gate))));
}

function startDraft(d) {
  const c = d.op === 'gate' ? null : CONCEPTS[d.op];
  if (c?.needsMeasure && !hasMeasure()) { toast(`${c.name} needs a Measure step first: it applies a step only after a measurement has written a classical bit.`, { ms: 7000 }); return; }
  if (c?.wraps === 'ref' && !d.params.ref) { toast('Uncompute needs an earlier reversible step to undo, such as a Compare.'); return; }
  if (c?.wraps === 'correct' && !conditionable().length) { toast('Add the step you want to apply after your Measure step, then choose Classically controlled.', { ms: 7000 }); return; }
  if (c?.wraps && c.wraps !== 'ref' && !circuit.s.nodes.some(n => WRAPPABLE(n.op))) { toast(`Add a step first: ${c.name} wraps an existing step.`); return; }
  if (c?.wraps === 'correct') { if (d.wrapId && !conditionable().some(n => n.id === d.wrapId)) d.wrapId = conditionable().slice(-1)[0].id; }
  else if (ui.selected && d.op !== 'gate' && c?.wraps && c.wraps !== 'ref' && WRAPPABLE(circuit.nodeById(ui.selected)?.op)) d.wrapId = ui.selected;
  ui.draft = d; ui.tab = 'steps';
  renderAll();
  const first = root.querySelector('.editor:not(.problem-card) [data-q]:not([disabled])') || root.querySelector('.editor:not(.problem-card) [data-commit]');
  if (first) first.focus();
}

async function commitDraft() {
  const d = ui.draft;
  if (!d) return;
  let built;
  try { built = buildNode(d); } catch (e) { d.error = e.message; renderInspector(); return; }
  const { node, replaces } = built;
  const prevErr = new Set((circuit.compiled?.errors || []).map(e => `${e.code}|${e.op_id}`));
  if (d.editing) circuit.replaceNode(d.editing, node, 'Edit step');
  else if (replaces) circuit.replaceNode(replaces, node, `Add ${CONCEPTS[d.op].name}`);
  else circuit.addNode(node, `Add ${d.op === 'gate' ? d.gate.label : CONCEPTS[d.op].name}`);
  const res = await circuit.compileNow();
  const fresh = (res?.errors || []).filter(e => !prevErr.has(`${e.code}|${e.op_id}`) && (e.op_id === node.id || !e.op_id || e.op_id === node.body?.id));
  if (fresh.length) {
    circuit.undo(); circuit.redoStack = [];
    d.error = fresh[0].message + (fresh[0].hint ? ' ' + fresh[0].hint : '');
    renderAll();
    return;
  }
  ui.draft = null; ui.selected = node.id;
  renderAll();
  const w = res?.warnings?.find(x => x.op_id === node.id);
  toast(w ? w.message : `${blockLabel(node)} added.`, w ? { kind: 'info', ms: 7000 } : {});
}

function cancelDraft() { ui.draft = null; renderAll(); }

function renderStage() {
  const canvas = $('[data-canvas]', root);
  const keep = canvas.scrollTop, keepL = canvas.scrollLeft;
  canvas.innerHTML = `<div class="stage-inner">${circuitGrid()}</div>`;
  canvas.scrollTop = keep; canvas.scrollLeft = keepL;
  bindGrid(canvas);
  renderFoot();
}

function circuitGrid() {
  const n = circuit.s.qubits;
  const { items, cols } = layout(circuit.s.nodes, n, ui.zoomed, circuit.compiled);
  const zoomCols = new Set();
  items.filter(it => it.zoom).forEach(it => { for (let c = it.col; c < it.col + it.w; c++) zoomCols.add(c); });
  const widths = Array.from({ length: Math.max(cols, 1) + 1 }, (_, c) => zoomCols.has(c) ? '74px' : '128px').join(' ');
  const errs = new Set((circuit.compiled?.errors || []).map(e => e.op_id).filter(Boolean));
  let h = `<div class="wires" style="grid-template-columns:64px ${widths} minmax(48px,1fr);grid-template-rows:repeat(${n}, 78px)">`;
  for (let q = 0; q < n; q++) {
    const inDraft = ui.draft && Object.values(ui.draft.roles).some(a => a.includes(q));
    h += `<div class="qlab" style="grid-column:1;grid-row:${q + 1}"><button type="button" data-qlab="${q}" data-fk="q${q}" aria-pressed="${!!inDraft}" ${ui.draft ? '' : 'tabindex="-1"'} title="${ui.draft ? 'Pick this qubit for the step' : `Qubit ${q}`}">q${q}</button></div>
      <div class="wire" style="grid-row:${q + 1}"></div>`;
  }
  for (const it of items) {
    const node = it.node;
    const idx = circuit.index(node.id);
    const rows = `${it.lo + 1} / span ${it.hi - it.lo + 1}`;
    if (it.zoom) {
      h += `<div class="zoom-frame" style="grid-column:${it.col + 2} / span ${it.w};grid-row:${rows}"><span>${esc(blockLabel(node))} · ${it.zoom.length} gate${it.zoom.length === 1 ? '' : 's'} <button type="button" class="linkish" data-unzoom="${node.id}">Fold</button></span></div>`;
      it.zoom.forEach(z => {
        const g = z.gate;
        const name = (g.controls?.length ? 'C'.repeat(g.controls.length) : '') + g.name.toUpperCase();
        h += `<div class="zgate ${z.hi > z.lo ? 'span' : ''}" style="grid-column:${z.col + 2};grid-row:${z.lo + 1} / span ${z.hi - z.lo + 1}" title="${esc(name)} on ${[...(g.controls || []), ...g.targets].map(q => 'q' + q).join(', ')}">${esc(name)}</div>`;
      });
      continue;
    }
    h += `<button type="button" class="block c-${colorOf(node)} ${errs.has(node.id) ? 'has-error' : ''}" data-node="${node.id}" data-fk="n-${node.id}"
      aria-pressed="${ui.selected === node.id}" style="grid-column:${it.col + 2};grid-row:${rows}"
      aria-label="Step ${idx + 1}: ${esc(blockLabel(node))}, ${esc(blockSub(node))}${errs.has(node.id) ? ', has a problem' : ''}">
      <span>${esc(blockLabel(node))}</span><span class="sub">${esc(blockSub(node))}</span></button>`;
  }
  h += `</div>`;
  if (!circuit.s.nodes.length) {
    h += `<div class="empty" style="min-height:220px"><h2>Your circuit is empty</h2>
      <p style="margin:0;max-width:440px">Pick a concept or gate from the palette, choose its qubits, then press Add step. Every qubit starts in |0⟩.</p>
      <p class="muted" style="margin:0;font-size:13px">Have code already? <a href="#/import">Bring code</a> · Want a goal? <a href="#/">Try a practice problem</a></p></div>`;
  }
  return h;
}

function bindGrid(stage) {
  $$('[data-node]', stage).forEach(b => {
    b.addEventListener('click', () => { ui.selected = ui.selected === b.dataset.node ? null : b.dataset.node; ui.tab = 'steps'; if (ui.draft && !ui.draft.editing) ui.draft = null; renderAll(); });
    b.addEventListener('dblclick', () => toggleZoom(b.dataset.node));
  });
  $$('[data-unzoom]', stage).forEach(b => b.addEventListener('click', () => toggleZoom(b.dataset.unzoom)));
  $$('[data-qlab]', stage).forEach(b => b.addEventListener('click', () => {
    if (!ui.draft) return;
    toggleQubit(ui.draft, +b.dataset.qlab);
    renderAll();
  }));
}

async function toggleZoom(id) {
  if (ui.zoomed === id) { ui.zoomed = null; renderAll(); return; }
  if (!circuit.compiled?.ok) await circuit.compileNow();
  if (!circuit.compiled?.ok) { toast('Fix the problems in the steps list first, then the gates can be shown.'); return; }
  ui.zoomed = id; ui.selected = id; renderAll();
}

function renderFoot() {
  const foot = root && $('[data-foot]', root);
  if (!foot) return;
  const r = circuit.compiled;
  const parts = [`${circuit.s.qubits} qubit${circuit.s.qubits === 1 ? '' : 's'}`, `${circuit.s.nodes.length} step${circuit.s.nodes.length === 1 ? '' : 's'}`];
  if (circuit.compiling) parts.push('Checking…');
  else if (circuit.compileError) parts.push(`<span class="bad">Can't check the circuit: ${esc(circuit.compileError)}</span>`);
  else if (r) {
    parts.push(`${r.gates.length} gates`);
    parts.push(r.ok ? (r.warnings.length ? `<span>${r.warnings.length} note${r.warnings.length === 1 ? '' : 's'}</span>` : '<span class="ok">✓ checked, no problems</span>') : `<span class="bad">${r.errors.length} problem${r.errors.length === 1 ? '' : 's'} to fix</span>`);
  }
  parts.push('Double-click a block to see its gates');
  foot.innerHTML = parts.join('<span aria-hidden="true">·</span>');
}

function renderInspector() {
  const ins = $('[data-inspector]', root);
  const tabs = [['steps', 'Steps'], ['results', 'Results'], ['explain', 'Explain']];
  ins.innerHTML = `<div class="tabs" role="tablist" aria-label="Inspector">${tabs.map(([k, l]) => `<button type="button" role="tab" id="tab-${k}" aria-controls="panel-${k}" aria-selected="${ui.tab === k}" tabindex="${ui.tab === k ? 0 : -1}" data-tab="${k}">${l}</button>`).join('')}</div>
    <div class="tab-body" role="tabpanel" id="panel-${ui.tab}" aria-labelledby="tab-${ui.tab}" data-panel></div>`;
  $$('[data-tab]', ins).forEach(b => {
    b.addEventListener('click', () => { ui.tab = b.dataset.tab; renderInspector(); $(`[data-tab="${ui.tab}"]`, ins).focus(); });
    b.addEventListener('keydown', e => {
      if (!['ArrowRight', 'ArrowLeft'].includes(e.key)) return;
      const i = tabs.findIndex(t => t[0] === ui.tab);
      ui.tab = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length][0];
      renderInspector(); $(`[data-tab="${ui.tab}"]`, ins).focus();
    });
  });
  const panel = $('[data-panel]', ins);
  if (ui.tab === 'steps') renderSteps(panel);
  else if (ui.tab === 'results') renderResultsTab(panel);
  else renderExplainTab(panel);
}

function stepInfo(id) {
  const r = circuit.compiled;
  return {
    ps: r?.pseudocode?.steps?.find(s => s.id === id) || null,
    errs: (r?.errors || []).filter(e => e.op_id === id),
    warns: (r?.warnings || []).filter(w => w.op_id === id),
  };
}

function problemCard() {
  const p = circuit.problem;
  if (!p) return '';
  const r = ui.problemResult;
  const names = (p.allowed_concepts || []).map(op => CONCEPTS[op]?.name || op).join(', ');
  return `<div class="editor problem-card" style="border-color:var(--accent)"><div class="label">Practice problem</div>
    <p style="margin:0;font-size:15px">${esc(p.statement)}</p>
    <div class="muted" style="font-size:12px">Uses: ${esc(names)}</div>
    ${r ? `<div class="note ${r.passed ? 'ok' : 'bad'}">${esc(r.passed ? (r.summary || 'Solved.') : (r.summary || 'Not yet.'))}</div>` : ''}
    ${(p.hint_ladder || []).slice(0, ui.problemHints || 0).map((t, i) => `<div class="note info">Hint ${i + 1}: ${esc(t)}</div>`).join('')}
    <div class="chips"><button type="button" class="btn primary small" data-pcheck>Check my circuit</button>
      <button type="button" class="btn small" data-phint ${(ui.problemHints || 0) >= (p.hint_ladder || []).length ? 'disabled' : ''}>Hint</button>
      <button type="button" class="btn ghost small" data-pleave>Leave problem</button></div></div>`;
}

function bindProblem(panel) {
  const on = (sel, fn) => { const el = $(sel, panel); if (el) el.addEventListener('click', fn); };
  on('[data-pcheck]', async () => {
    try { ui.problemResult = await api.post('/check-problem', { problem_id: circuit.problem.id, document: circuit.toDocument() }); }
    catch (e) { ui.problemResult = { passed: false, summary: e.message }; }
    renderInspector();
  });
  on('[data-phint]', () => { ui.problemHints = (ui.problemHints || 0) + 1; renderInspector(); });
  on('[data-pleave]', () => { circuit.problem = null; ui.problemResult = null; ui.problemHints = 0; renderInspector(); });
}

function renderSteps(panel) {
  let h = problemCard();
  if (ui.draft) h += renderEditor(ui.draft);
  else if (ui.selected && circuit.nodeById(ui.selected)) h += selectedCard(circuit.nodeById(ui.selected));
  const loose = (circuit.compiled?.errors || []).filter(e => !e.op_id);
  if (loose.length) h += loose.map(e => `<div class="note bad">${esc(e.message)}</div>`).join('');
  if (circuit.compileError) h += `<div class="note warn">Can't reach the server to check this circuit. Steps are kept; checking resumes when the server is back.</div>`;
  h += `<div class="label" style="margin-top:4px">Steps · read top to bottom</div>`;
  if (!circuit.s.nodes.length) h += `<div class="muted" style="font-size:14px">No steps yet.</div>`;
  h += circuit.s.nodes.map((n, i) => {
    const { ps, errs, warns } = stepInfo(n.id);
    return `<button type="button" class="step-row" data-row="${n.id}" data-fk="row-${n.id}" aria-current="${ui.selected === n.id}">
      <span class="n">${i + 1}</span><span style="min-width:0"><span class="t">${esc(ps ? pseudocodeLine(ps.code.split('  →')[0]) : blockLabel(n))}</span>
      ${ps?.effect ? `<span class="e">${esc(ps.effect)}</span>` : ''}
      ${errs.map(e => `<span class="issue">${esc(e.message)}</span>`).join(' ')}${!errs.length ? warns.map(w => `<span class="wissue">${esc(w.message)}</span>`).join(' ') : ''}</span></button>`;
  }).join('');
  panel.innerHTML = h;
  if (ui.draft) {
    const ed = $('.editor:not(.problem-card)', panel);
    bindEditor(ed, ui.draft, () => { renderAll(); });
    $('[data-commit]', ed).addEventListener('click', commitDraft);
    $('[data-cancel]', ed).addEventListener('click', cancelDraft);
  }
  $$('[data-row]', panel).forEach(b => b.addEventListener('click', () => { ui.selected = b.dataset.row; ui.draft = null; renderAll(); }));
  bindSelected(panel);
  bindProblem(panel);
}

function selectedCard(n) {
  const i = circuit.index(n.id);
  const { ps, errs, warns } = stepInfo(n.id);
  const canEdit = !!draftFromNode(n);
  const range = circuit.compiled?.node_ranges?.[n.id] || [];
  return `<div class="editor" style="border-color:var(--ink)">
    <h3>Step ${i + 1}: ${esc(blockLabel(n))}</h3>
    ${ps ? `<div><span class="label">Pseudocode</span><div class="mono" style="font-size:13px">${esc(pseudocodeLine(ps.code))}</div></div><p class="desc">${esc(ps.plain)}</p>` : ''}
    ${n.metadata?.lifted_from ? `<div class="note ok" style="font-size:13px">Grouped from ${n.metadata.lifted_from.length} imported gates${n.metadata.lines?.length ? ` (lines ${n.metadata.lines.join(', ')})` : ''}; checked to be the same operation.</div>` : ''}
    ${n.metadata?.source === 'import' && !n.metadata?.lifted_from && n.metadata?.lines?.length ? `<div class="muted" style="font-size:12px">From line ${n.metadata.lines.join(', ')}${n.metadata.loop ? ` (loop ${esc(n.metadata.loop)})` : ''} of the imported code.</div>` : ''}
    ${errs.map(e => `<div class="note bad">${esc(e.message)}${e.hint ? ' ' + esc(e.hint) : ''}</div>`).join('')}
    ${warns.map(w => `<div class="note warn">${esc(w.message)}</div>`).join('')}
    <div class="chips">
      <button type="button" class="btn small" data-sel-zoom>${ui.zoomed === n.id ? 'Fold gates' : `Show gates${range.length ? ` (${range.length})` : ''}`}</button>
      ${canEdit ? '<button type="button" class="btn small" data-sel-edit>Edit</button>' : ''}
      <button type="button" class="btn small" data-sel-up ${i === 0 ? 'disabled' : ''} aria-label="Move earlier">↑</button>
      <button type="button" class="btn small" data-sel-down ${i === circuit.s.nodes.length - 1 ? 'disabled' : ''} aria-label="Move later">↓</button>
      ${n.metadata?.lifted_from ? '<button type="button" class="btn small" data-sel-ungroup>Ungroup to gates</button>' : ''}
      ${WRAPPABLE(n.op) ? `<button type="button" class="btn small" data-sel-wrap="control" title="Run this step only when control qubits are 1">Control…</button><button type="button" class="btn small" data-sel-wrap="correct" title="${bitsMeasuredBefore(n.id).length ? 'Run this step only when a measured bit has a given value' : 'Needs a Measure step placed before this step'}" ${bitsMeasuredBefore(n.id).length ? '' : 'disabled'}>If measured…</button>` : ''}
      <button type="button" class="btn small danger" data-sel-del>Delete</button>
    </div></div>`;
}

function bindSelected(panel) {
  const id = ui.selected;
  if (!id || ui.draft) return;
  const on = (sel, fn) => { const el = $(sel, panel); if (el) el.addEventListener('click', fn); };
  on('[data-sel-zoom]', () => toggleZoom(id));
  on('[data-sel-edit]', () => startDraft(draftFromNode(circuit.nodeById(id))));
  on('[data-sel-up]', () => circuit.moveNode(id, -1));
  on('[data-sel-down]', () => circuit.moveNode(id, 1));
  on('[data-sel-del]', () => deleteNode(id));
  on('[data-sel-ungroup]', () => {
    const node = circuit.nodeById(id);
    const originals = node.metadata.lifted_from;
    circuit.change(s => {
      const i = s.nodes.findIndex(x => x.id === id);
      const fresh = originals.map(g => ({ ...JSON.parse(JSON.stringify(g)), id: `N${s.nextId++}` }));
      s.nodes.splice(i, 1, ...fresh);
    }, 'Ungroup');
    ui.selected = null; ui.zoomed = null;
    toast(`Ungrouped into ${originals.length} gates.`, { action: { label: 'Undo', run: doUndo } });
  });
  $$('[data-sel-wrap]', panel).forEach(b => b.addEventListener('click', () => { const d = newDraft(b.dataset.selWrap); d.wrapId = id; startDraft(d); }));
}

function deleteNode(id) {
  const name = blockLabel(circuit.nodeById(id));
  const err = circuit.removeNode(id);
  if (err) { toast(err); return; }
  ui.selected = null;
  toast(`Deleted ${name}.`, { action: { label: 'Undo', run: doUndo } });
}

function measureMap() {
  const pairs = [];
  circuit.s.nodes.filter(n => n.op === 'measure').forEach(n => n.targets.forEach((q, k) => pairs.push(`c${n.classical[k]} ← q${q}`)));
  return pairs;
}

function measureNote() {
  const pairs = measureMap();
  if (pairs.length) return `<div class="muted" style="font-size:12px">Measured: ${esc(pairs.join(', '))}</div>`;
  if (!circuit.s.nodes.length) return '';
  const all = Array.from({ length: circuit.s.qubits }, (_, q) => `q${q} → c${q}`).join(', ');
  return `<div class="muted" style="font-size:12px">No Measure step yet. These are calculated probabilities, reading the qubits in order (${esc(all)}). Add a Measure step to run the circuit.</div>`;
}

function renderResultsTab(panel) {
  const run = circuit.lastRun;
  const predicted = circuit.compiled?.ok ? circuit.compiled.step_log?.predicted : null;
  const width = Math.max(1, circuit.classicalBits() || circuit.s.qubits);
  let h = '';
  if (run && run.calculated) {
    const current = circuit.runIsCurrent();
    h += `<div class="note warn"><b>No Measure step, so nothing was measured${run.backend_label ? ` and nothing was sent to ${esc(run.backend_label)}` : ''}.</b>
      The bars below are the probabilities calculated from the circuit's final state, not measured results. Add a Measure step and run again to get measured results.</div>`;
    if (!current) h += '<div class="note warn">The circuit has changed since then. Run again to update this.</div>';
    const pred = current ? (run.predicted || predicted) : predicted;
    if (pred) h += `<div class="label">Calculated probabilities (exact)</div>${renderProbabilities({ predicted: pred, width })}`;
    else h += '<div class="muted">This circuit is too large to calculate the probabilities exactly here.</div>';
    h += `<div class="chips"><button type="button" class="btn primary small" data-ex-go>Explain this circuit</button></div>`;
  } else if (run) {
    const w = widthOf(run.counts, width);
    const current = circuit.runIsCurrent();
    const total = Object.values(run.counts).reduce((a, b) => a + b, 0);
    h += `<div class="label">${total.toLocaleString()} shots · ${esc(run.backend_label || run.backend)}</div>
      ${current ? '' : '<div class="note warn">These results are from an earlier version of the circuit. Run again to update them.</div>'}
      ${renderResults({ counts: run.counts, predicted: current ? predicted : null, width: w })}`;
    h += measureNote();
    const rc = run.math?.result_check;
    if (rc) {
      const noisy = /noisy backend/.test(rc.check || '');
      h += noisy
        ? `<div class="note ${rc.ok === false ? 'bad' : 'info'}">Compared with the exact prediction: ${esc(rc.detail || '')}.</div>`
        : `<div class="note ${rc.ok === false ? 'bad' : 'ok'}">${rc.ok === false ? 'Does not match' : 'Matches'} the exact prediction${rc.detail ? ` (${esc(rc.detail)})` : ''}.</div>`;
    }
    if (run.backend === 'ionq_sim_ideal') h += '<div class="muted" style="font-size:12px">IonQ\'s ideal simulator returns exact probabilities rather than separate shots, so these counts are those probabilities multiplied by the number of shots.</div>';
    const noiseFlags = (run.flags || []).filter(f => /^noise_model/.test(f.flag));
    noiseFlags.forEach(f => { h += `<div class="note bad">Check this run: ${esc(f.detail)}. The result may come from IonQ's ideal simulator.</div>`; });
    const codeBad = (run.math?.failed_checks || []).filter(c => /code|parsed/.test(c));
    if (codeBad.length) h += `<div class="note bad">The code that ran does not match the circuit: ${esc(codeBad.join('; '))}</div>`;
    if (run.save_error) h += `<div class="note bad">${esc(run.save_error)}</div>`;
    h += `<div class="chips"><button type="button" class="btn primary small" data-ex-go>Explain this result</button><a class="btn small" href="#/runs">My runs</a></div>`;
  } else {
    h += `<div class="muted">No run yet. Press Run to sample this circuit.</div>`;
    if (predicted) h += `<div class="label">Predicted probabilities (exact)</div>${renderProbabilities({ predicted, width })}${measureNote()}`;
  }
  panel.innerHTML = h;
  const b = $('[data-ex-go]', panel);
  if (b) b.addEventListener('click', () => { ui.tab = 'explain'; renderInspector(); runExplain(); });
}

function explainKey() { return (circuit.runIsCurrent() ? circuit.lastRun.id : '') + '|' + circuit.docKey(); }

function renderExplainTab(panel) {
  if (ui.explain && ui.explainKey === explainKey()) {
    panel.innerHTML = ui.explain;
    return;
  }
  panel.innerHTML = `<p style="margin:0">Get a step-by-step explanation of ${circuit.runIsCurrent() && !circuit.lastRun.calculated ? 'this result' : 'what this circuit does'}: the pseudocode, the principle behind each step, then the math and code when you open them.</p>
    <div><button type="button" class="btn primary" data-ex-go ${ui.explaining ? 'disabled' : ''}>${ui.explaining ? 'Explaining…' : 'Explain'}</button></div>
    ${circuit.runIsCurrent() && !circuit.lastRun.calculated ? '' : '<div class="muted" style="font-size:13px">No measured run for this circuit, so this explains the exact predicted probabilities.</div>'}`;
  $('[data-ex-go]', panel).addEventListener('click', runExplain);
}

async function runExplain() {
  if (!circuit.s.nodes.length) { toast('Add some steps first.'); return; }
  ui.explaining = true; if (ui.tab === 'explain') renderInspector();
  const key = explainKey();
  try {
    const cur = circuit.runIsCurrent() && !circuit.lastRun.calculated ? circuit.lastRun : null;
    const r = await fetchExplanation({ recordId: cur?.record_id || null, document: circuit.toDocument(), counts: cur?.counts || null, labels: labels() });
    ui.explain = renderExplanation(r); ui.explainKey = key;
  } catch (e) {
    ui.explain = `<div class="note bad">Couldn't explain this: ${esc(e.message)}</div><div><button type="button" class="btn" data-ex-retry>Try again</button></div>`;
    ui.explainKey = null;
  }
  ui.explaining = false;
  if (ui.tab === 'explain' && root) {
    renderInspector();
    const retry = $('[data-ex-retry]', root);
    if (retry) retry.addEventListener('click', runExplain);
  }
}

function exportMenu(anchor) {
  const existing = $('[data-export-menu]');
  if (existing) { existing.remove(); return; }
  const m = document.createElement('div');
  m.dataset.exportMenu = '';
  m.setAttribute('role', 'menu');
  m.className = 'card';
  const rect = anchor.getBoundingClientRect();
  Object.assign(m.style, { position: 'fixed', top: `${rect.bottom + 6}px`, right: `${Math.max(8, innerWidth - rect.right)}px`, zIndex: 50, padding: '6px', display: 'flex', flexDirection: 'column', minWidth: '240px', boxShadow: 'var(--shadow)' });
  const items = [['py', 'Qiskit (.py)'], ['qasm', 'OpenQASM 3 (.qasm)'], ['json', 'Circuit file (.json)'], ['copy', 'Copy Qiskit code']];
  m.innerHTML = items.map(([k, l]) => `<button type="button" role="menuitem" class="btn ghost" style="justify-content:flex-start" data-x="${k}">${l}</button>`).join('');
  document.body.appendChild(m);
  m.querySelector('button').focus();
  const close = () => { m.remove(); document.removeEventListener('mousedown', outside, true); anchor.focus(); };
  const outside = e => { if (!m.contains(e.target) && e.target !== anchor) close(); };
  document.addEventListener('mousedown', outside, true);
  m.addEventListener('keydown', e => {
    const bs = [...m.querySelectorAll('button')], i = bs.indexOf(document.activeElement);
    if (e.key === 'Escape') close();
    if (e.key === 'ArrowDown') { e.preventDefault(); bs[(i + 1) % bs.length].focus(); }
    if (e.key === 'ArrowUp') { e.preventDefault(); bs[(i + bs.length - 1) % bs.length].focus(); }
  });
  m.addEventListener('click', async e => {
    const k = e.target.closest('[data-x]')?.dataset.x;
    if (!k) return;
    close();
    const base = (circuit.s.title || 'circuit').replace(/[^\w-]+/g, '_');
    if (k === 'json') { download(`${base}.json`, JSON.stringify({ title: circuit.s.title, document: circuit.toDocument() }, null, 2), 'application/json'); return; }
    const r = await circuit.compileNow();
    if (!r?.ok) { toast(r ? 'Fix the problems in the steps list first.' : circuit.compileError, { kind: 'bad' }); return; }
    if (k === 'py') download(`${base}.py`, r.qiskit_py, 'text/x-python');
    else if (k === 'copy') { try { await navigator.clipboard.writeText(r.qiskit_py); toast('Qiskit code copied.'); } catch (_) { toast("Couldn't copy; use Export > Qiskit (.py) instead.", { kind: 'bad' }); } }
    else {
      try { const q = await api.post('/compile', { document: circuit.toDocument(), qasm: true }); download(`${base}.qasm`, q.qasm3, 'text/plain'); }
      catch (err) { toast(err.message, { kind: 'bad' }); }
    }
  });
}

let keysBound = false;
function bindGlobalKeys() {
  if (keysBound) return;
  keysBound = true;
  document.addEventListener('keydown', e => {
    if (!root || !document.body.contains(root)) return;
    const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || '');
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && !typing) { e.preventDefault(); if (e.shiftKey) doRedo(); else doUndo(); return; }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y' && !typing) { e.preventDefault(); doRedo(); return; }
    if (e.key === 'Escape' && ui.draft) { cancelDraft(); return; }
    if (typing) return;
    const focusedNode = document.activeElement?.dataset?.node;
    if ((e.key === 'Delete' || e.key === 'Backspace') && (focusedNode || ui.selected)) { e.preventDefault(); deleteNode(focusedNode || ui.selected); }
    else if (e.key.toLowerCase() === 'g' && (focusedNode || ui.selected)) toggleZoom(focusedNode || ui.selected);
  });
}
