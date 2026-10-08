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
