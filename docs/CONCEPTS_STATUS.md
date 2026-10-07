# Concepts expansion — status, decisions and deviations

Companion to `CONCEPTS_PLAN.md`. Written when milestones M0–M6 were first delivered.

## Decisions taken (answers to plan section 10)

| | Decision |
|---|---|
| Compiler location | **Python backend** (`backend/concepts/`). The browser asks `POST /compile`; it needs the backend running. Offline use is a later topic. |
| Naming | **Entangle** and **Measure** are the user-facing names everywhere (Classic sidebar, panels, generated-code comments, concept palette). Internal tool ids of the Classic canvas are unchanged (`link`, `look`). |
| Where | Main canvas only. Learn mode is untouched. |
| D1 | Keep both Set and Encode. Encode(basis) expands to Set. |
| D2 | **Correct** |
| D3 | Rotate takes an angle only. |
| D4 | Entangle stays a named composite (= Control{Flip}, or Control{Phase π} for style `cz`). |
| D5 | Compare lt/gt later (rejected with a clear message). |

## What exists

| Milestone | Delivered | Where |
|---|---|---|
| M0 | Recon report (delivered in chat before any code) | — |
| M1 | Schema v0.3, conventions, validator, primitives, Control, trace map, legacy migration | `backend/concepts/{schema,angles,validate,lower,gates,migrate}.py` |
| M2 | Entangle, Encode, Compare (eq/neq), Mark (value and via), Boost, Uncompute | `lower.py` |
| M3 | Fourier, Add (Draper, modulus 2ⁿ) | `lower.py` |
| M4 | Correct (`if_test`), IonQ deferred-measurement rewrite, backend warnings | `lower.py`, `ionq_lower.py` |
| M5 | Concepts mode UI: palette by family, step builder with live binary preview and π-fraction angles, Steps panel with inline validator messages, Control/Correct wrappers, "How is this implemented?" view driven by the trace | `frontend/js/concepts*.js`, `frontend/css/concepts.css` |
| M6 | 14-problem bank, auto-checker, problem UI with hint ladder | `backend/problems/`, `frontend/js/problems.js` |

Endpoints added: `POST /compile`, `GET /problems`, `POST /check-problem`. `POST /execute` accepts an optional `concept_ir`.

## Deliberate differences from the plan / previous behaviour

1. **Consecutive Boost clicks.** The old JS generator merged back-to-back Boost clicks into *one* diffuser even though its pseudocode said "N×". v0.3 applies one diffuser per click. Covered by `test_consecutive_boost_clicks_each_apply_a_diffuser`.
2. **Extra validator codes** beyond the plan: `E_PARAM` (bad/missing parameter), `E_UNKNOWN_OP`, `E_DUP_ID`, `E_CLBIT_RANGE`, `E_SCHEMA`.
3. **Mark via Compare** = Phase(π) on the Compare's ancilla, then Uncompute the Compare (one step in the UI).
4. **Problem checker extras**: `setup` / `postfix` ops, `marginal_clbits`, `auto_measure`, `at_least`, `must_use` (with parameter matching), and a `qubit_probabilities` check type. Teleportation is graded by un-preparing the sent state on q2 and expecting a definite 0, so the Z correction is actually tested.
5. **`/execute` now re-raises deliberate 4xx errors.** Before, any `HTTPException` raised inside its `try` was turned into a 500.
6. Three small pre-existing bugs fixed on the way: the top-bar qubit counter lost its id after the first update (second qubit placement threw), `clearCanvas()` did not reset qubit numbering, and the Qiskit panel's syntax highlighter printed stray `"qk-kw">` text.

## Not verified / known limits

* **IonQ API shape.** `docs.ionq.com` was not reachable from the build sandbox. The IonQ lowering reuses gate shapes already present in `ionq_runner.py` (`h x z cnot t ti mcx`) and adds `y s si rx ry rz` with a `"rotation"` key. **Please check `"rotation"` and the extra gate names against the current IonQ docs before submitting real jobs.** Everything is tested for *equivalence* (the lowered gate list, interpreted with Qiskit, equals the L2 circuit up to global phase), not against IonQ itself.
* On IonQ, Reset, measuring a qubit twice, and using a qubit after measuring it are refused with a plain explanation (they run on Aer).
* Uncontrolled `P(θ)` becomes `rz(θ)` for IonQ (differs by an unobservable global phase); controlled phases are decomposed exactly.
* The UI has no automated tests; it was exercised end-to-end in a real browser (all 14 problems driven through the interface).
* Compile needs the backend (`POST /compile`). Offline JS compile is not built.
* Concept steps and Classic ops can be mixed; Classic ops show as read-only rows. Qubits can't be deleted while steps exist (steps refer to qubits by position).

## Running the tests

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest tests -q
```

`backend/tests/fixtures/legacy/*.json` are produced by running the *real* browser pipeline (`frontend/js/ir.js`, `pseudocode.js`, `qiskit-generator.js`) under Node:

```bash
cd backend/tests && node make_legacy_fixtures.js
```
