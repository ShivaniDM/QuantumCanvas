// QuantumCanvas — Execute panel (simulator + IonQ hardware via backend)
// Communicates with backend/app.py — never holds API keys directly.
// Load order: must come after qiskit-generator.js

// ── Config ────────────────────────────────────────────────────────────
// Backend base URL — update if running on a different port
const BACKEND_URL = 'https://quantumcanvas-backend-f6hphzcrejgjbha8.centralus-01.azurewebsites.net';

// ── Execute panel state ───────────────────────────────────────────────
const execState = {
  backend: 'simulator',   // 'simulator' | 'ionq'
  shots:   1000,
  jobId:   null,
  polling: null,
  pipelineStep: 0,        // 0=idle 1=generating 2=submitting 3=polling 4=done 5=error
};

// ── Open / close ──────────────────────────────────────────────────────
function openExecutePanel() {
  const ir  = extractCanvasIR(state);
  validateIR(ir);
  if(!ir.validation.ok) {
    toast('Fix validation errors before executing', 'error');
    return;
  }
  const doc    = generatePseudocode(ir);
  const qiskit = generateQiskit(ir, doc);
  _renderExecPanel(ir, doc, qiskit);
  document.getElementById('exec-overlay').classList.add('open');
}

function closeExecutePanel() {
  if(execState.polling) { clearInterval(execState.polling); execState.polling = null; }
  document.getElementById('exec-overlay').classList.remove('open');
}

function execOverlayClick(e) {
  if(e.target === document.getElementById('exec-overlay')) closeExecutePanel();
}

// ── Render ────────────────────────────────────────────────────────────
function _renderExecPanel(ir, doc, qiskit) {
  const panel = document.getElementById('exec-panel');

  // Store for later use
  panel._ir     = ir;
  panel._doc    = doc;
  panel._qiskit = qiskit;

  const pipeSteps = ['IR', 'Pseudocode', 'Qiskit', 'Submit', 'Results'];

  let h = `
  <div class="exec-header">
    <div class="exec-title-block">
      <div class="exec-label">Execute ⚡</div>
      <div class="exec-title">${_h(doc.title)}</div>
      <div class="exec-meta">${ir.n} qubit${ir.n!==1?'s':''} · ${ir.N} states · ready to run</div>
    </div>
    <button class="exec-close" onclick="closeExecutePanel()">×</button>
  </div>

  <!-- Pipeline visualiser -->
  <div class="exec-pipeline" id="exec-pipe">
    ${pipeSteps.map((s,i) => `
      <div class="exec-pipe-step">
        <div class="exec-pipe-dot" id="pipe-dot-${i}">  ${i+1}</div>
        <div class="exec-pipe-lbl">${s}</div>
      </div>
      ${i < pipeSteps.length-1 ? '<span class="exec-pipe-arrow">→</span>' : ''}
    `).join('')}
  </div>

  <!-- Backend selector -->
  <div class="exec-backends">
    <div class="exec-backend-btn ${execState.backend==='simulator'?'selected':''}"
         id="be-sim" onclick="execSelectBackend('simulator')">
      <div class="exec-be-name">Aer Simulator</div>
      <div class="exec-be-desc">Local — runs in browser backend</div>
      <span class="exec-be-badge badge-avail">Available</span>
    </div>
    <div class="exec-backend-btn ${execState.backend==='ionq'?'selected':''}"
         id="be-ionq" onclick="execSelectBackend('ionq')">
      <div class="exec-be-name">IonQ Simulator</div>
      <div class="exec-be-desc">Cloud — IonQ forte-1 noise model</div>
      <span class="exec-be-badge badge-avail">API Connected</span>
    </div>
    <div class="exec-backend-btn disabled-backend">
      <div class="exec-be-name">IonQ Hardware</div>
      <div class="exec-be-desc">forte-1 QPU · trapped ion</div>
      <span class="exec-be-badge badge-queue">Queue: ~340 days</span>
    </div>
  </div>

  <!-- Shots config -->
  <div class="exec-config">
    <span class="exec-config-label">Shots:</span>
    <input class="exec-shots-input" id="exec-shots" type="number"
           min="1" max="10000" value="${execState.shots}"
           onchange="execState.shots=parseInt(this.value)||1000">
    <span class="exec-config-label" style="margin-left:8px;opacity:.6">
      (IonQ max: 10,000)
    </span>
  </div>

  <!-- Results area (hidden until run) -->
  <div class="exec-results" id="exec-results">
    <div class="exec-results-head">Results</div>
    <div id="exec-bars"></div>
  </div>

  <!-- Job log -->
  <div class="exec-log" id="exec-log">
    <p class="exec-log-line">Ready. Select backend and click Run.</p>
  </div>

  <!-- Footer -->
  <div class="exec-footer">
    <button class="exec-run-sim-btn" id="exec-run-sim"
            onclick="execRun('simulator')">▶ Run Simulator</button>
    <button class="exec-run-hw-btn"  id="exec-run-ionq"
            onclick="execRun('ionq')">⚡ Run IonQ</button>
    <button class="exec-cancel-btn"  onclick="closeExecutePanel()">Close</button>
    <span class="exec-save-note">All artifacts saved to logs/</span>
  </div>`;

  panel.innerHTML = h;
}

function execSelectBackend(b) {
  execState.backend = b;
  document.querySelectorAll('.exec-backend-btn').forEach(el => el.classList.remove('selected'));
  const map = { simulator: 'be-sim', ionq: 'be-ionq' };
  if(map[b]) document.getElementById(map[b])?.classList.add('selected');
}

// ── Run ───────────────────────────────────────────────────────────────
async function execRun(backend) {
  const panel  = document.getElementById('exec-panel');
  const ir     = panel._ir;
  const doc    = panel._doc;
  const qiskit = panel._qiskit;

  if(!ir || !doc || !qiskit) { execLog('No circuit loaded.', 'err'); return; }

  execState.backend = backend;
  const shots = parseInt(document.getElementById('exec-shots')?.value) || 1000;

  // Disable buttons during run
  document.getElementById('exec-run-sim').disabled  = true;
  document.getElementById('exec-run-ionq').disabled = true;

  execLog(`▶ Starting ${backend} run — ${shots} shots`, 'ok');
  execLog(`  Generating artifacts…`);
  _setPipeStep(1);

  // Build the payload — qiskit code is the contract with the backend
  const qiskitCode = qiskit.lines.map((l,i) => {
    const r = qiskit.remarks[i];
    return (r && !l.startsWith('#')) ? `${l}  # ${r}` : l;
  }).join('\n');

  const payload = {
    canvas_json:   JSON.stringify({ qubits: state.qubits.map(q=>({
                     id: q.id, label: q.label, state: q.state,
                     ops: q.ops, result: q.result
                   })), edges: state.edges }),
    ir_json:       JSON.stringify(ir),
    pseudocode_txt: _buildPseudocodeText(doc),
    qiskit_py:     qiskitCode,
    backend,
    shots,
  };

  _setPipeStep(2);
  execLog(`  Sending to backend (${BACKEND_URL}/execute)…`);

  try {
    const resp = await fetch(`${BACKEND_URL}/execute`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    });

    if(!resp.ok) {
      const err = await resp.text();
      throw new Error(`Backend ${resp.status}: ${err}`);
    }

    const data = await resp.json();

    if(data.job_id) {
      // Async job (IonQ hardware) — poll for result
      execState.jobId = data.job_id;
      execLog(`  Job submitted: ${data.job_id}`, 'ok');
      _setPipeStep(3);
      execLog(`  Polling for results…`);
      _pollJob(data.job_id, backend);
    } else if(data.counts) {
      // Synchronous result (simulator)
      _setPipeStep(4);
      _showResults(data.counts, shots, data.run_id);
    } else {
      throw new Error('Unexpected response format from backend.');
    }

  } catch(err) {
    _setPipeStep(5);
    execLog(`✖ ${err.message}`, 'err');
    addLog(`✖ Execute error: ${err.message}`, 'error');
    document.getElementById('exec-run-sim').disabled  = false;
    document.getElementById('exec-run-ionq').disabled = false;
  }
}

// ── Job polling (IonQ async) ──────────────────────────────────────────
function _pollJob(jobId, backend) {
  let attempts = 0;
  const maxAttempts = 60;   // 60 × 3s = 3 minutes max

  execState.polling = setInterval(async () => {
    attempts++;
    if(attempts > maxAttempts) {
      clearInterval(execState.polling);
      execState.polling = null;
      execLog('✖ Job poll timeout — check backend logs for job ' + jobId, 'err');
      _setPipeStep(5);
      return;
    }

    try {
      const resp = await fetch(`${BACKEND_URL}/job/${jobId}`);
      if(!resp.ok) throw new Error(`Poll ${resp.status}`);
      const data = await resp.json();

      execLog(`  Job ${jobId} — status: ${data.status} (${attempts * 3}s)`);

      if(data.status === 'completed' || data.status === 'ready') {
        clearInterval(execState.polling);
        execState.polling = null;
        _setPipeStep(4);
        _showResults(data.counts, null, data.run_id);
      } else if(data.status === 'failed' || data.status === 'canceled') {
        clearInterval(execState.polling);
        execState.polling = null;
        _setPipeStep(5);
        execLog(`✖ Job failed: ${data.error || data.status}`, 'err');
      }
    } catch(e) {
      execLog(`  Poll error: ${e.message}`, 'warn');
    }
  }, 3000);
}

// ── Result display ────────────────────────────────────────────────────
function _showResults(counts, shots, runId) {
  const resultsDiv = document.getElementById('exec-results');
  const barsDiv    = document.getElementById('exec-bars');
  if(!resultsDiv || !barsDiv) return;

  resultsDiv.classList.add('visible');

  const total = Object.values(counts).reduce((a,b) => a+b, 0);
  const sorted = Object.entries(counts).sort((a,b) => b[1]-a[1]);
  const maxCount = sorted[0]?.[1] || 1;

  const colours = ['var(--teal)', 'var(--rose)', 'var(--amber)', 'var(--violet)', 'var(--gray)'];

  barsDiv.innerHTML = sorted.map(([state, count], i) => {
    const pct     = ((count / total) * 100).toFixed(1);
    const barPct  = ((count / maxCount) * 100).toFixed(1);
    const colour  = colours[i % colours.length];
    return `<div class="exec-bar-row">
      <span class="exec-bar-state">|${state}⟩</span>
      <div class="exec-bar-track">
        <div class="exec-bar-fill" style="width:${barPct}%;background:${colour}"></div>
      </div>
      <span class="exec-bar-pct">${count} (${pct}%)</span>
    </div>`;
  }).join('');

  const runNote = runId ? `  Run saved to logs/${runId}/` : '';
  execLog(`✓ Done — ${total} shots. Top result: |${sorted[0]?.[0]}⟩ (${((sorted[0]?.[1]/total)*100).toFixed(1)}%)${runNote}`, 'ok');
  if(runId) addLog(`✓ Execute complete — artifacts in logs/${runId}/`, 'teal');

  document.getElementById('exec-run-sim').disabled  = false;
  document.getElementById('exec-run-ionq').disabled = false;
}

// ── Helpers ───────────────────────────────────────────────────────────
function _setPipeStep(step) {
  execState.pipelineStep = step;
  for(let i = 0; i < 5; i++) {
    const dot = document.getElementById(`pipe-dot-${i}`);
    if(!dot) continue;
    dot.className = 'exec-pipe-dot';
    if(step === 5 && i === (step-1)) dot.classList.add('error');
    else if(i < step) dot.classList.add('done');
    else if(i === step-1) dot.classList.add('active');
  }
}

function execLog(msg, cls='') {
  const log = document.getElementById('exec-log');
  if(!log) return;
  const p = document.createElement('p');
  p.className = `exec-log-line ${cls}`;
  p.textContent = `${_ts()} ${msg}`;
  log.appendChild(p);
  log.scrollTop = log.scrollHeight;
}

function _ts() {
  const d = new Date();
  return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}`;
}

function _buildPseudocodeText(doc) {
  const lines = [`${doc.title}`, `${'─'.repeat(doc.title.length)}`, ''];
  doc.steps.forEach(s => {
    lines.push(`${s.n}. ${s.code}`);
    lines.push(`   ${s.plain}`);
    lines.push('');
  });
  return lines.join('\n');
}
