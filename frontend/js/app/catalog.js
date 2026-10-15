export const FAMILIES = [
  { id: 'basics', name: 'Basics', ops: ['shake', 'flip', 'entangle', 'mark', 'boost', 'measure'], open: true },
  { id: 'prepare', name: 'Prepare', ops: ['set', 'encode', 'reset'] },
  { id: 'phase', name: 'Phase and rotation', ops: ['phase', 'rotate'] },
  { id: 'connect', name: 'Connect', ops: ['swap', 'control'] },
  { id: 'search', name: 'Search tools', ops: ['compare', 'uncompute'] },
  { id: 'number', name: 'Numbers', ops: ['fourier', 'add'] },
  { id: 'classical', name: 'Classical', ops: ['correct'] },
];

export const CONCEPTS = {
  shake: {
    name: 'Superposition', short: 'H', color: 'teal',
    desc: 'Hadamard on each qubit: equal amplitudes for 0 and 1.',
    analogy: 'Think of a wave that is spread over both answers at once. It is not a hidden coin that is secretly 0 or 1.',
    roles: [{ key: 'targets', label: 'Qubits', min: 1 }], params: [],
  },
  flip: {
    name: 'Flip', short: 'X', color: 'rose',
    desc: 'Pauli-X on each qubit: swaps the amplitudes of 0 and 1.',
    analogy: 'The quantum version of a classical NOT.',
    roles: [{ key: 'targets', label: 'Qubits', min: 1 }], params: [],
  },
  entangle: {
    name: 'Entangle', short: 'CNOT', color: 'violet',
    desc: 'A controlled gate that links two qubits so their outcomes are correlated.',
    analogy: 'Two outcomes that always agree, without either one being decided in advance.',
    roles: [{ key: 'targets', label: 'Control, then target', min: 2, max: 2, ordered: true }],
    params: [{ key: 'style', type: 'select', label: 'Gate', options: [['cx', 'CNOT (controlled-X)'], ['cz', 'CZ (controlled-Z)']], def: 'cx' }],
  },
  mark: {
    name: 'Oracle', short: 'Oracle', color: 'rose',
    desc: 'Marks one basis state by flipping the sign of its amplitude. Probabilities do not change yet.',
    analogy: 'An invisible minus sign on one answer. Amplitude amplification turns it into a visible difference.',
    roles: [{ key: 'targets', label: 'Register (first picked = rightmost bit)', min: 1, ordered: true, showIf: p => p.mode !== 'via' }],
    params: [
      { key: 'mode', type: 'select', label: 'Mark by', options: [['value', 'a basis state'], ['via', 'an earlier Compare']], def: 'value', virtual: true },
      { key: 'value', type: 'int', label: 'Basis state to mark', def: 0, binary: true, showIf: p => p.mode !== 'via' },
      { key: 'via', type: 'ref', label: 'Which Compare', refOps: ['compare'], showIf: p => p.mode === 'via' },
    ],
  },
  boost: {
    name: 'Amplitude amplification', short: 'Amplify', color: 'amber',
    desc: 'Reflects every amplitude about the average, so the marked state becomes more likely.',
    analogy: 'Like waves: the marked state adds up, the others cancel.',
    roles: [{ key: 'targets', label: 'Search register', min: 1 }],
    params: [{ key: 'repeat', type: 'int', label: 'Rounds (about √N is best)', def: 1, min: 1, max: 64 }],
  },
  measure: {
    name: 'Measure', short: 'Measure', color: 'gray',
    desc: 'Reads each qubit as 0 or 1 and stores it in the classical bit with the same number.',
    analogy: '',
    roles: [{ key: 'targets', label: 'Qubits', min: 1 }], params: [],
  },
  set: {
    name: 'Set value', short: 'Set', color: 'teal',
    desc: 'Writes a whole number into qubits that start at |0⟩, using X gates.',
    analogy: '',
    roles: [{ key: 'targets', label: 'Register (first picked = rightmost bit)', min: 1, ordered: true }],
    params: [{ key: 'value', type: 'int', label: 'Number', def: 0, binary: true }],
  },
  encode: {
    name: 'Encode data', short: 'Encode', color: 'teal',
    desc: 'Loads numbers into qubits, as bits or as rotation angles.',
    analogy: '',
    roles: [{ key: 'targets', label: 'Qubits (one per number for angle encoding)', min: 1, ordered: true }],
    params: [
      { key: 'method', type: 'select', label: 'Method', options: [['angle', 'Angle: each number sets P(1)'], ['basis', 'Basis: a whole number as bits']], def: 'angle' },
      { key: 'data', type: 'data', label: 'Data' },
      { key: 'scaling', type: 'select', label: 'Scaling', showIf: p => p.method === 'angle', options: [['arcsin_sqrt', 'P(1) = x'], ['pi_x', 'angle = π·x']], def: 'arcsin_sqrt' },
    ],
  },
  reset: {
    name: 'Reset', short: 'Reset', color: 'gray',
    desc: 'Returns one qubit to |0⟩ so it can be reused.',
    analogy: '',
    roles: [{ key: 'targets', label: 'Qubit', min: 1, max: 1 }], params: [],
  },
  phase: {
    name: 'Phase', short: 'P', color: 'amber',
    desc: 'Turns the phase of |1⟩ by an angle. Probabilities do not change on their own.',
    analogy: '',
    roles: [{ key: 'targets', label: 'Qubits', min: 1 }],
    params: [{ key: 'angle', type: 'angle', label: 'Angle', def: { pi: [1, 1] } }],
  },
  rotate: {
    name: 'Rotate', short: 'R', color: 'violet',
    desc: 'Rotates the state about an axis of the Bloch sphere. From |0⟩, RY(θ) gives P(1) = sin²(θ/2).',
    analogy: '',
    roles: [{ key: 'targets', label: 'Qubits', min: 1 }],
    params: [
      { key: 'axis', type: 'select', label: 'Axis', options: [['y', 'Y'], ['x', 'X'], ['z', 'Z']], def: 'y' },
      { key: 'angle', type: 'angle', label: 'Angle θ', def: { pi: [1, 2] } },
    ],
  },
  swap: {
    name: 'Swap', short: 'SWAP', color: 'violet',
    desc: 'Exchanges the states of two qubits.',
    analogy: '',
    roles: [{ key: 'targets', label: 'Two qubits', min: 2, max: 2 }], params: [],
  },
  control: {
    name: 'Control', short: 'Ctrl', color: 'violet', wraps: 'control',
    desc: 'Runs an existing step only where every control qubit is 1.',
    analogy: '',
    roles: [{ key: 'controls', label: 'Control qubits', min: 1 }], params: [],
  },
  compare: {
    name: 'Compare', short: 'Compare', color: 'amber',
    desc: 'Checks a register against a number and writes the answer to a helper qubit.',
    analogy: '',
    roles: [{ key: 'ancillas', label: 'Helper qubit (starts at 0)', min: 1, max: 1 }, { key: 'targets', label: 'Register to check', min: 1, ordered: true }],
    params: [
      { key: 'operator', type: 'select', label: 'Test', options: [['eq', 'equals'], ['neq', 'is not equal to']], def: 'eq' },
      { key: 'value', type: 'int', label: 'Number', def: 0, binary: true },
    ],
  },
  uncompute: {
    name: 'Uncompute', short: 'Undo step', color: 'gray', wraps: 'ref',
    desc: 'Applies the exact inverse of an earlier step: its gates in reverse order, each one inverted. Mainly used after Compare, to return the helper qubit to 0 so it is no longer entangled with the register.',
    analogy: '',
    roles: [],
    params: [{ key: 'ref', type: 'ref', label: 'Step to undo', refOps: null, unitaryOnly: true }],
  },
  fourier: {
    name: 'Fourier transform', short: 'QFT', color: 'teal',
    desc: 'Quantum Fourier transform: turns basis states into phases, and back when inverse.',
    analogy: '',
    roles: [{ key: 'targets', label: 'Register (first picked = rightmost bit)', min: 1, ordered: true }],
    params: [
      { key: 'inverse', type: 'bool', label: 'Inverse', def: false },
      { key: 'swaps', type: 'bool', label: 'Reverse qubit order at the end (standard)', def: true },
    ],
  },
  add: {
    name: 'Add constant', short: 'Add', color: 'amber',
    desc: 'Adds a fixed number modulo 2ⁿ without measuring.',
    analogy: '',
    roles: [{ key: 'targets', label: 'Register (first picked = rightmost bit)', min: 1, ordered: true }],
    params: [{ key: 'value', type: 'int', label: 'Number to add', def: 1, binary: true }],
  },
  correct: {
    name: 'Classically controlled', short: 'If c', color: 'rose', wraps: 'correct',
    desc: 'Applies one of your steps only when a measured classical bit equals 0 or 1, decided while the circuit runs (feed-forward). For example, the X and Z corrections at the end of teleportation. Needs a Measure step before it.',
    needsMeasure: true,
    analogy: '',
    roles: [],
    params: [
      { key: 'clbit', type: 'clbit', label: 'When classical bit', virtual: true },
      { key: 'equals', type: 'select', label: 'equals', options: [['1', '1'], ['0', '0']], def: '1', virtual: true },
    ],
  },
};

export const GATES = [
  { id: 'h', label: 'H', name: 'h', controls: 0, targets: 1, desc: 'Hadamard' },
  { id: 'x', label: 'X', name: 'x', controls: 0, targets: 1, desc: 'Pauli-X (NOT)' },
  { id: 'y', label: 'Y', name: 'y', controls: 0, targets: 1, desc: 'Pauli-Y' },
  { id: 'z', label: 'Z', name: 'z', controls: 0, targets: 1, desc: 'Pauli-Z (phase flip)' },
  { id: 's', label: 'S', name: 's', controls: 0, targets: 1, desc: 'Phase π/2' },
  { id: 'sdg', label: 'S†', name: 'sdg', controls: 0, targets: 1, desc: 'Phase −π/2' },
  { id: 't', label: 'T', name: 't', controls: 0, targets: 1, desc: 'Phase π/4' },
  { id: 'tdg', label: 'T†', name: 'tdg', controls: 0, targets: 1, desc: 'Phase −π/4' },
  { id: 'p', label: 'P(θ)', name: 'p', controls: 0, targets: 1, angle: true, desc: 'Phase by θ' },
  { id: 'rx', label: 'RX(θ)', name: 'rx', controls: 0, targets: 1, angle: true, desc: 'Rotate about X' },
  { id: 'ry', label: 'RY(θ)', name: 'ry', controls: 0, targets: 1, angle: true, desc: 'Rotate about Y' },
  { id: 'rz', label: 'RZ(θ)', name: 'rz', controls: 0, targets: 1, angle: true, desc: 'Rotate about Z' },
  { id: 'cx', label: 'CX', name: 'x', controls: 1, targets: 1, desc: 'Controlled-X (CNOT)' },
  { id: 'cz', label: 'CZ', name: 'z', controls: 1, targets: 1, desc: 'Controlled-Z' },
  { id: 'cy', label: 'CY', name: 'y', controls: 1, targets: 1, desc: 'Controlled-Y' },
  { id: 'ch', label: 'CH', name: 'h', controls: 1, targets: 1, desc: 'Controlled-H' },
  { id: 'cp', label: 'CP(θ)', name: 'p', controls: 1, targets: 1, angle: true, desc: 'Controlled phase' },
  { id: 'ccx', label: 'CCX', name: 'x', controls: 2, targets: 1, desc: 'Toffoli' },
  { id: 'swap', label: 'SWAP', name: 'swap', controls: 0, targets: 2, desc: 'Swap two qubits' },
  { id: 'cswap', label: 'CSWAP', name: 'swap', controls: 1, targets: 2, desc: 'Fredkin' },
];

export const GATE_FAMILIES = [
  { name: 'Single qubit', ids: ['h', 'x', 'y', 'z', 's', 'sdg', 't', 'tdg'] },
  { name: 'Rotations', ids: ['p', 'rx', 'ry', 'rz'] },
  { name: 'Multi-qubit', ids: ['cx', 'cz', 'cy', 'ch', 'cp', 'ccx', 'swap', 'cswap'] },
];

export const ANGLE_PRESETS = [[1, 1, 'π'], [1, 2, 'π/2'], [1, 4, 'π/4'], [-1, 2, '−π/2'], [-1, 4, '−π/4'], [1, 3, 'π/3'], [2, 3, '2π/3']];

export const WRAPPABLE = op => !['measure', 'reset', 'correct', 'uncompute'].includes(op);
export const UNITARY = op => !['measure', 'reset', 'correct'].includes(op);

export function gateLabel(node) {
  const p = node.params || {};
  const g = GATES.find(x => x.name === p.name && x.controls === (node.controls || []).length && (x.targets === (node.targets || []).length));
  const base = g ? g.label.replace('(θ)', '') : ('C'.repeat((node.controls || []).length) + String(p.name || '?').toUpperCase());
  return base;
}

export function colorOf(node) {
  if (node.op === 'gate') return 'gate';
  return (CONCEPTS[node.op] || {}).color || 'gray';
}

export function nameOf(node) {
  if (node.op === 'gate') return gateLabel(node);
  return (CONCEPTS[node.op] || {}).name || node.op;
}
