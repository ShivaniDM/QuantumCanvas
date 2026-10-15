import { api, SESSION_ID } from './api.js';
import { circuit } from './circuit.js';
import { saveRun } from './runs-store.js';
import { esc, openDialog, store, toast, uid } from './util.js';

const PREF = 'qc.run.prefs';
let listingCache = null;

export async function backends() {
  if (listingCache && Date.now() - listingCache.at < 60000) return listingCache.data;
  const data = await api.get('/backends');
  listingCache = { at: Date.now(), data };
  return data;
}

function payload(compiled, backend, shots) {
  const doc = circuit.toDocument();
  return {
    canvas_json: JSON.stringify({ concepts: { title: circuit.s.title, qubits: circuit.s.qubits, nodes: circuit.s.nodes } }),
    ir_json: JSON.stringify(doc),
    pseudocode_txt: (compiled.pseudocode?.steps || []).map(s => `${s.n}. ${s.code}`).join('\n'),
    qiskit_py: compiled.qiskit_py || '',
    backend, shots, session_id: SESSION_ID, concept_ir: doc,
  };
}

async function poll(jobId, onStatus) {
  for (let i = 0; i < 200; i++) {
    await new Promise(r => setTimeout(r, 3000));
    const d = await api.get(`/job/${encodeURIComponent(jobId)}`);
    onStatus(d.status);
    if (d.status === 'completed') return d;
    if (['failed', 'canceled', 'cancelled'].includes(d.status)) throw new Error(`The job ${d.status}${d.error ? ': ' + d.error : ''}.`);
  }
  throw new Error('Stopped waiting after 10 minutes. The job may still finish; check My runs later.');
}

export async function runCircuit(backendId, label, shots, onStatus = () => {}) {
  const compiled = circuit.compiled && circuit.compiled.ok ? circuit.compiled : await circuit.compileNow();
  if (!compiled) throw new Error(circuit.compileError || 'The circuit could not be checked.');
  if (!compiled.ok) throw new Error(`Fix this first: ${compiled.errors[0].message}`);
  const key = circuit.docKey();
  if (!circuit.s.nodes.some(n => n.op === 'measure')) {
    const run = {
      id: uid('c'), calculated: true, record_id: null, title: circuit.s.title, backend: backendId, backend_label: label, shots,
      counts: {}, predicted: compiled.step_log?.predicted || null, math: null, flags: [], at: new Date().toISOString(),
      document: circuit.toDocument(), docKey: key,
    };
    circuit.setRun(run);
    return run;
  }
  onStatus('submitting');
  let data = await api.post('/execute', payload(compiled, backendId, shots));
  if (!data.counts && data.job_id) {
    onStatus('queued');
    const done = await poll(data.job_id, onStatus);
    data = { ...data, ...done };
  }
  if (!data.counts) throw new Error('The backend returned no counts.');
  const run = {
    id: uid('r'), record_id: data.record_id || null, title: circuit.s.title, backend: backendId, backend_label: label, shots,
    counts: data.counts, math: data.math || null, flags: data.flags || [], compile_report: data.compile_report || null,
    at: new Date().toISOString(), document: circuit.toDocument(), docKey: key, save_error: data.save_error || null,
  };
  circuit.setRun(run);
  if (!saveRun(run)) toast('This run could not be stored in your browser (storage is full or blocked).', { kind: 'bad' });
  return run;
}

export async function openRunDialog({ onDone } = {}) {
  const compiled = circuit.compiled && circuit.compiled.ok ? circuit.compiled : await circuit.compileNow();
  if (!compiled) { toast(circuit.compileError || "Couldn't check the circuit.", { kind: 'bad' }); return; }
  if (!compiled.ok) { toast(`Fix this first: ${compiled.errors[0].message}`, { kind: 'bad' }); return; }
  if (!circuit.s.nodes.length) { toast('Add at least one step before running.'); return; }
  const prefs = store.get(PREF, { backend: 'aer', shots: 1000 });
  const dlg = openDialog({
    title: 'Run this circuit',
    body: `<div class="muted">${esc(circuit.s.title)} · ${circuit.s.qubits} qubit${circuit.s.qubits === 1 ? '' : 's'}</div><div data-list><div class="muted">Loading backends…</div></div>`,
    footer: `<label class="chips" style="font-size:14px">Shots <input type="number" min="1" max="10000" value="${prefs.shots}" data-shots style="width:100px"></label>
      <span class="muted" style="font-size:12px">Shots: how many times the circuit runs.</span><span style="flex:1"></span>
      <button type="button" class="btn ghost" data-cancel>Cancel</button><button type="button" class="btn primary" data-go>Run</button>`,
  });
  let selected = prefs.backend;
  const list = dlg.body.querySelector('[data-list]');
  const go = dlg.footer.querySelector('[data-go]');
  dlg.footer.querySelector('[data-cancel]').addEventListener('click', dlg.close);
  let rows = [];
  try {
    const data = await backends();
    rows = data.backends;
    if (!rows.find(r => r.id === selected && !r.unavailable)) selected = 'aer';
    const groups = [...new Set(rows.map(r => r.group))];
    const avail = rows.filter(r => !r.unavailable).length;
    list.innerHTML = `${avail < rows.length ? `<div class="muted" style="font-size:13px">${avail} of ${rows.length} simulators are available. Unavailable ones say why.</div>` : ''}
      <div role="radiogroup" aria-label="Backend" style="display:flex;flex-direction:column;gap:12px">${groups.map(g => {
        const gr = rows.filter(r => r.group === g);
        return `<div><div class="label" style="margin-bottom:6px">${esc(data.groups?.[g] || g)}</div>${gr.map(r => `
          <label class="choice" style="cursor:${r.unavailable ? 'default' : 'pointer'};opacity:${r.unavailable ? .6 : 1}">
            <input type="radio" name="backend" value="${esc(r.id)}" ${r.id === selected ? 'checked' : ''} ${r.unavailable ? 'disabled' : ''}>
            <span style="flex:1"><b>${esc(r.label)}</b> <span class="muted">· ${r.qubits} qubits${r.id === 'aer' ? ' · exact, no noise' : r.kind === 'noise_model' || r.kind === 'noisy' ? ' · simulates that device\'s noise' : ''}</span>
            ${r.unavailable ? `<br><span class="muted" style="font-size:12px">${esc(r.unavailable)}</span>` : ''}</span>
            ${r.id === 'aer' ? '<span class="pill">free · instant</span>' : ''}</label>`).join('')}</div>`;
      }).join('')}</div>`;
    list.addEventListener('change', e => { if (e.target.name === 'backend') selected = e.target.value; });
  } catch (e) {
    list.innerHTML = `<div class="note bad">${esc(e.message)}</div>`;
    go.disabled = true;
  }
  go.addEventListener('click', async () => {
    const shots = Math.max(1, Math.min(10000, parseInt(dlg.footer.querySelector('[data-shots]').value, 10) || 1000));
    const row = rows.find(r => r.id === selected) || { id: 'aer', label: 'Built-in simulator' };
    store.set(PREF, { backend: row.id, shots });
    go.disabled = true;
    const status = document.createElement('div');
    status.className = 'note info';
    status.setAttribute('role', 'status');
    dlg.body.appendChild(status);
    const words = { submitting: 'Running…', queued: 'Queued at the provider…', running: 'Running at the provider…' };
    try {
      const run = await runCircuit(row.id, row.label, shots, s => { status.textContent = words[s] || `Status: ${s}`; });
      dlg.close();
      toast(run.calculated ? 'No Measure step, so nothing was measured. Results shows the calculated probabilities.' : `Ran ${shots.toLocaleString()} shots on ${row.label}.`,
            run.calculated ? { ms: 7000 } : {});
      if (onDone) onDone(run);
    } catch (e) {
      status.className = 'note bad';
      status.textContent = e.message;
      go.disabled = false;
    }
  });
}
