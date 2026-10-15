import { api } from './api.js';
import { circuit } from './circuit.js';
import { listRuns } from './runs-store.js';
import { $$, esc } from './util.js';

export function renderHome(main) {
  const runs = listRuns().slice(0, 3);
  const hasCircuit = circuit.s.nodes.length > 0;
  main.innerHTML = `<div class="page">
    <section class="home-hero">
      <h1>Build quantum circuits from ideas, and see exactly what they become.</h1>
      <p>Every concept opens into its real gates, the maths behind it and the code it produces. Start from a blank circuit, a practice problem, or code you already have.</p>
    </section>
    <div class="doors">
      <a class="door" href="#/build"><span class="label">Have an idea</span><h2>Build</h2>
        <p>Compose a circuit from concepts or individual gates. Run it on a simulator and get a checked explanation.</p><span class="go">${hasCircuit ? `Continue “${esc(circuit.s.title)}” →` : 'Open a blank circuit →'}</span></a>
      <a class="door" href="#/import"><span class="label">Have code</span><h2>Bring code</h2>
        <p>Paste OpenQASM or Qiskit. Every gate is kept exactly, and familiar patterns are offered as concepts you can accept or skip.</p><span class="go">Paste code →</span></a>
    </div>
    ${runs.length ? `<section aria-labelledby="recent-h" style="margin-bottom:32px"><h2 id="recent-h" class="label" style="margin-bottom:10px">Recent runs</h2>
      <div class="recent">${runs.map(r => `<a class="btn" href="#/runs/${esc(r.id)}">${esc(r.title)} · ${esc(r.backend_label || r.backend)} · ${new Date(r.at).toLocaleDateString()}</a>`).join('')}
      <a class="btn ghost" href="#/runs">All runs →</a></div></section>` : ''}
    <section aria-labelledby="prob-h" class="problems">
      <h2 id="prob-h" style="margin:0 0 6px;font-size:20px">Practice problems</h2>
      <p class="muted" style="margin:0 0 12px;font-size:14px">Each one opens in Build and is checked automatically.</p>
      <div class="card" data-problems style="padding:14px"><p class="muted" style="margin:0">Loading problems…</p></div>
    </section>
  </div>`;
  loadProblems(main.querySelector('[data-problems]'));
}

async function loadProblems(host) {
  try {
    const list = await api.get('/problems');
    const fams = [...new Set(list.map(p => p.family))];
    host.innerHTML = fams.map(f => `<div class="label" style="margin:10px 0 6px">${esc(f.replace(/_/g, ' '))}</div>${list.filter(p => p.family === f).map(p => `
      <div class="sugg"><span class="what">${esc(p.statement)}<br><span class="muted" style="font-size:12px">${p.qubits} qubit${p.qubits > 1 ? 's' : ''}</span></span>
      <button type="button" class="btn small" data-prob="${esc(p.id)}">Try in Build</button></div>`).join('')}`).join('');
    $$('[data-prob]', host).forEach(b => b.addEventListener('click', () => {
      const p = list.find(x => x.id === b.dataset.prob);
      if (circuit.s.nodes.length && !confirm('This replaces the circuit in Build. You can undo it there. Continue?')) return;
      circuit.load({ qubits: p.qubits, operations: [] }, p.statement.slice(0, 60), 'Start problem');
      circuit.problem = p;
      location.hash = '#/build';
    }));
  } catch (e) {
    host.innerHTML = `<div class="note warn">Practice problems need the server: ${esc(e.message)}</div>`;
  }
}
