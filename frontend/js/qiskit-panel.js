// QuantumCanvas — Qiskit panel renderer, copy, Collab stub
// Load order: state.js → ir.js → pseudocode.js → ui.js → qiskit-generator.js → qiskit-panel.js

// ── Qiskit Panel ──────────────────────────────────────────────────────

function pcQiskit(){
  const ir = window._pcLastIR;
  if(!ir||!ir.validation.ok){ toast('Fix errors first','error'); return; }
  const doc    = generatePseudocode(ir);
  const qiskit = generateQiskit(ir, doc);
  _renderQiskitPanel(ir, doc, qiskit);
}

function _renderQiskitPanel(ir, doc, qiskit){
  const panel = document.getElementById('pc-panel');

  // Build annotated code lines
  const codeLines = qiskit.lines.map((line, i) => {
    const remark = qiskit.remarks[i];
    if(!line) return '';   // blank line
    return remark ? line : line;
  });

  const codeText = qiskit.lines.map((line, i) => {
    const remark = qiskit.remarks[i];
    if(!line) return '';
    return line + (remark ? `  # ${remark}` : '');
  }).join('\n');

  const copyId = 'qk-code-block';

  let h = `
  <div class="pc-header">
    <div class="pc-title-block">
      <div class="pc-label">Qiskit Output · Layer 2</div>
      <div class="pc-title">${_h(doc.title)}</div>
      <div class="pc-meta">${ir.n} qubit${ir.n!==1?'s':''} · ${qiskit.lines.filter(l=>l&&!l.startsWith('#')).length} gate instructions</div>
    </div>
    <button class="pc-close" onclick="closePseudocodePanel()">×</button>
  </div>

  <div class="qk-code-wrap">
    <div class="qk-toolbar">
      <span class="qk-lang-badge">Python · Qiskit</span>
      <button class="qk-copy-btn" onclick="qkCopy()">Copy</button>
    </div>
    <pre class="qk-pre" id="${copyId}">${buildHighlightedCode(qiskit)}</pre>
  </div>

  <div class="qk-map-section">
    <div class="qk-map-head">QuantumCanvas → Qiskit mapping</div>
    <table class="qk-map-tbl">
      <thead><tr><th>Canvas primitive</th><th>Qiskit gate(s)</th><th>Status</th></tr></thead>
      <tbody>
        <tr><td>◎ SHAKE</td><td><code>qc.h(q)</code></td><td class="qk-impl">✓ Implemented</td></tr>
        <tr><td>◈ MARK</td><td><code>qc.z(q)</code></td><td class="qk-impl">✓ Implemented</td></tr>
        <tr><td>▲ BOOST</td><td><code>H · X · CZ · X · H</code> (diffusion)</td><td class="qk-impl">✓ Implemented</td></tr>
        <tr><td>⋈ LINK</td><td><code>qc.cx(ctrl, tgt)</code></td><td class="qk-impl">✓ Implemented</td></tr>
        <tr><td>◙ LOOK</td><td><code>qc.measure(q, c)</code></td><td class="qk-impl">✓ Implemented</td></tr>
      </tbody>
    </table>
  </div>

  <div class="pc-footer">
    <button class="pc-qiskit-btn" onclick="qkBackToPseudocode()">← Pseudocode</button>
    <button class="qk-collab-btn" onclick="qkSendToCollab()">Send to Collab ▶</button>
    <button class="pc-footer-cancel" onclick="closePseudocodePanel()">Close</button>
  </div>`;

  panel.innerHTML = h;
  panel._qkCode = codeText;  // stored for copy
}

function buildHighlightedCode(qiskit){
  // Simple syntax highlighting via HTML spans (no external lib)
  const keywords = /\b(from|import|for|in|if|print|def|return)\b/g;
  const builtins = /\b(QuantumCircuit|AerSimulator|transpile|sorted)\b/g;
  const methods  = /\.(h|x|z|cx|cz|ccx|measure|draw|run|result|get_counts)\(/g;
  const strings  = /("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')/g;
  const numbers  = /\b(\d+)\b/g;
  const comments = /(#[^\n]*)/g;

  return qiskit.lines.map((line, i) => {
    if(!line) return '';
    const remark = qiskit.remarks[i];
    // Attach inline remark as a comment if the line itself isn't a comment
    const full = (remark && !line.startsWith('#')) ? `${line}  # ${remark}` : line;

    // Escape HTML first, then inject spans
    let s = full
      .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

    // Comments first (they swallow everything after #)
    s = s.replace(/(#[^<]*)/g, '<span class="qk-c">$1</span>');

    // Only style non-comment parts (crude but sufficient for display)
    if(!line.startsWith('#')){
      s = s
        .replace(/\b(from|import|for|in|print)\b/g, '<span class="qk-kw">$1</span>')
        .replace(/\b(QuantumCircuit|AerSimulator|transpile)\b/g, '<span class="qk-bi">$1</span>')
        .replace(/\.(h|x|z|cx|cz|ccx|measure|draw|run|result|get_counts)\(/g,
                 '.<span class="qk-fn">$1</span>(')
        .replace(/("(?:[^"<>])*"|'(?:[^'<>])*')/g, '<span class="qk-s">$1</span>')
        .replace(/\b(\d+)\b(?![^<]*<\/span>)/g, '<span class="qk-n">$1</span>');
    }
    return s;
  }).join('\n');
}

function qkCopy(){
  const panel = document.getElementById('pc-panel');
  const code  = panel._qkCode || document.getElementById('qk-code-block')?.innerText || '';
  navigator.clipboard.writeText(code).then(()=>{
    const btn = document.querySelector('.qk-copy-btn');
    if(btn){ btn.textContent='Copied!'; setTimeout(()=>btn.textContent='Copy', 1800); }
  }).catch(()=>{
    // Fallback for non-https
    const ta = document.createElement('textarea');
    ta.value = code; document.body.appendChild(ta);
    ta.select(); document.execCommand('copy');
    document.body.removeChild(ta);
    const btn = document.querySelector('.qk-copy-btn');
    if(btn){ btn.textContent='Copied!'; setTimeout(()=>btn.textContent='Copy', 1800); }
  });
}

function qkSendToCollab(){
  const panel  = document.getElementById('pc-panel');
  const code   = panel._qkCode || '';
  addLog('⟶ Qiskit code ready for Collab API — endpoint pending from Kenzo','violet');
  toast('Collab API endpoint not yet configured — ping Kenzo on Slack','warn');
  console.log('[QC Collab] Qiskit code to POST:\n\n' + code);
}

function qkBackToPseudocode(){
  openPseudocodePanel();
}

function _h(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

function _renderPC(ir,doc){
  window._pcLastIR=ir;
  const v=ir.validation;
  const panel=document.getElementById('pc-panel');

  const title=doc?doc.title:(v.errs.length?'Validation Failed':'Invalid Sequence');
  const meta =doc?doc.meta:`${ir.n} qubit${ir.n!==1?'s':''} · ${v.errs.length} error${v.errs.length!==1?'s':''}`;

  let h=`<div class="pc-header">
    <div class="pc-title-block">
      <div class="pc-label">Pseudocode Review</div>
      <div class="pc-title">${_h(title)}</div>
      <div class="pc-meta">${_h(meta)}</div>
    </div>
    <button class="pc-close" onclick="closePseudocodePanel()">×</button>
  </div>`;

  // raw execution timeline
  const tlOps = { shake:'Shake', mark:'Mark', boost:'Boost', link:'Link', look:'Look' };
  const tlDetails = entry => {
    const q = ir.qubits.find(q=>q.id===entry.qubit);
    const lbl = q?.label || entry.qubit;
    if(entry.op==='boost') return `(all marked qubits)`;
    if(entry.op==='link'){
      const edge = ir.edges.find(e=>e.src===entry.qubit||e.tgt===entry.qubit);
      if(edge){
        const sl=ir.qubits.find(q=>q.id===edge.src)?.label||edge.src;
        const tl=ir.qubits.find(q=>q.id===edge.tgt)?.label||edge.tgt;
        return `${sl} ↔ ${tl}`;
      }
    }
    if(entry.op==='look' && entry.correlated) return `${lbl}  (correlated collapse)`;
    return lbl;
  };
  h+=`<div class="pc-timeline">
    <div class="pc-tl-head" onclick="this.nextElementSibling.classList.toggle('open');this.querySelector('.tl-arr').textContent=this.nextElementSibling.classList.contains('open')?'▾':'▸'">
      <span class="tl-arr">▸</span> Raw Execution Timeline
      <span style="margin-left:auto;font-size:.58rem;color:var(--dim)">${ir.globalLog.length} event${ir.globalLog.length!==1?'s':''}</span>
    </div>
    <div class="pc-tl-list">`;
  ir.globalLog.forEach((entry,i)=>{
    h+=`<div class="pc-tl-row">
      <span class="pc-tl-n">${i+1}.</span>
      <span class="pc-tl-op tl-${entry.op}">${tlOps[entry.op]||entry.op}</span>
      <span class="pc-tl-detail">${_h(tlDetails(entry))}</span>
    </div>`;
  });
  h+=`</div></div>`;

  // violations + warnings
  if(v.errs.length||v.warns.length){
    h+=`<div class="pc-violations">`;
    v.errs.forEach(e=>h+=`<div class="pc-vcard error">
      <div class="pc-vcard-rule">✖ ${_h(e.rule)}</div>
      <div class="pc-vcard-msg">${_h(e.msg)}</div>
      <div class="pc-vcard-plain">${_h(e.plain)}</div>
      <div class="pc-vcard-fix">Fix: ${_h(e.fix)}</div>
    </div>`);
    v.warns.forEach(w=>h+=`<div class="pc-vcard warning">
      <div class="pc-vcard-rule">⚠ ${_h(w.rule)}</div>
      <div class="pc-vcard-msg">${_h(w.msg)}</div>
      <div class="pc-vcard-plain">${_h(w.plain)}</div>
      <div class="pc-vcard-fix">Suggestion: ${_h(w.fix)}</div>
    </div>`);
    h+=`</div>`;
  }

  // steps
  h+=`<div class="pc-steps">`;
  if(doc){
    doc.steps.forEach(step=>{
      const sc=STRIPE[step.op]||'s-init';
      h+=`<div class="pc-step">
        <div class="pc-stripe ${sc}"></div>
        <div class="pc-step-body">
          <div class="pc-step-num">Step ${step.n} · ${step.op}</div>
          <div class="pc-step-code">${_h(step.code)}</div>
          <div class="pc-step-plain">${_h(step.plain)}</div>
          <button class="pc-qnote-btn" onclick="pcQnote(this)">[ quantum ▸ ]</button>
          <div class="pc-qnote">${_h(step.qnote)}</div>
        </div>
      </div>`;
    });
  } else {
    h+=`<div class="pc-step dimmed">
      <div class="pc-stripe s-look"></div>
      <div class="pc-step-body">
        <div class="pc-step-num">Steps blocked</div>
        <div class="pc-step-code" style="color:var(--gray)">Fix errors on canvas to generate pseudocode.</div>
      </div>
    </div>`;
  }
  h+=`</div>`;

  // summary table
  if(doc){
    h+=`<div class="pc-summary">
      <div class="pc-sum-head">Qubit Summary</div>
      <table class="pc-tbl">
        <thead><tr><th>Qubit</th><th>Operations</th><th>Final State</th><th>Result</th></tr></thead>
        <tbody>`;
    doc.summary.forEach(r=>{
      const resultColor=r.result==='1'?'var(--teal)':r.result==='0'?'var(--gray)':'var(--dim)';
      h+=`<tr>
        <td>${_h(r.label)}</td>
        <td>${_h(r.ops)}</td>
        <td><span class="sbadge sb-${r.state}">${r.state}</span></td>
        <td style="color:${resultColor}">${r.result??'—'}</td>
      </tr>`;
    });
    h+=`</tbody></table></div>`;
    if(doc.patternNote)
      h+=`<div class="pc-pattern">${_h(doc.patternNote)}</div>`;
  }

  // footer
  const statusTxt = v.ok
    ? (v.warns.length ? '⚠ Valid with warnings' : '✓ Valid')
    : `✖ ${v.errs.length} error${v.errs.length!==1?'s':''}`;
  const statusCls = v.ok ? (v.warns.length?'warn':'ok') : 'err';
  h+=`<div class="pc-footer">
    <button class="pc-qiskit-btn" ${v.ok?'':'disabled'} onclick="pcQiskit()">Generate Qiskit ▶</button>
    <button class="pc-footer-cancel" onclick="closePseudocodePanel()">Close</button>
    <span class="pc-status ${statusCls}">${statusTxt}</span>
  </div>`;

  panel.innerHTML=h;
}
