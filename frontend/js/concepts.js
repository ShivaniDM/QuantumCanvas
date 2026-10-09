// QuantumCanvas — Concepts mode: palette, step builder, Steps panel, "How is this implemented?" view.
// The backend compiler (POST /compile) is the single source of truth for validation, pseudocode,
// Qiskit code and gates. This file only collects steps and shows what the compiler says.
// Load order: ... execute.js → concepts-catalog.js → concepts.js → problems.js

const QCConcepts = (() => {
  const S = {
    mode: 'classic',          // 'classic' | 'concepts'
    nodes: [],                // new-model steps: Concept IR nodes + {seq}
    nextNode: 1,
    draft: null,              // the step being built
    last: null,               // last /compile response
    lastError: null,
    compiling: false,
    timer: null,
    allowed: null,            // Set of allowed ops while a problem is active
    history: [],              // every add / remove / edit / move, with timestamps (saved with each run)
  };
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const conceptOf = op => QC_CONCEPTS[op];
  const qLabel = i => state.qubits[i]?.label || `q${i}`;

  // Replace "q0" style names from the compiler with the orb labels the learner sees ("Q1").
  const labelize = txt => String(txt ?? '').replace(/\bq(\d+)\b/g, (m, i) => state.qubits[+i] ? state.qubits[+i].label : m);

  // ── mode ───────────────────────────────────────────────────────────
  function setMode(mode) {
    S.mode = mode;
    document.body.dataset.mode = mode;
    document.querySelectorAll('#mode-switch button').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
    cancelDraft();
    if (mode === 'concepts') {
      setTool('select');
      scheduleCompile();
      toast('Concepts mode: pick a concept, click the qubits it acts on, set its values, press Add step.', 'info');
    } else {
      if (S.nodes.length) toast(`${S.nodes.length} concept step${S.nodes.length > 1 ? 's are' : ' is'} hidden in Classic mode and kept.`, 'warn');
    }
    refreshButtons();
    updateStatusText();
  }
  const active = () => S.mode === 'concepts';
  const hasSteps = () => active() && (S.nodes.length > 0 || legacyOpsCount() > 0);
  const legacyOpsCount = () => state.qubits.reduce((n, q) => n + q.ops.length, 0);
  function refreshButtons() {
    const on = hasSteps();
    const pc = $('pc-btn'), ex = $('exec-btn');
    if (active() && pc) { pc.disabled = !on; }
    if (active() && ex) { ex.disabled = !on; }
  }
  function updateStatusText() {
    const el = $('sb-valid');
    if (el && active()) el.textContent = S.nodes.length + legacyOpsCount();
  }

  // ── palette ────────────────────────────────────────────────────────
  function buildPalette() {
    const host = $('concept-tiles');
    if (!host) return;
    let h = '';
    QC_FAMILIES.forEach(f => {
      h += `<div class="ct-group">${f.name}</div>`;
      f.ops.forEach(op => {
        const c = conceptOf(op);
        h += `<div class="tool ct" data-concept="${op}" title="${esc(c.name)} — ${esc(c.desc)}" onclick="QCConcepts.pick('${op}')">
          <span class="tool-sym c-${c.color}">${c.sym}</span><span class="tool-lbl">${c.short}</span></div>`;
      });
    });
    host.innerHTML = h;
  }
  function applyAllowed(setOrNull) {
    S.allowed = setOrNull;
    document.querySelectorAll('.ct').forEach(el => el.classList.toggle('ct-off', !!S.allowed && !S.allowed.has(el.dataset.concept)));
  }

  // ── draft (step builder) ───────────────────────────────────────────
  function newDraft(op) {
    const c = conceptOf(op);
    const params = {};
    c.params.forEach(p => { if (p.def !== undefined) params[p.key] = JSON.parse(JSON.stringify(p.def)); });
    const roles = {};
    c.roles.forEach(r => roles[r.key] = []);
    if (c.wraps === 'control' && !roles.controls) roles.controls = [];
    return { op, roles, params, wrapId: null, activeRole: c.roles[0]?.key || null, error: null, editing: null };
  }
  function pick(op) {
    if (!active()) return;
    if (S.allowed && !S.allowed.has(op)) { toast(`${conceptOf(op).name} isn't allowed in this problem`, 'warn'); return; }
    const c = conceptOf(op);
    setTool('select');
    document.querySelectorAll('.ct').forEach(el => el.classList.toggle('active', el.dataset.concept === op));
    S.draft = newDraft(op);
    // wrappers / refs start with the most useful default choice
    if (c.wraps === 'control' || c.wraps === 'correct') S.draft.wrapId = defaultWrapId();
    if (op === 'mark' && !compareSteps().length) { S.draft.params.mode = 'value'; }
    renderDraft();
    refreshQubitBadges();
  }
  function cancelDraft() {
    S.draft = null;
    document.querySelectorAll('.ct').forEach(el => el.classList.remove('active'));
    const d = $('concept-draft'); if (d) d.classList.remove('open');
    refreshQubitBadges();
  }
  const ownSteps = () => S.nodes;                                     // steps the learner can edit
  function wrappable() { return ownSteps().filter(n => QC_WRAPPABLE(n.op)); }
  function defaultWrapId() { const w = wrappable(); return w.length ? w[w.length - 1].id : null; }
  function compareSteps() { return ownSteps().filter(n => n.op === 'compare'); }
  function measuredBits() {
    const bits = new Set();
    [...(S.last?.document?.operations || []), ...S.nodes].forEach(n => { if (n.op === 'measure') (n.classical || []).forEach(b => bits.add(b)); });
    return [...bits].sort((a, b) => a - b);
  }

  // clicking an orb while a draft is open
  function handleQubitClick(qid) {
    if (!active() || !S.draft) return false;
    const idx = state.qubits.findIndex(q => q.id === qid);
    const roles = visibleRoles();
    // already chosen somewhere -> unselect
    for (const r of roles) {
      const arr = S.draft.roles[r.key];
      const at = arr.indexOf(idx);
      if (at >= 0) { arr.splice(at, 1); S.draft.activeRole = r.key; renderDraft(); refreshQubitBadges(); return true; }
    }
    let role = roles.find(r => r.key === S.draft.activeRole) || roles[0];
    if (!role) { toast('This concept has no qubits to pick', 'warn'); return true; }
    if (role.max && S.draft.roles[role.key].length >= role.max) {
      const next = roles.find(r => !r.max || S.draft.roles[r.key].length < r.max);
      if (!next) { toast('All qubits for this step are chosen', 'warn'); return true; }
      role = next;
    }
    S.draft.roles[role.key].push(idx);
    if (role.max && S.draft.roles[role.key].length >= role.max) {
      const nxt = roles.find(r => S.draft.roles[r.key].length < (r.max || Infinity) && r.key !== role.key);
      if (nxt) S.draft.activeRole = nxt.key;
    } else S.draft.activeRole = role.key;
    S.draft.error = null;
    renderDraft(); refreshQubitBadges();
    return true;
  }
  const visibleRoles = () => {
    const c = conceptOf(S.draft.op);
    const roles = c.roles.filter(r => !r.showIf || r.showIf(S.draft.params));
    if (c.wraps === 'control' && !roles.find(r => r.key === 'controls')) roles.unshift({ key: 'controls', label: 'Control qubits', min: 1 });
    return roles;
  };

  function refreshQubitBadges() {
    state.qubits.forEach((q, i) => {
      const el = document.getElementById(q.id);
      if (!el) return;
      el.querySelectorAll('.role-badge').forEach(b => b.remove());
      el.classList.remove('in-draft');
      if (!S.draft || !active()) return;
      for (const [role, arr] of Object.entries(S.draft.roles)) {
        const at = arr.indexOf(i);
        if (at >= 0) {
          const b = document.createElement('span');
          b.className = `role-badge rb-${role}`;
          b.textContent = ({ targets: 'T', controls: 'C', ancillas: 'A' })[role] + (arr.length > 1 ? at + 1 : '');
          el.appendChild(b); el.classList.add('in-draft');
        }
      }
    });
  }
  function decorate(/* el, qid */) { refreshQubitBadges(); }

  // ── draft form ─────────────────────────────────────────────────────
  function binaryPreview(value, targets) {
    const n = Math.max(targets.length, 1);
    const v = Number.isFinite(+value) ? Math.max(0, Math.floor(+value)) : 0;
    const bits = v.toString(2).padStart(Math.max(n, v.toString(2).length), '0');
    const cells = bits.split('').reverse().map((b, i) =>
      `<span class="bit ${b === '1' ? 'one' : ''} ${i >= n ? 'over' : ''}"><i>${targets[i] !== undefined ? esc(qLabel(targets[i])) : '–'}</i>${b}</span>`).join('');
    return `<div class="bin-prev" title="The first qubit you pick is the rightmost bit">${cells}</div>
      <div class="bin-note">${v} = ${bits.length > n ? '<b class="warn">needs ' + bits.length + ' qubits</b>' : bits} · rightmost bit = first qubit picked</div>`;
  }
  function angleWidget(key, ang) {
    const [n, d] = ang?.pi || [1, 1];
    const presets = QC_ANGLE_PRESETS.map(([pn, pd, t]) =>
      `<button type="button" class="ang-pre ${pn === n && pd === d ? 'on' : ''}" data-ang="${key}:${pn}:${pd}">${t}</button>`).join('');
    return `<div class="ang-w"><div class="ang-pres">${presets}</div>
      <div class="ang-custom">θ = <input type="number" class="in-n" data-angn="${key}" value="${n}" step="1"> / <input type="number" class="in-d" data-angd="${key}" value="${d}" step="1" min="1"> × π
      <span class="ang-rad">(${(Math.PI * n / (d || 1)).toFixed(3)} rad)</span></div></div>`;
  }
  function fieldHtml(p, D) {
    const v = D.params[p.key];
    const id = `df-${p.key}`;
    switch (p.type) {
      case 'int': {
        const prev = p.binary ? binaryPreview(v, targetsForPreview(D)) : '';
        return `<label class="df"><span>${p.label}</span><input id="${id}" data-param="${p.key}" type="number" step="1" min="${p.min ?? 0}" ${p.max ? `max="${p.max}"` : ''} value="${esc(v)}"></label>${prev}`;
      }
      case 'angle': return `<div class="df"><span>${p.label}</span>${angleWidget(p.key, v)}</div>`;
      case 'select': return `<label class="df"><span>${p.label}</span><select id="${id}" data-param="${p.key}">${p.options.map(([val, txt]) =>
        `<option value="${val}" ${String(v) === String(val) ? 'selected' : ''}>${esc(txt)}</option>`).join('')}</select></label>`;
      case 'bool': return `<label class="df chk"><input id="${id}" data-param="${p.key}" type="checkbox" ${v ? 'checked' : ''}><span>${p.label}</span></label>`;
      case 'data': {
        if (D.params.method === 'basis')
          return `<label class="df"><span>Number to load</span><input data-param="data" type="number" step="1" min="0" value="${esc(D.params.dataText ?? 0)}"></label>`;
        return `<label class="df"><span>Numbers between 0 and 1, one per qubit</span><input data-param="dataText" type="text" placeholder="0.2, 0.8" value="${esc(D.params.dataText ?? '')}"></label>`;
      }
      case 'ref': {
        const opts = refCandidates(p).map(n => `<option value="${n.id}" ${D.params[p.key] === n.id || D.refId === n.id ? 'selected' : ''}>${esc(stepTitle(n))}</option>`).join('');
        return `<label class="df"><span>${p.label}</span><select data-param="${p.key}">${opts || '<option value="">(no earlier step to pick)</option>'}</select></label>`;
      }
      case 'clbit': {
        const bits = measuredBits();
        return `<label class="df"><span>${p.label}</span><select data-param="clbit">${bits.map(b =>
          `<option value="${b}" ${+D.params.clbit === b ? 'selected' : ''}>c${b}</option>`).join('') || '<option value="">(Measure something first)</option>'}</select></label>`;
      }
    }
    return '';
  }
  const targetsForPreview = D => D.roles.targets || [];
  function refCandidates(p) {
    let list = ownSteps().filter(n => !p.refOps || p.refOps.includes(n.op));
    if (p.unitaryOnly) list = list.filter(n => QC_UNITARY(n.op));
    return list;
  }
  function stepTitle(n) {
    const t = S.last?.pseudocode?.steps?.find(s => s.id === n.id);
    return `${stepIndex(n.id)}. ${labelize(t ? t.code.split('  →')[0] : fallbackText(n))}`;
  }
  const stepIndex = id => {
    const ops = S.last?.document?.operations;
    if (ops) { const i = ops.findIndex(o => o.id === id); if (i >= 0) return i + 1; }
    return S.nodes.findIndex(n => n.id === id) + 1;
  };

  function renderDraft() {
    const host = $('concept-draft');
    const D = S.draft;
    if (!host || !D) { if (host) host.classList.remove('open'); return; }
    const c = conceptOf(D.op);
    const roles = visibleRoles();
    // sensible defaults for pickers so what the select shows is what gets used
    c.params.forEach(p => {
      if (p.showIf && !p.showIf(D.params)) return;
      if (p.type === 'ref' && !D.params[p.key]) { const cs = refCandidates(p); if (cs.length) D.params[p.key] = cs[cs.length - 1].id; }
      if (p.type === 'clbit' && (D.params.clbit === undefined || D.params.clbit === '')) { const b = measuredBits(); if (b.length) D.params.clbit = b[0]; }
    });
    let h = `<div class="cd-head"><span class="cd-sym c-${c.color}">${c.sym}</span><b>${c.name}</b><span class="cd-desc">${esc(c.desc)}</span>
      <button class="cd-x" onclick="QCConcepts.cancelDraft()" aria-label="Cancel">×</button></div><div class="cd-body">`;
    // wrap / ref pickers
    if (c.wraps === 'control' || c.wraps === 'correct') {
      const w = wrappable();
      h += `<label class="df"><span>${c.wraps === 'control' ? 'Run this step only when the control is 1' : 'Apply this step when the condition holds'}</span>
        <select data-wrap>${w.map(n => `<option value="${n.id}" ${D.wrapId === n.id ? 'selected' : ''}>${esc(stepTitle(n))}</option>`).join('') ||
        '<option value="">(add a step to wrap first)</option>'}</select></label>`;
    }
    // qubit roles
    roles.forEach(r => {
      const arr = D.roles[r.key] || [];
      const ok = arr.length >= (r.min || 0);
      h += `<div class="cd-role ${D.activeRole === r.key ? 'on' : ''} ${ok ? 'ok' : ''}" data-role="${r.key}">
        <span class="cd-role-l">${ok ? '✓' : '○'} ${r.label}</span>
        <span class="cd-chips">${arr.map(i => `<span class="chip">${esc(qLabel(i))}</span>`).join('') || `<em>${D.activeRole === r.key ? 'click qubits on the canvas' : 'click here, then pick qubits'}</em>`}</span></div>`;
    });
    c.params.forEach(p => {
      if (p.showIf && !p.showIf(D.params)) return;
      h += fieldHtml(p, D);
    });
    if (D.op === 'measure') {
      const t = D.roles.targets || [];
      h += `<div class="cd-note">Answers go into classical bits ${t.length ? t.map(i => 'c' + i).join(', ') : '(one per qubit, same number as the qubit)'}.</div>`;
    }
    if (D.op === 'add') {
      const n = (D.roles.targets || []).length;
      h += `<div class="cd-note">Wraps around at 2<sup>${n || 'n'}</sup>${n ? ' = ' + (1 << n) : ''}.</div>`;
    }
    h += `<div class="cd-err" id="cd-err">${D.error ? esc(D.error) : ''}</div>
      <div class="cd-actions"><button class="cd-add" onclick="QCConcepts.commitDraft()">Add step</button>
      <button class="cd-cancel" onclick="QCConcepts.cancelDraft()">Cancel</button></div></div>`;
    host.innerHTML = h;
    host.classList.add('open');
  }

  function onDraftInput(e) {
    const D = S.draft; if (!D) return;
    const t = e.target;
    if (t.dataset.param) {
      const k = t.dataset.param;
      if (t.type === 'checkbox') D.params[k] = t.checked;
      else if (t.type === 'number') D.params[k] = t.value === '' ? '' : Number(t.value);
      else D.params[k] = t.value;
      if (k === 'dataText') D.params.dataText = t.value;
      if (k === 'data') D.params.dataText = t.value;
      // fields that change the form layout
      if (['mode', 'method'].includes(k) && e.type === 'change') { renderDraft(); refreshQubitBadges(); }
      else if (k === 'value' && e.type === 'input') updatePreview();
      if (k === 'ref') D.refId = t.value;
    } else if (t.dataset.wrap !== undefined) { D.wrapId = t.value; }
    else if (t.dataset.angn || t.dataset.angd) {
      const key = t.dataset.angn || t.dataset.angd;
      const cur = D.params[key]?.pi || [1, 1];
      D.params[key] = { pi: [t.dataset.angn ? Math.trunc(Number(t.value) || 0) : cur[0], t.dataset.angd ? Math.trunc(Number(t.value) || 1) || 1 : cur[1]] };
      if (e.type === 'change') { renderDraft(); refreshQubitBadges(); }
    }
  }
  function updatePreview() {
    const D = S.draft, host = $('concept-draft');
    const prev = host.querySelector('.bin-prev'), note = host.querySelector('.bin-note');
    if (!prev || !note) return;
    const tmp = document.createElement('div');
    tmp.innerHTML = binaryPreview(D.params.value, targetsForPreview(D));
    prev.replaceWith(tmp.querySelector('.bin-prev')); note.replaceWith(tmp.querySelector('.bin-note'));
  }
  function onDraftClick(e) {
    const D = S.draft; if (!D) return;
    const role = e.target.closest('[data-role]');
    if (role) { D.activeRole = role.dataset.role; renderDraft(); refreshQubitBadges(); return; }
    const pre = e.target.closest('[data-ang]');
    if (pre) { const [k, n, d] = pre.dataset.ang.split(':'); D.params[k] = { pi: [+n, +d] }; renderDraft(); refreshQubitBadges(); }
  }

  // ── build the node from the draft ──────────────────────────────────
  function nextId() { return `N${S.nextNode++}`; }
  function buildNode(D) {
    const c = conceptOf(D.op);
    const node = { id: null, op: D.op, targets: [...(D.roles.targets || [])], controls: [...(D.roles.controls || [])],
                   ancillas: [...(D.roles.ancillas || [])], classical: [], params: {}, condition: null, body: null, ref: null,
                   repeat: 1, metadata: { user_created: true } };
    const P = D.params;
    switch (D.op) {
      case 'set': node.params = { value: Number(P.value) }; break;
      case 'encode':
        node.params = { method: P.method };
        if (P.method === 'basis') node.params.data = Number(P.dataText ?? P.data ?? 0);
        else {
          node.params.scaling = P.scaling;
          node.params.data = String(P.dataText || '').split(/[\s,;]+/).filter(Boolean).map(Number);
          if (node.params.data.some(Number.isNaN)) throw new Error('Data must be numbers separated by commas, like 0.2, 0.8.');
        }
        break;
      case 'phase': node.params = { angle: P.angle }; break;
      case 'rotate': node.params = { axis: P.axis, angle: P.angle }; break;
      case 'entangle': node.params = { style: P.style }; break;
      case 'compare': node.params = { operator: P.operator, value: Number(P.value) }; break;
      case 'mark':
        if (P.mode === 'via') { node.params = { via: P.via || D.refId || compareSteps().slice(-1)[0]?.id }; node.targets = []; }
        else node.params = { value: Number(P.value) };
        break;
      case 'boost': node.repeat = Math.max(1, Math.trunc(Number(P.repeat) || 1)); break;
      case 'fourier': node.params = { inverse: !!P.inverse, swaps: P.swaps !== false }; break;
      case 'add': node.params = { value: Number(P.value), modulus: 1 << node.targets.length }; break;
      case 'measure': node.classical = node.targets.map(t => t); break;
      case 'uncompute': node.ref = P.ref || D.refId || null; break;
      case 'control': case 'correct': {
        const idx = S.nodes.findIndex(n => n.id === D.wrapId);
        if (idx < 0) throw new Error(`Pick the step to ${D.op === 'control' ? 'control' : 'correct'} first.`);
        const body = S.nodes[idx];
        node.body = stripSeq(body);
        node.targets = [];
        if (D.op === 'correct') {
          if (P.clbit === '' || P.clbit === undefined) throw new Error('Measure a qubit first, then pick its classical bit.');
          node.condition = { clbit: Number(P.clbit), equals: Number(P.equals) };
          node.controls = [];
        }
        node._replaces = body.id; node.seq = body.seq;
        break;
      }
    }
    if (!node.seq && node.seq !== 0) node.seq = state.nextSeq++;
    node.id = nextId();                 // allocated last: a rejected or failed draft never burns an id
    return node;
  }
  const stripSeq = n => { const { seq, _replaces, ...rest } = n; return rest; };

  async function commitDraft() {
    const D = S.draft; if (!D) return;
    const c = conceptOf(D.op);
    // quick local checks that don't need the server
    for (const r of visibleRoles()) {
      const n = (D.roles[r.key] || []).length;
      if (n < (r.min || 0)) return setDraftError(`${r.label}: pick ${r.min === r.max ? 'exactly ' + r.min : 'at least ' + r.min} qubit${r.min > 1 ? 's' : ''} on the canvas.`);
    }
    let node;
    try { node = buildNode(D); } catch (e) { return setDraftError(e.message); }
    const replaced = node._replaces ? S.nodes.find(n => n.id === node._replaces) : null;
    delete node._replaces;
    const before = S.nodes.slice();
    if (replaced) S.nodes = S.nodes.map(n => n.id === replaced.id ? node : n); else S.nodes = [...S.nodes, node];
    // ask the compiler whether the whole circuit is still valid
    const prevKeys = new Set((S.last?.errors || []).map(e => e.code + '|' + e.op_id));
    const res = await compileNow(true);
    if (res && res.errors) {
      const fresh = res.errors.filter(e => !prevKeys.has(e.code + '|' + e.op_id));
      if (fresh.length) {
        S.nodes = before; S.nextNode--; scheduleCompile();
        return setDraftError(labelize(fresh[0].message) + (fresh[0].hint ? ' ' + fresh[0].hint : ''));
      }
    }
    if (!res) toast('Could not reach the server to check this step. It was added, but is not checked yet.', 'warn');
    else if (res.warnings?.length) {
      const w = res.warnings.find(w => w.op_id === node.id || w.op_id === node.body?.id);
      if (w) toast(labelize(w.message), 'warn');
    }
    logEdit(replaced ? 'wrap' : 'add', node, replaced ? { wraps: replaced.id } : { targets: node.targets });
    cancelDraft();
    renderSteps(); refreshButtons(); updateStatusText();
    toast(`${c.name} added`, 'valid');
  }
  function setDraftError(msg) {
    S.draft.error = msg;
    const el = $('cd-err'); if (el) el.textContent = msg;
  }

  // ── steps list ─────────────────────────────────────────────────────
  function fallbackText(n) {
    const c = conceptOf(n.op);
    const t = (n.targets || []).map(qLabel).join(', ');
    return `${c ? c.name.toUpperCase() : n.op.toUpperCase()}${t ? ' [' + t + ']' : ''}`;
  }
  const idsInside = n => [n.id, ...(n.body ? idsInside(n.body) : [])];
  const usersOf = id => S.nodes.filter(n => !idsInside(n).includes(id) && (n.ref === id || n.params?.via === id));
  function removeStep(id) {
    const gone = S.nodes.find(n => n.id === id);
    const dependants = gone ? idsInside(gone).flatMap(usersOf) : [];
    if (dependants.length) { toast(`Remove “${fallbackText(dependants[0])}” first: it uses this step.`, 'warn'); return; }
    logEdit('remove', gone, { targets: gone?.targets });
    S.nodes = S.nodes.filter(n => n.id !== id);
    if (S.draft) cancelDraft();
    scheduleCompile(); refreshButtons(); updateStatusText(); renderSteps();
  }
  function moveStep(id, dir) {
    const i = S.nodes.findIndex(n => n.id === id), j = i + dir;
    if (i < 0 || j < 0 || j >= S.nodes.length) return;
    const a = S.nodes[i], b = S.nodes[j];
    [a.seq, b.seq] = [b.seq, a.seq];
    logEdit('move', a, { direction: dir > 0 ? 'down' : 'up' });
    S.nodes.sort((x, y) => x.seq - y.seq);
    scheduleCompile(); renderSteps();
  }
  function wrapStep(id, kind) {
    const users = usersOf(id);
    if (users.length) { toast(`“${fallbackText(users[0])}” refers to this step, so it can't be wrapped. Remove that step first.`, 'warn'); return; }
    pick(kind); if (S.draft) { S.draft.wrapId = id; renderDraft(); } }

  function renderSteps() {
    const host = $('steps-list'); if (!host) return;
    const res = S.last;
    const doc = res?.document?.operations || null;
    const rows = doc ? doc : S.nodes;
    const errs = res?.errors || [], warns = res?.warnings || [];
    const issueFor = id => errs.find(e => e.op_id === id) || null;
    const warnsFor = id => warns.filter(w => w.op_id === id);
    if (!rows.length) {
      host.innerHTML = `<div class="steps-empty">No steps yet.<br>Pick a concept on the left, then click the qubits it acts on.</div>`;
      renderIssues(); return;
    }
    host.innerHTML = rows.map((n, i) => {
      const own = S.nodes.find(x => x.id === n.id);
      const legacy = !own;
      const c = conceptOf(n.op) || { sym: '?', color: 'gray', name: n.op };
      const ps = res?.pseudocode?.steps?.find(s => s.id === n.id);
      const text = labelize(ps ? ps.code : fallbackText(n));
      const e = issueFor(n.id), ws = warnsFor(n.id), w = ws[0];
      const effect = ps?.effect ? labelize(ps.effect) : '';
      const lied = ps && ps.claim_ok === false;
      const canWrap = own && QC_WRAPPABLE(n.op);
      const ownIdx = S.nodes.findIndex(x => x.id === n.id);
      return `<div class="step ${e ? 'bad' : ''} ${w || lied ? 'warn' : ''}" data-step="${n.id}">
        <span class="step-n">${i + 1}</span><span class="step-sym c-${c.color}">${c.sym}</span>
        <div class="step-main"><div class="step-text">${esc(text)}</div>
          ${legacy ? '<div class="step-tag">from a Classic tool</div>' : ''}
          ${effect ? `<div class="step-effect ${lied ? 'lied' : ''}">${esc(effect)}</div>` : ''}
          ${e ? `<div class="step-issue">${esc(labelize(e.message))}</div>` : ''}${!e ? ws.map(x => `<div class="step-warn" title="${esc(x.code)}">${esc(labelize(x.message))}</div>`).join('') : ''}</div>
        <div class="step-btns">
          <button title="How is this implemented?" onclick="QCConcepts.how('${n.id}')">ⓘ</button>
          ${own ? `<button title="Move up" ${ownIdx === 0 ? 'disabled' : ''} onclick="QCConcepts.move('${n.id}',-1)">↑</button>
          <button title="Move down" ${ownIdx === S.nodes.length - 1 ? 'disabled' : ''} onclick="QCConcepts.move('${n.id}',1)">↓</button>` : ''}
          ${canWrap ? `<button title="Run only when qubits are 1 (Control)" onclick="QCConcepts.wrap('${n.id}','control')">●</button>
          <button title="Run depending on a measured bit (Correct)" onclick="QCConcepts.wrap('${n.id}','correct')">↯</button>` : ''}
          ${own ? `<button title="Remove step" class="del" onclick="QCConcepts.remove('${n.id}')">✕</button>` : ''}
        </div></div>`;
    }).join('');
    renderIssues();
  }
  function renderIssues() {
    const host = $('steps-issues'); if (!host) return;
    const res = S.last;
    if (S.lastError) { host.innerHTML = `<div class="iss iss-off">Can't reach the compiler (${esc(S.lastError)}). Start the backend to check and run concept circuits.</div>`; return; }
    if (!res) { host.innerHTML = ''; return; }
    const orphan = res.errors.filter(e => !e.op_id);
    const looseWarns = res.warnings.filter(w => !w.op_id);
    host.innerHTML = orphan.map(e => `<div class="iss iss-err">${esc(labelize(e.message))}</div>`).join('') +
      looseWarns.map(w => `<div class="iss iss-off" title="${esc(w.code)}">${w.code === 'W_BACKEND_UNSUPPORTED' ? 'IonQ: ' : ''}${esc(labelize(w.message))}</div>`).join('') +
      (res.ok ? `<div class="iss iss-ok">✓ ${res.gates.length} gates · ${res.warnings.length ? res.warnings.length + ' warning' + (res.warnings.length > 1 ? 's' : '') : 'no problems'}</div>` : '');
  }

  // ── compile (debounced) ────────────────────────────────────────────
  function payload() {
    return { legacy_ir: extractCanvasIR(state), nodes: S.nodes.map(n => ({ ...n })), classical_bits: 0, backend: 'ionq' };
  }
  function scheduleCompile() {
    clearTimeout(S.timer);
    if (!active()) return;
    S.timer = setTimeout(() => compileNow(), 220);
  }
  async function compileNow(quiet) {
    if (!state.qubits.length) { S.last = null; renderSteps(); return null; }
    try {
      const resp = await fetch(`${BACKEND_URL}/compile`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload()) });
      if (!resp.ok) throw new Error(`${resp.status}`);
      S.last = await resp.json(); S.lastError = null;
    } catch (e) { S.lastError = e.message || 'offline'; S.last = null; }
    renderSteps();
    return S.last;
  }

  // ── pseudocode / execute integration (reuses the existing panels) ──
  function irStub(res) {
    const labels = state.qubits.map(q => ({ id: q.id, label: q.label }));
    const errs = (res?.errors || []).map(e => ({ rule: e.code, qid: null, msg: labelize(e.message), plain: labelize(e.message), fix: e.hint || '' }));
    const warns = (res?.warnings || []).map(w => ({ rule: w.code, qid: null, msg: labelize(w.message), plain: labelize(w.message), fix: w.hint || '' }));
    const log = (res?.document?.operations || []).map(o => ({ op: o.op, qubit: state.qubits[(o.targets || [])[0]]?.id || '', correlated: false }));
    const n = state.qubits.length;
    return { n, N: Math.pow(2, n), optimal: 1, qubits: labels, edges: [], globalLog: log, _concept: res,
             validation: { ok: !!res?.ok, errs, warns, pattern: 'concepts' } };
  }
  function docForPanel(res) {
    const d = res.pseudocode;
    return { ...d, title: 'Concept circuit', meta: `${state.qubits.length} qubits · ${res.gates.length} gates · ${res.document.operations.length} steps`,
      steps: d.steps.map(s => ({ ...s, code: labelize(s.code), plain: labelize(s.plain), targets: s.targets.map(labelize) })),
      summary: state.qubits.map((q, i) => ({ label: q.label, ops: res.document.operations.filter(o => (o.targets || []).includes(i) || (o.controls || []).includes(i))
          .map(o => o.op[0].toUpperCase() + o.op.slice(1)).join(' → ') || '—', state: q.state, result: q.result })),
      patternNote: 'Compiled from concepts. Every gate below traces back to the step that produced it (ⓘ in the Steps list).' };
  }
  async function openPseudocode() {
    const res = await compileNow();
    if (!res) { toast('Start the backend to compile concept circuits.', 'error'); return; }
    const ir = irStub(res);
    _renderPC(ir, res.ok ? docForPanel(res) : null);
    document.getElementById('pc-overlay').classList.add('open');
  }
  // Naming: people see the canvas labels (Q1, Q2 …) everywhere. Qiskit code needs 0-based indices, so only
  // the COMMENTS are relabelled, and a legend line says which is which.
  function relabelComments(line) {
    const i = line.indexOf('#');
    return i < 0 ? line : line.slice(0, i) + labelize(line.slice(i));
  }
  function qiskitForPanel(res) {
    const legend = '# Qubits: ' + state.qubits.map((q, i) => `${q.label} = qubit ${i}`).join(', ');
    const lines = res.qiskit_lines.map(relabelComments);
    const at = lines.findIndex(l => l.startsWith('qc = '));
    lines.splice(Math.max(at, 0), 0, legend);
    return { lines, remarks: lines.map(() => '') };
  }
  async function openExecute() {
    const res = await compileNow();
    if (!res) { toast('Start the backend to run concept circuits.', 'error'); return false; }
    if (!res.ok) { toast(labelize(res.errors[0].message), 'error'); return true; }
    const ir = irStub(res), doc = docForPanel(res);
    document.getElementById('exec-panel')._concept = res.document;
    _renderExecPanel(ir, doc, qiskitForPanel(res));
    document.getElementById('exec-overlay').classList.add('open');
    _checkAvailability().then(_applyAvailability);
    return true;
  }
  const conceptDoc = () => (document.getElementById('exec-panel')._concept) || null;

  // ── how is this implemented? ───────────────────────────────────────
  const gateText = g => {
    const nm = g.name + (g.params?.length ? `(${g.params.map(fmtRad).join(', ')})` : '');
    const ctl = g.controls?.length ? ` controls ${g.controls.map(i => qLabel(i)).join(',')} →` : '';
    return `${nm}${ctl} ${g.targets.map(i => qLabel(i)).join(', ')}${g.cond ? `  if c${g.cond.clbit}=${g.cond.equals}` : ''}${g.clbits?.length ? ` → c${g.clbits[0]}` : ''}`;
  };
  const fmtRad = x => {
    const f = x / Math.PI;
    for (const d of [1, 2, 3, 4, 5, 6, 8, 16, 32, 64]) { const n = Math.round(f * d); if (Math.abs(n / d - f) < 1e-9) return n === 0 ? '0' : `${n === 1 ? '' : n === -1 ? '-' : n}π${d === 1 ? '' : '/' + d}`; }
    return x.toFixed(3);
  };
  async function how(id) {
    const res = await compileNow();
    if (!res || !res.ok) { toast(res ? 'Fix the errors in the Steps list first.' : 'Start the backend to see the implementation.', 'warn'); return; }
    const range = res.node_ranges[id] || [];
    const set = new Set(range);
    const ps = res.pseudocode.steps.find(s => s.id === id);
    const chainName = ch => ch.slice().reverse().map(x => { const o = res.document.operations.find(o => o.id === x); return o ? o.op : x; }).join(' › ');
    const gates = range.map(i => `<li><code>${esc(gateText(res.gates[i]))}</code><em>${esc(chainName(res.trace[i]))}</em></li>`).join('');
    const code = res.qiskit_lines.map((ln, i) => {
      const hit = res.line_gates[i].some(g => set.has(g));
      return `<span class="cl ${hit ? 'hit' : ''}">${esc(ln) || ' '}</span>`;
    }).join('\n');
    const ionq = res.ionq ? res.ionq.circuit.map((g, k) => set.has(res.ionq_src[k]) ? `<li><code>${esc(JSON.stringify(g))}</code></li>` : '').join('') : '';
    const wu = res.warnings.find(w => w.code === 'W_BACKEND_UNSUPPORTED');
    const html = `<div class="how-box"><div class="how-head"><div><div class="how-label">How is this implemented?</div>
      <div class="how-title">${esc(labelize(ps ? ps.code : id))}</div></div><button class="cd-x" onclick="QCConcepts.closeHow()">×</button></div>
      <div class="how-cols">
        <div class="how-step"><h4>1 · Concept</h4><p>${esc(labelize(ps?.plain || ''))}</p><p class="how-q">${esc(labelize(ps?.qnote || ''))}</p></div>
        <div class="how-step"><h4>2 · Gates (${range.length})</h4><ol class="how-gates">${gates || '<li><em>no gates (identity)</em></li>'}</ol></div>
        <div class="how-step"><h4>3 · Qiskit code</h4><pre class="how-code">${code}</pre></div>
        <div class="how-step"><h4>4 · IonQ hardware gates</h4>${res.ionq ? `<ol class="how-gates">${ionq || '<li><em>nothing (measurements happen at the end)</em></li>'}</ol>` :
          `<p class="how-warn">${esc(wu ? labelize(wu.message) : 'Not available for this circuit.')}</p>`}</div>
      </div></div>`;
    const ov = $('how-overlay'); ov.innerHTML = html; ov.classList.add('open');
  }
  function closeHow() { $('how-overlay').classList.remove('open'); }

  // ── hooks used by state.js / ui.js ─────────────────────────────────
  // Edit history: so a gap in the numbering (a deleted step) is explained in the run record, not a mystery.
  function logEdit(type, node, extra) {
    S.history.push({ t: new Date().toISOString(), type, id: node?.id ?? null, op: node?.op ?? null, ...(extra || {}) });
    if (S.history.length > 2000) S.history.shift();
  }

  // Everything needed to reopen a run: the concept steps themselves, not just the compiled result.
  function snapshot() {
    return { nodes: S.nodes.map(n => JSON.parse(JSON.stringify(n))), nextNode: S.nextNode, nextSeq: state.nextSeq,
             legacy_ir: extractCanvasIR(state), classical_bits: 0, history: S.history.slice(),
             qubits: state.qubits.map(q => ({ id: q.id, label: q.label, x: Math.round(q.x), y: Math.round(q.y) })) };
  }
  async function loadRun(run) {
    // accepts both formats: run record v2 (input.canvas_json, already an object) and the browser's v1 file
    let canvas = run.schema === 'quantumcanvas.run/v2' ? run.input?.canvas_json : run.canvas_json;
    if (typeof canvas === 'string') canvas = JSON.parse(canvas);
    const c = canvas?.concepts;
    if (!c || !Array.isArray(c.nodes)) throw new Error('This run file has no concept steps saved with it (it was saved before reopening was supported).');
    clearCanvas(); setMode('concepts');
    const wrap = document.getElementById('canvas-wrap').getBoundingClientRect();
    (c.qubits || []).forEach((q, i) => placeQubit(q.x ?? wrap.width / 2 + i * 120, q.y ?? wrap.height / 2));
    S.nodes = c.nodes; S.nextNode = c.nextNode || (c.nodes.length + 1); state.nextSeq = c.nextSeq ?? c.nodes.length;
    S.history = Array.isArray(c.history) ? c.history.slice() : [];
    logEdit('open_run', null, { run_id: run.run_id || null });
    await compileNow(); refreshButtons(); updateStatusText();
    toast(`Opened run ${run.run_id || ''} with ${S.nodes.length} steps`, 'valid');
  }
  function openRunFile() { $('run-file-input').click(); }
  async function onRunFile(e) {
    const f = e.target.files[0]; e.target.value = ''; if (!f) return;
    try { await loadRun(JSON.parse(await f.text())); } catch (err) { toast(err.message, 'error'); }
  }

  function reset() { if (S.nodes.length) logEdit('clear', null, { removed: S.nodes.map(n => n.id) }); S.nodes = []; S.nextNode = 1; S.last = null; cancelDraft(); renderSteps(); refreshButtons(); }
  const blocksQubitDelete = () => S.nodes.length > 0 || (active() && legacyOpsCount() > 0);
  function onCanvasChange() { if (active()) { scheduleCompile(); refreshButtons(); updateStatusText(); } }

  function init() {
    buildPalette();
    const rf = $('run-file-input'); if (rf) rf.addEventListener('change', onRunFile);
    const d = $('concept-draft');
    if (d) { d.addEventListener('input', onDraftInput); d.addEventListener('change', onDraftInput); d.addEventListener('click', onDraftClick); }
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && S.draft) cancelDraft(); });
    renderSteps();
  }
  document.addEventListener('DOMContentLoaded', init);

  return { snapshot, loadRun, openRunFile, onRunFile, docFor: docForPanel, qiskitFor: qiskitForPanel, setMode, active, hasSteps, pick, cancelDraft, commitDraft, handleQubitClick, decorate, remove: removeStep, move: moveStep,
           wrap: wrapStep, how, closeHow, openPseudocode, openExecute, conceptDoc, reset, blocksQubitDelete, onCanvasChange,
           scheduleCompile, compileNow, applyAllowed, labelize, state: S, refreshButtons };
})();
window.QCConcepts = QCConcepts;
