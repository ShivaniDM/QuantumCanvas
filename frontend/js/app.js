// QuantumCanvas — canvas state, primitives, rendering engine
// Load order: state.js → ir.js → pseudocode.js → ui.js → qiskit-generator.js → qiskit-panel.js

const state = {
  tool: 'select',
  qubits: [],
  edges: [],
  nextId: 1,
  nextSeq: 0,      // global chronological counter for pseudocode ordering
  dragging: null,
  dragOffset: {x:0,y:0},
  linkSource: null,
};

const STATES = {
  ground:     {label:'|0⟩', amp:'0.00', color:'var(--border)'},
  super:      {label:'|+⟩', amp:'±0.50', color:'var(--teal)'},
  marked:     {label:'|−⟩', amp:'−0.50', color:'var(--rose)'},
  boosted:    {label:'|✓⟩', amp:'+1.00', color:'var(--amber)'},
  entangled:  {label:'|Φ⟩', amp:'corr', color:'var(--violet)'},
  measured:   {label:'|m⟩', amp:'done', color:'var(--dim)'},
};

function getWrap(){return document.getElementById('canvas-wrap')}
function getEdgeLayer(){return document.getElementById('edge-layer')}

function setTool(t){
  state.tool = t;
  state.linkSource = null;
  document.querySelectorAll('.sidebar .tool').forEach(el=>{
    el.classList.toggle('active', (el.dataset.tool===t)||(el.dataset.prim===t));
  });
  document.querySelectorAll('.prim-item').forEach(el=>{
    el.classList.toggle('active-prim', el.id === 'pi-'+t);
  });
  const wrap = getWrap();
  wrap.classList.toggle('select-mode', t==='select');
  wrap.style.cursor = t==='qubit'?'crosshair':t==='select'?'default':'copy';
  document.getElementById('sb-tool').textContent = t;
  if(t==='link') toast('Click source qubit, then target qubit', 'info');
}

function placeQubit(x, y){
  const id = 'q'+state.nextId++;
  const q = {id, x, y, state:'ground', ops:[], label:'Q'+(state.nextId-1)};
  state.qubits.push(q);
  renderQubit(q);
  document.getElementById('hint').style.display='none';
  updateStatus();
  addLog(`placed ${id} at (${Math.round(x)},${Math.round(y)})`, '');
  return q;
}

function renderQubit(q){
  let el = document.getElementById(q.id);
  if(!el){
    el = document.createElement('div');
    el.className = 'qnode';
    el.id = q.id;
    el.innerHTML = `<div class="orb-ring"></div><div class="qlabel">${q.label}</div><div class="amp-display"></div>`;
    el.addEventListener('mousedown', e=>onQMouseDown(e, q.id));
    el.addEventListener('click', e=>onQClick(e, q.id));
    getWrap().appendChild(el);
  }
  el.style.left = q.x+'px';
  el.style.top = q.y+'px';
  el.className = 'qnode state-'+q.state;
  if(q.id === state.selected) el.classList.add('selected');
  el.querySelector('.qlabel').textContent = q.label;
  const st = STATES[q.state];
  el.querySelector('.amp-display').textContent = st ? st.amp : '';
}

function onQMouseDown(e, id){
  if(state.tool !== 'select') return;
  e.stopPropagation();
  const q = state.qubits.find(x=>x.id===id);
  const rect = getWrap().getBoundingClientRect();
  state.dragging = id;
  state.dragOffset = {x: e.clientX - rect.left - q.x, y: e.clientY - rect.top - q.y};
  state.selected = id;
  renderAll();
}

function onQClick(e, id){
  e.stopPropagation();
  if(state.tool === 'select'){
    state.selected = id;
    renderAll();
    return;
  }
  applyPrimitive(state.tool, id);
}

function applyPrimitive(prim, qid){
  const q = state.qubits.find(x=>x.id===qid);
  if(!q) return;

  if(prim === 'shake'){
    if(q.state === 'measured'){
      invalidFlash(qid); toast('Measured qubit cannot be re-used — place a new qubit', 'error'); return;
    }
    if(q.state === 'super' || q.state === 'marked' || q.state === 'boosted'){
      toast('Already in superposition', 'warn'); return;
    }
    q.state = 'super'; q.ops.push({op:'shake', seq:state.nextSeq++});
    addLog(`◎ Shake → ${qid}: equal superposition |+⟩`, 'teal');
    toast('Shaken — all outcomes equally possible', 'valid');
  }
  else if(prim === 'mark'){
    if(q.state === 'ground'){
      invalidFlash(qid); toast('Cannot Mark — Shake first to create superposition', 'error'); return;
    }
    if(q.state === 'measured'){
      invalidFlash(qid); toast('Cannot Mark a measured qubit', 'error'); return;
    }
    if(q.state === 'marked'){
      toast('Already marked', 'warn'); return;
    }
    q.state = 'marked'; q.ops.push({op:'mark', seq:state.nextSeq++});
    addLog(`◈ Mark → ${qid}: phase flipped |−⟩`, 'rose');
    toast('Marked — target hidden-tagged with phase flip', 'valid');
  }
  else if(prim === 'boost'){
    const marked = state.qubits.filter(x=>x.state==='marked');
    if(marked.length === 0){
      invalidFlash(qid); toast('Cannot Boost — no qubit is Marked yet', 'error'); return;
    }
    if(q.state === 'measured'){
      invalidFlash(qid); toast('Cannot Boost a measured qubit', 'error'); return;
    }
    if(q.state === 'ground'){
      invalidFlash(qid); toast('Boost needs superposition — Shake first', 'error'); return;
    }
    // Boost all marked qubits — one user action, shared seq stamp
    const boostSeq = state.nextSeq++;
    state.qubits.forEach(x=>{
      if(x.state==='marked'){x.state='boosted'; x.ops.push({op:'boost', seq:boostSeq});}
      else if(x.state==='super'){x.state='ground'; x.ops.push({op:'boost-collapsed', seq:boostSeq});}
    });
    addLog(`▲ Boost → amplitude amplified, marked item dominates`, 'amber');
    toast('Boosted — marked qubit now at high probability', 'valid');
    checkRunnable();
  }
  else if(prim === 'link'){
    if(!state.linkSource){
      if(q.state === 'ground'){
        invalidFlash(qid); toast('Link source needs Shake first — apply Shake then try Link', 'error'); return;
      }
      if(q.state === 'measured'){
        invalidFlash(qid); toast('Cannot Link from a measured qubit', 'error'); return;
      }
      state.linkSource = qid;
      state.selected = qid;
      toast('Source selected — now click the target qubit', 'info');
      renderAll();
      return;
    } else {
      const src = state.linkSource;
      if(src === qid){ state.linkSource=null; toast('Cannot link a qubit to itself', 'warn'); return; }
      const target = state.qubits.find(x=>x.id===qid);
      if(target.state === 'measured'){
        invalidFlash(qid); state.linkSource=null;
        toast('Cannot Link to a measured qubit — already classical', 'error'); return;
      }
      // existing edge?
      const exists = state.edges.find(e=>(e.src===src&&e.tgt===qid)||(e.src===qid&&e.tgt===src));
      if(exists){ state.linkSource=null; toast('Already linked', 'warn'); return; }
      state.edges.push({src, tgt:qid, type:'entangle'});
      const srcQ = state.qubits.find(x=>x.id===src);
      const linkSeq = state.nextSeq++;
      srcQ.state = 'entangled'; srcQ.ops.push({op:'link', seq:linkSeq});
      target.state = 'entangled'; target.ops.push({op:'link', seq:linkSeq});
      state.linkSource = null;
      addLog(`⋈ Link → ${src}↔${qid}: Bell state |Φ⟩`, 'violet');
      toast('Linked — measuring one determines the other', 'valid');
    }
  }
  else if(prim === 'look'){
    if(q.state === 'ground'){
      toast('Nothing to measure — apply Shake first', 'warn'); return;
    }
    if(q.state === 'measured'){
      toast('Already measured', 'warn'); return;
    }
    const result = measureQubit(q);
    const lookSeq = state.nextSeq++;
    q.state = 'measured'; q.ops.push({op:'look', seq:lookSeq}); q.result = result;
    // Log the measured qubit first — it causes the partner collapse, not the other way round
    addLog(`◙ Look → ${qid} collapsed to |${result}⟩`, '');
    // break entanglement pairs — partner collapses at the same seq instant
    state.edges.forEach(e=>{
      if(e.src===qid||e.tgt===qid){
        const partner = state.qubits.find(x=>x.id===(e.src===qid?e.tgt:e.src));
        if(partner && partner.state==='entangled'){
          partner.state = 'measured';
          partner.result = result === '0' ? '1' : '0'; // correlated
          partner.ops.push({op:'look', seq:lookSeq, correlated:true});
          addLog(`◙ Look → ${partner.id} collapsed to |${partner.result}⟩ (correlated)`, 'violet');
        }
      }
    });
    showResult(qid, result);
    toast(`Measured: ${qid} = |${result}⟩`, 'valid');
  }

  renderAll();
  updateStatus();
}

function measureQubit(q){
  // probability based on state
  if(q.state === 'boosted') return '1'; // high probability
  if(q.state === 'marked') return Math.random() > 0.1 ? '1' : '0';
  if(q.state === 'super') return Math.random() > 0.5 ? '1' : '0';
  if(q.state === 'entangled') return Math.random() > 0.5 ? '1' : '0';
  return '0';
}

function showResult(qid, result){
  const panel = document.getElementById('result-panel');
  const bars = document.getElementById('result-bars');
  const note = document.getElementById('result-note');
  const q = state.qubits.find(x=>x.id===qid);

  let p0, p1, noteText;
  if(q.ops.some(o=>o.op==='boost') || result==='1'){
    p0 = 5; p1 = 95;
    noteText = `<b>Grover-like result</b> — Shake→Mark→Boost→Look found the target`;
  } else if(q.ops.filter(o=>o.op==='shake').length && !q.ops.some(o=>o.op==='mark')){
    p0 = 50; p1 = 50;
    noteText = `<b>Equal superposition</b> — 50/50 without Mark or Boost`;
  } else {
    p0 = result==='0'?80:20; p1 = result==='0'?20:80;
    noteText = `<b>${qid}</b> collapsed to |${result}⟩`;
  }

  bars.innerHTML = `
    <div class="result-bar-wrap">
      <div class="result-bar-val" style="color:var(--teal)">${p0}%</div>
      <div class="result-bar" style="height:${p0*0.5}px;background:var(--teal)"></div>
      <div class="result-bar-lbl">|0⟩</div>
    </div>
    <div class="result-bar-wrap">
      <div class="result-bar-val" style="color:var(--rose)">${p1}%</div>
      <div class="result-bar" style="height:${p1*0.5}px;background:var(--rose)"></div>
      <div class="result-bar-lbl">|1⟩</div>
    </div>`;
  note.innerHTML = noteText;
  panel.style.display = 'block';
}

function runSystem(){
  // auto-run Grover if we have Shake+Mark+Boost path
  const boosted = state.qubits.filter(q=>q.state==='boosted');
  if(boosted.length > 0){
    addLog(`▶ Run — executing Grover sequence`, 'teal');
    addLog(`  50 samples · 1 iteration · 0.021s`, 'teal');
    const runSeq = state.nextSeq++;
    boosted.forEach(q=>{
      q.state='measured'; q.result='1'; q.ops.push({op:'look', seq:runSeq, auto:true});
    });
    state.qubits.filter(q=>q.state==='super').forEach(q=>{
      q.state='measured'; q.result='0'; q.ops.push({op:'look', seq:runSeq + 0.1, auto:true});
    });
    showResult(boosted[0].id, '1');
    renderAll();
    toast('Run complete — result mapped back to canvas', 'valid');
    return;
  }
  toast('Apply Shake → Mark → Boost first, then Run', 'warn');
}

function invalidFlash(qid){
  const el = document.getElementById(qid);
  if(!el) return;
  el.classList.add('invalid-flash');
  setTimeout(()=>el.classList.remove('invalid-flash'),500);
}

function toast(msg, type='valid'){
  const wrap = document.getElementById('toast-wrap');
  const t = document.createElement('div');
  t.className = 'toast '+type;
  t.textContent = msg;
  wrap.appendChild(t);
  requestAnimationFrame(()=>t.classList.add('show'));
  setTimeout(()=>{
    t.classList.remove('show');
    setTimeout(()=>t.remove(),300);
  }, 2800);
}

function addLog(msg, cls=''){
  const log = document.getElementById('state-log');
  const e = document.createElement('div');
  e.className = 'log-entry '+(cls||'');
  const now = new Date();
  e.textContent = `${now.getSeconds().toString().padStart(2,'0')}:${now.getMilliseconds().toString().padStart(3,'0')} ${msg}`;
  log.appendChild(e);
  log.scrollTop = log.scrollHeight;
}

function renderAll(){
  state.qubits.forEach(q=>renderQubit(q));
  renderEdges();
  checkRunnable();
}

function renderEdges(){
  const svg = getEdgeLayer();
  const rect = getWrap().getBoundingClientRect();
  svg.setAttribute('width', rect.width);
  svg.setAttribute('height', rect.height);
  svg.innerHTML = `<defs><marker id="ea" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></marker></defs>`;
  state.edges.forEach(e=>{
    const s = state.qubits.find(x=>x.id===e.src);
    const t = state.qubits.find(x=>x.id===e.tgt);
    if(!s||!t) return;
    const line = document.createElementNS('http://www.w3.org/2000/svg','line');
    line.setAttribute('x1',s.x); line.setAttribute('y1',s.y);
    line.setAttribute('x2',t.x); line.setAttribute('y2',t.y);
    line.setAttribute('stroke','#9B6DFF');
    line.setAttribute('stroke-width','1.5');
    line.setAttribute('stroke-dasharray','5 4');
    line.setAttribute('opacity','.6');
    line.setAttribute('marker-end','url(#ea)');
    svg.appendChild(line);
  });
  // link preview
  if(state.linkSource){
    const s = state.qubits.find(x=>x.id===state.linkSource);
    if(s && state._mousePos){
      const line = document.createElementNS('http://www.w3.org/2000/svg','line');
      line.setAttribute('x1',s.x); line.setAttribute('y1',s.y);
      line.setAttribute('x2',state._mousePos.x); line.setAttribute('y2',state._mousePos.y);
      line.setAttribute('stroke','#9B6DFF');
      line.setAttribute('stroke-width','1');
      line.setAttribute('stroke-dasharray','4 4');
      line.setAttribute('opacity','.4');
      svg.appendChild(line);
    }
  }
}

function checkRunnable(){
  const hasSequence = state.qubits.some(q=>q.ops.some(o=>o.op==='shake'));
  const hasBoosted  = state.qubits.some(q=>q.state==='boosted');
  document.getElementById('run-btn').disabled  = !hasBoosted && !hasSequence;
  document.getElementById('pc-btn').disabled   = !hasSequence;
  const execBtn = document.getElementById('exec-btn');
  if(execBtn) execBtn.disabled = !hasSequence;
  const valid = state.qubits.filter(q=>q.ops.some(o=>o.op==='shake')).length;
  document.getElementById('sb-valid').textContent = valid;
}

function updateStatus(){
  const n = state.qubits.length;
  document.getElementById('qubit-count').textContent = n;
  document.getElementById('sb-qubits').textContent = n;
  if(n===0) document.getElementById('tb-status').innerHTML = '<b>0</b> qubits · select a primitive to begin';
  else {
    const states = [...new Set(state.qubits.map(q=>q.state))].join(', ');
    document.getElementById('tb-status').innerHTML = `<b>${n}</b> qubits · states: ${states}`;
  }
  if(n > 0) document.getElementById('hint').style.display='none';
}

function clearCanvas(){
  state.qubits.forEach(q=>{
    const el = document.getElementById(q.id);
    if(el) el.remove();
  });
  state.qubits = [];
  state.edges = [];
  state.linkSource = null;
  state.nextSeq = 0;
  state.selected = null;
  getEdgeLayer().innerHTML = '';
  document.getElementById('hint').style.display='';
  document.getElementById('result-panel').style.display='none';
  document.getElementById('state-log').innerHTML='<div class="log-entry" style="opacity:.4">— canvas cleared —</div>';
  updateStatus();
  checkRunnable();
}

// canvas click — place qubit
document.getElementById('canvas-wrap').addEventListener('click', e=>{
  if(state.tool !== 'qubit') return;
  const rect = e.currentTarget.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;
  placeQubit(x, y);
});

// drag
document.addEventListener('mousemove', e=>{
  const wrap = getWrap();
  const rect = wrap.getBoundingClientRect();
  state._mousePos = {x: e.clientX-rect.left, y: e.clientY-rect.top};
  if(state.linkSource) renderEdges();
  if(!state.dragging) return;
  const q = state.qubits.find(x=>x.id===state.dragging);
  if(!q) return;
  q.x = e.clientX - rect.left - state.dragOffset.x;
  q.y = e.clientY - rect.top - state.dragOffset.y;
  renderQubit(q);
  renderEdges();
});
document.addEventListener('mouseup', ()=>{ state.dragging=null; });

// keyboard shortcuts
document.addEventListener('keydown', e=>{
  const map = {'s':'select','q':'qubit','1':'shake','2':'mark','3':'boost','4':'link','5':'look','Escape':'select'};
  if(e.target.tagName==='INPUT') return;
  if(map[e.key]) setTool(map[e.key]);
  if(e.key==='Delete'||e.key==='Backspace'){
    if(state.selected){
      const idx = state.qubits.findIndex(x=>x.id===state.selected);
      if(idx>-1){
        const el = document.getElementById(state.selected);
        if(el) el.remove();
        state.edges = state.edges.filter(e=>e.src!==state.selected&&e.tgt!==state.selected);
        state.qubits.splice(idx,1);
        state.selected=null;
        renderEdges(); updateStatus();
      }
    }
  }
});

// init
toast('Place qubits with ⊕, then apply Shake → Mark → Boost → Look', 'info');
// QuantumCanvas — Internal Representation extractor and validator
// Load order: state.js → ir.js → pseudocode.js → ui.js → qiskit-generator.js → qiskit-panel.js

// ════════════════════════════════════════════════════════════════════
//  QUANTUMCANVAS PSEUDOCODE ENGINE  v1.0
//  Canvas → IR → Validation → Pseudocode → Review Panel
// ════════════════════════════════════════════════════════════════════

const PC_VALID_OPS = ['shake','mark','boost','link','look'];

// ── IR Extraction ────────────────────────────────────────────────────
function extractCanvasIR(s) {
  const n = s.qubits.length;

  // Build per-qubit records, normalising both old string ops and new {op,seq} objects
  const qubits = s.qubits.map(q => {
    const raw = (q.ops||[]).map(o => typeof o==='string' ? {op:o, seq:null} : o);
    const ops = raw.filter(o => PC_VALID_OPS.includes(o.op));

    const edge = s.edges.find(e => e.src===q.id || e.tgt===q.id);
    const partner = edge ? (edge.src===q.id ? edge.tgt : edge.src) : null;

    return {
      id: q.id, label: q.label||q.id.toUpperCase(),
      pos: {x:Math.round(q.x), y:Math.round(q.y)},
      final_state: q.state,
      // plain op names for validation
      ops: ops.map(o=>o.op),
      // full tagged entries for log reconstruction
      taggedOps: ops,
      result: q.result??null, partner
    };
  });

  const edges = s.edges.map((e,i) => ({
    id:`e${i+1}`, src:e.src, tgt:e.tgt, type:e.type||'entangle'
  }));

  // Build globalLog: collect every tagged op from every qubit, sort by seq.
  // Ops without a seq (legacy string format) fall back to per-qubit order via index.
  const allEntries = [];
  qubits.forEach(q => {
    q.taggedOps.forEach((tagged, i) => {
      allEntries.push({
        qubit: q.id,
        op: tagged.op,
        seq: tagged.seq ?? (i * 0.001),   // legacy fallback — keeps rough per-qubit order
        correlated: tagged.correlated ?? false,
        auto: tagged.auto ?? false,
      });
    });
  });
  allEntries.sort((a,b) => a.seq !== b.seq ? a.seq - b.seq : (a.correlated ? 1 : -1));
  const globalLog = allEntries.map((e,i) => ({ step:i+1, qubit:e.qubit, op:e.op, correlated:e.correlated, auto:e.auto }));

  const N = Math.pow(2,n);
  const optimal = Math.max(1, Math.round(Math.PI/4*Math.sqrt(N)));

  return { n, N, optimal, qubits, edges, globalLog, validation:null };
}

// ── Validation ───────────────────────────────────────────────────────
function validateIR(ir) {
  const errs=[], warns=[];
  const E = (rule, qid, msg, plain, fix) =>
    errs.push({rule, qid, msg, plain, fix});
  const W = (rule, qid, msg, plain, fix) =>
    warns.push({rule, qid, msg, plain, fix});

  if(ir.n===0){
    E('GV-03',null,'Canvas is empty.',
      'Place at least one qubit before generating pseudocode.',
      'Use ⊕ Qubit tool then apply Shake.');
    return _finishVal(ir,errs,warns);
  }
  if(!ir.qubits.some(q=>q.ops.length>0)){
    E('GV-04',null,'No operations applied.',
      'Qubits exist but no primitive has been applied. Shake a qubit to begin.',
      'Select ◎ Shake and click a qubit.');
    return _finishVal(ir,errs,warns);
  }

  ir.qubits.forEach(q => {
    const ops=q.ops;
    if(!ops.length) return;
    const idx=op=>ops.indexOf(op);
    const has=op=>ops.includes(op);

    // QV-01: shake before mark
    if(has('mark') && (!has('shake') || idx('shake')>idx('mark')))
      E('QV-01',q.id,
        `${q.label}: Mark before Shake.`,
        `You tagged ${q.label} as a target before spreading it into superposition. The phase oracle needs a quantum state to act on — ground state has nothing to flip.`,
        `Apply Shake to ${q.label} first, then Mark.`);

    // QV-03: look is terminal
    if(has('look')){
      const after=ops.slice(idx('look')+1).filter(o=>PC_VALID_OPS.includes(o));
      if(after.length)
        E('QV-03',q.id,
          `${q.label}: Operation after Look — [${after.join(', ')}].`,
          `${q.label} was measured and then you applied more operations. Once measured it is a classical bit — no quantum operations can follow.`,
          `Remove operations after Look on ${q.label}.`);
    }

    // QV-04: shake before link (as source)
    const isLinkSrc = ir.edges.some(e=>e.src===q.id);
    if(isLinkSrc && has('link') && (!has('shake')||idx('shake')>idx('link')))
      E('QV-04',q.id,
        `${q.label}: Link source used before Shake.`,
        `Entanglement needs ${q.label} in superposition. A ground-state qubit creates classical correlation, not quantum entanglement.`,
        `Shake ${q.label} before using it as a Link source.`);

    // QV-05: link target not already measured
    const isLinkTgt = ir.edges.some(e=>e.tgt===q.id);
    if(isLinkTgt && has('look') && has('link') && idx('look')<idx('link'))
      E('QV-05',q.id,
        `${q.label}: Measured before entangled.`,
        `${q.label} was measured before being linked. Classical bits cannot be entangled.`,
        `Apply Link before Look on ${q.label}.`);
  });

  // GV-01: boost with no mark anywhere
  const anyBoosted = ir.qubits.some(q=>q.ops.includes('boost'));
  const anyMarked  = ir.qubits.some(q=>q.ops.includes('mark'));
  if(anyBoosted && !anyMarked)
    E('GV-01',null,'Boost with no marked qubit.',
      'Amplitude amplification needs a target to amplify. Without Mark, all amplitudes are equal — Boost cancels itself out.',
      'Apply Mark to at least one qubit before Boost.');

  // GV-02: over-boosted
  if(anyBoosted){
    const boostCount = ir.qubits.reduce((a,q)=>a+q.ops.filter(o=>o==='boost').length,0);
    if(boostCount > ir.optimal)
      W('GV-02',null,
        `Boost applied ${boostCount}×; optimal for a ${Math.pow(2,ir.n)}-state search space is ${ir.optimal}×.`,
        `After the optimal boost count (${ir.optimal}×) the marked item's probability reverses. You have applied Boost ${boostCount} times — the target is losing probability.`,
        `Re-run with ${ir.optimal} Boost step${ir.optimal>1?'s':''}.`);
  }

  return _finishVal(ir,errs,warns);
}

function _detectPattern(ir){
  const all  = qbs => qbs.every(q=>q.ops.includes('shake'));
  const any  = op  => ir.qubits.some(q=>q.ops.includes(op));
  const linked = ir.edges.length>0;
  if(ir.n===0) return 'empty';
  if(linked && !any('mark') && !any('boost')) return 'bell_pair';
  if(any('mark') && any('boost') && linked) return 'entangled_search';
  if(any('mark') && any('boost')) return 'grover_like';
  if(any('mark') && !any('boost')) return 'marked_no_boost';
  if(all(ir.qubits) && !any('mark')) return 'superposition_only';
  return 'mixed';
}

function _finishVal(ir,errs,warns){
  ir.validation={
    ok: errs.length===0, errs, warns,
    pattern: _detectPattern(ir),
  };
  return ir;
}
/* QuantumCanvas — pseudocode panel, Qiskit panel */

/* ══════════════════════════════════════════════════════════
   PSEUDOCODE ENGINE — styles
   ══════════════════════════════════════════════════════════ */

/* topbar button */
.pc-btn {
  padding: 6px 14px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--gray);
  font-family: 'DM Sans', sans-serif;
  font-size: .8rem;
  font-weight: 500;
  cursor: pointer;
  transition: all .15s;
  letter-spacing: .02em;
}
.pc-btn:hover { border-color: var(--violet); color: var(--violet); background: var(--violet2); }
.pc-btn:disabled { opacity: .3; cursor: default; }

/* overlay */
#pc-overlay {
  position: absolute; inset: 0;
  background: rgba(10,12,20,.82);
  z-index: 200; display: none;
  align-items: flex-start; justify-content: center;
  padding: 20px; overflow-y: auto;
}
#pc-overlay.open { display: flex; }

/* panel */
#pc-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  width: 100%; max-width: 580px;
  flex-shrink: 0; overflow: hidden;
  box-shadow: 0 24px 64px rgba(0,0,0,.6);
}

.pc-header {
  display: flex; align-items: flex-start;
  justify-content: space-between;
  padding: 14px 16px 10px;
  border-bottom: 1px solid var(--border);
}
.pc-title-block { flex: 1; }
.pc-label {
  font-family: 'Space Mono', monospace;
  font-size: .6rem; color: var(--gray);
  letter-spacing: .12em; text-transform: uppercase; margin-bottom: 3px;
}
.pc-title { font-size: .95rem; font-weight: 500; color: var(--white); margin-bottom: 2px; }
.pc-meta  { font-family: 'Space Mono', monospace; font-size: .65rem; color: var(--gray); }
.pc-close {
  background: none; border: none; color: var(--gray);
  font-size: 1.1rem; cursor: pointer; padding: 0 4px;
  line-height: 1; transition: color .15s;
}
.pc-close:hover { color: var(--white); }

/* violation / warning cards */
.pc-violations {
  padding: 10px 14px; border-bottom: 1px solid var(--border);
  display: flex; flex-direction: column; gap: 6px;
}
.pc-vcard {
  border-radius: 6px; padding: 9px 11px; font-size: .78rem;
}
.pc-vcard.error   { background: rgba(255,107,157,.08); border: 1px solid rgba(255,107,157,.25); color: var(--rose); }
.pc-vcard.warning { background: rgba(255,184,77,.08);  border: 1px solid rgba(255,184,77,.25);  color: var(--amber); }
.pc-vcard-rule  { font-family: 'Space Mono', monospace; font-size: .62rem; opacity: .7; margin-bottom: 3px; }
.pc-vcard-msg   { font-weight: 500; margin-bottom: 3px; }
.pc-vcard-plain { font-size: .73rem; opacity: .85; margin-bottom: 4px; line-height: 1.5; }
.pc-vcard-fix   { font-size: .68rem; font-family: 'Space Mono', monospace; opacity: .7; }

/* steps */
.pc-steps { padding: 4px 0; }
.pc-step {
  display: flex;
  border-bottom: 1px solid var(--border);
}
.pc-step:last-child { border-bottom: none; }
.pc-step.dimmed { opacity: .3; }

.pc-stripe { width: 3px; flex-shrink: 0; }
.s-init    { background: var(--border); }
.s-shake   { background: var(--teal); }
.s-mark    { background: var(--rose); }
.s-boost   { background: var(--amber); }
.s-link    { background: var(--violet); }
.s-look    { background: var(--gray); }

.pc-step-body { padding: 10px 14px; flex: 1; min-width: 0; }
.pc-step-num  {
  font-family: 'Space Mono', monospace;
  font-size: .58rem; color: var(--gray); margin-bottom: 3px; text-transform: uppercase; letter-spacing: .06em;
}
.pc-step-code {
  font-family: 'Space Mono', monospace;
  font-size: .76rem; color: var(--white); margin-bottom: 4px;
  word-break: break-all; line-height: 1.5;
}
.pc-step-plain  { font-size: .76rem; color: var(--gray); line-height: 1.55; margin-bottom: 4px; }
.pc-qnote-btn {
  font-family: 'Space Mono', monospace; font-size: .6rem;
  color: var(--dim); cursor: pointer; border: none;
  background: none; padding: 0; transition: color .15s;
}
.pc-qnote-btn:hover { color: var(--gray); }
.pc-qnote {
  font-family: 'Space Mono', monospace; font-size: .65rem;
  color: var(--gray); margin-top: 5px; display: none; line-height: 1.6;
  border-left: 2px solid var(--border); padding-left: 8px;
}
.pc-qnote.open { display: block; }

/* summary table */
.pc-summary { border-top: 1px solid var(--border); padding: 10px 14px; }
.pc-sum-head {
  font-family: 'Space Mono', monospace; font-size: .6rem;
  color: var(--gray); text-transform: uppercase; letter-spacing: .1em; margin-bottom: 7px;
}
.pc-tbl { width: 100%; border-collapse: collapse; font-size: .72rem; }
.pc-tbl th {
  text-align: left; font-family: 'Space Mono', monospace; font-size: .58rem;
  color: var(--gray); text-transform: uppercase; letter-spacing: .08em;
  padding: 3px 6px; border-bottom: 1px solid var(--border);
}
.pc-tbl td {
  padding: 5px 6px; color: var(--white);
  border-bottom: 1px solid rgba(30,37,64,.5);
  font-family: 'Space Mono', monospace; font-size: .68rem;
}
.pc-tbl tr:last-child td { border-bottom: none; }
.sbadge {
  display: inline-block; padding: 1px 7px; border-radius: 20px;
  font-size: .58rem; font-weight: 500;
}
.sb-boosted   { background: var(--amber2); color: var(--amber); }
.sb-measured  { background: rgba(46,53,80,.6); color: var(--gray); }
.sb-super     { background: var(--teal2); color: var(--teal); }
.sb-marked    { background: var(--rose2); color: var(--rose); }
.sb-entangled { background: var(--violet2); color: var(--violet); }
.sb-ground    { background: var(--card); color: var(--gray); }

/* pattern note */
.pc-pattern {
  font-size: .72rem; color: var(--gray); font-style: italic;
  padding: 8px 14px; border-top: 1px solid var(--border); line-height: 1.55;
}

/* footer */
.pc-footer {
  padding: 12px 14px; border-top: 1px solid var(--border);
  display: flex; gap: 8px; align-items: center;
}
.pc-qiskit-btn {
  padding: 8px 18px; border-radius: 6px;
  border: 1px solid var(--teal); background: var(--teal2);
  color: var(--teal); font-family: 'DM Sans', sans-serif;
  font-size: .8rem; font-weight: 500; cursor: pointer;
  transition: background .15s; letter-spacing: .04em;
}
.pc-qiskit-btn:hover { background: rgba(0,212,170,.2); }
.pc-qiskit-btn:disabled {
  opacity: .35; cursor: default;
  border-color: var(--border); color: var(--gray); background: transparent;
}
.pc-footer-cancel {
  padding: 8px 14px; border-radius: 6px;
  border: 1px solid var(--border); background: transparent;
  color: var(--gray); font-family: 'DM Sans', sans-serif;
  font-size: .8rem; cursor: pointer; transition: all .15s;
}
.pc-footer-cancel:hover { border-color: var(--gray); color: var(--white); }
.pc-status {
  font-family: 'Space Mono', monospace; font-size: .65rem; margin-left: auto;
}
.pc-status.ok   { color: var(--teal); }
.pc-status.warn { color: var(--amber); }
.pc-status.err  { color: var(--rose); }

/* raw timeline */
.pc-timeline { padding: 10px 14px; border-bottom: 1px solid var(--border); }
.pc-tl-head {
  font-family: 'Space Mono', monospace; font-size: .6rem; color: var(--gray);
  text-transform: uppercase; letter-spacing: .1em; margin-bottom: 0;
  display: flex; align-items: center; gap: 6px; cursor: pointer; user-select: none;
}
.pc-tl-head:hover { color: var(--white); }
.pc-tl-list {
  display: none; margin-top: 6px;
  font-family: 'Space Mono', monospace; font-size: .68rem; line-height: 1.85;
}
.pc-tl-list.open { display: block; }
.pc-tl-row { display: flex; gap: 8px; align-items: baseline; }
.pc-tl-n { color: var(--dim); min-width: 16px; font-size: .58rem; text-align: right; flex-shrink: 0; }
.pc-tl-op { font-weight: 700; }
.tl-shake { color: var(--teal); }
.tl-mark  { color: var(--rose); }
.tl-boost { color: var(--amber); }
.tl-link  { color: var(--violet); }
.tl-look  { color: var(--gray); }
.pc-tl-detail { color: var(--dim); font-size: .65rem; }

/* ── Qiskit panel ── */
.qk-code-wrap {
  border-top: 1px solid var(--border);
  background: #0d1117;
}
.qk-toolbar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 6px 14px;
  border-bottom: 1px solid rgba(255,255,255,.06);
}
.qk-lang-badge {
  font-family: 'Space Mono', monospace; font-size: .6rem;
  color: var(--gray); letter-spacing: .08em;
}
.qk-copy-btn {
  font-family: 'Space Mono', monospace; font-size: .65rem;
  background: none; border: 1px solid var(--border);
  color: var(--gray); border-radius: 4px; padding: 2px 10px;
  cursor: pointer; transition: all .15s;
}
.qk-copy-btn:hover { border-color: var(--teal); color: var(--teal); }
.qk-pre {
  margin: 0; padding: 14px 16px;
  font-family: 'Space Mono', monospace; font-size: .72rem;
  line-height: 1.7; color: #e6edf3;
  overflow-x: auto; white-space: pre;
  max-height: 360px; overflow-y: auto;
}
/* syntax colours */
.qk-kw { color: #ff7b72; }   /* keywords */
.qk-bi { color: #79c0ff; }   /* builtins / classes */
.qk-fn { color: #d2a8ff; }   /* method names */
.qk-s  { color: #a5d6ff; }   /* strings */
.qk-n  { color: #f2cc60; }   /* numbers */
.qk-c  { color: #6e7681; }   /* comments */

/* mapping table */
.qk-map-section {
  border-top: 1px solid var(--border);
  padding: 10px 14px;
}
.qk-map-head {
  font-family: 'Space Mono', monospace; font-size: .6rem;
  color: var(--gray); text-transform: uppercase; letter-spacing: .1em;
  margin-bottom: 7px;
}
.qk-map-tbl { width: 100%; border-collapse: collapse; font-size: .72rem; }
.qk-map-tbl th {
  text-align: left; font-family: 'Space Mono', monospace;
  font-size: .58rem; color: var(--gray); text-transform: uppercase;
  letter-spacing: .08em; padding: 3px 8px;
  border-bottom: 1px solid var(--border);
}
.qk-map-tbl td {
  padding: 5px 8px; color: var(--white);
  border-bottom: 1px solid rgba(30,37,64,.5);
  font-size: .72rem;
}
.qk-map-tbl tr:last-child td { border-bottom: none; }
.qk-map-tbl code {
  font-family: 'Space Mono', monospace; font-size: .68rem;
  color: var(--violet); background: var(--violet2);
  padding: 1px 5px; border-radius: 3px;
}
.qk-impl { color: var(--teal); font-size: .68rem; }

/* collab button */
.qk-collab-btn {
  padding: 8px 14px; border-radius: 6px;
  border: 1px solid var(--violet); background: var(--violet2);
  color: var(--violet); font-family: 'DM Sans', sans-serif;
  font-size: .8rem; font-weight: 500; cursor: pointer;
  transition: all .15s; letter-spacing: .02em;
}
.qk-collab-btn:hover { background: rgba(155,109,255,.2); }

/* ── Execute button (topbar) ── */
.exec-btn {
  padding: 6px 14px;
  border-radius: 6px;
  border: 1px solid var(--teal);
  background: var(--teal2);
  color: var(--teal);
  font-family: 'DM Sans', sans-serif;
  font-size: .8rem;
  font-weight: 500;
  cursor: pointer;
  transition: all .15s;
  letter-spacing: .02em;
}
.exec-btn:hover { background: rgba(0,212,170,.2); }
.exec-btn:disabled { opacity: .3; cursor: default; background: transparent; border-color: var(--border); color: var(--gray); }

/* ── Execute overlay panel ── */
#exec-overlay {
  position: absolute; inset: 0;
  background: rgba(10,12,20,.88);
  z-index: 210; display: none;
  align-items: flex-start; justify-content: center;
  padding: 20px; overflow-y: auto;
}
#exec-overlay.open { display: flex; }
#exec-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  width: 100%; max-width: 600px;
  flex-shrink: 0; overflow: hidden;
  box-shadow: 0 24px 64px rgba(0,0,0,.7);
}

/* execute panel sections */
.exec-header {
  display: flex; align-items: flex-start; justify-content: space-between;
  padding: 14px 16px 10px; border-bottom: 1px solid var(--border);
}
.exec-title-block { flex: 1; }
.exec-label {
  font-family: 'Space Mono', monospace; font-size: .6rem; color: var(--gray);
  text-transform: uppercase; letter-spacing: .12em; margin-bottom: 3px;
}
.exec-title { font-size: .95rem; font-weight: 500; color: var(--white); margin-bottom: 2px; }
.exec-meta  { font-family: 'Space Mono', monospace; font-size: .65rem; color: var(--gray); }
.exec-close {
  background: none; border: none; color: var(--gray);
  font-size: 1.1rem; cursor: pointer; padding: 0 4px; line-height: 1; transition: color .15s;
}
.exec-close:hover { color: var(--white); }

/* pipeline steps */
.exec-pipeline {
  padding: 12px 14px; border-bottom: 1px solid var(--border);
  display: flex; gap: 0; align-items: center;
}
.exec-pipe-step {
  display: flex; flex-direction: column; align-items: center; gap: 3px;
  flex: 1;
}
.exec-pipe-dot {
  width: 28px; height: 28px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: .7rem; font-weight: 700; border: 2px solid var(--border);
  font-family: 'Space Mono', monospace; color: var(--gray);
  transition: all .3s;
}
.exec-pipe-dot.done  { border-color: var(--teal);   color: var(--teal);   background: var(--teal2); }
.exec-pipe-dot.active{ border-color: var(--amber);  color: var(--amber);  background: var(--amber2); }
.exec-pipe-dot.error { border-color: var(--rose);   color: var(--rose);   background: var(--rose2); }
.exec-pipe-lbl {
  font-family: 'Space Mono', monospace; font-size: .55rem;
  color: var(--gray); text-align: center; line-height: 1.3;
}
.exec-pipe-arrow { color: var(--border); font-size: .75rem; flex-shrink: 0; margin: 0 2px; padding-bottom: 14px; }

/* backend selector */
.exec-backends {
  padding: 10px 14px; border-bottom: 1px solid var(--border);
  display: flex; gap: 8px;
}
.exec-backend-btn {
  flex: 1; padding: 10px 8px; border-radius: 7px;
  border: 1px solid var(--border); background: var(--card);
  cursor: pointer; transition: all .15s; text-align: center;
}
.exec-backend-btn:hover { border-color: var(--gray); }
.exec-backend-btn.selected { border-color: var(--teal); background: var(--teal2); }
.exec-backend-btn.disabled-backend { opacity: .4; cursor: default; }
.exec-be-name  { font-family: 'Space Mono', monospace; font-size: .72rem; color: var(--white); margin-bottom: 2px; }
.exec-be-desc  { font-size: .65rem; color: var(--gray); }
.exec-be-badge {
  display: inline-block; font-size: .55rem; padding: 1px 6px; border-radius: 20px;
  margin-top: 4px; font-family: 'Space Mono', monospace;
}
.badge-avail  { background: var(--teal2);   color: var(--teal); }
.badge-queue  { background: var(--amber2);  color: var(--amber); }
.badge-unavail{ background: var(--rose2);   color: var(--rose); }

/* shots / job status */
.exec-config {
  padding: 10px 14px; border-bottom: 1px solid var(--border);
  display: flex; gap: 14px; align-items: center;
}
.exec-config-label {
  font-family: 'Space Mono', monospace; font-size: .65rem; color: var(--gray);
}
.exec-shots-input {
  font-family: 'Space Mono', monospace; font-size: .75rem;
  background: var(--card); border: 1px solid var(--border);
  color: var(--white); border-radius: 5px; padding: 4px 8px; width: 80px;
}
.exec-shots-input:focus { outline: none; border-color: var(--teal); }

/* results */
.exec-results {
  padding: 10px 14px; border-bottom: 1px solid var(--border);
  min-height: 60px; display: none;
}
.exec-results.visible { display: block; }
.exec-results-head {
  font-family: 'Space Mono', monospace; font-size: .6rem; color: var(--gray);
  text-transform: uppercase; letter-spacing: .1em; margin-bottom: 8px;
}
.exec-bar-row {
  display: flex; align-items: center; gap: 8px; margin-bottom: 5px;
}
.exec-bar-state { font-family: 'Space Mono', monospace; font-size: .68rem; color: var(--gray); min-width: 36px; }
.exec-bar-track { flex: 1; height: 14px; background: var(--card); border-radius: 3px; overflow: hidden; }
.exec-bar-fill  { height: 100%; border-radius: 3px; transition: width .6s cubic-bezier(.4,0,.2,1); }
.exec-bar-pct   { font-family: 'Space Mono', monospace; font-size: .65rem; color: var(--white); min-width: 38px; text-align: right; }

/* job log */
.exec-log {
  padding: 8px 14px; border-bottom: 1px solid var(--border);
  font-family: 'Space Mono', monospace; font-size: .65rem; color: var(--gray);
  max-height: 120px; overflow-y: auto; line-height: 1.8; min-height: 30px;
}
.exec-log-line { margin: 0; }
.exec-log-line.ok   { color: var(--teal); }
.exec-log-line.warn { color: var(--amber); }
.exec-log-line.err  { color: var(--rose); }

/* footer */
.exec-footer {
  padding: 12px 14px; display: flex; gap: 8px; align-items: center;
}
.exec-run-sim-btn {
  padding: 8px 16px; border-radius: 6px;
  border: 1px solid var(--teal); background: var(--teal2);
  color: var(--teal); font-family: 'DM Sans', sans-serif; font-size: .8rem;
  font-weight: 500; cursor: pointer; transition: all .15s; letter-spacing: .03em;
}
.exec-run-sim-btn:hover   { background: rgba(0,212,170,.2); }
.exec-run-sim-btn:disabled{ opacity:.35; cursor:default; border-color:var(--border); color:var(--gray); background:transparent; }
.exec-run-hw-btn {
  padding: 8px 16px; border-radius: 6px;
  border: 1px solid var(--violet); background: var(--violet2);
  color: var(--violet); font-family: 'DM Sans', sans-serif; font-size: .8rem;
  font-weight: 500; cursor: pointer; transition: all .15s; letter-spacing: .03em;
}
.exec-run-hw-btn:hover   { background: rgba(155,109,255,.2); }
.exec-run-hw-btn:disabled{ opacity:.35; cursor:default; border-color:var(--border); color:var(--gray); background:transparent; }
.exec-cancel-btn {
  padding: 8px 12px; border-radius: 6px;
  border: 1px solid var(--border); background: transparent;
  color: var(--gray); font-family: 'DM Sans', sans-serif; font-size: .8rem;
  cursor: pointer; transition: all .15s;
}
.exec-cancel-btn:hover { border-color: var(--gray); color: var(--white); }
.exec-save-note { font-family: 'Space Mono', monospace; font-size: .6rem; color: var(--dim); margin-left: auto; }

/* ── QPU cost card ── */
.exec-qpu-card {
  margin: 0; border-top: 1px solid var(--border);
  padding: 12px 14px;
  background: linear-gradient(135deg, rgba(155,109,255,.06) 0%, rgba(0,212,170,.04) 100%);
}
.exec-qpu-card-inner {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  margin-bottom: 8px;
}
.exec-qpu-left { flex: 1; }
.exec-qpu-title {
  font-size: .85rem; font-weight: 500; color: var(--white); margin-bottom: 3px;
}
.exec-qpu-sub {
  font-family: 'Space Mono', monospace; font-size: .62rem;
  color: var(--gray); margin-bottom: 6px;
}
.exec-qpu-cost { font-size: .8rem; }
.exec-cost-num  { font-weight: 700; color: var(--amber); font-size: .95rem; }
.exec-cost-note { font-family: 'Space Mono', monospace; font-size: .65rem; color: var(--gray); }
.exec-qpu-right { display: flex; flex-direction: column; gap: 6px; flex-shrink: 0; }
.exec-qpu-confirm {
  padding: 8px 16px; border-radius: 6px;
  border: 1px solid var(--violet); background: var(--violet2);
  color: var(--violet); font-family: 'DM Sans', sans-serif;
  font-size: .78rem; font-weight: 500; cursor: pointer; transition: all .15s;
  white-space: nowrap;
}
.exec-qpu-confirm:hover:not(:disabled) { background: rgba(155,109,255,.25); }
.exec-qpu-confirm:disabled { opacity:.35; cursor:default; }
.exec-qpu-cancel {
  padding: 6px 16px; border-radius: 6px;
  border: 1px solid var(--border); background: transparent;
  color: var(--gray); font-family: 'DM Sans', sans-serif;
  font-size: .75rem; cursor: pointer; transition: all .15s; text-align: center;
}
.exec-qpu-cancel:hover { border-color: var(--gray); color: var(--white); }
.exec-qpu-warn {
  font-family: 'Space Mono', monospace; font-size: .62rem;
  color: var(--amber); opacity: .75; line-height: 1.5;
}

/* hardware results comparison */
.exec-hw-results { border-top: 1px solid var(--border); }
.exec-compare-badge {
  font-family: 'Space Mono', monospace; font-size: .6rem;
  background: var(--violet2); color: var(--violet);
  padding: 1px 7px; border-radius: 20px; margin-left: 8px; vertical-align: middle;
}
// QuantumCanvas — Pseudocode panel renderer and UI helpers
// Load order: state.js → ir.js → pseudocode.js → ui.js → qiskit-generator.js → qiskit-panel.js

// ── Panel Renderer ───────────────────────────────────────────────────
const STRIPE={INITIALIZE:'s-init',SHAKE:'s-shake',MARK:'s-mark',BOOST:'s-boost',LINK:'s-link',LOOK:'s-look'};

function openPseudocodePanel(){
  const ir  = extractCanvasIR(state);
  validateIR(ir);
  let doc=null;
  if(ir.validation.ok) doc=generatePseudocode(ir);
  _renderPC(ir,doc);
  document.getElementById('pc-overlay').classList.add('open');
}
function closePseudocodePanel(){
  document.getElementById('pc-overlay').classList.remove('open');
}
function pcOverlayClick(e){
  if(e.target===document.getElementById('pc-overlay')) closePseudocodePanel();
}
function pcQnote(btn){
  const n=btn.nextElementSibling;
  n.classList.toggle('open');
  btn.textContent=n.classList.contains('open')?'[ quantum ▾ ]':'[ quantum ▸ ]';
}
// ════════════════════════════════════════════════════════════════════
//  QISKIT GENERATOR  — Layer 2
//  Source of truth: PseudocodeDoc steps (not IR directly)
//  Label → qubit index map built from ir.qubits order
// ════════════════════════════════════════════════════════════════════

// ── Dev helpers ──────────────────────────────────────────────────────
window.QC={
  ir:  ()=>extractCanvasIR(state),
  val: ()=>{ const ir=extractCanvasIR(state); return validateIR(ir); },
  doc: ()=>{ const ir=extractCanvasIR(state); validateIR(ir); return ir.validation.ok?generatePseudocode(ir):ir.validation; },
  open:openPseudocodePanel,
};
console.log('[QC] Pseudocode engine ready. Dev: QC.ir() · QC.val() · QC.doc() · QC.open()');
// QuantumCanvas — Qiskit code generator (PseudocodeDoc → Python)
// Load order: state.js → ir.js → pseudocode.js → ui.js → qiskit-generator.js → qiskit-panel.js

function generateQiskit(ir, doc) {
  const n = ir.n;

  // Build label→index map from canonical qubit order in IR
  const labelToIdx = {};
  ir.qubits.forEach((q, i) => { labelToIdx[q.label] = i; });

  const lines   = [];   // code lines
  const remarks = [];   // parallel human remarks (same index as lines)

  const emit = (code, remark='') => { lines.push(code); remarks.push(remark); };
  const blank = (remark='') => emit('', remark);

  // ── Header ──────────────────────────────────────────────────────────
  emit('from qiskit import QuantumCircuit, transpile');
  emit('from qiskit_aer import AerSimulator');
  blank();
  emit(`# Generated by QuantumCanvas  —  ${doc.title}`);
  emit(`# Pattern: ${ir.validation.pattern}`);
  blank();

  // ── Circuit init ─────────────────────────────────────────────────────
  emit(`qc = QuantumCircuit(${n}, ${n})`,
       `${n} qubit${n>1?'s':''}, ${n} classical bit${n>1?'s':''} for measurement`);
  blank();

  // ── Walk pseudocode steps ─────────────────────────────────────────────
  let hasUnimplemented = false;

  doc.steps.forEach(step => {
    switch(step.op) {

      case 'INITIALIZE':
        emit('# INITIALIZE — all qubits start in |0⟩ (Qiskit default, no gates needed)');
        blank();
        break;

      case 'SHAKE': {
        emit(`# SHAKE ${step.targets.join(', ')} — Hadamard: equal superposition`);
        step.targets.forEach(lbl => {
          const idx = labelToIdx[lbl];
          if(idx === undefined) return;
          emit(`qc.h(${idx})`,
               `${lbl} → |+⟩ = (|0⟩+|1⟩)/√2`);
        });
        blank();
        break;
      }

      case 'MARK': {
        emit(`# MARK ${step.targets.join(', ')} — phase oracle: Z gate flips amplitude sign`);
        step.targets.forEach(lbl => {
          const idx = labelToIdx[lbl];
          if(idx === undefined) return;
          emit(`qc.z(${idx})`,
               `${lbl}: |+⟩ → |−⟩  (phase flip, probabilities unchanged)`);
        });
        blank();
        break;
      }

      case 'BOOST': {
        // Grover diffusion operator: H X CZ X H on all qubits in register
        // For a single marked qubit this is: H·X·CZ·X·H (multi-controlled phase)
        // We emit the full diffusion over the entire register the circuit has seen so far.
        const boostQubits = ir.qubits.map((_,i)=>i);   // diffusion acts on whole register
        const boostLabels = ir.qubits.map(q=>q.label).join(', ');

        emit(`# BOOST — Grover diffusion operator on [${boostLabels}]`);
        emit(`# Step 1: H on all`);
        boostQubits.forEach(i => emit(`qc.h(${i})`));
        blank('');
        emit(`# Step 2: X on all`);
        boostQubits.forEach(i => emit(`qc.x(${i})`));
        blank('');

        if(n === 1){
          emit(`qc.z(0)`, 'single-qubit: Z is the full diffusion');
        } else if(n === 2){
          emit(`qc.cz(0, 1)`, 'controlled-Z as the multi-qubit phase kick');
        } else {
          // n≥3: multi-controlled Z via CCX decomposition
          emit(`# Multi-controlled Z (phase kick) — CCX chain`);
          for(let i = 0; i < n-2; i++){
            emit(`qc.ccx(${i}, ${i+1}, ${i+2})`);
          }
          emit(`qc.z(${n-1})`);
          for(let i = n-3; i >= 0; i--){
            emit(`qc.ccx(${i}, ${i+1}, ${i+2})`);
          }
        }
        blank('');
        emit(`# Step 3: X on all`);
        boostQubits.forEach(i => emit(`qc.x(${i})`));
        blank('');
        emit(`# Step 4: H on all`);
        boostQubits.forEach(i => emit(`qc.h(${i})`));
        blank();
        break;
      }

      case 'LINK': {
        // targets is [controlLabel, targetLabel]
        const [ctrlLbl, tgtLbl] = step.targets;
        const ctrlIdx = labelToIdx[ctrlLbl];
        const tgtIdx  = labelToIdx[tgtLbl];
        if(ctrlIdx === undefined || tgtIdx === undefined) break;
        emit(`# LINK ${ctrlLbl} → ${tgtLbl} — CNOT: entangle pair`);
        emit(`qc.cx(${ctrlIdx}, ${tgtIdx})`,
             `control=${ctrlLbl}(q${ctrlIdx}), target=${tgtLbl}(q${tgtIdx}) → Bell pair |Φ+⟩`);
        blank();
        break;
      }

      case 'LOOK': {
        const tag = step.code.includes('correlated') ? ' (correlated)' : '';
        emit(`# LOOK ${step.targets.join(', ')}${tag} — measure into classical bits`);
        step.targets.forEach(lbl => {
          const idx = labelToIdx[lbl];
          if(idx === undefined) return;
          emit(`qc.measure(${idx}, ${idx})`,
               `${lbl} → classical bit ${idx}`);
        });
        blank();
        break;
      }

      default:
        break;
    }
  });

  // ── Simulator block ──────────────────────────────────────────────────
  emit('# ── Run on Aer simulator ──────────────────────────────────────');
  emit('simulator = AerSimulator()');
  emit('compiled  = transpile(qc, simulator)');
  emit('job       = simulator.run(compiled, shots=1000)');
  emit('result    = job.result()');
  emit('counts    = result.get_counts()');
  blank();
  emit('print("Circuit:")', 'print the circuit diagram');
  emit('print(qc.draw(output="text"))');
  blank();
  emit('print("\\nMeasurement counts (1000 shots):")');
  emit('for state, count in sorted(counts.items(), key=lambda x: -x[1]):');
  emit('    print(f"  |{state}⟩: {count} ({count/10:.1f}%)")');

  return { lines, remarks, hasUnimplemented, n, labelToIdx };
}
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
// QuantumCanvas — Execute panel
// Flow: IonQ Simulator → visual results → QPU cost card → optional QPU run
// Backend URL — set to Azure backend
const BACKEND_URL = 'quantumcanvas-backend-f6hphzcrejgjbha8.centralus-01.azurewebsites.net';

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
  // Strip any non-numeric keys (circuit_hash etc) and coerce values to Number
  const clean = Object.fromEntries(
    Object.entries(counts)
      .filter(([k,v]) => k !== 'circuit_hash' && typeof Number(v) === 'number' && !isNaN(Number(v)))
      .map(([k,v]) => [k, Number(v)])
  );
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
  const clean = Object.fromEntries(Object.entries(counts).filter(([k])=>k!=='circuit_hash'));
  const total = Object.values(clean).reduce((a,b)=>a+b,0);

  const hwDiv = document.getElementById('exec-hw-results');
  hwDiv.style.display = 'block';
  _renderBars('exec-hw-bars', clean, total, 'var(--violet)');

  const top = Object.entries(clean).sort((a,b)=>b[1]-a[1])[0];
  execLog(`✓ QPU done — ${total} shots · top: |${top?.[0]}⟩ (${top?((top[1]/total*100).toFixed(1)):'?'}%)`, 'ok');
  if(runId) execLog(`  QPU artifacts saved to logs/${runId}/`);

  document.getElementById('exec-qpu-card').style.display = 'none';
}

// ── Shared bar renderer ───────────────────────────────────────────────
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
