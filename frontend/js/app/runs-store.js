import { store } from './util.js';

const KEY = 'qc.runs.v2';
const MAX_RUNS = 200;

export function listRuns() {
  return store.get(KEY, []);
}

export function getRun(id) {
  return listRuns().find(r => r.id === id) || null;
}

export function saveRun(run) {
  const all = listRuns().filter(r => r.id !== run.id);
  all.unshift(run);
  const ok = store.set(KEY, all.slice(0, MAX_RUNS));
  return ok;
}

export function deleteRun(id) {
  store.set(KEY, listRuns().filter(r => r.id !== id));
}

export function clearRuns() {
  store.remove(KEY);
}
