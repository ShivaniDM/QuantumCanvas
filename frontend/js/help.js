// QuantumCanvas — "How it works" guide (opens once on a first visit, and from the ? Help button),
// plus a note on small screens, where the main canvas is cramped.
// Load order: last (after math-view.js).

const QCHelp = (() => {
  const SEEN_KEY = 'qc-help-seen-v1';
  const small = () => window.innerWidth < 760;

  const css = `
  #help-overlay{position:fixed;inset:0;background:rgba(5,7,14,.72);display:none;align-items:center;justify-content:center;z-index:400;padding:16px}
  #help-overlay.open{display:flex}
  .help-box{background:var(--card);border:1px solid var(--border);border-radius:14px;max-width:560px;width:100%;max-height:calc(100vh - 32px);overflow-y:auto;padding:22px 24px;box-shadow:0 18px 50px rgba(0,0,0,.55)}
  .help-box h2{font-size:1.1rem;margin:0 0 4px;color:var(--white)}
  .help-sub{color:var(--gray);font-size:.82rem;margin-bottom:14px}
  .help-box ol{margin:0 0 12px 18px;padding:0;color:var(--white);font-size:.88rem;line-height:1.55}
  .help-box li{margin-bottom:8px}
  .help-box b{color:var(--teal);font-weight:500}
  .help-tip{background:var(--teal3);border:1px solid var(--teal2);border-radius:8px;padding:9px 12px;font-size:.8rem;color:var(--gray);margin-bottom:10px}
  .help-warn{background:var(--amber2);border:1px solid rgba(255,184,77,.3);border-radius:8px;padding:9px 12px;font-size:.8rem;color:var(--amber);margin-bottom:10px}
  .help-go{background:var(--teal);color:#06261f;border:0;border-radius:8px;padding:8px 18px;font-weight:600;cursor:pointer;font-size:.85rem}
  #small-note{display:none;position:fixed;left:8px;right:8px;bottom:8px;z-index:300;background:var(--amber2);border:1px solid rgba(255,184,77,.35);color:var(--amber);border-radius:10px;padding:9px 12px;font-size:.8rem;backdrop-filter:blur(6px)}
  #small-note button{float:right;background:none;border:0;color:var(--amber);font-size:.9rem;cursor:pointer}
  @media (max-width: 759px){ .tb-tag,.tb-status,.tb-sep{display:none} }`;

  const smallWarning = `<div class="help-warn">You're on a small screen. The canvas works best on a laptop, or a tablet in landscape.
    On a phone, <b>🎓 Learn</b> is the easiest place to start.</div>`;

  function html() {
    return `<div class="help-box" role="dialog" aria-modal="true" aria-labelledby="help-title">
      <h2 id="help-title">How QuantumCanvas works</h2>
      <div class="help-sub">Build a quantum circuit from ideas, see the exact maths, run it, and copy the Qiskit code.</div>
      ${small() ? smallWarning : ''}
      <ol>
        <li><b>Place qubits.</b> Pick <b>⊕ Qubit</b> on the left, then click the canvas once per qubit.</li>
        <li><b>Build.</b> <b>Classic</b> has five quick actions: click Shake, Mark, Boost, Entangle or Measure, then click a qubit.
            <b>Concepts</b> (switch at the top) has the full set: pick a concept, click the qubits it acts on, then press <b>Add step</b>.</li>
        <li><b>Understand.</b> <b>{ } Pseudocode</b> explains every step in words; its <b>∑ Math</b> tab shows the exact state after each step.
            The <b>?</b> on a step explains just that step.</li>
        <li><b>Run.</b> <b>Execute ⚡</b> → <b>Aer Simulator</b> runs it for free in seconds. <b>💬 Explain</b> then describes the result, checked against the exact simulation.</li>
        <li><b>Take the code.</b> In the Pseudocode panel, <b>Generate Qiskit ▶</b> gives code you can paste into a notebook or your project.</li>
      </ol>
      <div class="help-tip">Practise with <b>🧩 Problems</b> (checked automatically), or open <b>🎓 Learn</b> for the Fall Fest notebook with a gate-by-gate sandbox.</div>
      <button class="help-go" onclick="QCHelp.close()">Start building</button>
    </div>`;
  }

  function ensure() {
    if (document.getElementById('help-overlay')) return;
    const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
    const ov = document.createElement('div'); ov.id = 'help-overlay';
    ov.addEventListener('click', e => { if (e.target === ov) close(); });
    document.body.appendChild(ov);
    const note = document.createElement('div'); note.id = 'small-note';
    note.innerHTML = `<button onclick="this.parentElement.style.display='none'" aria-label="Dismiss">✕</button>
      Best on a laptop or a tablet in landscape. On a phone, try <a href="learn.html" style="color:inherit">🎓 Learn</a>.`;
    document.body.appendChild(note);
    document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
  }
  function open() {
    ensure();
    const ov = document.getElementById('help-overlay');
    ov.innerHTML = html(); ov.classList.add('open');
  }
  function close() {
    const ov = document.getElementById('help-overlay');
    if (ov) ov.classList.remove('open');
    try { localStorage.setItem(SEEN_KEY, '1'); } catch (_) { /* storage blocked: fine, it just shows again */ }
  }
  function init() {
    ensure();
    if (small()) document.getElementById('small-note').style.display = 'block';
    let seen = false;
    try { seen = localStorage.getItem(SEEN_KEY) === '1'; } catch (_) { /* treat as first visit */ }
    if (!seen) open();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
  return { open, close };
})();
window.QCHelp = QCHelp;
