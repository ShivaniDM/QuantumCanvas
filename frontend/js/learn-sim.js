// QuantumCanvas Learn — circuit model, statevector simulator, Qiskit code generator, cell parser.
// Qubit order follows Qiskit: qubit 0 is the RIGHTMOST bit of a bitstring.

const GATES = {
  h:   {label:'H',    n:1, desc:'Hadamard — equal superposition',        color:'teal'},
  x:   {label:'X',    n:1, desc:'Pauli-X — bit flip (NOT)',              color:'rose'},
  y:   {label:'Y',    n:1, desc:'Pauli-Y',                               color:'rose'},
  z:   {label:'Z',    n:1, desc:'Pauli-Z — phase flip',                  color:'rose'},
  s:   {label:'S',    n:1, desc:'S — quarter-turn phase',                color:'amber'},
  t:   {label:'T',    n:1, desc:'T — eighth-turn phase',                 color:'amber'},
  rx:  {label:'Rx',   n:1, desc:'Rotate about X by θ',    param:true,    color:'violet'},
  ry:  {label:'Ry',   n:1, desc:'Rotate about Y by θ',    param:true,    color:'violet'},
  rz:  {label:'Rz',   n:1, desc:'Rotate about Z by θ',    param:true,    color:'violet'},
  cx:  {label:'CX',   n:2, desc:'CNOT — flip target if control is 1',    color:'teal'},
  cz:  {label:'CZ',   n:2, desc:'Controlled-Z',                          color:'teal'},
  swap:{label:'SWAP', n:2, desc:'Swap two qubits',                       color:'teal'},
  measure:{label:'M', n:1, desc:'Measure into a classical bit',          color:'gray'},
  block:{label:'▦',   n:0, desc:'Opaque block (not simulated)',          color:'gray'},
};

// complex numbers as [re, im]
const C = {
  mul:(a,b)=>[a[0]*b[0]-a[1]*b[1], a[0]*b[1]+a[1]*b[0]],
  add:(a,b)=>[a[0]+b[0], a[1]+b[1]],
};
const R2 = Math.SQRT1_2;

function gateMatrix(g, th=0){
  const c = Math.cos(th/2), s = Math.sin(th/2);
  switch(g){
    case 'h':  return [[[R2,0],[R2,0]],[[R2,0],[-R2,0]]];
    case 'x':  return [[[0,0],[1,0]],[[1,0],[0,0]]];
    case 'y':  return [[[0,0],[0,-1]],[[0,1],[0,0]]];
    case 'z':  return [[[1,0],[0,0]],[[0,0],[-1,0]]];
    case 's':  return [[[1,0],[0,0]],[[0,0],[0,1]]];
    case 't':  return [[[1,0],[0,0]],[[0,0],[R2,R2]]];
    case 'rx': return [[[c,0],[0,-s]],[[0,-s],[c,0]]];
    case 'ry': return [[[c,0],[-s,0]],[[s,0],[c,0]]];
    case 'rz': return [[[c,-s],[0,0]],[[0,0],[c,s]]];
  }
  return null;
}

function apply1(sv, q, M){
  const out = sv.slice();
  for(let i=0;i<sv.length;i++){
    if(i & (1<<q)) continue;
    const j = i | (1<<q);
    const a = sv[i], b = sv[j];
    out[i] = C.add(C.mul(M[0][0],a), C.mul(M[0][1],b));
    out[j] = C.add(C.mul(M[1][0],a), C.mul(M[1][1],b));
  }
  return out;
}

function applyOp(sv, op){
  const g = op.g;
  if(g==='measure' || g==='block') return sv;
  if(GATES[g].n===1) return apply1(sv, op.q[0], gateMatrix(g, op.theta||0));
  const out = sv.slice();
  const [a,b] = op.q;
  for(let i=0;i<sv.length;i++){
    if(g==='cx'){ if(i>>a&1) out[i^(1<<b)] = sv[i]; }
    else if(g==='cz'){ if((i>>a&1)&&(i>>b&1)) out[i] = [-sv[i][0],-sv[i][1]]; }
    else if(g==='swap'){ const ba=i>>a&1, bb=i>>b&1; out[(i & ~(1<<a) & ~(1<<b)) | (bb<<a) | (ba<<b)] = sv[i]; }
  }
  return out;
}

// time order: by column, then by wire
function ordered(ops){ return ops.slice().sort((p,q)=> p.col-q.col || Math.min(...p.q)-Math.min(...q.q)); }

function simulate(n, ops, upTo=Infinity){
  let sv = Array.from({length:1<<n}, (_,i)=> i===0?[1,0]:[0,0]);
  ordered(ops).forEach((op,k)=>{ if(k<upTo) sv = applyOp(sv, op); });
  return sv;
}

function probabilities(sv){ return sv.map(a=>a[0]*a[0]+a[1]*a[1]); }
function bits(i, n){ return i.toString(2).padStart(n,'0'); }

// Qiskit-style histogram: bit k of the key is classical bit k (measure q -> clbit q); unmeasured clbits stay 0.
// With no measure gates every qubit is reported.
function distribution(n, ops){
  const p = probabilities(simulate(n, ops));
  const meas = new Set(ops.filter(o=>o.g==='measure').map(o=>o.q[0]));
  const used = meas.size ? meas : new Set(Array.from({length:n},(_,i)=>i));
  const d = {};
  p.forEach((pr,i)=>{
    if(pr<1e-12) return;
    let key = '';
    for(let q=n-1;q>=0;q--) key += used.has(q) ? (i>>q&1) : 0;
    d[key] = (d[key]||0)+pr;
  });
  return {dist:d, measured: meas.size>0, nBits: n};
}

function sample(dist, shots){
  const keys = Object.keys(dist), counts = {};
  for(let s=0;s<shots;s++){
    let r = Math.random(), acc = 0, pick = keys[keys.length-1];
    for(const k of keys){ acc += dist[k]; if(r<acc){ pick=k; break; } }
    counts[pick] = (counts[pick]||0)+1;
  }
  return counts;
}

function marginalP1(n, ops){
  const p = probabilities(simulate(n, ops));
  return Array.from({length:n}, (_,q)=> p.reduce((s,pr,i)=> s + ((i>>q&1)?pr:0), 0));
}

function fmtAngle(th){
  const k = th/Math.PI;
  const fr = [[0,'0'],[1,'π'],[-1,'-π'],[.5,'π/2'],[-.5,'-π/2'],[.25,'π/4'],[-.25,'-π/4'],[2,'2π'],[.75,'3π/4'],[1.5,'3π/2']];
  for(const [v,s] of fr) if(Math.abs(k-v)<1e-6) return s;
  return th.toFixed(3);
}
function pyAngle(th){
  const k = th/Math.PI;
  const fr = {'0':'0','1':'np.pi','-1':'-np.pi','0.5':'np.pi/2','-0.5':'-np.pi/2','0.25':'np.pi/4','-0.25':'-np.pi/4','2':'2*np.pi'};
  const key = String(+k.toFixed(6));
  return fr[key] || th.toFixed(4);
}

function fmtComplex(a){
  const [re,im] = a;
  const f = x=> (Math.abs(x)<5e-4?'0':x.toFixed(3));
  if(Math.abs(im)<5e-4) return f(re);
  if(Math.abs(re)<5e-4) return f(im)+'i';
  return `${f(re)}${im<0?'−':'+'}${f(Math.abs(im))}i`;
}

// ── Qiskit code generation (with simple loop folding) ────────────────────
function generateCode(n, ops, opts={}){
  const meas = ops.filter(o=>o.g==='measure');
  const L = [];
  L.push('from qiskit import QuantumCircuit');
  L.push('import numpy as np', '');
  L.push(`qc = QuantumCircuit(${n}, ${n})`, '');
  const seq = ordered(ops).filter(o=>o.g!=='measure');
  const call = o=>{
    const g = o.g;
    if(g==='block') return `# ${o.label||'block'} on qubits ${o.q.join(', ')} — build with the library class (see notebook)`;
    if(GATES[g].param) return `qc.${g}(${pyAngle(o.theta||0)}, ${o.q[0]})`;
    return `qc.${g}(${o.q.join(', ')})`;
  };
  for(let i=0;i<seq.length;){
    const o = seq[i];
    // fold: same 1q gate (same θ) on qubits 0,1,2,… in a row → for loop
    if(GATES[o.g].n===1 && o.q[0]===0){
      let k=1;
      while(i+k<seq.length && seq[i+k].g===o.g && seq[i+k].q[0]===k && (seq[i+k].theta||0)===(o.theta||0)) k++;
      if(k>=3){
        L.push(`for i in range(${k}):`);
        L.push(`    ${GATES[o.g].param ? `qc.${o.g}(${pyAngle(o.theta||0)}, i)` : `qc.${o.g}(i)`}`);
        i+=k; continue;
      }
    }
    // fold: cx chain (0,1),(1,2),(2,3)…
    if(o.g==='cx' && o.q[0]===0 && o.q[1]===1){
      let k=1;
      while(i+k<seq.length && seq[i+k].g==='cx' && seq[i+k].q[0]===k && seq[i+k].q[1]===k+1) k++;
      if(k>=3){ L.push(`for i in range(${k}):`, '    qc.cx(i, i + 1)'); i+=k; continue; }
    }
    L.push(call(o)); i++;
  }
  if(meas.length){
    L.push('');
    meas.sort((a,b)=>a.q[0]-b.q[0]);
    if(meas.length===n && meas.every((m,k)=>m.q[0]===k)) L.push('qc.measure(range(%d), range(%d))'.replace(/%d/g,n));
    else meas.forEach(m=>L.push(`qc.measure(${m.q[0]}, ${m.q[0]})`));
  }
  if(!opts.bare){ L.push('', 'print(qc.draw("text"))'); }
  return L.join('\n');
}

// ── Cell parser: literal qc.<gate>(...) lines, with simple `for i in range(N)` loops ──
function evalNum(s){
  s = s.trim().replace(/np\.pi|numpy\.pi|math\.pi|\bpi\b/g,'(Math.PI)');
  if(!/^[0-9+\-*/(). Math PI]*$/.test(s)) return null;
  try{ const v = Function('"use strict";return ('+s.replace(/Math\.PI/g,'Math.PI')+')')(); return Number.isFinite(v)?v:null; }catch(e){ return null; }
}

function parseCell(src){
  const lines = src.split('\n');
  let n = null; const ops = []; const skipped = [];
  const m0 = src.match(/QuantumCircuit\(\s*(\d+)/); if(m0) n = +m0[1];
  const col = {};                      // next free column per wire
  const push = (g, qs, theta, label)=>{
    const c = Math.max(0, ...qs.map(q=>col[q]||0));
    qs.forEach(q=>col[q]=c+1);
    ops.push({g, q:qs, col:c, theta, label});
  };
  const handle = (line, vars)=>{
    const sub = s=> s.replace(/\bi\s*([+-])\s*(\d+)/g,(_,sg,d)=> vars.i+(sg==='+'?+d:-d)).replace(/\bi\b/g, vars.i);
    const m = line.trim().match(/^qc\.(\w+)\((.*)\)\s*$/);
    if(!m) return false;
    const g = m[1], args = m[2].split(',').map(a=>a.trim());
    const num = a=>{ const v = evalNum(vars.i===undefined?a:sub(a)); return v; };
    if(['h','x','y','z','s','t'].includes(g) && args.length===1){ const q=num(args[0]); if(q===null) return false; push(g,[q]); return true; }
    if(['rx','ry','rz'].includes(g) && args.length===2){ const th=evalNum(args[0]), q=num(args[1]); if(th===null||q===null) return false; push(g,[q],th); return true; }
    if(['cx','cz','swap'].includes(g) && args.length===2){ const a=num(args[0]), b=num(args[1]); if(a===null||b===null) return false; push(g,[a,b]); return true; }
    if(g==='measure' && args.length===2){ const q=num(args[0]); if(q===null) return false; push('measure',[q]); return true; }
    return false;
  };
  let loop = null;
  const flush = ()=>{
    if(!loop) return;
    if(loop.ok) for(let i=0;i<loop.count;i++) loop.body.forEach(b=>{ if(!handle(b,{i})) skipped.push(b.trim()); });
    else loop.body.forEach(b=>skipped.push(b.trim()));
    loop = null;
  };
  for(const raw of lines){
    const lm = raw.match(/^\s*for\s+i\s+in\s+range\((\d+|n)(?:\s*-\s*(\d+))?\)\s*:/);
    if(lm){ flush(); const base = lm[1]==='n' ? n : +lm[1]; loop = {count: base - (+lm[2]||0), body:[], ok: base!=null}; continue; }
    if(loop && /^\s+\S/.test(raw)){ loop.body.push(raw); continue; }
    flush();
    if(/^\s*qc\./.test(raw) && !handle(raw,{})) skipped.push(raw.trim());
  }
  flush();
  if(!ops.length) return null;
  const maxQ = Math.max(...ops.flatMap(o=>o.q))+1;
  return {n: Math.max(n||0, maxQ), ops, skipped};
}
