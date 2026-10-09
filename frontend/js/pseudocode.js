// QuantumCanvas — Pseudocode generator (IR → human-readable steps)
// Load order: state.js → ir.js → pseudocode.js → ui.js → qiskit-generator.js → qiskit-panel.js

// ── Pseudocode Generator ─────────────────────────────────────────────
function generatePseudocode(ir){
  const labels = ir.qubits.map(q=>q.label);
  const steps  = [];
  let sn = 0;

  const addStep=(op,targets,code,plain,qnote)=>
    steps.push({n:++sn,op,targets,code,plain,qnote});

  // Always inject INITIALIZE
  addStep('INITIALIZE', labels,
    `INITIALIZE [${labels.join(', ')}]  →  |${'0'.repeat(ir.n)}⟩`,
    `All ${ir.n} qubit${ir.n>1?'s':''} start in the ground state — like coins lying flat, showing neither 0 nor 1 yet.`,
    `|${'0'.repeat(ir.n)}⟩ computational basis state`);

  // Walk global log in chronological order.
  // Group consecutive entries with the same op AND (for boost) the same seq.
  // This preserves exact user action order.
  const log = ir.globalLog;
  let i=0;
  while(i<log.length){
    const op=log[i].op;
    const batch=[];
    // For boost: group all consecutive boost entries (one click = one logical action)
    // For other ops: group consecutive same-op entries
    if(op==='boost'){
      while(i<log.length && log[i].op==='boost'){ batch.push(log[i]); i++; }
    } else {
      while(i<log.length && log[i].op===op){ batch.push(log[i]); i++; }
    }
    const tgts = [...new Set(batch.map(b=>ir.qubits.find(q=>q.id===b.qubit)?.label||b.qubit))];

    if(op==='shake'){
      // Bug 3 fix: states and count are scoped to THIS batch's qubits only
      const batchN = tgts.length;
      const batchStates = Math.pow(2, batchN);
      const qnNote = batchN===1
        ? `H|0⟩ = (|0⟩+|1⟩)/√2`
        : batchN===2
          ? `H⊗2|00⟩ = ½(|00⟩+|01⟩+|10⟩+|11⟩)`
          : `H⊗${batchN}|${'0'.repeat(batchN)}⟩ = (1/√${batchStates}) Σ|x⟩ for x∈{0,1}^${batchN}`;
      const tgtStr = tgts.length===1 ? tgts[0] : `[${tgts.join(', ')}]`;
      addStep('SHAKE',tgts,
        `SHAKE [${tgts.join(', ')}]  →  spread ${tgtStr} into ${batchStates === 2 ? 'both possibilities' : `all ${batchStates} combinations`} equally`,
        tgts.length===1
          ? `Shake puts ${tgts[0]} into superposition — both |0⟩ and |1⟩ are simultaneously possible with equal probability. The qubit is no longer a definite 0 or 1.`
          : `Shake puts each of [${tgts.join(', ')}] into superposition. All ${batchStates} combinations of these ${batchN} qubits now exist simultaneously with equal probability.`,
        qnNote);
    }
    else if(op==='mark'){
      addStep('MARK',tgts,
        `MARK [${tgts.join(', ')}]  →  flip hidden phase of target`,
        `Marking ${tgts.join(' and ')} flips a hidden sign on the target answer. The probabilities still look equal — but the target now carries a negative amplitude underneath. This is how the search knows what it is looking for.`,
        `Phase oracle: Uf|x⟩ = (−1)^f(x)|x⟩ on [${tgts.join(', ')}]`);
    }
    else if(op==='boost'){
      // Bug 4 fix: count distinct Boost CLICKS, not entries in the batch.
      // All qubits boosted by one click share the same seq value.
      // Collect the seq values from the source tagged ops on each qubit.
      const boostedQubits = batch.map(b => ir.qubits.find(q=>q.id===b.qubit));
      const seqValues = new Set();
      boostedQubits.forEach(q => {
        if(!q) return;
        q.taggedOps.filter(t=>t.op==='boost').forEach(t=>seqValues.add(t.seq));
      });
      // If seq values aren't available (legacy), fall back to 1 per unique qubit label
      const boostClickCount = seqValues.size > 0 ? seqValues.size : 1;
      const opt = ir.optimal;
      const N   = ir.N;   // search space: 2^n states — this is what optimal is based on
      const overBoost = boostClickCount > opt;
      const countStr = boostClickCount===1 ? '1×' : `${boostClickCount}×`;
      const optStr   = opt===1 ? '1×' : `${opt}×`;
      const warnNote = overBoost
        ? `  ⚠ optimal is ${optStr} for a ${N}-state search space`
        : ` (optimal: ${optStr} for a ${N}-state search space)`;
      addStep('BOOST',tgts,
        `BOOST [${tgts.join(', ')}]  ${countStr}  →  amplify marked target${warnNote}`,
        overBoost
          ? `Boost uses interference to raise the marked target's probability. You applied Boost ${boostClickCount} times — for a ${N}-state search space the optimal is ${opt}×. Past that point the target's probability reverses back down.`
          : `Boost uses interference to raise the marked target's probability and lower all others. ${countStr} applied — optimal for a ${N}-state search space is ${optStr}.`,
        `Grover diffusion: (2|ψ⟩⟨ψ|−I) on [${tgts.join(', ')}]`);
    }
    else if(op==='link'){
      // Each link action produces two entries (src + tgt). Emit one step per edge.
      const processedEdges = new Set();
      batch.forEach(b=>{
        const edge=ir.edges.find(e=>e.src===b.qubit || e.tgt===b.qubit);
        if(!edge||processedEdges.has(edge.id)) return;
        processedEdges.add(edge.id);
        const sl=ir.qubits.find(q=>q.id===edge.src)?.label||edge.src;
        const tl=ir.qubits.find(q=>q.id===edge.tgt)?.label||edge.tgt;
        addStep('LINK',[sl,tl],
          `LINK ${sl} → ${tl}  →  create quantum correlation (controlled operation)`,
          `Linking ${sl} and ${tl} creates a quantum correlation via a controlled-NOT gate. The measurement outcome of one qubit becomes correlated with the other. The exact entangled state depends on the state of ${sl} before this operation.`,
          `CNOT gate: cx(${sl}, ${tl}) — entanglement type depends on prior state of control qubit`);
      });
    }
    else if(op==='look'){
      // Bug 2 fix: all look entries in batch (including correlated collapses) get their own line
      const correlatedInBatch = batch.filter(b=>b.correlated);
      const directInBatch     = batch.filter(b=>!b.correlated);

      if(directInBatch.length){
        const dtgts   = [...new Set(directInBatch.map(b=>ir.qubits.find(q=>q.id===b.qubit)?.label||b.qubit))];
        const dresults = directInBatch.map(b=>{ const q=ir.qubits.find(q=>q.id===b.qubit); return q?.result??'?'; });
        const dResStr  = directInBatch.map((b,ri)=>{ const l=ir.qubits.find(q=>q.id===b.qubit)?.label||b.qubit; return `${l}=${dresults[ri]}`; }).join(', ');
        addStep('LOOK',dtgts,
          `LOOK [${dtgts.join(', ')}]  →  measure — collapse to a classical value`,
          `Measuring ${dtgts.join(' and ')} collapses the superposition to a definite 0 or 1. This is irreversible — ${dtgts.length>1?'these qubits become':'this qubit becomes'} classical. The outcome is probabilistic; the distribution depends on the circuit above.`,
          `Projective measurement ⟨x|ρ|x⟩. Result: ${dResStr}`);
      }
      if(correlatedInBatch.length){
        const ctgts    = [...new Set(correlatedInBatch.map(b=>ir.qubits.find(q=>q.id===b.qubit)?.label||b.qubit))];
        const cresults = correlatedInBatch.map(b=>{ const q=ir.qubits.find(q=>q.id===b.qubit); return q?.result??'?'; });
        const cResStr  = correlatedInBatch.map((b,ri)=>{ const l=ir.qubits.find(q=>q.id===b.qubit)?.label||b.qubit; return `${l}=${cresults[ri]}`; }).join(', ');
        addStep('LOOK',ctgts,
          `LOOK [${ctgts.join(', ')}]  →  correlated collapse (entanglement)`,
          `${ctgts.join(' and ')} ${ctgts.length>1?'collapse':'collapses'} automatically because ${ctgts.length>1?'they were':'it was'} entangled with the measured qubit. No measurement was needed — the Link determined the outcome instantly.`,
          `Entanglement collapse: measuring the linked qubit forces this qubit to a correlated classical value`);
      }
    }
  }

  const patternTitles={
    grover_like:'Quantum Search — Grover-like Pattern',
    bell_pair:'Bell Pair — Quantum Entanglement',
    superposition_only:'Superposition Only — Equal Distribution',
    entangled_search:'Entangled Search — Grover + Entanglement',
    marked_no_boost:'Incomplete Search — Mark without Boost',
    mixed:'Mixed Operations',
    empty:'Empty Canvas',invalid:'Invalid Sequence',
  };
  const patternNotes={
    grover_like:'This sequence follows the Grover search structure: initialize → equal superposition → phase marking → amplitude amplification → measurement.',
    bell_pair:'One qubit shaken into superposition, then linked to a second via a CNOT gate, creating a correlated entangled pair. If the control qubit was in equal superposition, this produces a Bell state.',
    superposition_only:'All qubits are in equal superposition. No target marked. Useful for generating uniform random outcomes.',
    entangled_search:'Combines entanglement with amplitude amplification for a more complex search structure.',
    marked_no_boost:'A target is marked but Boost not applied. Phase is flipped but probabilities unchanged. Add Boost to amplify.',
    mixed:'Multiple patterns across qubits.',
    empty:'',invalid:'',
  };

  const pat=ir.validation.pattern;
  return {
    title: patternTitles[pat]||'Quantum Circuit',
    meta: `${ir.n} qubit${ir.n!==1?'s':''} · ${ir.N.toLocaleString()} states · ${steps.length} steps`,
    steps,
    summary: ir.qubits.map(q=>({
      label:q.label,
      ops:q.ops.map(o=>o[0].toUpperCase()+o.slice(1)).join(' → ')||'—',
      state:q.final_state, result:q.result
    })),
    patternNote: patternNotes[pat]||'',
  };
}
