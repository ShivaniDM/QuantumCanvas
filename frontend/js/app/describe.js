import { CONCEPTS, gateLabel } from './catalog.js';
import { fmtAngle } from './util.js';

export const bits = (v, n) => Math.max(0, Math.floor(+v || 0)).toString(2).padStart(Math.max(1, n), '0');
const qs = list => (list || []).map(q => `q${q}`).join(', ');

export function blockLabel(n) {
  if (n.op === 'gate') return gateLabel(n);
  const c = CONCEPTS[n.op];
  if (!c) return n.op;
  if (n.op === 'mark') return n.params?.via ? 'Oracle' : `Oracle |${bits(n.params?.value, (n.targets || []).length)}⟩`;
  if (n.op === 'rotate') return `R${String(n.params?.axis || 'y').toUpperCase()}`;
  if (n.op === 'fourier' && n.params?.inverse) return 'QFT†';
  return c.name;
}

export function blockSub(n, stepNo) {
  const p = n.params || {};
  const T = n.targets || [];
  switch (n.op) {
    case 'gate': return [p.angle ? fmtAngle(p.angle) : '', (n.controls || []).length ? `${qs(n.controls)} → ${qs(T)}` : qs(T)].filter(Boolean).join(' · ');
    case 'shake': return `H on ${qs(T)}`;
    case 'flip': return `X on ${qs(T)}`;
    case 'entangle': return `${p.style === 'cz' ? 'CZ' : 'CNOT'} q${T[0]} → q${T[1]}`;
    case 'mark': return p.via ? 'via Compare' : `on ${qs(T)}`;
    case 'boost': return `${n.repeat > 1 ? `${n.repeat} rounds · ` : ''}${qs(T)}`;
    case 'measure': return `→ ${(n.classical || []).map(c => `c${c}`).join(', ')}`;
    case 'set': return `= ${p.value} (|${bits(p.value, T.length)}⟩)`;
    case 'phase': return `${fmtAngle(p.angle)} on ${qs(T)}`;
    case 'rotate': return `${fmtAngle(p.angle)} on ${qs(T)}`;
    case 'compare': return `${p.operator === 'neq' ? '≠' : '='} ${p.value} → q${(n.ancillas || [])[0]}`;
    case 'fourier': return qs(T);
    case 'add': return `+${p.value} mod ${p.modulus || 2 ** T.length}`;
    case 'control': return `if ${qs(n.controls)} = 1: ${n.body ? blockLabel(n.body) : ''}`;
    case 'correct': return `if c${n.condition?.clbit} = ${n.condition?.equals}: ${n.body ? blockLabel(n.body) : ''}`;
    case 'uncompute': return 'reverses an earlier step';
    case 'reset': return `q${T[0]} → |0⟩`;
    case 'encode': return p.method === 'basis' ? `= ${p.data}` : `angles on ${qs(T)}`;
    default: return qs(T);
  }
}

const KEYWORD = { SHAKE: 'SUPERPOSE', MARK: 'ORACLE', BOOST: 'AMPLIFY' };
export function pseudocodeLine(code) {
  return String(code || '').replace(/^([A-Z]+)/, w => KEYWORD[w] || w);
}
