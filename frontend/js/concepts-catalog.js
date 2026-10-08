// QuantumCanvas — Concept catalog (UI metadata for the Concept IR v0.3 concepts).
// Pure data: which qubit roles a concept needs, which parameters, and how it is grouped.
// The compiler on the backend (backend/concepts/) is the source of truth for what a concept DOES.
// Load order: ... → concepts-catalog.js → concepts.js → problems.js

const QC_FAMILIES = [
  { id: 'prepare',   name: 'Prepare',        ops: ['set', 'flip', 'encode', 'reset'] },
  { id: 'superpose', name: 'Superposition',  ops: ['shake', 'rotate', 'phase'] },
  { id: 'connect',   name: 'Connect',        ops: ['entangle', 'swap', 'control'] },
  { id: 'search',    name: 'Search',         ops: ['compare', 'mark', 'boost', 'uncompute'] },
  { id: 'number',    name: 'Numbers',        ops: ['fourier', 'add'] },
  { id: 'classical', name: 'Classical',      ops: ['measure', 'correct'] },
];

// roles: which qubits to pick (click orbs in order). min/max count; "ordered" = order matters.
// params: form fields. type: int | angle | select | bool | list | ref
// wraps: this concept wraps an existing step (Control, Correct) or refers to one (Uncompute, Mark via)
const QC_CONCEPTS = {
  set: {
    sym: 'Ⅱ', color: 'teal', name: 'Set', short: 'SET',
    desc: 'Write a number into qubits that start at 0',
    req: 'Qubits must be fresh (|0⟩)',
    roles: [{ key: 'targets', label: 'Register (first = rightmost bit)', min: 1 }],
    params: [{ key: 'value', type: 'int', label: 'Number', def: 0, binary: true }],
  },
  flip: {
    sym: '⇅', color: 'rose', name: 'Flip', short: 'FLIP',
    desc: 'Turn 0 into 1 and 1 into 0',
    req: 'Works on any state',
    roles: [{ key: 'targets', label: 'Qubits', min: 1 }], params: [],
  },
  encode: {
    sym: '⤓', color: 'teal', name: 'Encode', short: 'ENCODE',
    desc: 'Load data into qubits, as bits or as a tilt',
    req: 'Basis needs fresh qubits',
    roles: [{ key: 'targets', label: 'Qubits (one per number for angle)', min: 1 }],
    params: [
      { key: 'method', type: 'select', label: 'Method', options: [['basis', 'Basis: a whole number as bits'], ['angle', 'Angle: each number sets P(1)']], def: 'angle' },
      { key: 'data', type: 'data', label: 'Data' },
      { key: 'scaling', type: 'select', label: 'Scaling', showIf: p => p.method === 'angle',
        options: [['arcsin_sqrt', 'P(1) = x  (arcsin√x)'], ['pi_x', 'Angle = π·x']], def: 'arcsin_sqrt' },
    ],
  },
  reset: {
    sym: '↺', color: 'gray', name: 'Reset', short: 'RESET',
    desc: 'Send one qubit back to 0 so it can be reused',
    req: 'One qubit at a time',
    roles: [{ key: 'targets', label: 'Qubit', min: 1, max: 1 }], params: [],
  },
  shake: {
    sym: '◎', color: 'teal', name: 'Shake', short: 'SHAKE',
    desc: 'Spread qubits into an even mix of 0 and 1',
    req: 'Any state',
    roles: [{ key: 'targets', label: 'Qubits', min: 1 }], params: [],
  },
  rotate: {
    sym: '⟳', color: 'violet', name: 'Rotate', short: 'ROTATE',
    desc: 'Tilt a qubit by an angle you choose',
    req: 'For RY, P(1) = sin²(θ/2)',
    roles: [{ key: 'targets', label: 'Qubits', min: 1 }],
    params: [
      { key: 'axis', type: 'select', label: 'Axis', options: [['x', 'X'], ['y', 'Y'], ['z', 'Z']], def: 'y' },
      { key: 'angle', type: 'angle', label: 'Angle θ', def: { pi: [1, 2] } },
    ],
  },
  phase: {
    sym: 'φ', color: 'amber', name: 'Phase', short: 'PHASE',
    desc: 'Turn a hidden angle; probabilities stay the same',
    req: 'π → Z, π/2 → S, π/4 → T',
    roles: [{ key: 'targets', label: 'Qubits', min: 1 }],
    params: [{ key: 'angle', type: 'angle', label: 'Angle', def: { pi: [1, 1] } }],
  },
  entangle: {
    sym: '⋈', color: 'violet', name: 'Entangle', short: 'ENTANGLE',
    desc: 'Tie two qubits together',
    req: 'Shake the first qubit first',
    roles: [{ key: 'targets', label: 'First = control, second = target', min: 2, max: 2, ordered: true }],
    params: [{ key: 'style', type: 'select', label: 'Style', options: [['cx', 'Control-flip (CNOT)'], ['cz', 'Control-phase (CZ)']], def: 'cx' }],
  },
  swap: {
    sym: '⇄', color: 'violet', name: 'Swap', short: 'SWAP',
    desc: 'Exchange two qubits',
    req: 'Exactly two qubits',
    roles: [{ key: 'targets', label: 'Two qubits', min: 2, max: 2 }], params: [],
  },
  control: {
    sym: '●', color: 'violet', name: 'Control', short: 'CONTROL', wraps: 'control',
    desc: 'Run a step only when control qubits are 1',
    req: 'Wraps an existing step',
    roles: [{ key: 'controls', label: 'Control qubits', min: 1 }], params: [],
  },
  compare: {
    sym: '≟', color: 'amber', name: 'Compare', short: 'COMPARE',
    desc: 'Check a register against a number; answer goes to a helper qubit',
    req: 'Helper (ancilla) must be 0',
    // helper first: it takes exactly one qubit, so the form moves on to the register by itself
    roles: [{ key: 'ancillas', label: '1 · Helper qubit for the answer (starts at 0)', min: 1, max: 1 }, { key: 'targets', label: '2 · Register to check', min: 1 }],
    params: [
      { key: 'operator', type: 'select', label: 'Test', options: [['eq', 'equals'], ['neq', 'is not equal to']], def: 'eq' },
      { key: 'value', type: 'int', label: 'Number', def: 0, binary: true },
    ],
  },
  mark: {
    sym: '◈', color: 'rose', name: 'Mark', short: 'MARK',
    desc: 'Tag one answer with a hidden minus sign',
    req: 'Needs a superposition to act on',
    roles: [{ key: 'targets', label: 'Register', min: 1, showIf: p => p.mode === 'value' }],
    params: [
      { key: 'mode', type: 'select', label: 'Mark by', options: [['value', 'a number'], ['via', 'an earlier Compare']], def: 'value', virtual: true },
      { key: 'value', type: 'int', label: 'Number', def: 0, binary: true, showIf: p => p.mode === 'value' },
      { key: 'via', type: 'ref', label: 'Which Compare', refOps: ['compare'], showIf: p => p.mode === 'via' },
    ],
  },
  boost: {
    sym: '▲', color: 'amber', name: 'Boost', short: 'BOOST',
    desc: 'Make the marked answer more likely',
    req: 'Mark first; ~√N rounds',
    roles: [{ key: 'targets', label: 'Search register (not the helper)', min: 1 }],
    params: [{ key: 'repeat', type: 'int', label: 'Rounds', def: 1, min: 1, max: 64 }],
  },
  uncompute: {
    sym: '⌫', color: 'gray', name: 'Uncompute', short: 'UNDO', wraps: 'ref',
    desc: 'Run an earlier step backwards to clean up helpers',
    req: 'Only reversible steps',
    roles: [],
    params: [{ key: 'ref', type: 'ref', label: 'Undo which step', refOps: null, unitaryOnly: true }],
  },
  fourier: {
    sym: '∿', color: 'teal', name: 'Fourier', short: 'FOURIER',
    desc: 'Turn numbers into hidden angles (and back)',
    req: 'Register of any size',
    roles: [{ key: 'targets', label: 'Register (first = rightmost bit)', min: 1, ordered: true }],
    params: [
      { key: 'inverse', type: 'bool', label: 'Inverse (undo the transform)', def: false },
      { key: 'swaps', type: 'bool', label: 'Reverse qubit order at the end (standard)', def: true },
    ],
  },
  add: {
    sym: '＋', color: 'amber', name: 'Add', short: 'ADD',
    desc: 'Add a fixed number, wrapping around, without measuring',
    req: 'Wraps at 2ⁿ',
    roles: [{ key: 'targets', label: 'Register (first = rightmost bit)', min: 1, ordered: true }],
    params: [{ key: 'value', type: 'int', label: 'Add this number', def: 1, binary: true }],
  },
  measure: {
    sym: '◙', color: 'gray', name: 'Measure', short: 'MEASURE',
    desc: 'Look at qubits; answers go into classical bits',
    req: 'Collapses the qubit',
    roles: [{ key: 'targets', label: 'Qubits', min: 1 }], params: [],
  },
  correct: {
    sym: '↯', color: 'rose', name: 'Correct', short: 'CORRECT', wraps: 'correct',
    desc: 'Apply a fix-up step depending on a measured bit',
    req: 'Needs an earlier Measure',
    roles: [], params: [
      { key: 'clbit', type: 'clbit', label: 'When classical bit', virtual: true },
      { key: 'equals', type: 'select', label: 'equals', options: [['1', '1'], ['0', '0']], def: '1', virtual: true },
    ],
  },
};

// ops that may be wrapped by Control / Correct (reversible quantum steps only)
const QC_WRAPPABLE = op => !['measure', 'reset', 'correct', 'uncompute'].includes(op);
const QC_UNITARY = op => !['measure', 'reset', 'correct'].includes(op);
const QC_ANGLE_PRESETS = [[1, 1, 'π'], [1, 2, 'π/2'], [1, 4, 'π/4'], [-1, 2, '−π/2'], [-1, 4, '−π/4'], [1, 3, 'π/3'], [2, 3, '2π/3']];
