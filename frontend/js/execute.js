// QuantumCanvas — Execute panel
// Flow: IonQ Simulator → visual results → QPU cost card → optional QPU run
// Backend URL — set to Azure backend
const BACKEND_URL = 'https://quantumcanvas-backend-f6hphzcrejgjbha8.centralus-01.azurewebsites.net';

// ── Panel state ───────────────────────────────────────────────────────
const execState = {
  shots:        1000,
  jobId:        null,
  polling:      null,
  pipelineStep: 0,
  simResults:   null,   // stored after simulator run for comparison
  runId:        null,
};

// ── Open / close ──────────────────────────────────────────────────────
function openExecutePanel() {
  const ir = extractCanvasIR(state);
  validateIR(ir);
  if(!ir.validation.ok) { toast('Fix validation errors before executing', 'error'); return; }
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
  panel._ir = ir; panel._doc = doc; panel._qiskit = qiskit;

  const pipeSteps = ['IR', 'Pseudocode', 'Qiskit', 'Submit', 'Results'];

  panel.innerHTML = `
  <div class="exec-header">
    <div class="exec-title-block">
      <div class="exec-label">Execute ⚡</div>
      <div class="exec-title">${_h(doc.title)}</div>
      <div class="exec-meta">${ir.n} qubit${ir.n!==1?'s':''} · ${ir.N} states · ready to run</div>
    </div>
    <button class="exec-close" onclick="closeExecutePanel()">×</button>
  </div>

  <div class="exec-pipeline" id="exec-pipe">
    ${pipeSteps.map((s,i) => `
      <div class="exec-pipe-step">
        <div class="exec-pipe-dot" id="pipe-dot-${i}">${i+1}</div>
        <div class="exec-pipe-lbl">${s}</div>
      </div>
      ${i < pipeSteps.length-1 ? '<span class="exec-pipe-arrow">→</span>' : ''}
    `).join('')}
  </div>

  <div class="exec-config">
    <span class="exec-config-label">Shots:</span>
    <input class="exec-shots-input" id="exec-shots" type="number"
           min="1" max="10000" value="${execState.shots}"
           onchange="execState.shots=parseInt(this.value)||1000">
    <span class="exec-config-label" style="margin-left:8px;opacity:.5">(max 10,000)</span>
  </div>

  <!-- Simulator results -->
  <div class="exec-results" id="exec-results">
    <div class="exec-results-head" id="exec-results-head">IonQ Simulator Results</div>
    <div id="exec-bars"></div>
  </div>

  <!-- QPU cost card — shown after simulator run -->
  <div class="exec-qpu-card" id="exec-qpu-card" style="display:none">
    <div class="exec-qpu-card-inner">
      <div class="exec-qpu-left">
        <div class="exec-qpu-title">Run on QPU?</div>
        <div class="exec-qpu-sub" id="exec-qpu-sub">forte-1 · trapped ion · real hardware</div>
        <div class="exec-qpu-cost" id="exec-qpu-cost">Fetching cost estimate…</div>
      </div>
      <div class="exec-qpu-right">
        <button class="exec-qpu-confirm" id="exec-qpu-confirm"
                onclick="execRunQPU()" disabled>Run on QPU ⚡</button>
        <button class="exec-qpu-cancel" onclick="execDismissQPU()">Not now</button>
      </div>
    </div>
    <div class="exec-qpu-warn">
      ⚠ QPU jobs enter a queue and may take days. Results will appear when ready.
    </div>
  </div>

  <!-- Hardware results (shown alongside simulator if QPU run completes) -->
  <div class="exec-results exec-hw-results" id="exec-hw-results" style="display:none">
    <div class="exec-results-head">QPU Hardware Results
      <span class="exec-compare-badge">forte-1</span>
    </div>
    <div id="exec-hw-bars"></div>
  </div>

  <div class="exec-log" id="exec-log">
    <p class="exec-log-line">Ready — click Run to execute on IonQ simulator.</p>
  </div>

  <div class="exec-footer">
    <button class="exec-run-sim-btn" id="exec-run-sim"
            onclick="execRunSimulator()">⚡ Run IonQ Simulator</button>
    <button class="exec-cancel-btn" onclick="closeExecutePanel()">Close</button>
    <span class="exec-save-note">Artifacts saved to logs/</span>
  </div>`;
}

// ── Build payload ─────────────────────────────────────────────────────
function _buildPayload(backend) {
  const panel  = document.getElementById('exec-panel');
  const qiskit = panel._qiskit;
  const ir     = panel._ir;
  const doc    = panel._doc;
  const shots  = parseInt(document.getElementById('exec-shots')?.value) || 1000;

  const qiskitCode = qiskit.lines.map((l,i) => {
    const r = qiskit.remarks[i];
    return (r && !l.startsWith('#')) ? `${l}  # ${r}` : l;
  }).join('\n');

  return {
    canvas_json:    JSON.stringify({ qubits: state.qubits.map(q=>({
                      id:q.id, label:q.label, state:q.state, ops:q.ops, result:q.result
                    })), edges: state.edges }),
    ir_json:        JSON.stringify(ir),
    pseudocode_txt: _buildPseudocodeText(doc),
    qiskit_py:      qiskitCode,
    backend,
    shots,
  };
}

// ── Step 1: Run simulator ─────────────────────────────────────────────
async function execRunSimulator() {
  execState.simResults = null;
  document.getElementById('exec-qpu-card').style.display = 'none';
  document.getElementById('exec-hw-results').style.display = 'none';
  document.getElementById('exec-run-sim').disabled = true;
  _setPipeStep(1);

  const shots = parseInt(document.getElementById('exec-shots')?.value) || 1000;
  execLog(`⚡ Running IonQ simulator — ${shots} shots`, 'ok');
  execLog('  Submitting circuit…');
  _setPipeStep(2);

  try {
    const resp = await fetch(`${BACKEND_URL}/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(_buildPayload('ionq')),
    });
    if(!resp.ok) throw new Error(`Backend ${resp.status}: ${await resp.text()}`);
    const data = await resp.json();

    if(data.job_id) {
      execState.runId = data.run_id;
      execLog(`  Job submitted: ${data.job_id}`, 'ok');
      _setPipeStep(3);
      _pollSimJob(data.job_id);
    } else if(data.counts) {
      _setPipeStep(4);
      _onSimResults(data.counts, data.run_id);
    } else {
      throw new Error('Unexpected response from backend.');
    }
  } catch(e) {
    _setPipeStep(5);
    execLog(`✖ ${e.message}`, 'err');
    document.getElementById('exec-run-sim').disabled = false;
  }
}

// ── Poll simulator job ────────────────────────────────────────────────
function _pollSimJob(jobId) {
  let attempts = 0;
  execState.polling = setInterval(async () => {
    attempts++;
    if(attempts > 60) {
      clearInterval(execState.polling); execState.polling = null;
      execLog('✖ Timeout waiting for simulator result', 'err');
      _setPipeStep(5);
      document.getElementById('exec-run-sim').disabled = false;
      return;
    }
    try {
      const resp = await fetch(`${BACKEND_URL}/job/${jobId}`);
      if(!resp.ok) throw new Error(`Poll ${resp.status}`);
      const data = await resp.json();
      execLog(`  Status: ${data.status} (${attempts*3}s)`);
      if(data.status === 'completed' || data.status === 'ready') {
        clearInterval(execState.polling); execState.polling = null;
        _setPipeStep(4);
        _onSimResults(data.counts, data.run_id || execState.runId);
      } else if(data.status === 'failed' || data.status === 'canceled') {
        clearInterval(execState.polling); execState.polling = null;
        _setPipeStep(5);
        execLog(`✖ Job ${data.status}: ${data.error||''}`, 'err');
        document.getElementById('exec-run-sim').disabled = false;
      }
    } catch(e) { execLog(`  Poll error: ${e.message}`, 'warn'); }
  }, 3000);
}

// ── Simulator results → show visually → fetch QPU cost ───────────────
function _onSimResults(counts, runId) {
  execState.simResults = counts;
  const shots = parseInt(document.getElementById('exec-shots')?.value) || 1000;
  const panel  = document.getElementById('exec-panel');
  const nQubits = panel?._ir?.n || 1;
  // Normalise keys (integer → bitstring) and strip non-numeric entries
  const clean = _normaliseCounts(counts, nQubits);
  const total = Object.values(clean).reduce((a,b) => a+b, 0) || shots;

  _renderBars('exec-bars', clean, total, 'var(--teal)');

  document.getElementById('exec-results').classList.add('visible');
  document.getElementById('exec-results-head').textContent = 'IonQ Simulator Results';

  const top = Object.entries(clean).sort((a,b)=>b[1]-a[1])[0];
  const topPct = top ? (top[1]/total*100).toFixed(1) : '?';
  execLog(`✓ Simulator done — ${total} shots · top: |${top?.[0]}⟩ (${topPct}%)`, 'ok');
  if(runId) execLog(`  Artifacts saved to logs/${runId}/`);

  document.getElementById('exec-run-sim').disabled = false;

  // Now fetch QPU cost estimate and show card
  _fetchQPUCost();
}

// ── Step 2: Fetch QPU cost and show card ──────────────────────────────
async function _fetchQPUCost() {
  const card = document.getElementById('exec-qpu-card');
  card.style.display = 'block';
  document.getElementById('exec-qpu-cost').textContent = 'Fetching cost estimate…';
  document.getElementById('exec-qpu-confirm').disabled = true;

  try {
    const resp = await fetch(`${BACKEND_URL}/cost`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(_buildPayload('ionq')),
    });
    if(!resp.ok) throw new Error(`${resp.status}`);
    const data = await resp.json();

    const cost     = data.cost_usd   ? `$${data.cost_usd.toFixed(2)}` : 'unknown';
    const queue    = data.queue_days ? `~${data.queue_days} day queue` : 'queue unknown';
    const target   = data.target     || 'qpu.forte-1';
    const gate1q   = data.gate_counts?.['1q'] ?? '?';
    const gate2q   = data.gate_counts?.['2q'] ?? '?';

    document.getElementById('exec-qpu-sub').textContent =
      `${target} · ${gate1q} single-qubit gates · ${gate2q} two-qubit gates`;
    document.getElementById('exec-qpu-cost').innerHTML =
      `<span class="exec-cost-num">${cost}</span> <span class="exec-cost-note">estimated · ${queue}</span>`;
    document.getElementById('exec-qpu-confirm').disabled = false;
    execLog(`  QPU cost estimate: ${cost} · ${queue}`, 'warn');

  } catch(e) {
    document.getElementById('exec-qpu-cost').innerHTML =
      `<span style="color:var(--gray)">Cost estimate unavailable (${e.message})</span>`;
    document.getElementById('exec-qpu-confirm').disabled = false;
    execLog(`  QPU cost estimate unavailable: ${e.message}`, 'warn');
  }
}

function execDismissQPU() {
  document.getElementById('exec-qpu-card').style.display = 'none';
  execLog('  QPU run skipped.');
}

// ── Step 3: Run QPU (user confirmed) ─────────────────────────────────
async function execRunQPU() {
  document.getElementById('exec-qpu-confirm').disabled = true;
  document.getElementById('exec-qpu-cancel').disabled  = true;
  execLog('⚡ Submitting to QPU (forte-1)…', 'ok');

  try {
    const payload = _buildPayload('ionq');
    payload.backend = 'qpu';   // tells backend to use qpu.forte-1

    const resp = await fetch(`${BACKEND_URL}/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if(!resp.ok) throw new Error(`Backend ${resp.status}: ${await resp.text()}`);
    const data = await resp.json();

    if(data.job_id) {
      execLog(`  QPU job submitted: ${data.job_id}`, 'ok');
      execLog(`  Job is queued — polling every 30s. Leave this open or check back later.`, 'warn');
      _pollQPUJob(data.job_id);
    } else {
      throw new Error('No job ID returned from backend.');
    }
  } catch(e) {
    execLog(`✖ QPU submit failed: ${e.message}`, 'err');
    document.getElementById('exec-qpu-confirm').disabled = false;
    document.getElementById('exec-qpu-cancel').disabled  = false;
  }
}

// ── Poll QPU job (slower — 30s intervals, hardware queue) ────────────
function _pollQPUJob(jobId) {
  let attempts = 0;
  const maxAttempts = 200;  // 200 × 30s = 100 minutes before giving up
  execLog(`  Polling QPU job ${jobId} every 30s…`);

  execState.polling = setInterval(async () => {
    attempts++;
    if(attempts > maxAttempts) {
      clearInterval(execState.polling); execState.polling = null;
      execLog('  QPU poll stopped after 100 min. Job may still be running — check IonQ dashboard.', 'warn');
      return;
    }
    try {
      const resp = await fetch(`${BACKEND_URL}/job/${jobId}`);
      if(!resp.ok) throw new Error(`Poll ${resp.status}`);
      const data = await resp.json();
      execLog(`  QPU status: ${data.status} (${attempts*30}s elapsed)`);

      if(data.status === 'completed' || data.status === 'ready') {
        clearInterval(execState.polling); execState.polling = null;
        _onQPUResults(data.counts, data.run_id);
      } else if(data.status === 'failed' || data.status === 'canceled') {
        clearInterval(execState.polling); execState.polling = null;
        execLog(`✖ QPU job ${data.status}`, 'err');
      }
    } catch(e) { execLog(`  Poll error: ${e.message}`, 'warn'); }
  }, 30000);
}

// ── QPU results — show alongside simulator ────────────────────────────
function _onQPUResults(counts, runId) {
  if(!counts || !Object.keys(counts).length) {
    execLog('✖ QPU returned no counts.', 'err'); return;
  }
  const panel   = document.getElementById('exec-panel');
  const nQubits = panel?._ir?.n || 1;
  const clean   = _normaliseCounts(counts, nQubits);
  const total   = Object.values(clean).reduce((a,b)=>a+b,0);

  const hwDiv = document.getElementById('exec-hw-results');
  hwDiv.style.display = 'block';
  _renderBars('exec-hw-bars', clean, total, 'var(--violet)');

  const top = Object.entries(clean).sort((a,b)=>b[1]-a[1])[0];
  execLog(`✓ QPU done — ${total} shots · top: |${top?.[0]}⟩ (${top?((top[1]/total*100).toFixed(1)):'?'}%)`, 'ok');
  if(runId) execLog(`  QPU artifacts saved to logs/${runId}/`);

  document.getElementById('exec-qpu-card').style.display = 'none';
}

// ── Shared bar renderer ───────────────────────────────────────────────
// Normalise IonQ integer state keys ("0","1","2","3") → bitstrings ("00","01","10","11")
function _normaliseCounts(counts, nQubits) {
  const normalised = {};
  for(const [key, val] of Object.entries(counts)) {
    if(key === 'circuit_hash') continue;
    const n = Number(val);
    if(isNaN(n)) continue;
    // If key is a small integer string and doesn't look like a bitstring already
    const isInt = /^\d+$/.test(key) && !(/^[01]+$/.test(key) && key.length > 1);
    const bits  = isInt
      ? parseInt(key, 10).toString(2).padStart(nQubits || 1, '0')
      : key;
    normalised[bits] = (normalised[bits] || 0) + n;
  }
  return normalised;
}

function _renderBars(containerId, counts, total, primaryColour) {
  const el = document.getElementById(containerId);
  if(!el) return;

  const sorted   = Object.entries(counts).sort((a,b)=>b[1]-a[1]);
  const maxCount = sorted[0]?.[1] || 1;
  const colours  = [primaryColour, 'var(--rose)', 'var(--amber)', 'var(--teal)', 'var(--gray)'];

  el.innerHTML = sorted.map(([st, count], i) => {
    const pct    = ((count/total)*100).toFixed(1);
    const barPct = ((count/maxCount)*100).toFixed(1);
    const col    = i===0 ? primaryColour : colours[i % colours.length];
    return `<div class="exec-bar-row">
      <span class="exec-bar-state">|${st}⟩</span>
      <div class="exec-bar-track">
        <div class="exec-bar-fill" style="width:${barPct}%;background:${col}"></div>
      </div>
      <span class="exec-bar-pct">${count} <span style="opacity:.6">(${pct}%)</span></span>
    </div>`;
  }).join('');
}

// ── Helpers ───────────────────────────────────────────────────────────
function _setPipeStep(step) {
  for(let i=0;i<5;i++){
    const dot=document.getElementById(`pipe-dot-${i}`);
    if(!dot) continue;
    dot.className='exec-pipe-dot';
    if(step===5 && i===4) dot.classList.add('error');
    else if(i<step)       dot.classList.add('done');
    else if(i===step-1)   dot.classList.add('active');
  }
}

function execLog(msg, cls='') {
  const log=document.getElementById('exec-log');
  if(!log) return;
  const p=document.createElement('p');
  p.className=`exec-log-line ${cls}`;
  p.textContent=`${_ts()} ${msg}`;
  log.appendChild(p);
  log.scrollTop=log.scrollHeight;
}

function _ts() {
  const d=new Date();
  return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}`;
}

function _buildPseudocodeText(doc) {
  const lines=[`${doc.title}`,`${'─'.repeat(doc.title.length)}`,''];
  doc.steps.forEach(s=>{lines.push(`${s.n}. ${s.code}`);lines.push(`   ${s.plain}`);lines.push('');});
  return lines.join('\n');
}
