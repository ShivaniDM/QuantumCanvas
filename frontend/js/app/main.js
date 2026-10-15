import { renderBuild } from './build.js';
import { renderHelp } from './help.js';
import { renderHome } from './home.js';
import { renderImport } from './importer.js';
import { renderRunDetail, renderRuns, renderShared } from './runs.js';
import { store } from './util.js';

const main = document.getElementById('main');

const TITLES = { home: 'QuantumCanvas', build: 'Build · QuantumCanvas', import: 'Bring code · QuantumCanvas',
                 runs: 'My runs · QuantumCanvas', help: 'Help · QuantumCanvas' };

function parse() {
  const raw = location.hash.replace(/^#\/?/, '');
  const [path, qs] = raw.split('?');
  const parts = path.split('/').filter(Boolean);
  return { parts, query: new URLSearchParams(qs || '') };
}

function route() {
  const { parts, query } = parse();
  const [head = 'home', arg] = parts;
  document.querySelectorAll('[data-nav]').forEach(a => {
    const on = a.dataset.nav === head || (head === 'import' && a.dataset.nav === 'build') || (head === 'shared' && a.dataset.nav === 'runs');
    if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  document.title = TITLES[head] || TITLES.home;
  window.scrollTo(0, 0);
  switch (head) {
    case 'build': renderBuild(main, arg); break;
    case 'import': renderImport(main, query); break;
    case 'runs': if (arg) renderRunDetail(main, arg); else renderRuns(main); break;
    case 'shared': renderShared(main, arg); break;
    case 'help': renderHelp(main); break;
    default: renderHome(main);
  }
}

function applyTheme(t) {
  if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
  const btn = document.getElementById('theme-btn');
  btn.textContent = t === 'dark' ? 'Dark' : t === 'light' ? 'Light' : 'Auto';
  btn.setAttribute('aria-label', `Colour theme: ${btn.textContent}. Click to change.`);
}

applyTheme(store.get('qc.theme', null));
document.getElementById('theme-btn').addEventListener('click', () => {
  const cur = store.get('qc.theme', null);
  const next = cur === null ? 'light' : cur === 'light' ? 'dark' : null;
  store.set('qc.theme', next);
  applyTheme(next);
});

window.addEventListener('hashchange', route);
route();
