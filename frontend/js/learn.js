// QuantumCanvas Learn — UI controller: palette, circuit editor, tracker, results, math, code.
// Load order: learn-sim.js → learn-notebook.js → learn.js

const BACKEND_URL =
  (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
    ? 'http://localhost:8000'
    : 'https://quantumcanvas-backend-f6hphzcrejgjbha8.centralus-01.azurewebsites.net';

const NOTEBOOKS = [
  {name:'Challenge 1 · Tutorial 1 — VQE for H₂', url:'notebooks/challenge_1_tutorial_1.ipynb'},
];
const MAX_QUBITS = 6, ORB = 62, CW = 54, RH = 58, MIN_COLS = 12;
const PALETTE = [
  ['Single qubit', ['h','x','y','z','s','t']],
  ['Rotations', ['rx','ry','rz']],
  ['Two qubit', ['cx','cz','swap']],
  ['Readout', ['measure']],
];

const S = {
  n: 2, ops: [], nextId: 1,
  armed: null, pending: null, selected: null, hlQubit: null,
  hist: [], defTheta: {}, loaded: null, counts: null, tab: 'measure',
};

const $ = id => document.getElementById(id);

// ── helpers ──────────────────────────────────────────────────────────
function toast(msg, type=''){
  const t = document.createElement('div'); t.className = 'l-toast '+type; t.textContent = msg;
  $('toasts').appendChild(t); setTimeout(()=>t.remove(), 2600);
}
function setMsg(m){ $('sb-msg').textContent = m; }
function snapshot(){ return JSON.stringify({n:S.n, ops:S.ops, nextId:S.nextId}); }
function pushHist(){ S.hist.push(snapshot()); if(S.hist.length>100) S.hist.shift(); }
function restore(js){ const o = JSON.parse(js); S.n=o.n; S.ops=o.ops; S.nextId=o.nextId; S.selected=null; S.pending=null; S.counts=null; }
function opById(id){ return S.ops.find(o=>o.id===id); }
function wiresOf(o){ return o.g==='block' ? Array.from({length:Math.max(...o.q)-Math.min(...o.q)+1},(_,i)=>Math.min(...o.q)+i) : o.q; }
function occupied(q,c){ return S.ops.some(o=>o.col===c && wiresOf(o).includes(q)); }
function opName(o){
  const L = GATES[o.g].label;
  if(o.g==='block') return `${o.label||'block'} on q${o.q.join(',q')}`;
  if(GATES[o.g].param) return `${L}(${fmtAngle(o.theta||0)}) q${o.q[0]}`;
  return `${L} ${o.q.map(q=>'q'+q).join(', ')}`;
}
function copyText(text, msg){
  const done = ()=>toast(msg||'Copied');
  if(navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done, ()=>fallbackCopy(text, done));
  else fallbackCopy(text, done);
}
function fallbackCopy(text, done){
  const ta = document.createElement('textarea'); ta.value = text; ta.style.position='fixed'; ta.style.opacity='0';
  document.body.appendChild(ta); ta.select();
  try{ document.execCommand('copy'); done(); }catch(e){ toast('Copy failed — select the text manually','err'); }
  ta.remove();
}

// ── palette ──────────────────────────────────────────────────────────
function buildPalette(){
  $('palette').innerHTML = PALETTE.map(([title, gs])=>
    `<div class="l-pal-group">${title}</div><div class="l-pal">` +
    gs.map(g=>`<button class="l-g" draggable="true" data-g="${g}" data-c="${GATES[g].color}" title="${GATES[g].desc}">${GATES[g].label}</button>`).join('') +
    `</div>`).join('');
  $('palette').addEventListener('click', e=>{
    const b = e.target.closest('.l-g'); if(!b) return;
    arm(S.armed === b.dataset.g ? null : b.dataset.g);
  });
  $('palette').addEventListener('dragstart', e=>{
    const b = e.target.closest('.l-g'); if(!b) return;
    e.dataTransfer.setData('text/plain', b.dataset.g); e.dataTransfer.effectAllowed = 'copy';
    arm(b.dataset.g);
  });
}
function arm(g){
  S.armed = g; S.pending = null;
  document.querySelectorAll('.l-g').forEach(b=>b.classList.toggle('armed', b.dataset.g===g));
  $('armed-label').innerHTML = g ? `Armed: <b>${GATES[g].label}</b> — ${GATES[g].desc}${GATES[g].n===2?' (click control, then target in the same column)':''}` : 'No gate selected — pick one on the left';
  renderCircuit();
}

// ── circuit editing ──────────────────────────────────────────────────
function placeAt(g, q, c){
  if(occupied(q,c)){ toast('That slot is taken — pick another column','warn'); return; }
  if(GATES[g].n === 2){
    if(!S.pending || S.pending.c !== c || S.pending.g !== g){
      if(S.n < 2){ toast('Two-qubit gates need at least 2 qubits — add one in the Tracker','warn'); return; }
      S.pending = {g, q, c}; setMsg('Now click the target wire in the same column'); renderCircuit(); return;
    }
    if(S.pending.q === q){ S.pending = null; renderCircuit(); return; }
    const ctrl = S.pending.q; S.pending = null;
    commit({g, q:[ctrl, q], col:c});
    return;
  }
  const op = {g, q:[q], col:c};
  if(GATES[g].param) op.theta = S.defTheta[q] ?? Math.PI/2;
  commit(op);
}
function commit(op){
  pushHist(); op.id = S.nextId++; S.ops.push(op); S.selected = op.id; S.counts = null;
  setMsg(`Added ${opName(op)}`); render();
}
function deleteSelected(){
  if(S.selected==null) return;
  pushHist(); S.ops = S.ops.filter(o=>o.id!==S.selected); S.selected = null; S.counts = null; render();
}
function undo(){
  if(!S.hist.length){ toast('Nothing to undo'); return; }
  restore(S.hist.pop()); render();
}
function setQubits(n){
  if(n<1 || n>MAX_QUBITS){ toast(`Between 1 and ${MAX_QUBITS} qubits`,'warn'); return; }
  pushHist();
  const before = S.ops.length;
  S.ops = S.ops.filter(o=>wiresOf(o).every(q=>q<n) );
  if(before !== S.ops.length) toast(`Removed ${before-S.ops.length} gate(s) on deleted qubits (Undo brings them back)`,'warn');
  S.n = n; S.selected = null; S.pending = null; S.counts = null; S.hlQubit = null; render();
}

function renderCircuit(){
  const maxCol = S.ops.reduce((m,o)=>Math.max(m,o.col),-1);
  const cols = Math.max(MIN_COLS, maxCol+3);
  const el = $('circuit');
  el.style.width = (ORB + cols*CW) + 'px'; el.style.height = (S.n*RH) + 'px';
  if(S.armed) el.dataset.armed = GATES[S.armed].label; else delete el.dataset.armed;
  const p1 = marginalP1(S.n, S.ops);
  const cy = q => q*RH + RH/2, cx = c => ORB + c*CW + CW/2;
  let h = '';
  for(let q=0;q<S.n;q++){
    const hl = S.hlQubit===q ? ' hl' : '';
    const pct = Math.round(p1[q]*100);
    h += `<div class="l-wire${hl}" style="left:${ORB-4}px;top:${cy(q)-1}px;width:${cols*CW+4}px"></div>`;
    h += `<div class="l-orb${hl}" data-orb="${q}" title="q${q}: P(1)=${pct}% — click to highlight this qubit" style="top:${cy(q)-23}px;background:linear-gradient(to top,rgba(0,212,170,.45) ${pct}%,var(--card) ${pct}%)"><span>q${q}</span></div>`;
    for(let c=0;c<cols;c++){
      const pend = S.pending && S.pending.q===q && S.pending.c===c ? ' pending' : '';
      h += `<div class="l-slot${pend}" data-q="${q}" data-c="${c}" data-armed="${S.armed?GATES[S.armed].label:''}" style="left:${ORB+c*CW}px;top:${q*RH}px;width:${CW}px;height:${RH}px"></div>`;
    }
  }
  S.ops.forEach(o=>{
    const sel = o.id===S.selected ? ' sel' : '';
    const g = GATES[o.g];
    if(o.g==='block'){
      const lo = Math.min(...o.q), hi = Math.max(...o.q);
      h += `<div class="l-block${sel}" data-id="${o.id}" title="Not simulated" style="left:${cx(o.col)-22}px;top:${cy(lo)-26}px;width:44px;height:${cy(hi)-cy(lo)+52}px"><span style="writing-mode:vertical-rl">${o.label||'block'}</span></div>`;
    }else if(g.n===1){
      const sub = g.param ? `<small>${fmtAngle(o.theta||0)}</small>` : '';
      h += `<div class="l-gate g-${g.color}${sel}" data-id="${o.id}" title="${g.desc}" style="left:${cx(o.col)-20}px;top:${cy(o.q[0])-20}px">${g.label}${sub}</div>`;
    }else{
      const [a,b] = o.q, lo = Math.min(a,b), hi = Math.max(a,b);
      h += `<div class="l-vline${sel}" data-id="${o.id}" style="left:${cx(o.col)-1}px;top:${cy(lo)}px;height:${cy(hi)-cy(lo)}px"></div>`;
      if(o.g==='swap'){
        [a,b].forEach(w=>h += `<div class="l-swapx${sel}" data-id="${o.id}" style="left:${cx(o.col)-9}px;top:${cy(w)-9}px">×</div>`);
      }else{
        h += `<div class="l-dot${sel}" data-id="${o.id}" style="left:${cx(o.col)-6}px;top:${cy(a)-6}px"></div>`;
        h += o.g==='cx'
          ? `<div class="l-tgt${sel}" data-id="${o.id}" style="left:${cx(o.col)-13}px;top:${cy(b)-13}px"></div>`
          : `<div class="l-dot${sel}" data-id="${o.id}" style="left:${cx(o.col)-6}px;top:${cy(b)-6}px"></div>`;
      }
    }
  });
  el.innerHTML = h;
  $('del-btn').disabled = S.selected==null;
}

function circuitEvents(){
  const el = $('circuit');
  el.addEventListener('click', e=>{
    const orb = e.target.closest('[data-orb]');
    if(orb){ const q = +orb.dataset.orb; S.hlQubit = S.hlQubit===q ? null : q; renderCircuit(); renderTracker(); return; }
    const gate = e.target.closest('[data-id]');
    if(gate){ S.selected = +gate.dataset.id; S.pending=null; render(); return; }
    const slot = e.target.closest('.l-slot');
    if(!slot) return;
    if(!S.armed){ S.selected = null; render(); toast('Pick a gate on the left first','warn'); return; }
    placeAt(S.armed, +slot.dataset.q, +slot.dataset.c);
  });
  el.addEventListener('contextmenu', e=>{
    const gate = e.target.closest('[data-id]'); if(!gate) return;
    e.preventDefault(); S.selected = +gate.dataset.id; deleteSelected();
  });
  el.addEventListener('dragover', e=>{ if(e.target.closest('.l-slot')){ e.preventDefault(); e.dataTransfer.dropEffect='copy'; } });
  el.addEventListener('drop', e=>{
    const slot = e.target.closest('.l-slot'); if(!slot) return;
    e.preventDefault();
    const g = e.dataTransfer.getData('text/plain');
    if(!GATES[g]) return;
    const q = +slot.dataset.q, c = +slot.dataset.c;
    if(GATES[g].n===2){
      // dropped two-qubit gate: control = drop wire, target = neighbouring wire
      const t = q+1<S.n ? q+1 : q-1;
      if(t<0){ toast('Two-qubit gates need at least 2 qubits','warn'); return; }
      if(occupied(q,c) || occupied(t,c)){ toast('That column is taken on one of the wires','warn'); return; }
      commit({g, q:[q,t], col:c});
    }else placeAt(g,q,c);
  });
}

// ── angles (sliders) ─────────────────────────────────────────────────
function renderAngles(){
  const host = $('angles');
  const sel = opById(S.selected);
  const editing = sel && GATES[sel.g].param ? sel : null;
  let h = `<div class="l-ang-h">${editing
    ? `Editing <b>${opName(editing)}</b> — drag to change θ live.`
    : 'Angle for new rotation gates (Rx, Ry, Rz) on each wire. Select a placed rotation to edit it.'}</div>`;
  for(let q=0;q<S.n;q++){
    const act = editing && editing.q[0]===q;
    const th = act ? editing.theta : (S.defTheta[q] ?? Math.PI/2);
    h += `<label class="l-ang${act?' act':''}"><b>q${q}</b><input type="range" min="-32" max="32" step="1" value="${Math.round(th/(Math.PI/16))}" data-q="${q}"><span>θ = ${fmtAngle(th)} (${th.toFixed(2)} rad)</span></label>`;
  }
  host.innerHTML = h;
}
function angleEvents(){
  $('angles').addEventListener('input', e=>{
    const r = e.target.closest('input[type=range]'); if(!r) return;
    const q = +r.dataset.q, th = (+r.value) * Math.PI/16;
    const sel = opById(S.selected);
    if(sel && GATES[sel.g].param && sel.q[0]===q){ sel.theta = th; S.counts = null; renderCircuit(); renderTracker(); renderResults(); renderCode();
      r.nextElementSibling.textContent = `θ = ${fmtAngle(th)} (${th.toFixed(2)} rad)`; }
    else { S.defTheta[q] = th; r.nextElementSibling.textContent = `θ = ${fmtAngle(th)} (${th.toFixed(2)} rad)`; }
  });
  // one undo step per slider drag
  $('angles').addEventListener('pointerdown', e=>{
    const sel = opById(S.selected);
    if(e.target.matches('input[type=range]') && sel && GATES[sel.g].param && sel.q[0]===+e.target.dataset.q) pushHist();
  });
}

// ── tracker ──────────────────────────────────────────────────────────
function renderTracker(){
  $('q-count').textContent = S.n;
  $('step-count').textContent = S.ops.length;
  $('depth').textContent = S.ops.length ? Math.max(...S.ops.map(o=>o.col))+1 : 0;
  $('steps').innerHTML = ordered(S.ops).map(o=>
    `<li data-id="${o.id}" class="${o.id===S.selected?'sel':''}">${opName(o)}</li>`).join('');
  $('sb-right').textContent = `${S.n} qubits · ${S.ops.length} steps`;
}

// ── measurement ──────────────────────────────────────────────────────
function renderResults(){
  const {dist, measured} = distribution(S.n, S.ops);
  const keys = Object.keys(dist).sort();
  const hasBlock = S.ops.some(o=>o.g==='block');
  const total = S.counts ? Object.values(S.counts).reduce((a,b)=>a+b,0) : 0;
  const allKeys = [...new Set([...keys, ...(S.counts?Object.keys(S.counts):[])])].sort();
  let h = `<p class="l-note">${S.ops.length?'':'Empty circuit: all qubits stay in |'+'0'.repeat(S.n)+'⟩. '}Exact probabilities from the statevector${measured?' of the <b>measured</b> qubits':' (no <b>M</b> gate yet, so all qubits are shown)'}. Bitstrings read <b>q${S.n-1} … q0</b> like Qiskit. Press <b>▶ Run</b> to sample shots.</p>`;
  if(hasBlock) h += `<p class="l-note l-warn">⚠ This circuit contains an opaque block (e.g. UCCSD). It is drawn but <b>not simulated</b>, so probabilities cover only the gates around it.</p>`;
  h += '<div class="l-bars">' + allKeys.slice(0,40).map(k=>{
    const p = dist[k]||0, cnt = S.counts?.[k];
    return `<div class="l-bar"><span>|${k}⟩</span><div class="track"><div class="fill" style="width:${(p*100).toFixed(1)}%"></div></div><span>${(p*100).toFixed(1)}%</span><span class="shots">${cnt!=null?cnt:''}</span></div>`;
  }).join('') + '</div>';
  if(S.counts) h += `<p class="l-note" style="margin-top:10px">Amber numbers: ${total} sampled shots (${S.countsFrom}).</p>`;
  $('tab-measure').innerHTML = h;
}

// ── mathematics ──────────────────────────────────────────────────────
function matHtml(rows){
  const cols = rows[0].length;
  return `<div class="l-mat" style="grid-template-columns:repeat(${cols},auto)">${rows.flat().map(c=>`<span>${c}</span>`).join('')}</div>`;
}
const STATIC_MATS = {
  cx:   [['1','0','0','0'],['0','1','0','0'],['0','0','0','1'],['0','0','1','0']],
  cz:   [['1','0','0','0'],['0','1','0','0'],['0','0','1','0'],['0','0','0','−1']],
  swap: [['1','0','0','0'],['0','0','1','0'],['0','1','0','0'],['0','0','0','1']],
};
function ketString(sv, n){
  const terms = sv.map((a,i)=>({a,i})).filter(t=>t.a[0]**2+t.a[1]**2>1e-6);
  if(terms.length>8) return `${terms.length} non-zero amplitudes (see table)`;
  return terms.map(({a,i})=>`${fmtComplex(a)}|${bits(i,n)}⟩`).join(' + ').replace(/\+ −/g,'− ') || '0';
}
function renderMath(){
  const sel = opById(S.selected);
  const seq = ordered(S.ops);
  const upTo = sel ? seq.indexOf(sel)+1 : seq.length;
  const sv = simulate(S.n, S.ops, upTo);
  let h = '<div class="l-math">';
  if(sel){
    const g = GATES[sel.g];
    h += `<h4>Selected gate</h4><div><b>${opName(sel)}</b> — ${g.desc}</div>`;
    if(sel.g==='block') h += `<p class="l-note l-warn">Opaque block: not simulated. In Qiskit Nature this is the <code>UCCSD</code> circuit; see the notebook cell.</p>`;
    else if(sel.g==='measure') h += `<p class="l-note">Measurement collapses q${sel.q[0]} to 0 or 1 with the probabilities in the Measurement tab.</p>`;
    else{
      const M = g.n===1 ? gateMatrix(sel.g, sel.theta||0).map(r=>r.map(fmtComplex)) : STATIC_MATS[sel.g];
      h += `<h4>Matrix</h4>${matHtml(M)}`;
    }
  }else h += `<h4>Tip</h4><p class="l-note">Click a placed gate (or a step in the Tracker) to see its matrix and the state right after it.</p>`;
  h += `<h4>${sel?`State after step ${upTo}`:'Final state'} (q${S.n-1}…q0)</h4><div class="l-ket">|ψ⟩ = ${ketString(sv,S.n)}</div>`;
  h += `<h4>Amplitudes</h4><table class="l-amps"><tr><th>basis</th><th>amplitude</th><th>probability</th></tr>` +
    sv.map((a,i)=>({a,i,p:a[0]**2+a[1]**2})).filter(t=>t.p>1e-9 || S.n<=3)
      .map(t=>`<tr><td>|${bits(t.i,S.n)}⟩</td><td>${fmtComplex(t.a)}</td><td>${(t.p*100).toFixed(2)}%</td></tr>`).join('') + '</table></div>';
  $('tab-math').innerHTML = h;
}

// ── code ─────────────────────────────────────────────────────────────
function renderCode(){
  const code = generateCode(S.n, S.ops);
  $('tab-code').innerHTML = `<div class="l-code-bar"><button class="l-btn sm" id="copy-code">Copy code</button><button class="l-btn sm" id="dl-code">Download .py</button></div>
    <p class="l-note">Paste this into your Colab / JupyterHub cell. Runs of the same gate on qubits 0,1,2… are folded into a <code>for</code> loop.</p>
    <div class="l-code">${highlightPy(code)}</div>`;
  $('copy-code').onclick = ()=>copyText(code,'Qiskit code copied');
  $('dl-code').onclick = downloadPy;
}
function downloadPy(){
  const name = ($('file-name').value.trim() || 'circuit').replace(/[^\w.-]+/g,'_') + '.py';
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([generateCode(S.n,S.ops)],{type:'text/x-python'}));
  a.download = name; a.click(); setTimeout(()=>URL.revokeObjectURL(a.href), 500);
}

// ── run ──────────────────────────────────────────────────────────────
async function run(){
  if(!S.ops.length){ toast('Add some gates first','warn'); return; }
  const shots = 1024, mode = $('backend').value, btn = $('run-btn');
  btn.disabled = true; btn.textContent = '… running';
  try{
    if(mode==='aer'){
      const code = generateCode(S.n, S.ops, {bare:true});
      const body = {canvas_json: JSON.stringify({n:S.n, ops:S.ops}), ir_json: JSON.stringify({kind:'learn', n:S.n, ops:ordered(S.ops).map(({g,q,col,theta})=>({g,q,col,theta}))}),
                    pseudocode_txt:'', qiskit_py: code, backend:'aer', shots};
      const r = await fetch(`${BACKEND_URL}/execute`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
      if(!r.ok) throw new Error((await r.json().catch(()=>({}))).detail || `Server returned ${r.status}`);
      S.counts = (await r.json()).counts; S.countsFrom = 'Qiskit Aer';
    }else{
      S.counts = sample(distribution(S.n,S.ops).dist, shots); S.countsFrom = 'local simulator';
    }
    setMsg(`Ran ${shots} shots on ${S.countsFrom}`); showTab('measure'); renderResults();
  }catch(err){
    toast(`${mode==='aer'?'Aer server not reachable':'Run failed'}: ${err.message}. ${mode==='aer'?'Switch to Local simulator.':''}`,'err');
  }finally{ btn.disabled = false; btn.textContent = '▶ Run'; }
}

// ── notebook → canvas bridge ─────────────────────────────────────────
function loadCircuit(circ, cellIndex){
  pushHist();
  S.n = Math.min(MAX_QUBITS, circ.n);
  S.ops = circ.ops.filter(o=>o.q.every(q=>q<S.n)).map(o=>({...o, id:S.nextId++}));
  S.selected = null; S.pending = null; S.counts = null; S.hlQubit = null;
  S.loaded = {cell:cellIndex, title:circ.title, note:circ.note, skipped:circ.skipped||[], dropped: circ.n>MAX_QUBITS};
  $('file-name').value = `cell${cellIndex}_${(circ.title||'circuit').replace(/[^\w]+/g,'_').replace(/^_|_$/g,'').toLowerCase()}`;
  showBanner(); showTab('measure'); render();
  setMsg(`Loaded cell [${cellIndex}] onto the canvas`);
}
function showBanner(){
  const b = $('banner'), L = S.loaded;
  if(!L){ b.hidden = true; return; }
  b.hidden = false;
  b.innerHTML = `<div><b>From notebook cell [${L.cell}]</b>${L.title?` — ${esc(L.title)}`:''}.
    ${L.note?esc(L.note):'Gate-by-gate view of the cell\'s <code>qc.*</code> lines.'}
    ${L.skipped.length?`<br>Not drawn (not a plain gate call): ${L.skipped.slice(0,4).map(s=>`<code>${esc(s)}</code>`).join(' ')}${L.skipped.length>4?' …':''}`:''}
    ${L.dropped?`<br><span class="l-warn">Circuit has more than ${MAX_QUBITS} qubits; gates on extra qubits were left out.</span>`:''}
    <br>The notebook itself is untouched — edit freely, then copy code from the <i>Qiskit code</i> tab.</div><button aria-label="Dismiss" id="banner-x">×</button>`;
  $('banner-x').onclick = ()=>{ S.loaded=null; Notebook.setLinked(null); showBanner(); };
}

// ── tabs / menu / misc ───────────────────────────────────────────────
function showTab(t){
  S.tab = t;
  document.querySelectorAll('.l-tabs button').forEach(b=>b.classList.toggle('on', b.dataset.tab===t));
  ['measure','math','code'].forEach(k=>$('tab-'+k).hidden = k!==t);
}
function render(){
  renderCircuit(); renderAngles(); renderTracker(); renderResults(); renderMath(); renderCode();
}
function newCircuit(){
  pushHist(); S.n=2; S.ops=[]; S.selected=null; S.pending=null; S.counts=null; S.loaded=null; S.hlQubit=null;
  $('file-name').value = 'untitled-circuit'; Notebook.setLinked(null); showBanner(); render();
}
async function openNotebookFile(file){
  try{
    const nb = JSON.parse(await file.text());
    Notebook.load(nb, file.name); toast(`Opened ${file.name}`);
  }catch(err){ toast('Could not open file: '+err.message,'err'); }
}
async function loadBundled(nbInfo){
  try{ await Notebook.loadUrl(nbInfo.url, nbInfo.url.split('/').pop()); }
  catch(err){
    $('nb-sub').textContent = 'could not load';
    $('nb-cells').innerHTML = `<div class="l-md" style="padding:14px"><p>Could not load the notebook (${esc(err.message)}).</p><p>Serve the <code>frontend/</code> folder over http (e.g. <code>python -m http.server</code>) — browsers block <code>fetch</code> on <code>file://</code>. Or use <b>Files → Open .ipynb</b>.</p></div>`;
  }
}
function menuEvents(){
  const menu = $('menu'), btn = $('menu-btn');
  const toggle = open => { menu.hidden = !open; btn.setAttribute('aria-expanded', String(open)); };
  btn.onclick = e=>{ e.stopPropagation(); toggle(menu.hidden); };
  document.addEventListener('click', e=>{ if(!menu.contains(e.target)) toggle(false); });
  $('menu-notebooks').innerHTML = NOTEBOOKS.map((n,i)=>`<button data-nb="${i}">${n.name}</button>`).join('') +
    '<button data-act="open-file">Open .ipynb from computer…</button>';
  document.addEventListener('click', e=>{
    const nbBtn = e.target.closest('[data-nb]');
    if(nbBtn){ loadBundled(NOTEBOOKS[+nbBtn.dataset.nb]); toggle(false); return; }
    const a = e.target.closest('[data-act]'); if(!a) return;
    const act = a.dataset.act; toggle(false);
    if(act==='open-file') $('file-input').click();
    else if(act==='download-py') downloadPy();
    else if(act==='new') newCircuit();
    else if(act==='tutorial') $('tutorial').hidden = false;
    else if(act==='close-tutorial'){ $('tutorial').hidden = true; try{ localStorage.setItem('qc-learn-seen','1'); }catch(e){} }
  });
  $('file-input').onchange = e=>{ if(e.target.files[0]) openNotebookFile(e.target.files[0]); e.target.value=''; };
}

document.addEventListener('keydown', e=>{
  if(['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName) && e.target.type!=='range') return;
  if((e.ctrlKey||e.metaKey) && e.key.toLowerCase()==='z'){ e.preventDefault(); undo(); return; }
  if(e.key==='Delete' || e.key==='Backspace'){ if(S.selected!=null){ e.preventDefault(); deleteSelected(); } return; }
  if(e.key==='Escape'){ arm(null); S.selected=null; render(); return; }
  const k = e.key.toLowerCase();
  if(!e.ctrlKey && !e.metaKey && !e.altKey && 'hxyzst'.includes(k) && k.length===1) arm(k);
});

window.LearnApp = {copyText, toast, loadCircuit};

document.addEventListener('DOMContentLoaded', ()=>{
  buildPalette(); circuitEvents(); angleEvents(); menuEvents();
  $('q-plus').onclick = ()=>setQubits(S.n+1);
  $('q-minus').onclick = ()=>setQubits(S.n-1);
  $('undo-btn').onclick = undo;
  $('clear-btn').onclick = ()=>{ if(!S.ops.length) return; pushHist(); S.ops=[]; S.selected=null; S.pending=null; S.counts=null; render(); };
  $('del-btn').onclick = deleteSelected;
  $('run-btn').onclick = run;
  $('steps').onclick = e=>{ const li = e.target.closest('li'); if(li){ S.selected = +li.dataset.id; showTab('math'); render(); } };
  document.querySelector('.l-tabs').onclick = e=>{ const b = e.target.closest('button'); if(b) showTab(b.dataset.tab); };
  render();
  loadBundled(NOTEBOOKS[0]);
  let seen = false; try{ seen = localStorage.getItem('qc-learn-seen'); }catch(e){}
  if(!seen) $('tutorial').hidden = false;
});
