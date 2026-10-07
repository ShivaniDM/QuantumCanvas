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

## Explanation faithfulness (added after reviewing run f9e60a7115d2)

A reviewed run (Encode, Shake, Entangle, Mark, Boost on one qubit, measure q0 → 894/106) showed that the
template pseudocode could state things the circuit did not do. Fixes, all computed from the circuit
(`backend/concepts/analysis.py`, exact statevector, ≤ 12 qubits, only up to the first measurement):

* Every step gets an **effect** sentence with real numbers (chance of 1 before → after, entanglement in bits,
  chance of the marked answer round by round for Boost). It is appended to the pseudocode sentence as "Result: …".
* When a template claim would be false the sentence is **replaced** (`claim_ok: false`): Boost that lowers the marked
  answer, Boost with no Mark, Boost on one qubit, Boost past its best round, Shake over encoded data, Entangle with
  nothing in superposition.
* Code comments name the action only (`# BOOST [q1]`), never what it supposedly does.
* New warnings: `W_SHAKE_AFTER_ENCODE`, `W_BOOST_SINGLE_QUBIT`, `W_UNMEASURED_EFFECT` (a step is flagged only if removing
  it, and removing all flagged steps together, leaves the measured distribution identical; skipped when a step
  can't be removed without breaking another).
* One naming convention: people see canvas labels (Q1, Q2) in every view and in code **comments**; code keeps
  0-based indices, and a legend line (`# Qubits: Q1 = qubit 0, …`) ties them together.
* A run's `canvas_json` now carries the concept steps (`concepts.nodes`), and **📂 Open run** in the Steps panel reopens
  a saved run file.
* Step ids are allocated only once a step is fully built (no gaps from rejected drafts). A step that another step
  refers to (Uncompute / Mark via) can't be removed or wrapped; the compiler also rejects an Uncompute that points
  into a wrapped step (`E_UNCOMPUTE_REF`).
* The reviewed run is kept as a regression fixture: `backend/tests/fixtures/runs/f9e60a7115d2.json`, `tests/test_faithfulness.py`.

Runs saved before this change have an empty `canvas_json` for concept circuits and can't be reopened.

## Logging, math layer and explanation layer (plan 9a, 9b, 9c)

| Plan | Delivered | Where |
|---|---|---|
| M0.3 logging | Run record **v2**: one per execution, append-only revisions, validated against a JSON Schema before saving. Identity, versions (git SHA, compiler, IR schema, math layer, qiskit, qiskit-aer), input (canvas with the concept steps, IR, validator errors/warnings), compile (gates, trace, canonical Qiskit, QASM 3, pseudocode, IonQ circuit), execution (**backend requested vs backend the provider executed**, job id, status, shots, **seed**, **transpiled circuit** with depth / 2-qubit count / basis gates, timings, **full raw provider response**), results (counts, math log, result check), explanation (template, LLM prompt + response + claim check + tokens + latency + cache + fallback), errors by stage, flags, **edit history**. | `backend/runlog/`, `backend/executor.py` |
| | Failed runs still produce a record (validate / compile / submit / fetch). A save that fails is returned as `save_error` and shown in red in the UI; nothing is dropped silently. Stack traces go to the server log only. | `executor.py`, `execute.js` |
| | `backend_mismatch` is flagged from the provider's own response (the QPU-requested-but-simulator-executed case), `backend_executed_unknown` when the provider names nothing. | `runlog/record.py` |
| | Secrets (env values, secret-looking keys, Bearer tokens, API-key shapes, emails, URL credentials) are redacted before anything is written, including the older per-circuit artifact files. Big blobs are gzip-compressed beside the record with a checksum pointer, never truncated. Structured JSON-lines server log (`logs/server.jsonl`) joins to a run by `run_id`. | `runlog/redact.py`, `serverlog.py`, `store.py` |
| | `GET /runs/{id}` and `POST /runs/{id}/replay` (recompile → identical code and prediction; canvas↔IR round trip; Aer counts reproduced from the stored seed). Research events (`POST /research/event`) are **off** unless `RESEARCH_LOGGING=on` and the event carries consent; stored apart, pseudonymous. **Check IRB requirements before any study use.** | `app.py`, `runlog/replay.py` |
| M0.5 math layer | `backend/mathlayer/` is the seed `math_layer.py` ported (the golden log for run f9e60a7115d2 is a test) and extended to every concept incl. Control, Compare, Mark via, Uncompute, Fourier, Add, Reset, Correct (exact measurement-branching for dynamic circuits). The emitted code is parsed with `ast` (never executed) and compared, step by step, with an **independent** reference semantics (it does not import the compiler). Runs after every execution; the step log is stored with the run; broken contracts and idle steps are shown in the UI. | `backend/mathlayer/` |
| M7 explanation layer | The verified explanation is rendered **from the step log** (`explain/template.py`; the live pseudocode now uses it too, replacing the earlier `analysis.py`). Optional AI text via any OpenAI-compatible provider (`LLM_*`), primary → fallback → template; deterministic **claim checker** (numbers + direction words per step, negation-aware); contradicting text is discarded and recorded; cache; daily budget. | `backend/explain/` |

New endpoints: `POST /explain`, `GET /runs/{id}`, `POST /runs/{id}/replay`, `POST /research/event`.
Setup of the key: `docs/LLM_SETUP.md` (+ `python backend/tools/check_llm.py`).

Bugs found by the new layers while building them (all fixed, all tested): the Mark-via reference was wrong (the step on its own is Compare†·Phase, only Compare + Mark is diagonal); the claim checker once accepted an invented "99%" because entropy bits were read as percentages; redaction regexes backtracked catastrophically on a 200 KB string.

## Not verified / known limits

* **IonQ API shape.** `docs.ionq.com` was not reachable from the build sandbox. The IonQ lowering reuses gate shapes already present in `ionq_runner.py` (`h x z cnot t ti mcx`) and adds `y s si rx ry rz` with a `"rotation"` key. **Please check `"rotation"` and the extra gate names against the current IonQ docs before submitting real jobs.** Everything is tested for *equivalence* (the lowered gate list, interpreted with Qiskit, equals the L2 circuit up to global phase), not against IonQ itself.
* Effect analysis is exact but limited: it stops at the first measurement or Reset, and is skipped above 12 qubits (the step then shows no computed claim, only the generic sentence).
* The LLM path is tested with mocked and stub providers. A live Cloudflare/Groq call has to be checked by you with `python backend/tools/check_llm.py` (the sandbox has no key and no route to those hosts).
* An async IonQ job's run record is attached in memory: if the backend restarts between submit and completion, the final revision is not written (the first revision, with the job id, is).
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
