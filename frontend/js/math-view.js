// QuantumCanvas — Math tab + per-step "?" explanations.
// Everything numeric comes from the backend (POST /math, POST /explain-step): exact kets, gate matrices and
// U·state calculations are computed, never written by a model. The optional AI paragraph is checked against them.
// Load order: ... qiskit-panel.js → execute.js → concepts.js → math-view.js

const QCMath = (() => {
  const h = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const C = { doc: null, math: null, key: null, tab: 'pc' };
  const labels = () => (typeof state !== 'undefined' ? state.qubits.map(q => q.label) : []);
  const pct = p => `${(100 * p).toFixed(p > 0 && p < 0.001 ? 2 : p < 0.1 ? 1 : 0).replace(/\.0$/, '')}%`;
  const fix = t => (window.QCConcepts ? QCConcepts.labelize(t) : t);

  async function post(path, body) {
    const r = await fetch(`${BACKEND_URL}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!r.ok) {
      let d = ''; try { d = (await r.json()).detail || ''; } catch (e) { /* not json */ }
      throw new Error(d || `Backend returned ${r.status}`);
    }
    return r.json();
  }

  // ── pieces ─────────────────────────────────────────────────────────
  function matrix(rows, cls = '') {
    return `<table class="mt-mat ${cls}"><tbody>${rows.map(r => `<tr>${r.map(c => `<td class="${c === '0' ? 'z' : ''}">${h(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  }
  function column(vals, basis) {
    return `<table class="mt-mat mt-col"><tbody>${vals.map((v, i) => `<tr><td class="${v === '0' ? 'z' : ''}">${h(v)}</td><td class="mt-lbl">|${h(basis[i])}⟩</td></tr>`).join('')}</tbody></table>`;
  }
  function stateBlock(view, name) {
    if (!view) return '';
    const many = view.branches.length > 1;
    const rows = view.branches.map(b => `<div class="mt-branch">${many ? `<span class="mt-bp">${pct(b.prob)}${b.bits ? ` · c=${h(b.bits)}` : ''}</span>` : ''}
      <span class="mt-ket">${h(b.ket)}</span>${b.truncated ? ' <i>(more terms not shown)</i>' : ''}
      <div class="mt-bars">${b.terms.map(t => `<div class="mt-bar" title="|${h(t.basis)}⟩: ${pct(t.prob)}"><span class="mt-bar-l">|${h(t.basis)}⟩</span><span class="mt-bar-t"><span style="width:${Math.max(1, 100 * t.prob * (many ? b.prob : 1))}%"></span></span><span class="mt-bar-v">${pct(t.prob)}</span></div>`).join('')}</div></div>`).join('');
    return `<div class="mt-state"><div class="mt-sname">${name}</div>${rows}${view.truncated ? `<i>${view.n_branches} outcomes in all; showing the likeliest ${view.branches.length}</i>` : ''}</div>`;
  }

  function stepBody(s, m) {
    let body = '';
    if (s.unavailable) body = `<div class="mt-note">${h(s.unavailable)}</div>`;
    else {
      if (s.equation) body += `<div class="mt-eq">${h(s.equation)}</div>`;
      if (s.matrix) {
        body += `<div class="mt-sec">Gate matrix <span class="mt-sub">acts on ${h(s.local_qubits.join(', '))}</span></div>
          <div class="mt-row">${matrix(s.matrix)}</div>
          <div class="mt-sec">What it does to each basis state</div>
          <div class="mt-actions">${s.action.map(a => `<div><code>U|${h(a.from)}⟩ = ${h(a.to)}</code></div>`).join('')}</div>`;
      } else if (s.too_large) body += `<div class="mt-note">This step acts on ${s.too_large.qubits} qubits together (a ${s.too_large.dim}×${s.too_large.dim} matrix), too big to draw. The state change below is still exact.</div>`;
      else if (s.identity) body += `<div class="mt-note">This step does nothing to the state (identity).</div>`;
      if (s.measure) {
        body += `<div class="mt-sec">Chance of each outcome, from ⟨ψ|P|ψ⟩</div><div class="mt-actions">${s.measure.map(q => `<div><code>${h(q.qubit)}: P(0) = ${pct(q.p0)}, P(1) = ${pct(q.p1)}</code></div>`).join('')}</div>`;
      }
      body += `<div class="mt-sec">State</div><div class="mt-states">${stateBlock(s.before, '|ψ⟩ before')}<span class="mt-arrow">→</span>${stateBlock(s.after, '|ψ⟩ after')}</div>`;
      if (s.product) {
        body += `<div class="mt-sec">The calculation: U · |ψ⟩ = |ψ′⟩ <span class="mt-sub">(whole circuit, ${m.n_qubits} qubit${m.n_qubits > 1 ? 's' : ''})</span></div>
          <div class="mt-prod">${matrix(s.product.U)}<span class="mt-op">·</span>${column(s.product.before, s.product.basis)}<span class="mt-op">=</span>${column(s.product.after, s.product.basis)}</div>`;
      }
    }
    return body;
  }
  function stepCard(s, i, m) {
    const title = `${s.op.toUpperCase()} [${s.target_names.join(', ')}]`;
    const body = stepBody(s, m);
    return `<div class="mt-card" data-step="${h(s.id)}">
      <div class="mt-head"><span class="mt-n">Step ${i + 1}</span><b>${h(fix(title))}</b>
        <button class="pc-ask" title="Explain this step in words, using the exact maths" onclick="QCMath.ask('${h(s.id)}', this)">?</button></div>
      ${body}<div class="pc-ask-box"></div></div>`;
  }

  function render(m) {
    if (m.skipped) return `<div class="mt-note">${h(m.skipped)}</div>`;
    const init = m.initial?.branches?.[0];
    return `<div class="mt-intro">Exact quantum maths for each step, computed from your circuit (not guessed). ${h(m.order_note)}
      <div class="mt-start"><span class="mt-sname">Start</span> <span class="mt-ket">${h(init?.ket || '')}</span></div></div>
      ${m.steps.map((s, i) => stepCard(s, i, m)).join('')}`;
  }

  // ── Math tab ───────────────────────────────────────────────────────
  async function loadMath() {
    const box = document.getElementById('pc-math'); if (!box || !C.doc) return;
    const key = JSON.stringify([C.doc, labels()]);
    if (C.key === key && C.math) { box.innerHTML = render(C.math); return; }
    box.innerHTML = '<div class="mt-note">Working out the maths…</div>';
    try {
      C.math = await post('/math', { document: C.doc, labels: labels() }); C.key = key;
      box.innerHTML = render(C.math);
    } catch (e) { box.innerHTML = `<div class="mt-note err">Could not work out the maths: ${h(e.message)}</div>`; }
  }
  const SHOW = '.pc-timeline,.pc-violations,.pc-steps,.pc-summary,.pc-pattern';
  function tab(which) {
    C.tab = which;
    const p = document.getElementById('pc-panel'); if (!p) return;
    p.querySelectorAll('.pc-tabs button').forEach(b => b.classList.toggle('on', b.dataset.t === which));
    p.querySelectorAll(SHOW).forEach(el => { el.style.display = which === 'pc' ? '' : 'none'; });
    const mb = document.getElementById('pc-math'); if (mb) mb.style.display = which === 'math' ? 'block' : 'none';
    if (which === 'math') loadMath();
  }
  // Called at the end of every pseudocode render (so the tabs survive going to Qiskit and back).
  function installTabs(res) {
    const p = document.getElementById('pc-panel'); if (!p) return;
    C.doc = res?.ok ? res.document : null; C.tab = 'pc';
    const head = p.querySelector('.pc-header'); if (!head) return;
    head.insertAdjacentHTML('afterend', `<div class="pc-tabs"><button class="on" data-t="pc" onclick="QCMath.tab('pc')">Pseudocode</button>
      <button data-t="math" onclick="QCMath.tab('math')" ${C.doc ? '' : 'disabled title="Fix the errors first"'}>∑ Math</button></div>`);
    const foot = p.querySelector('.pc-footer');
    const holder = `<div id="pc-math" class="pc-math" style="display:none"></div>`;
    if (foot) foot.insertAdjacentHTML('beforebegin', holder); else p.insertAdjacentHTML('beforeend', holder);
  }

  // ── "?" : explain one step ─────────────────────────────────────────
  async function ask(id, btn) {
    const host = btn.closest('.pc-step-body, .mt-card'); const box = host?.querySelector('.pc-ask-box'); if (!box) return;
    if (box.dataset.open === '1') { box.dataset.open = '0'; box.innerHTML = ''; return; }
    if (!C.doc) { box.innerHTML = '<div class="ex-note err">Fix the errors in the Steps list first.</div>'; return; }
    box.dataset.open = '1';
    box.innerHTML = '<div class="ex-note">Working out the maths and checking the explanation…</div>';
    try {
      const r = await post('/explain-step', { document: C.doc, step_id: id, labels: labels(), use_llm: true });
      box.innerHTML = renderAsk(r, !host.classList.contains('mt-card'));
    } catch (e) { box.innerHTML = `<div class="ex-note err">Could not explain this step: ${h(e.message)}</div>`; box.dataset.open = '0'; }
  }
  function renderAsk(r, withMath) {
    const L = r.llm || {}, T = r.template || {};
    let out = '';
    if (L.status === 'ok' && L.text) {
      out += `<div class="ex-ai"><span class="ex-badge">${h(L.label)}</span>${L.cache_hit ? ' <i>(cached)</i>' : ''}<p>${h(fix(L.text))}</p>
        <div class="ex-fine">Every number and direction in this text was checked against the exact simulation.</div></div>`;
      out += `<details class="ex-tmpl"><summary>Verified explanation (no AI)</summary><p>${h(fix(T.text || ''))}</p></details>`;
    } else {
      out += `<div class="ex-tmpl-open"><span class="ex-badge plain">Verified explanation</span><p>${h(fix(T.text || ''))}</p></div>`;
      const why = { rejected: 'An AI explanation was written but contradicted the simulation, so it was thrown away.',
                    unavailable: 'The AI explanation is unavailable right now.', budget: "Today's AI explanation allowance is used up.",
                    unconfigured: 'AI explanations are not switched on for this server.' }[L.status];
      if (why) out += `<div class="ex-note">${h(why)}</div>`;
      const errs = (L.attempts || []).filter(a => a.error).map(a => `${a.provider || ''}: ${a.error}`);
      if (errs.length) out += `<div class="ex-note err"><b>Why:</b> ${h(errs.join(' | '))}</div>`;
    }
    const s = r.math;
    if (withMath && s && !s.unavailable) {
      const n = s.product ? Math.log2(s.product.basis.length) : (C.math?.n_qubits || 0);
      out += `<details class="ex-tmpl" open><summary>The maths for this step</summary>${stepBody(s, { n_qubits: n })}</details>`;
    }
    return out;
  }
  return { tab, installTabs, ask, loadMath };
})();
window.QCMath = QCMath;
