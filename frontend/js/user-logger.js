// QuantumCanvas — User Logger
// Lets each user keep a personal copy of a completed run. Two options, both
// self-contained, no backend required:
//
//   A · Browser storage  — localStorage, personal history
//   B · Download file     — a .json bundle saved to the file manager
//
// (The circuit's canonical log — canvas/IR/pseudocode/Qiskit/results — is
// handled separately by the backend's logs/runs/<circuit_hash>/ mechanism,
// see execute.js's "💾 Save current state" button. This module is only for
// a user's own personal copy of a run, unrelated to that.)
//
// Exposes window.QCLogger plus the on* / qc* globals used by inline handlers.

(function () {
  'use strict';

  const LS_INDEX   = 'qc_logs_index';      // array of run summaries
  const LS_RUN     = id => `qc_log_${id}`; // full record per run
  const LS_PREFS   = 'qc_log_prefs';       // { defaultOption, username }
  const SCHEMA     = 'quantumcanvas.run/v1';

  // ── Preferences ──────────────────────────────────────────────────────
  function getPrefs() {
    try {
      const p = JSON.parse(localStorage.getItem(LS_PREFS)) || {};
      return { defaultOption: p.defaultOption || 'local', username: p.username || '' };
    } catch (_) { return { defaultOption: 'local', username: '' }; }
  }
  function setPrefs(patch) {
    const next = Object.assign(getPrefs(), patch);
    try { localStorage.setItem(LS_PREFS, JSON.stringify(next)); } catch (_) {}
    return next;
  }

  // ── Username → safe label (used only to personalise filenames) ───────
  function sanitiseUsername(name, fallback = 'anonymous') {
    const cleaned = String(name || '').trim().toLowerCase()
      .replace(/[^a-z0-9_.-]+/g, '-').replace(/^[-.]+|[-.]+$/g, '');
    return cleaned.slice(0, 40) || fallback;
  }

  // ── Small helpers ────────────────────────────────────────────────────
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function toast(msg, kind) {
    if (typeof window.toast === 'function') { window.toast(msg, kind); return; }
    if (typeof execLog === 'function') { execLog(msg, kind === 'error' ? 'err' : (kind || '')); return; }
    console.log('[QCLogger]', msg);
  }
  function topState(counts) {
    const clean = {};
    if (counts && typeof counts === 'object') {
      for (const [k, v] of Object.entries(counts)) {
        if (k === 'circuit_hash') continue;
        const n = Number(v); if (!isNaN(n)) clean[k] = n;
      }
    }
    const sorted = Object.entries(clean).sort((a, b) => b[1] - a[1]);
    const total  = sorted.reduce((a, [, v]) => a + v, 0);
    if (!sorted.length || !total) return null;
    return { state: sorted[0][0], pct: (sorted[0][1] / total * 100).toFixed(1), total };
  }

  // ── The current run awaiting a save decision ─────────────────────────
  let currentRun = null;

  // Called by execute.js after results are in.
  function onRunComplete(record) {
    if (!record) return;
    currentRun = record;
    renderInline();
  }

  // ── Option A · Browser localStorage ──────────────────────────────────
  function listLocal() {
    try { return JSON.parse(localStorage.getItem(LS_INDEX)) || []; }
    catch (_) { return []; }
  }
  function getLocal(id) {
    try { return JSON.parse(localStorage.getItem(LS_RUN(id))); }
    catch (_) { return null; }
  }
  function saveLocal(record) {
    const id  = record.local_id || `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    const rec = Object.assign({}, record, { local_id: id });
    const top = topState(record.results);
    const summary = {
      id,
      title:      record.title || 'Untitled circuit',
      backend:    record.backend || 'unknown',
      shots:      record.shots || 0,
      n_qubits:   record.n_qubits ?? null,
      created_at: record.created_at || new Date().toISOString(),
      top:        top ? `|${top.state}⟩ ${top.pct}%` : '—',
    };
    let idx;
    try {
      localStorage.setItem(LS_RUN(id), JSON.stringify(rec));
      idx = listLocal().filter(r => r.id !== id);
      idx.unshift(summary);
      localStorage.setItem(LS_INDEX, JSON.stringify(idx.slice(0, 200)));
    } catch (e) {
      toast('Browser storage full — export or clear old logs.', 'error');
      throw e;
    }
    return id;
  }
  function deleteLocal(id) {
    try { localStorage.removeItem(LS_RUN(id)); } catch (_) {}
    try { localStorage.setItem(LS_INDEX, JSON.stringify(listLocal().filter(r => r.id !== id))); } catch (_) {}
  }
  function clearAllLocal() {
    listLocal().forEach(r => { try { localStorage.removeItem(LS_RUN(r.id)); } catch (_) {} });
    try { localStorage.removeItem(LS_INDEX); } catch (_) {}
  }

  // ── Option B · Download a file ───────────────────────────────────────
  function download(record) {
    const user  = sanitiseUsername(record.username || getPrefs().username || 'anonymous');
    const runId = record.run_id || defaultRunId(record);
    const bundle = Object.assign({ schema: SCHEMA, username: user, run_id: runId }, record);
    const json = JSON.stringify(bundle, null, 2);
    const name = `quantumcanvas_${user}_${runId}.json`;
    const blob = new Blob([json], { type: 'application/json' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return { name, run_id: runId, username: user };
  }
  function defaultRunId(record) {
    const d = new Date(record.created_at || Date.now());
    const p = n => String(n).padStart(2, '0');
    const be = (record.backend || 'run').toUpperCase();
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}_` +
           `${p(d.getHours())}-${p(d.getMinutes())}-${p(d.getSeconds())}_${be}`;
  }

  // ══════════════════════════════════════════════════════════════════════
  //  UI
  // ══════════════════════════════════════════════════════════════════════

  // Inline "save this run" block, injected into the Execute panel.
  function renderInline() {
    const host = document.getElementById('qc-save-inline');
    if (!host || !currentRun) return;
    const prefs = getPrefs();
    const top   = topState(currentRun.results);
    host.style.display = 'block';
    host.innerHTML = `
      <div class="qc-save-head">Keep a personal copy of this run</div>
      <div class="qc-save-sub">${esc(currentRun.title || 'Untitled circuit')}
        · ${esc(currentRun.backend)} · ${currentRun.shots} shots${top ? ` · top |${esc(top.state)}⟩ ${top.pct}%` : ''}</div>
      <div class="qc-save-user">
        <label class="qc-lbl" for="qc-username">Label (optional)</label>
        <input class="qc-input" id="qc-username" type="text" placeholder="anonymous"
               value="${esc(prefs.username)}"
               oninput="QCLogger.setUsername(this.value)">
      </div>
      <div class="qc-save-opts">
        <button class="qc-opt qc-opt-a" onclick="QCLogger.saveCurrent('local')">
          <span class="qc-opt-key">A</span>
          <span class="qc-opt-txt"><b>Browser storage</b><small>localStorage · no backend</small></span>
        </button>
        <button class="qc-opt qc-opt-b" onclick="QCLogger.saveCurrent('download')">
          <span class="qc-opt-key">B</span>
          <span class="qc-opt-txt"><b>Download file</b><small>.json to your device</small></span>
        </button>
      </div>
      <div class="qc-save-foot">
        <label class="qc-default-lbl">Default:
          <select class="qc-default-sel" onchange="QCLogger.setDefault(this.value)">
            <option value="local"    ${prefs.defaultOption === 'local'    ? 'selected' : ''}>A · Browser</option>
            <option value="download" ${prefs.defaultOption === 'download' ? 'selected' : ''}>B · Download</option>
          </select>
        </label>
        <button class="qc-browse-btn" onclick="QCLogger.openPanel()">🗂 View saved logs</button>
      </div>
      <div class="qc-save-status" id="qc-save-status"></div>`;
  }

  function setUsername(val) { setPrefs({ username: val }); }
  function setDefault(val) { setPrefs({ defaultOption: val }); }

  function saveStatus(msg, kind) {
    const el = document.getElementById('qc-save-status');
    if (el) { el.className = `qc-save-status ${kind || ''}`; el.innerHTML = msg; }
    toast(msg.replace(/<[^>]+>/g, ''), kind === 'err' ? 'error' : kind);
  }

  async function saveCurrent(option) {
    if (!currentRun) { toast('No run to save yet — execute a circuit first.', 'error'); return; }
    const user = sanitiseUsername(getPrefs().username);
    currentRun.username = user;
    try {
      if (option === 'local') {
        const id = saveLocal(currentRun);
        saveStatus(`✓ Saved to browser storage <span class="qc-mono">(${id})</span>`, 'ok');
      } else if (option === 'download') {
        const r = download(currentRun);
        saveStatus(`✓ Downloaded <span class="qc-mono">${esc(r.name)}</span>`, 'ok');
      }
    } catch (e) {
      saveStatus(`✖ ${esc(e.message || e)}`, 'err');
    }
  }

  // ── Saved-logs browser (localStorage) ────────────────────────────────
  function openPanel() {
    let overlay = document.getElementById('qc-logs-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'qc-logs-overlay';
      overlay.onclick = e => { if (e.target === overlay) closePanel(); };
      overlay.innerHTML = '<div id="qc-logs-panel"></div>';
      document.body.appendChild(overlay);
    }
    overlay.classList.add('open');
    renderPanel();
  }
  function closePanel() {
    const overlay = document.getElementById('qc-logs-overlay');
    if (overlay) overlay.classList.remove('open');
  }
  function renderPanel() {
    const panel = document.getElementById('qc-logs-panel');
    if (!panel) return;
    const rows = listLocal();
    const list = rows.length ? rows.map(r => `
      <div class="qc-log-row" id="qc-log-row-${esc(r.id)}">
        <div class="qc-log-main">
          <div class="qc-log-title">${esc(r.title)}</div>
          <div class="qc-log-meta">${esc(r.backend)} · ${r.shots} shots · ${esc(r.top)}
            · <span class="qc-mono">${esc(new Date(r.created_at).toLocaleString())}</span></div>
        </div>
        <div class="qc-log-actions">
          <button class="qc-mini" title="Download" onclick="QCLogger.downloadLocal('${esc(r.id)}')">⭳</button>
          <button class="qc-mini qc-mini-danger" title="Delete" onclick="QCLogger.removeLocal('${esc(r.id)}')">✕</button>
        </div>
      </div>`).join('')
      : '<div class="qc-log-empty">No saved runs yet. Execute a circuit and choose <b>Browser storage</b>.</div>';

    panel.innerHTML = `
      <div class="qc-logs-header">
        <div>
          <div class="qc-logs-label">Saved Logs</div>
          <div class="qc-logs-title">Browser storage · ${rows.length} run${rows.length !== 1 ? 's' : ''}</div>
        </div>
        <button class="qc-logs-close" onclick="QCLogger.closePanel()">×</button>
      </div>
      <div class="qc-logs-body">${list}</div>
      <div class="qc-logs-foot">
        <span class="qc-mono qc-dim">Stored only in this browser</span>
        ${rows.length ? '<button class="qc-clear-btn" onclick="QCLogger.clearAll()">Clear all</button>' : ''}
      </div>`;
  }
  function downloadLocal(id) {
    const rec = getLocal(id);
    if (!rec) { toast('Run not found', 'error'); return; }
    download(rec);
  }
  function removeLocal(id) {
    deleteLocal(id);
    renderPanel();
  }
  function clearAll() {
    if (window.confirm('Delete all runs saved in this browser? This cannot be undone.')) {
      clearAllLocal();
      renderPanel();
    }
  }

  // ── Public API ───────────────────────────────────────────────────────
  window.QCLogger = {
    onRunComplete, renderInline,
    saveCurrent, setUsername, setDefault,
    saveLocal, listLocal, getLocal, deleteLocal, clearAllLocal,
    download, sanitiseUsername, getPrefs, setPrefs,
    openPanel, closePanel, downloadLocal, removeLocal, clearAll,
  };
})();
