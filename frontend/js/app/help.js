import { CONCEPTS } from './catalog.js';
import { resetAnalogies } from './progress.js';
import { esc, toast } from './util.js';

const TERMS = [
  ['Qubit', 'The basic unit of quantum information. Its state is a vector of two amplitudes, one for |0⟩ and one for |1⟩. Qubits are numbered q0, q1, q2…'],
  ['Basis state', 'One of the definite states |0⟩ and |1⟩, or for several qubits |00⟩, |01⟩, |10⟩, |11⟩ and so on.'],
  ['Amplitude', 'The number attached to a basis state in the state vector. It can be negative or complex.'],
  ['Born rule', 'The probability of a measurement outcome is the squared magnitude of its amplitude.'],
  ['Normalized', 'A state whose probabilities add up to 1.'],
  ['Superposition', 'A state with non-zero amplitude on more than one basis state. It is not a hidden 0 or 1 waiting to be revealed.'],
  ['Relative phase', 'A sign or complex factor on one amplitude relative to another. It changes nothing on its own, but shows up after further gates.'],
  ['Interference', 'Amplitudes from different paths adding up or cancelling, which changes the probabilities.'],
  ['Entanglement', 'A state of several qubits that cannot be written one qubit at a time. Measured outcomes are correlated.'],
  ['Measurement', 'Reading a qubit as 0 or 1. The result is random according to the Born rule, and the state becomes the measured basis state.'],
  ['Gate', 'An operation on qubits, written as a matrix. Applying a gate multiplies the state vector by that matrix.'],
  ['Concept', 'A named group of gates in QuantumCanvas, such as Superposition (H) or Amplitude amplification. Every concept opens into its exact gates.'],
  ['Pseudocode', "The circuit's steps written in structured plain language, before they become code."],
  ['Bit order', 'Qiskit writes the highest-numbered bit on the left: |q1 q0⟩. So |01⟩ means q1 = 0 and q0 = 1.'],
  ['Shots', 'How many times a circuit is run. Each shot gives one outcome; the counts show how often each appeared.'],
  ['Counts', 'How many shots gave each outcome.'],
  ['Measured frequency', 'Counts divided by shots. It is close to, but rarely exactly, the predicted probability.'],
  ['Predicted probability', 'The exact probability worked out from the state, with no sampling.'],
  ['Backend', 'Where a circuit runs: the built-in simulator (Qiskit Aer) or an IonQ cloud simulator, either ideal or with a device noise model.'],
  ['Oracle', 'A step that marks one or more basis states, usually by flipping the sign of their amplitude.'],
  ['Amplitude amplification', 'Reflecting every amplitude about the average so that marked states become more likely. The core of Grover search.'],
];

export function renderHelp(main) {
  main.innerHTML = `<div class="page help" style="max-width:920px">
    <h1 style="margin:0 0 8px;font-size:28px">Help</h1>
    <p class="muted" style="margin:0">How QuantumCanvas is organised, the keyboard shortcuts, and the terms it uses.</p>
    <h2>Where things are</h2>
    <dl class="glossary">
      <dt>Build</dt><dd>Compose a circuit from concepts or gates, run it, and get a checked explanation. The panel under the qubit lines shows the same circuit as Qiskit, OpenQASM 3, pseudocode and maths. Edit the Qiskit or OpenQASM and the canvas follows; pseudocode and maths are generated, so they are read-only.</dd>
      <dt>Bring code</dt><dd>Paste OpenQASM or Qiskit. Every gate is kept exactly; familiar patterns are offered as concepts you can accept or skip.</dd>
      <dt>My runs</dt><dd>Every run from this browser, with share links for runs stored on the server.</dd>
      <dt>Practice problems</dt><dd>On the home page. Each opens in Build and is checked automatically.</dd>
    </dl>
    <h2>Keyboard</h2>
    <dl class="glossary">
      <dt><span class="kbd">Ctrl</span> <span class="kbd">Z</span> · <span class="kbd">Ctrl</span> <span class="kbd">Shift</span> <span class="kbd">Z</span></dt><dd>Undo and redo in Build.</dd>
      <dt><span class="kbd">Tab</span></dt><dd>Moves through the palette, the blocks on the canvas and the inspector.</dd>
      <dt><span class="kbd">G</span></dt><dd>Show or fold the gates of the selected block.</dd>
      <dt><span class="kbd">Delete</span></dt><dd>Delete the selected block (undo brings it back).</dd>
      <dt><span class="kbd">Esc</span></dt><dd>Cancel the step you are adding, close a dialog, or leave the code editor.</dd>
      <dt><span class="kbd">Ctrl</span> <span class="kbd">Enter</span></dt><dd>In the code editor: apply your edits now instead of waiting.</dd>
    </dl>
    <h2>Concepts</h2>
    <dl class="glossary">${Object.values(CONCEPTS).map(c => `<dt>${esc(c.name)}</dt><dd>${esc(c.desc)}</dd>`).join('')}</dl>
    <h2>Glossary</h2>
    <dl class="glossary">${TERMS.map(([t, d]) => `<dt id="term-${t.toLowerCase().replace(/\s+/g, '-')}">${esc(t)}</dt><dd>${esc(d)}</dd>`).join('')}</dl>
    <h2>Your data</h2>
    <p style="font-size:14px">Your circuit and runs are stored in this browser. Runs also create a record on the QuantumCanvas server so they can be explained and shared.</p>
    <button type="button" class="btn small" data-reset>Show concept analogies again</button>
  </div>`;
  main.querySelector('[data-reset]').addEventListener('click', () => {
    resetAnalogies(); toast('Analogies will show again for the next two times you add each concept.');
  });
}
