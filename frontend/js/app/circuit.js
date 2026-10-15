import { api } from './api.js';
import { store, debounce } from './util.js';

const KEY = 'qc.build.v1';
const MAX_HISTORY = 200;
export const MAX_QUBITS = 12;

const blank = () => ({ title: 'Untitled circuit', qubits: 2, nodes: [], nextId: 1 });

function qubitsOf(n) {
  return [...(n.targets || []), ...(n.controls || []), ...(n.ancillas || []), ...(n.body ? qubitsOf(n.body) : [])];
}

export const circuit = {
  s: { ...blank(), ...store.get(KEY, {}) },
  undoStack: [],
  redoStack: [],
  compiled: null,
  compileError: null,
  compiling: false,
  lastRun: store.get('qc.build.lastRun', null),
  listeners: new Set(),

  on(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); },
  emit(kind) { this.listeners.forEach(fn => fn(kind)); },

  snapshot() { return JSON.parse(JSON.stringify({ title: this.s.title, qubits: this.s.qubits, nodes: this.s.nodes, nextId: this.s.nextId })); },
  persist() { store.set(KEY, this.snapshot()); },

  change(mutate, label) {
    this.undoStack.push({ snap: this.snapshot(), label });
    if (this.undoStack.length > MAX_HISTORY) this.undoStack.shift();
    this.redoStack = [];
    mutate(this.s);
    this.persist();
    this.emit('change');
    this.scheduleCompile();
  },
  canUndo() { return this.undoStack.length > 0; },
  canRedo() { return this.redoStack.length > 0; },
  undo() {
    const top = this.undoStack.pop();
    if (!top) return null;
    this.redoStack.push({ snap: this.snapshot(), label: top.label });
    Object.assign(this.s, top.snap);
    this.persist(); this.emit('change'); this.scheduleCompile();
    return top.label;
  },
  redo() {
    const top = this.redoStack.pop();
    if (!top) return null;
    this.undoStack.push({ snap: this.snapshot(), label: top.label });
    Object.assign(this.s, top.snap);
    this.persist(); this.emit('change'); this.scheduleCompile();
    return top.label;
  },

  newId() { return `N${this.s.nextId++}`; },
  nodeById(id) { return this.s.nodes.find(n => n.id === id) || null; },
  index(id) { return this.s.nodes.findIndex(n => n.id === id); },
  qubitsOf,
  highestQubitUsed() { return Math.max(-1, ...this.s.nodes.flatMap(qubitsOf)); },

  classicalBits() {
    let m = -1;
    const visit = n => { (n.classical || []).forEach(c => { m = Math.max(m, c); }); if (n.condition) m = Math.max(m, n.condition.clbit); if (n.body) visit(n.body); };
    this.s.nodes.forEach(visit);
    return m + 1;
  },

  toDocument() {
    const strip = n => {
      const { seq, ...rest } = n;
      return { id: rest.id, op: rest.op, targets: rest.targets || [], controls: rest.controls || [], ancillas: rest.ancillas || [],
               classical: rest.classical || [], params: rest.params || {}, condition: rest.condition || null,
               body: rest.body ? strip(rest.body) : null, ref: rest.ref || null, repeat: rest.repeat || 1, metadata: rest.metadata || {} };
    };
    return { version: '0.4', qubits: this.s.qubits, classical_bits: this.classicalBits(), operations: this.s.nodes.map(strip) };
  },
  docKey() { return JSON.stringify(this.toDocument()); },

  load(doc, title, label = 'Open circuit') {
    this.change(s => {
      s.qubits = Math.max(1, Math.min(MAX_QUBITS, doc.qubits || 1));
      s.nodes = JSON.parse(JSON.stringify(doc.operations || []));
      s.title = title || s.title;
      const nums = s.nodes.map(n => parseInt(String(n.id).replace(/\D/g, ''), 10)).filter(Number.isFinite);
      s.nextId = (nums.length ? Math.max(...nums) : 0) + 1;
      s.nodes.forEach(n => { if (!/^N\d+$/.test(n.id) && !/^g\d+$/.test(n.id)) n.id = `N${s.nextId++}`; });
    }, label);
  },

  addNode(node, label) {
    this.change(s => { s.nodes.push(node); }, label || 'Add step');
  },
  replaceNode(id, node, label) {
    this.change(s => { s.nodes = s.nodes.map(n => n.id === id ? node : n); }, label || 'Edit step');
  },
  usersOf(id) {
    const inside = n => [n.id, ...(n.body ? inside(n.body) : [])];
    return this.s.nodes.filter(n => !inside(n).includes(id) && (n.ref === id || n.params?.via === id));
  },
  removeNode(id) {
    const users = this.usersOf(id);
    if (users.length) return `Step ${this.index(users[0].id) + 1} uses this step, so remove that one first.`;
    this.change(s => { s.nodes = s.nodes.filter(n => n.id !== id); }, 'Delete step');
    return null;
  },
  moveNode(id, dir) {
    const i = this.index(id), j = i + dir;
    if (i < 0 || j < 0 || j >= this.s.nodes.length) return;
    this.change(s => { const a = s.nodes[i]; s.nodes[i] = s.nodes[j]; s.nodes[j] = a; }, dir < 0 ? 'Move step earlier' : 'Move step later');
  },
  setQubits(n) {
    n = Math.max(1, Math.min(MAX_QUBITS, n));
    if (n <= this.highestQubitUsed()) return `q${this.highestQubitUsed()} is used by a step, so the circuit needs at least ${this.highestQubitUsed() + 1} qubits.`;
    this.change(s => { s.qubits = n; }, n > this.s.qubits ? 'Add qubit' : 'Remove qubit');
    return null;
  },
  applyCode(qubits, nodes, session) {
    const top = this.undoStack[this.undoStack.length - 1];
    const mutate = s => { s.qubits = Math.max(1, Math.min(MAX_QUBITS, qubits)); s.nodes = nodes; };
    if (session && top && top.session === session) {
      this.redoStack = [];
      mutate(this.s);
      this.persist(); this.emit('change'); this.scheduleCompile();
      return;
    }
    this.change(mutate, 'Edit code');
    this.undoStack[this.undoStack.length - 1].session = session;
  },
  setTitle(t) { this.s.title = t || 'Untitled circuit'; this.persist(); this.emit('title'); },
  clear() { this.change(s => { s.nodes = []; s.nextId = 1; }, 'Clear circuit'); },
  reset(title) { this.change(s => { Object.assign(s, blank(), { title: title || 'Untitled circuit' }); }, 'New circuit'); },

  async compileNow() {
    const key = this.docKey();
    this.compiling = true; this.emit('compiling');
    try {
      const res = await api.post('/compile', { document: this.toDocument() });
      if (key === this.docKey()) { this.compiled = res; this.compileError = null; }
    } catch (e) {
      if (key === this.docKey()) { this.compiled = null; this.compileError = e.message; }
    }
    this.compiling = false;
    this.emit('compiled');
    return this.compiled;
  },
  scheduleCompile: null,

  setRun(run) {
    this.lastRun = run;
    store.set('qc.build.lastRun', run);
    this.emit('run');
  },
  runIsCurrent() { return !!this.lastRun && this.lastRun.docKey === this.docKey(); },
};

circuit.scheduleCompile = debounce(() => circuit.compileNow(), 250);

export function layout(nodes, nQubits, zoomedId, compiled) {
  const level = new Array(nQubits).fill(0);
  const items = [];
  for (const n of nodes) {
    const qs = qubitsOf(n).filter(q => q >= 0 && q < nQubits);
    if (!qs.length) { items.push({ node: n, col: Math.max(0, ...level), lo: 0, hi: 0, w: 1 }); continue; }
    const lo = Math.min(...qs), hi = Math.max(...qs);
    let start = 0;
    for (let q = lo; q <= hi; q++) start = Math.max(start, level[q]);
    const range = n.id === zoomedId && compiled?.node_ranges?.[n.id];
    if (range && range.length) {
      const sub = new Array(nQubits).fill(0);
      const gates = range.map(i => {
        const g = compiled.gates[i];
        const gq = [...(g.controls || []), ...g.targets];
        const glo = Math.min(...gq), ghi = Math.max(...gq);
        let c = 0;
        for (let q = glo; q <= ghi; q++) c = Math.max(c, sub[q]);
        for (let q = glo; q <= ghi; q++) sub[q] = c + 1;
        return { gate: g, col: start + c, lo: glo, hi: ghi };
      });
      const w = Math.max(1, ...sub);
      items.push({ node: n, col: start, lo, hi, w, zoom: gates });
      for (let q = lo; q <= hi; q++) level[q] = start + w;
    } else {
      items.push({ node: n, col: start, lo, hi, w: 1 });
      for (let q = lo; q <= hi; q++) level[q] = start + 1;
    }
  }
  const cols = Math.max(1, ...level);
  return { items, cols };
}
