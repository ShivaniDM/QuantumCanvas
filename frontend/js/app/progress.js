import { store } from './util.js';

const ANALOGY_KEY = 'qc.analogy.v1';
export const ANALOGY_VISITS = 2;

export function seeAnalogy(op) {
  const seen = store.get(ANALOGY_KEY, {});
  const n = (seen[op] || 0) + 1;
  seen[op] = n;
  store.set(ANALOGY_KEY, seen);
  return n <= ANALOGY_VISITS;
}

export function resetAnalogies() {
  store.remove(ANALOGY_KEY);
}
