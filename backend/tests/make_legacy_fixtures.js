// Builds legacy fixtures by running the REAL ir.js / pseudocode.js / qiskit-generator.js.
// Usage:  node make_legacy_fixtures.js          (from backend/tests)
// Output: fixtures/legacy/<name>.json = { ir, qiskit, actions }
// The click sequences replay state.js applyPrimitive() bookkeeping (no DOM needed).
const fs = require('fs'), path = require('path'), vm = require('vm');
const js = p => fs.readFileSync(path.join(__dirname, '../../frontend/js', p), 'utf8');
vm.runInThisContext(js('ir.js'));
vm.runInThisContext(js('pseudocode.js'));
vm.runInThisContext(js('qiskit-generator.js'));

function replay(n, actions) {
  const s = { qubits: [], edges: [], nextSeq: 0 };
  for (let i = 1; i <= n; i++) s.qubits.push({ id: 'q' + i, label: 'Q' + i, x: i * 100, y: 100, state: 'ground', ops: [] });
  const Q = id => s.qubits.find(q => q.id === id);
  for (const [prim, a, b] of actions) {
    if (prim === 'shake') { const q = Q(a); q.state = 'super'; q.ops.push({ op: 'shake', seq: s.nextSeq++ }); }
    else if (prim === 'mark') { const q = Q(a); q.state = 'marked'; q.ops.push({ op: 'mark', seq: s.nextSeq++ }); }
    else if (prim === 'boost') {
      const seq = s.nextSeq++;
      s.qubits.forEach(x => {
        if (x.state === 'marked') { x.state = 'boosted'; x.ops.push({ op: 'boost', seq }); }
        else if (x.state === 'super') x.ops.push({ op: 'boost', seq });
      });
    } else if (prim === 'link') {
      s.edges.push({ src: a, tgt: b, type: 'entangle' });
      const seq = s.nextSeq++;
      Q(a).state = 'entangled'; Q(a).ops.push({ op: 'link', seq });
      Q(b).state = 'entangled'; Q(b).ops.push({ op: 'link', seq });
    } else if (prim === 'look') {
      const q = Q(a), seq = s.nextSeq++;
      q.state = 'measured'; q.result = '1'; q.ops.push({ op: 'look', seq });
      s.edges.forEach(e => {
        if (e.src === a || e.tgt === a) {
          const p = Q(e.src === a ? e.tgt : e.src);
          if (p.state === 'entangled') { p.state = 'measured'; p.result = '0'; p.ops.push({ op: 'look', seq, correlated: true }); }
        }
      });
    }
  }
  return s;
}

const cases = {
  superposition_3: [3, [['shake', 'q1'], ['shake', 'q2'], ['shake', 'q3'], ['look', 'q1'], ['look', 'q2'], ['look', 'q3']]],
  bell_pair: [2, [['shake', 'q1'], ['link', 'q1', 'q2'], ['look', 'q1']]],
  grover_2q_mark_q2: [2, [['shake', 'q1'], ['shake', 'q2'], ['mark', 'q2'], ['boost'], ['look', 'q1'], ['look', 'q2']]],
  grover_3q_mark_q1_q3: [3, [['shake', 'q1'], ['shake', 'q2'], ['shake', 'q3'], ['mark', 'q1'], ['mark', 'q3'], ['boost'], ['look', 'q1'], ['look', 'q2'], ['look', 'q3']]],
  grover_3q_mark_q3: [3, [['shake', 'q1'], ['shake', 'q2'], ['shake', 'q3'], ['mark', 'q3'], ['boost'], ['look', 'q1'], ['look', 'q2'], ['look', 'q3']]],
  entangled_search: [3, [['shake', 'q1'], ['shake', 'q2'], ['shake', 'q3'], ['link', 'q1', 'q3'], ['mark', 'q2'], ['boost']]],
  single_qubit_mark: [1, [['shake', 'q1'], ['mark', 'q1'], ['boost'], ['look', 'q1']]],
  double_boost: [3, [['shake', 'q1'], ['shake', 'q2'], ['shake', 'q3'], ['mark', 'q3'], ['boost'], ['boost'], ['look', 'q1']]],
};

const out = path.join(__dirname, 'fixtures/legacy');
for (const [name, [n, actions]] of Object.entries(cases)) {
  const s = replay(n, actions);
  const ir = extractCanvasIR(s); validateIR(ir);
  if (!ir.validation.ok) { console.log('SKIP (legacy validator rejects):', name, ir.validation.errs.map(e => e.rule)); continue; }
  const doc = generatePseudocode(ir);
  const q = generateQiskit(ir, doc);
  const qiskit = q.lines.join('\n');
  fs.writeFileSync(path.join(out, name + '.json'), JSON.stringify({ name, actions, ir, qiskit }, null, 1));
  console.log('wrote', name, '-', q.lines.filter(l => l.startsWith('qc.')).length, 'gate lines');
}
