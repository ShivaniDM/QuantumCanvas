import { CONCEPTS, GATES, ANGLE_PRESETS, WRAPPABLE, UNITARY } from './catalog.js';
import { circuit } from './circuit.js';
import { bits, blockLabel, blockSub } from './describe.js';
import { esc, fmtAngle } from './util.js';
import { seeAnalogy } from './progress.js';

export function newDraft(op, gateId) {
  if (op === 'gate') {
    const g = GATES.find(x => x.id === gateId);
    return { op: 'gate', gate: g, roles: { controls: [], targets: [] }, params: { name: g.name, ...(g.angle ? { angle: { pi: [1, 2] } } : {}) },
             active: g.controls ? 'controls' : 'targets', editing: null, error: null };
  }
  const c = CONCEPTS[op];
  const params = {};
  c.params.forEach(p => { if (p.def !== undefined) params[p.key] = JSON.parse(JSON.stringify(p.def)); });
  const roles = {};
  c.roles.forEach(r => { roles[r.key] = []; });
  if (c.wraps === 'control') roles.controls = roles.controls || [];
  const d = { op, roles, params, active: c.roles[0]?.key || null, editing: null, wrapId: null, error: null, showAnalogy: !!c.analogy && seeAnalogy(op) };
  if (c.wraps === 'correct') d.wrapId = conditionable().slice(-1)[0]?.id || null;
  else if (c.wraps) d.wrapId = wrappable().slice(-1)[0]?.id || null;
  if (op === 'uncompute') { const list = undoable(); d.params.ref = (list.filter(n => n.op === 'compare').slice(-1)[0] || list.slice(-1)[0])?.id || ''; }
  if (op === 'mark' && !compareSteps().length) d.params.mode = 'value';
  return d;
}

export function draftFromNode(node) {
  if (node.op === 'gate') {
    const g = GATES.find(x => x.name === node.params.name && x.controls === node.controls.length && x.targets === node.targets.length);
    if (!g) return null;
    return { op: 'gate', gate: g, roles: { controls: [...node.controls], targets: [...node.targets] }, params: JSON.parse(JSON.stringify(node.params)),
             active: 'targets', editing: node.id, error: null };
  }
  const c = CONCEPTS[node.op];
  if (!c || c.wraps) return null;
  const d = newDraft(node.op);
  d.editing = node.id;
  d.roles = { targets: [...(node.targets || [])], controls: [...(node.controls || [])], ancillas: [...(node.ancillas || [])] };
  Object.assign(d.params, JSON.parse(JSON.stringify(node.params || {})));
  if (node.op === 'mark') d.params.mode = node.params?.via ? 'via' : 'value';
  if (node.op === 'boost') d.params.repeat = node.repeat || 1;
  if (node.op === 'encode') d.params.dataText = Array.isArray(node.params.data) ? node.params.data.join(', ') : String(node.params.data ?? '');
  return d;
}

const wrappable = () => circuit.s.nodes.filter(n => WRAPPABLE(n.op));
const firstMeasureIndex = () => circuit.s.nodes.findIndex(n => n.op === 'measure');
export const hasMeasure = () => firstMeasureIndex() >= 0;
export const conditionable = () => { const m = firstMeasureIndex(); return m < 0 ? [] : wrappable().filter(n => circuit.index(n.id) > m); };
export const bitsMeasuredBefore = id => {
  const i = id ? circuit.index(id) : circuit.s.nodes.length;
  return [...new Set(circuit.s.nodes.slice(0, i < 0 ? circuit.s.nodes.length : i).filter(n => n.op === 'measure').flatMap(n => n.classical || []))].sort((a, b) => a - b);
};
const undoable = () => circuit.s.nodes.filter(n => UNITARY(n.op) && n.op !== 'uncompute' && !(n.body && !UNITARY(n.body.op)));
const compareSteps = () => circuit.s.nodes.filter(n => n.op === 'compare');
const stepName = n => `${circuit.index(n.id) + 1}. ${blockLabel(n)} · ${blockSub(n)}`;

export function visibleRoles(d) {
  if (d.op === 'gate') {
    const r = [];
    if (d.gate.controls) r.push({ key: 'controls', label: d.gate.controls === 1 ? 'Control qubit' : `Control qubits (${d.gate.controls})`, min: d.gate.controls, max: d.gate.controls });
    r.push({ key: 'targets', label: d.gate.targets === 1 ? 'Target qubit' : 'Target qubits (2)', min: d.gate.targets, max: d.gate.targets });
    return r;
  }
  const c = CONCEPTS[d.op];
  const roles = c.roles.filter(r => !r.showIf || r.showIf(d.params));
  if (c.wraps === 'control' && !roles.find(r => r.key === 'controls')) roles.unshift({ key: 'controls', label: 'Control qubits', min: 1 });
  return roles;
}

export function toggleQubit(d, q) {
  const roles = visibleRoles(d);
  for (const r of roles) {
    const at = d.roles[r.key].indexOf(q);
    if (at >= 0) { d.roles[r.key].splice(at, 1); d.active = r.key; d.error = null; return; }
  }
  let role = roles.find(r => r.key === d.active) || roles[0];
  if (!role) return;
  if (role.max && d.roles[role.key].length >= role.max) {
    const next = roles.find(r => !r.max || d.roles[r.key].length < r.max);
    if (!next) { d.error = 'All qubits for this step are chosen. Click a chosen qubit to remove it.'; return; }
    role = next;
  }
  d.roles[role.key].push(q);
  if (role.max && d.roles[role.key].length >= role.max) {
    const nxt = roles.find(r => r.key !== role.key && d.roles[r.key].length < (r.max || Infinity));
    if (nxt) d.active = nxt.key;
  } else d.active = role.key;
  d.error = null;
}

function angleField(key, ang) {
  const [n, dd] = ang?.pi || [1, 1];
  const pres = ANGLE_PRESETS.map(([pn, pd, t]) => `<button type="button" class="chip" data-ang="${key}:${pn}:${pd}" aria-pressed="${pn === n && pd === dd}">${t}</button>`).join('');
  return `<div class="field"><span>Angle θ = ${esc(fmtAngle(ang))}</span><div class="chips">${pres}</div>
    <div class="chips" style="font-size:13px">θ = <input type="number" step="1" data-angn="${key}" value="${n}" style="width:70px" aria-label="Angle numerator"> /
    <input type="number" step="1" min="1" data-angd="${key}" value="${dd}" style="width:70px" aria-label="Angle denominator"> × π</div></div>`;
}

function binaryPreview(value, targets) {
  const n = Math.max(1, targets.length);
  const v = Math.max(0, Math.floor(+value || 0));
  const b = bits(v, n);
  const over = b.length > n;
  const cells = b.split('').map((x, i) => {
    const pos = b.length - 1 - i;
    return `<span class="${x === '1' ? 'one' : ''}">${x}<i>${targets[pos] !== undefined ? 'q' + targets[pos] : '–'}</i></span>`;
  }).join('');
  return `<div class="bits" aria-label="Binary preview">${cells}</div>
    <div class="muted" style="font-size:12px">${over ? `<span class="err">${v} needs ${b.length} qubits.</span>` : `|${b}⟩, read right to left: the first qubit picked is the rightmost bit.`}</div>`;
}

function paramField(p, d) {
  const v = d.params[p.key];
  switch (p.type) {
    case 'int': return `<label class="field"><span>${esc(p.label)}</span><input type="number" step="1" min="${p.min ?? 0}" ${p.max ? `max="${p.max}"` : ''} data-param="${p.key}" value="${esc(v)}"></label>${p.binary ? binaryPreview(v, d.roles.targets || []) : ''}`;
    case 'angle': return angleField(p.key, v);
    case 'select': return `<label class="field"><span>${esc(p.label)}</span><select data-param="${p.key}">${p.options.map(([val, txt]) => `<option value="${val}" ${String(v) === String(val) ? 'selected' : ''}>${esc(txt)}</option>`).join('')}</select></label>`;
    case 'bool': return `<label class="chips" style="font-size:14px"><input type="checkbox" data-param="${p.key}" ${v ? 'checked' : ''}> ${esc(p.label)}</label>`;
    case 'data': return d.params.method === 'basis'
      ? `<label class="field"><span>Number to load</span><input type="number" step="1" min="0" data-param="dataText" value="${esc(d.params.dataText ?? 0)}"></label>`
      : `<label class="field"><span>Numbers between 0 and 1, one per qubit</span><input type="text" data-param="dataText" placeholder="0.2, 0.8" value="${esc(d.params.dataText ?? '')}"></label>`;
    case 'ref': {
      let list = p.unitaryOnly ? undoable() : circuit.s.nodes;
      if (p.refOps) list = list.filter(n => p.refOps.includes(n.op));
      if (!d.params[p.key] && list.length) d.params[p.key] = list[list.length - 1].id;
      return `<label class="field"><span>${esc(p.label)}</span><select data-param="${p.key}">${list.map(n => `<option value="${n.id}" ${d.params[p.key] === n.id ? 'selected' : ''}>${esc(stepName(n))}</option>`).join('') || '<option value="">No reversible earlier step to undo</option>'}</select></label>`;
    }
    case 'clbit': {
      const bitsUsed = bitsMeasuredBefore(d.wrapId);
      if ((d.params.clbit === undefined || d.params.clbit === '' || !bitsUsed.includes(+d.params.clbit)) && bitsUsed.length) d.params.clbit = bitsUsed[0];
      if (!bitsUsed.length) d.params.clbit = '';
      const src = b => { const m = circuit.s.nodes.filter(n => n.op === 'measure' && (n.classical || []).includes(b)).slice(-1)[0]; const k = m ? m.classical.indexOf(b) : -1; return m ? ` (measured from q${m.targets[k]})` : ''; };
      return `<label class="field"><span>${esc(p.label)}</span><select data-param="clbit">${bitsUsed.map(b => `<option value="${b}" ${+d.params.clbit === b ? 'selected' : ''}>c${b}${src(b)}</option>`).join('') || '<option value="">No bit is measured before this step</option>'}</select></label>`;
    }
  }
  return '';
}

export function renderEditor(d) {
  const isGate = d.op === 'gate';
  const c = isGate ? null : CONCEPTS[d.op];
  const title = isGate ? `${d.gate.label} gate` : c.name;
  const desc = isGate ? d.gate.desc : c.desc;
  const showAnalogy = !isGate && d.showAnalogy;
  let h = `<div class="editor" role="group" aria-labelledby="ed-title">
    <h3 id="ed-title">${esc(d.editing ? 'Edit: ' : 'Add: ')}${esc(title)}</h3>
    <p class="desc">${esc(desc)}</p>${showAnalogy ? `<div class="analogy">${esc(c.analogy)}</div>` : ''}`;
  if (!isGate && c.wraps && c.wraps !== 'ref') {
    const list = c.wraps === 'correct' ? conditionable() : wrappable();
    const none = c.wraps === 'correct' ? 'Add the step to apply after a Measure step first' : 'Add a step to wrap first';
    h += `<label class="field"><span>${c.wraps === 'control' ? 'Step to run only when the controls are 1' : 'Step to apply when the condition holds (only steps placed after a Measure)'}</span>
      <select data-wrap>${list.map(n => `<option value="${n.id}" ${d.wrapId === n.id ? 'selected' : ''}>${esc(stepName(n))}</option>`).join('') || `<option value="">${none}</option>`}</select></label>`;
  }
  visibleRoles(d).forEach(r => {
    const arr = d.roles[r.key] || [];
    const done = arr.length >= (r.min || 0);
    h += `<div class="field" data-role="${r.key}"><span>${done ? '✓' : '○'} ${esc(r.label)}${d.active === r.key ? ' <b>· picking</b>' : ''}</span>
      <div class="qpick" role="group" aria-label="${esc(r.label)}">${Array.from({ length: circuit.s.qubits }, (_, q) => {
        const at = arr.indexOf(q);
        const other = visibleRoles(d).some(o => o.key !== r.key && (d.roles[o.key] || []).includes(q));
        return `<button type="button" data-q="${q}" data-role-btn="${r.key}" aria-pressed="${at >= 0}" ${other ? 'disabled' : ''}>q${q}${at >= 0 && r.ordered && arr.length > 1 ? `<span class="ord">${at + 1}</span>` : ''}</button>`;
      }).join('')}</div></div>`;
  });
  if (isGate) { if (d.gate.angle) h += angleField('angle', d.params.angle); }
  else c.params.forEach(p => { if (!p.showIf || p.showIf(d.params)) h += paramField(p, d); });
  if (d.op === 'measure') {
    const t = d.roles.targets || [];
    h += `<div class="muted" style="font-size:13px">Results go to classical bits ${t.length ? t.map(i => 'c' + i).join(', ') : 'with the same numbers as the qubits'}.</div>`;
  }
  h += `<div class="err" role="alert">${d.error ? esc(d.error) : ''}</div>
    <div class="chips"><button type="button" class="btn primary" data-commit>${d.editing ? 'Save changes' : 'Add step'}</button>
    <button type="button" class="btn ghost" data-cancel>Cancel</button>${visibleRoles(d).length ? '<span class="muted" style="font-size:12px">or click the qubit labels on the canvas</span>' : ''}</div></div>`;
  return h;
}

export function bindEditor(root, d, rerender) {
  root.addEventListener('click', e => {
    const qb = e.target.closest('[data-q]');
    if (qb) {
      d.active = qb.dataset.roleBtn;
      toggleQubit(d, +qb.dataset.q);
      rerender();
      return;
    }
    const ang = e.target.closest('[data-ang]');
    if (ang) { const [k, n, dd] = ang.dataset.ang.split(':'); d.params[k] = { pi: [+n, +dd] }; rerender(); }
  });
  const onInput = e => {
    const t = e.target;
    if (t.dataset.param) {
      const k = t.dataset.param;
      if (t.type === 'checkbox') d.params[k] = t.checked;
      else if (t.type === 'number' && k !== 'dataText') d.params[k] = t.value === '' ? '' : Number(t.value);
      else d.params[k] = t.value;
      if (e.type === 'change' && ['mode', 'method', 'style', 'axis'].includes(k)) rerender();
      else if (k === 'value' && e.type === 'input') {
        const host = t.closest('.editor');
        const prev = host.querySelector('.bits');
        if (prev) { const tmp = document.createElement('div'); tmp.innerHTML = binaryPreview(d.params.value, d.roles.targets || []); prev.nextElementSibling.replaceWith(tmp.children[1]); prev.replaceWith(tmp.children[0]); }
      }
    } else if (t.dataset.wrap !== undefined) { d.wrapId = t.value; if (d.op === 'correct') rerender(); }
    else if (t.dataset.angn || t.dataset.angd) {
      const key = t.dataset.angn || t.dataset.angd;
      const cur = d.params[key]?.pi || [1, 1];
      d.params[key] = { pi: [t.dataset.angn ? Math.trunc(Number(t.value) || 0) : cur[0], t.dataset.angd ? (Math.trunc(Number(t.value) || 1) || 1) : cur[1]] };
      if (e.type === 'change') rerender();
    }
  };
  root.addEventListener('input', onInput);
  root.addEventListener('change', onInput);
}

export function buildNode(d) {
  for (const r of visibleRoles(d)) {
    const n = (d.roles[r.key] || []).length;
    if (n < (r.min || 0)) throw new Error(`${r.label}: pick ${r.min === r.max ? 'exactly ' + r.min : 'at least ' + r.min} qubit${r.min > 1 ? 's' : ''}.`);
  }
  const base = { id: d.editing || circuit.newId(), op: d.op, targets: [...(d.roles.targets || [])], controls: [...(d.roles.controls || [])],
                 ancillas: [...(d.roles.ancillas || [])], classical: [], params: {}, condition: null, body: null, ref: null, repeat: 1, metadata: { source: 'canvas' } };
  const P = d.params;
  if (d.op === 'gate') {
    base.params = { name: P.name, ...(P.angle ? { angle: P.angle } : {}) };
    return { node: base };
  }
  switch (d.op) {
    case 'set': base.params = { value: Number(P.value) }; break;
    case 'encode':
      base.params = { method: P.method };
      if (P.method === 'basis') base.params.data = Number(P.dataText ?? 0);
      else {
        base.params.scaling = P.scaling;
        base.params.data = String(P.dataText || '').split(/[\s,;]+/).filter(Boolean).map(Number);
        if (!base.params.data.length || base.params.data.some(Number.isNaN)) throw new Error('Enter numbers separated by commas, like 0.2, 0.8.');
      }
      break;
    case 'phase': base.params = { angle: P.angle }; break;
    case 'rotate': base.params = { axis: P.axis, angle: P.angle }; break;
    case 'entangle': base.params = { style: P.style }; break;
    case 'compare': base.params = { operator: P.operator, value: Number(P.value) }; break;
    case 'mark':
      if (P.mode === 'via') { base.params = { via: P.via }; base.targets = []; if (!P.via) throw new Error('Add a Compare step first.'); }
      else base.params = { value: Number(P.value) };
      break;
    case 'boost': base.repeat = Math.max(1, Math.trunc(Number(P.repeat) || 1)); break;
    case 'fourier': base.params = { inverse: !!P.inverse, swaps: P.swaps !== false }; break;
    case 'add': base.params = { value: Number(P.value), modulus: 1 << base.targets.length }; break;
    case 'measure': base.classical = base.targets.slice(); break;
    case 'uncompute': base.ref = P.ref || null; if (!base.ref) throw new Error('Pick the step to undo.'); break;
    case 'control': case 'correct': {
      const body = circuit.nodeById(d.wrapId);
      if (!body) throw new Error(`Pick the step to ${d.op === 'control' ? 'control' : 'apply'} first.`);
      base.body = JSON.parse(JSON.stringify(body));
      base.targets = [];
      if (d.op === 'correct') {
        if (P.clbit === '' || P.clbit === undefined) throw new Error('Measure a qubit first, then pick its classical bit.');
        base.condition = { clbit: Number(P.clbit), equals: Number(P.equals) };
        base.controls = [];
      }
      return { node: base, replaces: body.id };
    }
  }
  return { node: base };
}
