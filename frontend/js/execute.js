// QuantumCanvas — Execute panel
// Backends: Aer simulator (local qiskit) · IonQ simulator · IonQ hardware (QPU).
// Simulators run straight to results. Hardware requires a dry-run cost estimate
// and explicit confirmation before it is submitted.
//
// Backend URL — use the local dev server when the page is served from
// localhost (so the new Aer backend can be tested), otherwise the Azure host.
const BACKEND_URL =
  (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
    ? 'http://localhost:8000'
    : 'https://quantumcanvas-backend-f6hphzcrejgjbha8.centralus-01.azurewebsites.net';

// ── Panel state ───────────────────────────────────────────────────────
const execState = {
  shots:            1000,
  jobId:            null,
  polling:          null,
  pipelineStep:     0,
  simResults:       null,   // stored after simulator run for comparison
  runId:            null,
  lastSavedIrJson:  null,   // ir_json string last confirmed saved to logs/runs/
  lastSavedInfo:    null,   // {circuit_hash, run_id, path, ...} from that save
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

  <!-- Explicit "save current state" — snapshots IR/pseudocode/Qiskit to
       logs/runs/<circuit_hash>/ on your own timing, before any execution.
       Execute also auto-saves first if this hasn't happened yet. -->
  <div class="exec-state-save">
    <button class="exec-save-state-btn" id="exec-save-state-btn"
            onclick="saveCurrentState()">💾 Save current state</button>
    <span class="exec-save-status" id="exec-save-status">Not saved yet — Execute will auto-save first.</span>
  </div>

  <!-- Simulator results -->
  <div class="exec-results" id="exec-results">
    <div class="exec-results-head" id="exec-results-head">Simulator Results</div>
    <div id="exec-bars"></div>
  </div>

  <!-- QPU cost card — shown only for the IonQ Hardware flow, before submitting -->
  <div class="exec-qpu-card" id="exec-qpu-card" style="display:none">
    <div class="exec-qpu-card-inner">
      <div class="exec-qpu-left">
        <div class="exec-qpu-title">Run on IonQ Hardware?</div>
        <div class="exec-qpu-sub" id="exec-qpu-sub">forte-1 · trapped ion · real hardware</div>
        <div class="exec-qpu-cost" id="exec-qpu-cost">Fetching cost estimate…</div>
      </div>
      <div class="exec-qpu-right">
        <button class="exec-qpu-confirm" id="exec-qpu-confirm"
                onclick="execRunQPU()" disabled>Proceed — Run on Hardware ⚡</button>
        <button class="exec-qpu-cancel" onclick="execDismissQPU()">Cancel</button>
      </div>
    </div>
    <div class="exec-qpu-warn">
      ⚠ This runs on real hardware and costs money. QPU jobs enter a queue and may take days.
    </div>
  </div>

  <!-- Hardware results (shown alongside simulator if QPU run completes) -->
  <div class="exec-results exec-hw-results" id="exec-hw-results" style="display:none">
    <div class="exec-results-head">QPU Hardware Results
      <span class="exec-compare-badge">forte-1</span>
    </div>
    <div id="exec-hw-bars"></div>
  </div>

  <!-- Save-log options (A: browser · B: download · C: GitHub repo) -->
  <div class="qc-save-inline" id="qc-save-inline" style="display:none"></div>

  <div class="exec-log" id="exec-log">
    <p class="exec-log-line">Ready — choose a backend to execute.</p>
  </div>

  <div class="exec-footer">
    <button class="exec-run-sim-btn" id="exec-run-aer"
            onclick="execRunSimulator('aer')">⚡ Aer Simulator</button>
    <button class="exec-run-sim-btn" id="exec-run-ionq"
            onclick="execRunSimulator('ionq')">⚡ IonQ Simulator</button>
    <button class="exec-run-hw-btn" id="exec-run-hw"
            onclick="execRunHardware()">🖥 IonQ Hardware</button>
    <button class="exec-cancel-btn" onclick="closeExecutePanel()">Close</button>
    <span class="exec-save-note">Artifacts saved to logs/runs/</span>
  </div>`;

  // Reflect whether this exact circuit was already saved in an earlier
  // panel session (lastSavedIrJson persists across opens/closes) —
  // comparing the raw ir_json string is enough to know "unchanged since
  // last save", no need to recompute anything server-side just to check.
  if (execState.lastSavedIrJson === JSON.stringify(ir)) {
    _setSaveStatus(`✓ already saved — logs/runs/${execState.lastSavedInfo?.run_id}/`, 'ok');
  }
}

// ── Capture a run record for the user-logger (A/B/C save options) ─────
// Reuses _buildPayload so the saved artifacts are byte-identical to what the
// backend received, then attaches the results and a little metadata.
function _recordLastRun(counts, runId, kind, raw) {
  try {
    const panel   = document.getElementById('exec-panel');
    const backend = execState.lastBackend || kind;
    const payload = _buildPayload(backend);
    execState.lastRun = {
      schema:         'quantumcanvas.run/v1',
      run_id:         runId || null,
      title:          panel?._doc?.title || 'Untitled circuit',
      backend:        payload.backend,
      shots:          payload.shots,
      kind:           kind,                       // 'sim' | 'qpu'
      n_qubits:       panel?._ir?.n ?? null,
      created_at:     new Date().toISOString(),
      canvas_json:    payload.canvas_json,
      ir_json:        payload.ir_json,
      pseudocode_txt: payload.pseudocode_txt,
      qiskit_py:      payload.qiskit_py,
      results:        counts || null,
      raw:            raw || null,
    };
    if (window.QCLogger) QCLogger.onRunComplete(execState.lastRun);
  } catch (e) { console.warn('QCLogger record failed', e); }
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

// ── Save current state (explicit button + automatic-before-execute) ───
// Tracks the exact ir_json string last confirmed saved to logs/runs/. Simple
// string equality is enough to know "unchanged since last save" — the
// backend is the one that computes the real circuit hash used as the folder
// name, so the frontend doesn't need to replicate that, just detect "did the
// circuit change since I last saved it".
async function _ensureSaved(payload) {
  if (payload.ir_json === execState.lastSavedIrJson) {
    return execState.lastSavedInfo;   // unchanged since last save — skip
  }
  const resp = await fetch(`${BACKEND_URL}/log-circuit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      canvas_json:    payload.canvas_json,
      ir_json:        payload.ir_json,
      pseudocode_txt: payload.pseudocode_txt,
      qiskit_py:      payload.qiskit_py,
    }),
  });
  if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
  const data = await resp.json();
  execState.lastSavedIrJson = payload.ir_json;
  execState.lastSavedInfo   = data;
  return data;
}

// ── Explicit "💾 Save current state" button ────────────────────────────
async function saveCurrentState() {
  const panel = document.getElementById('exec-panel');
  if (!panel?._ir) { execLog('Nothing to save yet.', 'warn'); return; }
  const btn = document.getElementById('exec-save-state-btn');
  if (btn) btn.disabled = true;
  _setSaveStatus('… saving', '');
  try {
    const payload = _buildPayload('snapshot');   // backend field unused by /log-circuit
    const data    = await _ensureSaved(payload);
    const note    = data.already_saved
      ? `already saved — logs/runs/${data.run_id}/ (no changes)`
      : `saved — logs/runs/${data.run_id}/`;
    execLog(`💾 Circuit ${note}`, 'ok');
    _setSaveStatus(`✓ logs/runs/${data.run_id}/`, 'ok');
  } catch (e) {
    execLog(`✖ Save failed: ${e.message}`, 'err');
    _setSaveStatus(`✖ ${e.message}`, 'err');
  } finally {
    if (btn) btn.disabled = false;
  }
}

function _setSaveStatus(msg, cls) {
  const el = document.getElementById('exec-save-status');
  if (el) { el.textContent = msg; el.className = `exec-save-status ${cls||''}`; }
}

// ── Enable/disable all run buttons together ───────────────────────────
function _setRunButtonsDisabled(disabled) {
  ['exec-run-aer', 'exec-run-ionq', 'exec-run-hw'].forEach(id => {
    const b = document.getElementById(id);
    if(b) b.disabled = disabled;
  });
}

// ── Run a simulator backend ('aer' or 'ionq') — no cost, straight to results
async function execRunSimulator(backend) {
  const label = backend === 'aer' ? 'Aer' : 'IonQ';
  execState.lastBackend = backend;
  execState.simResults = null;
  document.getElementById('exec-qpu-card').style.display = 'none';
  document.getElementById('exec-hw-results').style.display = 'none';
  _setRunButtonsDisabled(true);
  _setPipeStep(1);

  const shots = parseInt(document.getElementById('exec-shots')?.value) || 1000;
  execLog(`⚡ Running ${label} simulator — ${shots} shots`, 'ok');
  execLog('  Submitting circuit…');
  _setPipeStep(2);

  try {
    const payload = _buildPayload(backend);
    await _ensureSaved(payload);   // auto-saves circuit state first if it hasn't been yet
    const resp = await fetch(`${BACKEND_URL}/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if(!resp.ok) throw new Error(`Backend ${resp.status}: ${await resp.text()}`);
    const data = await resp.json();

    if(data.counts) {
      // Aer returns synchronously
      _setPipeStep(4);
      _onSimResults(data.counts, data.run_id);
    } else if(data.job_id) {
      // IonQ simulator is async — poll
      execState.runId = data.run_id;
      execLog(`  Job submitted: ${data.job_id}`, 'ok');
      _setPipeStep(3);
      _pollSimJob(data.job_id);
    } else {
      throw new Error('Unexpected response from backend.');
    }
  } catch(e) {
    _setPipeStep(5);
    execLog(`✖ ${e.message}`, 'err');
    _setRunButtonsDisabled(false);
  }
}

// ── IonQ Hardware — dry-run cost estimate first, then require confirmation
async function execRunHardware() {
  execState.lastBackend = 'qpu';
  document.getElementById('exec-hw-results').style.display = 'none';
  const card = document.getElementById('exec-qpu-card');
  card.style.display = 'block';
  document.getElementById('exec-qpu-cost').textContent = 'Fetching cost estimate…';
  document.getElementById('exec-qpu-confirm').disabled = true;
  execLog('🖥 IonQ Hardware selected — running dry-run cost estimate (no charge yet)…', 'warn');
  await _fetchQPUCost();
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
      _setRunButtonsDisabled(false);
      return;
    }
    try {
      const resp = await fetch(`${BACKEND_URL}/job/${jobId}`);
      if(!resp.ok) throw new Error(`Poll ${resp.status}`);
      const data = await resp.json();
      execLog(`  Status: ${data.status} (${attempts*3}s)`);
      // v0.4: only 'completed' means results are ready. 'ready'/'started'/
      // 'submitted' are intermediate - keep polling through them.
      if(data.status === 'completed') {
        clearInterval(execState.polling); execState.polling = null;
        _setPipeStep(4);
        _onSimResults(data.counts, data.run_id || execState.runId);
      } else if(data.status === 'failed' || data.status === 'canceled' || data.status === 'cancelled') {
        clearInterval(execState.polling); execState.polling = null;
        _setPipeStep(5);
        execLog(`✖ Job ${data.status}: ${data.error||''}`, 'err');
        _setRunButtonsDisabled(false);
      }
    } catch(e) { execLog(`  Poll error: ${e.message}`, 'warn'); }
  }, 3000);
}

// ── Simulator results → show visually ────────────────────────────────
function _onSimResults(counts, runId) {
  execState.simResults = counts;
  const shots = parseInt(document.getElementById('exec-shots')?.value) || 1000;
  const panel  = document.getElementById('exec-panel');
  const nQubits = panel?._ir?.n || 1;
  const label = execState.lastBackend === 'aer' ? 'Aer' : 'IonQ';

  document.getElementById('exec-results').classList.add('visible');
  document.getElementById('exec-results-head').textContent = `${label} Simulator Results`;

  // Normalise keys (integer → bitstring) and strip non-numeric entries
  const clean = _normaliseCounts(counts, nQubits);
  const total = Object.values(clean).reduce((a,b) => a+b, 0);

  // Empty counts → make it visible rather than a silent blank panel.
  if(!total) {
    document.getElementById('exec-bars').innerHTML =
      `<div style="opacity:.75;font-size:.72rem;padding:6px 0">`
      + `${label} returned no counts. Backend responded but the histogram was empty — `
      + `check logs/runs/${runId || '…'}/ionq_results_raw.json for the raw IonQ response.</div>`;
    execLog(`⚠ ${label} simulator returned no counts (empty histogram).`, 'warn');
    if(runId) execLog(`  See logs/runs/${runId}/ionq_results_raw.json`);
    _setRunButtonsDisabled(false);
    return;
  }

  _renderBars('exec-bars', clean, total, 'var(--teal)');
  const top = Object.entries(clean).sort((a,b)=>b[1]-a[1])[0];
  const topPct = top ? (top[1]/total*100).toFixed(1) : '?';
  execLog(`✓ ${label} simulator done — ${total} shots · top: |${top?.[0]}⟩ (${topPct}%)`, 'ok');
  if(runId) execLog(`  Artifacts saved to logs/runs/${runId}/`);

  _recordLastRun(counts, runId, 'sim');
  _setRunButtonsDisabled(false);
  // Simulators do not show a cost card — that is reserved for IonQ Hardware.
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
      body: JSON.stringify(_buildPayload('qpu')),
    });
    if(!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
    const data = await resp.json();
    if(data.error) throw new Error(data.error);

    const cost   = (data.cost_usd != null) ? `$${Number(data.cost_usd).toFixed(2)}` : 'not returned';
    const queue  = data.queue_days ? `~${data.queue_days} day queue` : 'queue unknown';
    const target = data.target || 'qpu.forte-1';
    const status = data.status || 'unknown';
    const pet    = (data.predicted_execution_time != null)
                     ? ` · ~${data.predicted_execution_time}s runtime` : '';
    const gates  = _fmtGateCounts(data.gate_counts);

    document.getElementById('exec-qpu-sub').textContent =
      `${target} · status: ${status}${gates ? ' · ' + gates : ''}`;
    document.getElementById('exec-qpu-cost').innerHTML =
      `<span class="exec-cost-num">${cost}</span> `
      + `<span class="exec-cost-note">estimated · ${queue}${pet}</span>`
      + _rawBlock('IonQ estimate response', data.raw ?? data);
    document.getElementById('exec-qpu-confirm').disabled = false;
    execLog(`  QPU cost estimate: ${cost} · status=${status} · ${queue}`, 'warn');

  } catch(e) {
    document.getElementById('exec-qpu-cost').innerHTML =
      `<span style="color:var(--gray)">Cost estimate unavailable (${_h(e.message)})</span>`;
    document.getElementById('exec-qpu-confirm').disabled = false;
    execLog(`  QPU cost estimate unavailable: ${e.message}`, 'warn');
  }
}

// Format IonQ gate_counts (shape can vary: {"1q":N,"2q":M} or a number).
function _fmtGateCounts(gc){
  if(gc == null) return '';
  if(typeof gc === 'object'){
    const parts = Object.entries(gc).map(([k,v]) => `${v} ${k}`);
    return parts.length ? `gates: ${parts.join(', ')}` : '';
  }
  return `gates: ${gc}`;
}

// Collapsible raw-JSON viewer so every field IonQ returns is visible.
function _rawBlock(label, obj){
  if(obj == null) return '';
  let json;
  try { json = JSON.stringify(obj, null, 2); } catch(_) { json = String(obj); }
  return `<details style="margin-top:8px">`
    + `<summary style="cursor:pointer;font-family:'Space Mono',monospace;font-size:.62rem;color:var(--gray)">${_h(label)} — raw JSON</summary>`
    + `<pre style="max-height:220px;overflow:auto;background:rgba(0,0,0,.25);border:1px solid var(--border);`
    + `border-radius:6px;padding:8px;margin-top:6px;font-size:.62rem;color:var(--gray);white-space:pre-wrap">`
    + `${_h(json)}</pre></details>`;
}

function execDismissQPU() {
  document.getElementById('exec-qpu-card').style.display = 'none';
  execLog('  QPU run skipped.');
}

// ── Step 3: Run on real hardware (user confirmed) ────────────────────
async function execRunQPU() {
  const shots = parseInt(document.getElementById('exec-shots')?.value) || 1000;
  const costEl = document.getElementById('exec-qpu-cost');
  const costTxt = costEl ? costEl.textContent.trim() : '';

  // Explicit guard — this is a REAL charge on real hardware. Also serves as a
  // visible signal that the click reached this handler.
  if(!window.confirm(
      `This submits a REAL job to IonQ qpu.forte-1.\n\n`
    + `Estimated cost: ${costTxt || 'see the card'}\n`
    + `Shots: ${shots}\n\n`
    + `It charges real money and enters a multi-day queue. Continue?`)) {
    execLog('  Hardware run cancelled at confirmation.', 'warn');
    return;
  }

  document.getElementById('exec-qpu-confirm').disabled = true;
  document.getElementById('exec-qpu-cancel').disabled  = true;

  const payload = _buildPayload('qpu');   // backend='qpu' → submit_qpu → qpu.forte-1
  execLog(`⚡ Submitting REAL hardware job → POST ${BACKEND_URL}/execute (backend=qpu, shots=${shots})`, 'ok');

  try {
    await _ensureSaved(payload);   // auto-saves circuit state first if it hasn't been yet
    const resp = await fetch(`${BACKEND_URL}/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const text = await resp.text();                    // read once, keep body for errors
    if(!resp.ok) throw new Error(`Backend ${resp.status}: ${text}`);
    const data = JSON.parse(text);

    if(data.job_id) {
      execLog(`  ✓ Hardware job accepted by IonQ: ${data.job_id}`, 'ok');
      execLog(`  Queued on forte-1 — polling every 30s. This can take days.`, 'warn');
      _pollQPUJob(data.job_id);
    } else {
      throw new Error(`No job_id in response: ${text}`);
    }
  } catch(e) {
    // e.message now carries IonQ's real reason (e.g. insufficient credits / access)
    execLog(`✖ Hardware submit rejected: ${e.message}`, 'err');
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

      if(data.status === 'completed') {
        clearInterval(execState.polling); execState.polling = null;
        _onQPUResults(data.counts, data.run_id, data.raw);
      } else if(data.status === 'failed' || data.status === 'canceled' || data.status === 'cancelled') {
        clearInterval(execState.polling); execState.polling = null;
        execLog(`✖ QPU job ${data.status}`, 'err');
        _onQPUResults(null, data.run_id, data.raw);   // still show what IonQ returned
      }
    } catch(e) { execLog(`  Poll error: ${e.message}`, 'warn'); }
  }, 30000);
}

// ── QPU results — show counts (if any) + all hardware metadata IonQ returned
function _onQPUResults(counts, runId, raw) {
  const hwDiv = document.getElementById('exec-hw-results');
  hwDiv.style.display = 'block';

  const panel   = document.getElementById('exec-panel');
  const nQubits = panel?._ir?.n || 1;
  const clean   = counts ? _normaliseCounts(counts, nQubits) : {};
  const total   = Object.values(clean).reduce((a,b)=>a+b,0);

  if(total) {
    _renderBars('exec-hw-bars', clean, total, 'var(--violet)');
    const top = Object.entries(clean).sort((a,b)=>b[1]-a[1])[0];
    execLog(`✓ QPU done — ${total} shots · top: |${top?.[0]}⟩ (${top?((top[1]/total*100).toFixed(1)):'?'}%)`, 'ok');
  } else {
    document.getElementById('exec-hw-bars').innerHTML =
      `<div style="opacity:.7;font-size:.72rem;padding:4px 0">No measurement counts returned — see hardware response below.</div>`;
    execLog('  QPU returned no counts (showing raw hardware response).', 'warn');
  }

  // Surface every metadata field IonQ sent back for a real hardware job.
  if(raw && typeof raw === 'object') {
    const keys = ['status','target','qubits','shots','execution_time',
                  'predicted_execution_time','cost_usd','request','response',
                  'results_url','warning','failure'];
    const rows = keys
      .filter(k => raw[k] != null && raw[k] !== '')
      .map(k => `<div style="display:flex;justify-content:space-between;gap:12px;padding:2px 0;font-size:.66rem">`
              + `<span style="color:var(--gray)">${k}</span>`
              + `<b style="color:var(--white);text-align:right;word-break:break-all">`
              + `${_h(typeof raw[k]==='object' ? JSON.stringify(raw[k]) : String(raw[k]))}</b></div>`)
      .join('');
    document.getElementById('exec-hw-bars').insertAdjacentHTML('beforeend',
      `<div style="margin-top:10px;border-top:1px solid var(--border);padding-top:8px">${rows}</div>`
      + _rawBlock('IonQ hardware job', raw));
  }

  if(runId) execLog(`  QPU artifacts saved to logs/runs/${runId}/`);
  _recordLastRun(counts, runId, 'qpu', raw);
  document.getElementById('exec-qpu-card').style.display = 'none';
}

// ── Shared bar renderer ───────────────────────────────────────────────
// Normalise IonQ integer state keys ("0","1","2","3") → bitstrings ("00","01","10","11")
function _normaliseCounts(counts, nQubits) {
  const normalised = {};
  if(!counts || typeof counts !== 'object') return normalised;   // null-safe
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
