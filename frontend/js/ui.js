// QuantumCanvas — Pseudocode panel renderer and UI helpers
// Load order: state.js → ir.js → pseudocode.js → ui.js → qiskit-generator.js → qiskit-panel.js

// ── Panel Renderer ───────────────────────────────────────────────────
const STRIPE={INITIALIZE:'s-init',SHAKE:'s-shake',MARK:'s-mark',BOOST:'s-boost',LINK:'s-link',LOOK:'s-look'};

function openPseudocodePanel(){
  const ir  = extractCanvasIR(state);
  validateIR(ir);
  let doc=null;
  if(ir.validation.ok) doc=generatePseudocode(ir);
  _renderPC(ir,doc);
  document.getElementById('pc-overlay').classList.add('open');
}
function closePseudocodePanel(){
  document.getElementById('pc-overlay').classList.remove('open');
}
function pcOverlayClick(e){
  if(e.target===document.getElementById('pc-overlay')) closePseudocodePanel();
}
function pcQnote(btn){
  const n=btn.nextElementSibling;
  n.classList.toggle('open');
  btn.textContent=n.classList.contains('open')?'[ quantum ▾ ]':'[ quantum ▸ ]';
}
// ════════════════════════════════════════════════════════════════════
//  QISKIT GENERATOR  — Layer 2
//  Source of truth: PseudocodeDoc steps (not IR directly)
//  Label → qubit index map built from ir.qubits order
// ════════════════════════════════════════════════════════════════════

// ── Dev helpers ──────────────────────────────────────────────────────
window.QC={
  ir:  ()=>extractCanvasIR(state),
  val: ()=>{ const ir=extractCanvasIR(state); return validateIR(ir); },
  doc: ()=>{ const ir=extractCanvasIR(state); validateIR(ir); return ir.validation.ok?generatePseudocode(ir):ir.validation; },
  open:openPseudocodePanel,
};
console.log('[QC] Pseudocode engine ready. Dev: QC.ir() · QC.val() · QC.doc() · QC.open()');
