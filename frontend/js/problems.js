// QuantumCanvas — Problem bank UI: pick a problem, build with the allowed concepts, press Check.
// Problems and grading live on the backend (GET /problems, POST /check-problem).
// Load order: ... concepts.js → problems.js

const QCProblems = (() => {
  const P = { list: [], active: null, hints: 0, result: null, loadError: null };
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const FAMILY = {
    state_preparation: 'State preparation', correlation: 'Correlation', manipulation: 'Manipulation', phase: 'Phase', search: 'Search',
    arithmetic: 'Arithmetic', phase_algorithms: 'Phase algorithms', communication: 'Communication', dynamic: 'Dynamic circuits', data_encoding: 'Data encoding',
  };

  async function load() {
    try {
      const r = await fetch(`${BACKEND_URL}/problems`);
      if (!r.ok) throw new Error(r.status);
      P.list = await r.json(); P.loadError = null;
    } catch (e) { P.loadError = e.message || 'offline'; }
  }

  async function open() {
    await load();
    const ov = $('prob-overlay');
    let h = `<div class="prob-box"><div class="how-head"><div><div class="how-label">Problem bank</div><div class="how-title">Pick a problem to solve with concepts</div></div>
      <button class="cd-x" onclick="QCProblems.closeList()">×</button></div><div class="prob-body">`;
    if (P.loadError) h += `<div class="iss iss-off">Can't reach the backend (${esc(P.loadError)}). Start it to load problems.</div>`;
    const fams = [...new Set(P.list.map(p => p.family))];
    fams.forEach(f => {
      h += `<h4 class="prob-fam">${esc(FAMILY[f] || f)}</h4>`;
      P.list.filter(p => p.family === f).forEach(p => {
        h += `<div class="prob-item ${P.active?.id === p.id ? 'on' : ''}"><div><div class="prob-st">${esc(p.statement)}</div>
          <div class="prob-meta">${p.qubits} qubit${p.qubits > 1 ? 's' : ''} · ${p.allowed_concepts.map(esc).join(', ')}</div></div>
          <button onclick="QCProblems.start('${p.id}')">${P.active?.id === p.id ? 'Restart' : 'Start'}</button></div>`;
      });
    });
    ov.innerHTML = h + '</div></div>';
    ov.classList.add('open');
  }
  const closeList = () => $('prob-overlay').classList.remove('open');

  async function start(id) {
    if (!P.list.length) await load();
    const p = P.list.find(x => x.id === id);
    if (!p) return;
    const dirty = state.qubits.length > 0;
    if (dirty && !confirm('Starting a problem clears the canvas. Continue?')) return;
    clearCanvas();
    QCConcepts.setMode('concepts');
    const wrap = document.getElementById('canvas-wrap').getBoundingClientRect();
    for (let i = 0; i < p.qubits; i++) placeQubit(wrap.width / 2 + (i - (p.qubits - 1) / 2) * 120, wrap.height / 2);
    P.active = p; P.hints = 0; P.result = null;
    QCConcepts.applyAllowed(new Set(p.allowed_concepts));
    closeList();
    render();
    toast(`Problem started: ${p.qubits} qubit${p.qubits > 1 ? 's' : ''} placed.`, 'info');
  }

  function stop() {
    P.active = null; P.result = null; P.hints = 0;
    QCConcepts.applyAllowed(null);
    render();
  }

  function hint() {
    if (!P.active) return;
    P.hints = Math.min(P.hints + 1, P.active.hint_ladder.length);
    render();
  }

  async function check() {
    if (!P.active) return;
    const res = await QCConcepts.compileNow();
    if (!res) { toast('Start the backend to check solutions.', 'error'); return; }
    P.result = { pending: true }; render();
    try {
      const r = await fetch(`${BACKEND_URL}/check-problem`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ problem_id: P.active.id, document: res.document }) });
      if (!r.ok) throw new Error(`${r.status}`);
      P.result = await r.json();
    } catch (e) { P.result = { error: e.message }; }
    render();
  }

  function render() {
    const host = $('problem-card');
    if (!host) return;
    const p = P.active;
    if (!p) { host.innerHTML = ''; host.classList.remove('open'); return; }
    const r = P.result;
    let h = `<div class="pc-top"><span class="pc-tag">PROBLEM</span><button class="cd-x" title="Leave problem" onclick="QCProblems.stop()">×</button></div>
      <div class="pc-st">${esc(p.statement)}</div>
      <div class="pc-allow">Allowed: ${p.allowed_concepts.map(c => `<span class="chip">${esc(c)}</span>`).join(' ')}</div>`;
    if (p.hint_ladder?.length) {
      h += `<div class="pc-hints">${p.hint_ladder.slice(0, P.hints).map((t, i) => `<div class="pc-hint"><b>Hint ${i + 1}</b> ${esc(t)}</div>`).join('')}</div>`;
    }
    h += `<div class="pc-actions"><button class="pc-check" onclick="QCProblems.check()">Check my circuit</button>
      <button class="pc-hintbtn" ${P.hints >= (p.hint_ladder?.length || 0) ? 'disabled' : ''} onclick="QCProblems.hint()">Hint${P.hints ? ` (${P.hints}/${p.hint_ladder.length})` : ''}</button></div>`;
    if (r?.pending) h += `<div class="pc-res">Checking…</div>`;
    else if (r?.error) h += `<div class="pc-res bad">Couldn't reach the checker (${esc(r.error)}).</div>`;
    else if (r) {
      h += `<div class="pc-res ${r.passed ? 'good' : 'bad'}"><b>${r.passed ? '✓ Solved' : '✗ Not yet'}</b>${r.passed ? '' : `<div>${esc(QCConcepts.labelize(r.summary))}</div>`}
        ${(r.checks || []).filter(c => c.name !== 'setup').map(c => `<div class="pc-chk ${c.passed ? 'ok' : 'no'}">${c.passed ? '✓' : '✗'} ${esc(c.name)}: ${esc(QCConcepts.labelize(c.detail))}</div>`).join('')}</div>`;
    }
    host.innerHTML = h;
    host.classList.add('open');
  }

  document.addEventListener('DOMContentLoaded', render);
  return { open, closeList, start, stop, hint, check, state: P };
})();
window.QCProblems = QCProblems;
