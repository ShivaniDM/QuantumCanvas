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
