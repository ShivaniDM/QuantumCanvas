// QuantumCanvas Learn — read-only notebook viewer (Colab-style cells).
// Depends on learn-sim.js (parseCell). Calls window.LearnApp.* hooks defined in learn.js.

const esc = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

function highlightPy(src){
  const re = /(#.*$)|("""[\s\S]*?"""|"[^"\n]*"|'[^'\n]*')|\b(import|from|as|def|return|for|in|if|else|elif|print|class|lambda|with|True|False|None|raise|assert)\b|\b(\d+\.?\d*(?:e-?\d+)?)\b/gm;
  return esc(src).replace(re,(m,c,s,k,n)=>
    c?`<span class="tk-c">${c}</span>`: s?`<span class="tk-s">${s}</span>`: k?`<span class="tk-k">${k}</span>`: `<span class="tk-n">${n}</span>`);
}

function renderTex(tex, display){
  try{
    if(window.katex) return katex.renderToString(tex,{displayMode:display,throwOnError:false});
  }catch(e){}
  return `<code>${esc(tex)}</code>`;
}

// Small markdown → HTML. Handles what the Fall Fest notebooks use: headings, lists, bold/italic, code,
// links (incl. in-notebook #anchors), blockquotes, $math$, and a whitelist of inline HTML (<b>, <i>, <br>, <code>).
function mdToHtml(src){
  const anchors = [];
  let callout = false;
  src = src.replace(/<a\s+id="([^"]+)"\s*><\/a>/g,(_,id)=>{ anchors.push(id); return ''; });
  if(/<div[^>]*alert/.test(src)) callout = true;
  src = src.replace(/<\/?div[^>]*>/g,'');
  src = src.replace(/!\[[^\]]*\]\([^)]*\)/g,'');                 // images are not bundled
  const maths = [];
  src = src.replace(/\$\$([\s\S]+?)\$\$/g,(_,t)=>{ maths.push(renderTex(t.trim(),true)); return `\u0001${maths.length-1}\u0001`; });
  src = src.replace(/\$([^$\n]+?)\$/g,(_,t)=>{ maths.push(renderTex(t.trim(),false)); return `\u0001${maths.length-1}\u0001`; });
  src = src.replace(/<(\/?)(b|i|em|strong|code|br)\s*\/?>/g,'\u0002$1$2\u0002');
  src = esc(src).replace(/\u0002(\/?)(\w+)\u0002/g,(_,sl,t)=> t==='br'?'<br>':`<${sl}${t}>`);

  const inline = s=>{
    const codes = [];
    s = s.replace(/`([^`]+)`/g,(_,c)=>{ codes.push(c); return `\u0003${codes.length-1}\u0003`; });
    s = s.replace(/\*\*(.+?)\*\*/g,'<b>$1</b>')
         .replace(/(^|[\s(])\*(?!\s)(.+?)\*(?=[\s).,;:]|$)/g,'$1<i>$2</i>')
         .replace(/\[([^\]]+)\]\((#[^)]+)\)/g,'<a href="#" data-anchor="$2">$1</a>')
         .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
    return s.replace(/\u0003(\d+)\u0003/g,(_,i)=>`<code>${codes[i]}</code>`);
  };

  const out = []; let list = null, para = [];
  const flushPara = ()=>{ if(para.length){ out.push(`<p>${inline(para.join(' ').replace(/<br> /g,'<br>'))}</p>`); para=[]; } };
  const flushList = ()=>{ if(list){ out.push(`</${list}>`); list=null; } };
  for(const line of src.split('\n')){
    let m;
    if(!line.trim()){ flushPara(); flushList(); continue; }
    if((m = line.match(/^(#{1,6})\s+(.*)$/))){ flushPara(); flushList(); out.push(`<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`); continue; }
    if((m = line.match(/^\s*[*-]\s+(.*)$/))){ flushPara(); if(list!=='ul'){ flushList(); out.push('<ul>'); list='ul'; } out.push(`<li>${inline(m[1])}</li>`); continue; }
    if((m = line.match(/^\s*\d+\.\s+(.*)$/))){ flushPara(); if(list!=='ol'){ flushList(); out.push('<ol>'); list='ol'; } out.push(`<li>${inline(m[1])}</li>`); continue; }
    if((m = line.match(/^&gt;\s?(.*)$/))){ flushPara(); flushList(); out.push(`<blockquote>${inline(m[1])}</blockquote>`); continue; }
    flushList(); para.push(line.trim() + (/ {2}$/.test(line) ? '<br>' : ''));
  }
  flushPara(); flushList();
  const html = out.join('\n').replace(/\u0001(\d+)\u0001/g,(_,i)=>maths[i]);
  return {html, anchors, callout};
}

const Notebook = {
  data: null,        // parsed ipynb
  sidecar: {},       // {cellIndex: {n, ops, title, note}}
  name: '',
  linked: null,

  async loadUrl(url, name){
    const resp = await fetch(url);
    if(!resp.ok) throw new Error(`Could not load ${url} (${resp.status})`);
    const nb = await resp.json();
    let side = {};
    try{
      const r = await fetch(url.replace(/\.ipynb$/,'.qc.json'));
      if(r.ok) side = (await r.json()).cells || {};
    }catch(e){}
    this.load(nb, name, side);
  },

  load(nb, name, side={}){
    if(!nb || !Array.isArray(nb.cells)) throw new Error('Not a valid .ipynb file');
    this.data = nb; this.name = name; this.sidecar = side; this.linked = null;
    this.render();
  },

  cellSource(c){ return Array.isArray(c.source) ? c.source.join('') : (c.source||''); },

  // circuit available for a code cell: curated sidecar first, then literal qc.<gate>() parsing
  circuitFor(i){
    const sc = this.sidecar[String(i)];
    if(sc) return {n: sc.n, ops: sc.ops.map(o=>({...o})), title: sc.title, note: sc.note, skipped: []};
    const c = this.data.cells[i];
    if(c.cell_type !== 'code') return null;
    const parsed = parseCell(this.cellSource(c));
    return parsed ? {...parsed, title: `cell ${i}`} : null;
  },

  render(){
    const host = document.getElementById('nb-cells');
    host.innerHTML = '';
    const title = (this.data.cells.find(c=>c.cell_type==='markdown' && /^#\s/m.test(this.cellSource(c))) || {});
    const t = (this.cellSource(title).match(/^#\s+(.*)$/m)||[])[1];
    document.getElementById('nb-title').textContent = (t||this.name).replace(/<[^>]+>/g,'').trim();
    document.getElementById('nb-sub').textContent = `${this.name} · ${this.data.cells.length} cells`;
    const anchorMap = {};
    this.data.cells.forEach((c,i)=>{
      const src = this.cellSource(c);
      if(!src.trim()) return;
      const el = document.createElement('div');
      el.className = `l-cell ${c.cell_type}`; el.id = `cell-${i}`;
      if(c.cell_type === 'markdown'){
        const {html, anchors, callout} = mdToHtml(src);
        if(!html.trim()) return;
        anchors.forEach(a=>anchorMap[a]=el.id);
        el.innerHTML = `<div class="l-gutter"></div><div class="l-body"><div class="l-md${callout?' callout':''}">${html}</div></div>`;
      }else{
        const circ = this.circuitFor(i);
        el.innerHTML = `<div class="l-gutter">[${i}]</div><div class="l-body">
          <pre class="l-pre">${highlightPy(src)}</pre>
          <div class="l-cell-actions">
            ${circ ? `<button class="l-vis" data-vis="${i}">◧ Visualise</button>` : `<span class="l-nocirc">no gate-level circuit in this cell</span>`}
            <button class="l-copy" data-copy="${i}">Copy</button>
            <span class="l-linkedtag" hidden>● shown on canvas</span>
          </div></div>`;
      }
      host.appendChild(el);
    });
    host.onclick = e=>{
      const a = e.target.closest('[data-anchor]');
      if(a){ e.preventDefault(); const t = document.getElementById(anchorMap[a.dataset.anchor.slice(1)]); if(t) t.scrollIntoView({behavior:'smooth',block:'start'}); return; }
      const v = e.target.closest('[data-vis]');
      if(v){ this.visualise(+v.dataset.vis); return; }
      const c = e.target.closest('[data-copy]');
      if(c){ const i = +c.dataset.copy; LearnApp.copyText(this.cellSource(this.data.cells[i]), `Copied cell [${i}]`); }
    };
    host.scrollTop = 0;
  },

  visualise(i){
    const circ = this.circuitFor(i);
    if(!circ){ LearnApp.toast('No circuit found in this cell','warn'); return; }
    this.setLinked(i);
    LearnApp.loadCircuit(circ, i);
  },

  setLinked(i){
    document.querySelectorAll('.l-cell.linked').forEach(e=>{ e.classList.remove('linked'); const t=e.querySelector('.l-linkedtag'); if(t) t.hidden=true; });
    this.linked = i;
    if(i==null) return;
    const el = document.getElementById(`cell-${i}`);
    if(el){ el.classList.add('linked'); const t=el.querySelector('.l-linkedtag'); if(t) t.hidden=false; el.scrollIntoView({behavior:'smooth',block:'nearest'}); }
  },
};
