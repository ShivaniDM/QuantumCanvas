# QuantumCanvas: Concept Vocabulary Expansion — Design Plan

**Owner:** Shivani Mayekar · **Date:** 2026-10-07 · **Target:** Claude Code
**Seed tests:** `validate_concepts.py` (Qiskit 2.5 / Aer 0.17 — every gate claim in this plan was checked there)

---

## 0. How to work on this (read first)

1. **Recon before code (Milestone 0).** Read the existing repo and report back before changing anything:
   - where the current 5 concepts (Shake, Entangle, Mark, Boost, Measure) are defined,
   - what the current IR / circuit JSON looks like,
   - where pseudocode, Qiskit generation, Aer execution and IonQ submission live,
   - the frontend palette / drag-drop component and how a concept's params are edited,
   - existing tests and how they run,
   - **what is logged today and where**: run storage, server logs, error handling. List every field section 9c requires that is currently missing.
   Then propose where the new modules go. **Match the existing structure; don't invent a parallel one.**
2. Work milestone by milestone (section 9). **All tests for a milestone pass before starting the next.**
3. Existing saved circuits and the current 5 concepts must keep working (write a migration, section 3.5).
4. **Out of scope:** the IonQ hardware-routing issue (`submit_hardware()` hardcoding `"simulator"`). Don't fix it here; if you touch that code path, flag it in the summary.
5. No AI/LLM in the compile path. Compilation stays deterministic: same Concept IR → same gates, every time.

---

## 1. Goal

Expand from 5 concepts to a vocabulary that can express real problem families (state prep, correlation, search, arithmetic, phase algorithms, dynamic circuits, communication) **without becoming a gate composer**. Users reason in concepts; gates are revealed through a "How is this implemented?" view, never hidden.

## 2. Architecture

```
Problem → Concept Canvas → Concept IR (L1) → validate → expand composites
        → Logical Gate IR (L2) → backend lowering (L3) → Aer | IonQ | (IBM later)
                     ↘ trace map (concept id → gate ranges) → "How is this implemented?" view

        L1 + emitted code + results ──► MATH LAYER (step log, section 9a) ──► explanation (section 9b)
                                                                                template first, LLM optional
```

**Order of authority:** deterministic compile → math layer → explanation. An explanation (template or LLM) may only state what the math layer's step log contains. Nothing downstream may contradict the math layer.

- **L1 Concept IR** stores *intent* (`compare`, `phase`, `uncompute`), never gates.
- **L2 Logical Gate IR** is backend-neutral gates (`x`, `h`, `p`, `ry`, `cx`, `mcx`, `swap`, `measure`, `reset`, `if`).
- **L3** is backend-specific: Qiskit circuit for Aer, IonQ-compatible circuit (with rewrites, section 6) for IonQ.
- **Trace map** is mandatory, not optional: every L2 gate records the L1 op id (and composite-parent id) that produced it. This powers the "How is this implemented?" view and the explanation-faithfulness research (each explanation must be traceable to exactly the gates it describes).

## 3. Concept IR (L1) schema

### 3.1 Document

```json
{
  "version": "0.3",
  "qubits": 4,
  "classical_bits": 3,
  "operations": [ /* Node[] in execution order */ ]
}
```

### 3.2 Node (every op uses this shape; unused fields omitted or empty)

```json
{
  "id": "op_17",
  "op": "rotate",
  "targets": [1],
  "controls": [],
  "ancillas": [],
  "classical": [],
  "params": { "axis": "y", "angle": { "pi": [2, 3] } },
  "condition": null,
  "body": null,
  "ref": null,
  "repeat": 1,
  "metadata": { "label": "Prepare biased state", "user_created": true }
}
```

### 3.3 Conventions — fixed now, enforced by the validator

These are the bugs the seed tests found. Do not leave them implicit.

| Topic | Rule | Why |
|---|---|---|
| **Bit order** | Register values are stored as **integers**. `targets[0]` is the **least-significant bit**. Display strings are MSB-left (matches Qiskit counts). Never store `"101"`-style strings as the source of truth. | `"110"` read left-to-right prepares `011` in Qiskit. `"101"` only worked because it's a palindrome. |
| **Angles** | `{ "pi": [num, den] }` for rational multiples of π, or `{ "rad": float }`. No string expressions, no `eval`. | Deterministic, safe, lets the compiler pick Z/S/T exactly. |
| **Phase lowering** | Phase **always** lowers to `P(θ)` (or Z/S/T when exact). **Never RZ.** | P and RZ differ by a global phase; under Control that becomes a relative phase. CP ≠ CRZ (tested). |
| **Ancillas** | Declared explicitly per node. Must be \|0⟩ when used (fresh or after Reset). | Compare/Mark/Add correctness depends on it. |
| **Classical bits** | Measure writes only to declared classical bits; `condition` reads only bits already written. | Correct / dynamic circuits. |

### 3.4 Validation errors (user-facing messages, not stack traces)

Each rule gets a code, a plain-language message for learners, and a unit test.

- `E_QUBIT_RANGE` target/control/ancilla out of range
- `E_OVERLAP` a qubit appears twice across targets/controls/ancillas of one node
- `E_SET_NOT_FRESH` Set used on a qubit that's not \|0⟩ (suggest Reset first, or Flip)
- `E_ANCILLA_DIRTY` ancilla not \|0⟩ when used
- `E_UNCOMPUTE_NONUNITARY` referenced block contains Measure / Reset / Correct
- `E_UNCOMPUTE_INTERFERENCE` an op between the ref and the Uncompute touches the ref's qubits and is not diagonal (see 4.3 Uncompute)
- `E_UNCOMPUTE_REF` ref missing, or ref appears after the Uncompute
- `E_ADD_OVERFLOW` Add without `modulus` and without a carry qubit
- `E_COND_UNWRITTEN` condition reads a classical bit not yet measured
- `E_ENCODE_SCALE` angle encoding without an allowed `scaling`
- `W_NOOP_ENTANGLE` (warning) Entangle on qubits with no prior superposition → produces nothing visible (CZ on \|00⟩ is a no-op — tested)
- `W_BACKEND_UNSUPPORTED` (warning at compile-for-backend time) op needs a feature the chosen backend lacks (section 6)

### 3.5 Migration

Write `migrate_v02_to_v03()` (or whatever the current version is) that maps existing saved circuits of the 5 concepts to the new schema. Golden test: every existing example/saved circuit in the repo compiles to an **operator-equivalent** circuit before and after migration.

---

## 4. Concept catalog

Concepts are split into **primitives** (lower directly to gates) and **composites** (expand into primitives first, then lower). Composites are built the same way a user-minted custom primitive would be. This keeps one mechanism for both, and supports the "expert mints shareable primitives" roadmap.

### 4.1 Primitives

| Concept | `op` | Params | Lowers to | Notes |
|---|---|---|---|---|
| Shake | `shake` | — | `H` per target | existing |
| Set | `set` | `value: int` | `X` on bits that are 1 (LSB = targets[0]) | absolute; requires fresh qubits |
| Flip | `flip` | — | `X` | relative; any state |
| Phase | `phase` | `angle` | π→`Z`, π/2→`S`, π/4→`T`, −π/2→`Sdg`, −π/4→`Tdg`, else `P(θ)` | never RZ |
| Rotate | `rotate` | `axis: x\|y\|z`, `angle` | `RX/RY/RZ(θ)` | see open decision D3 (probability input) |
| Swap | `swap` | exactly 2 targets | `SWAP` (show 3×CX in "how") | |
| Measure | `measure` | `classical` (same length as targets) | `measure` | existing |
| Reset | `reset` | — | `reset` per qubit | one qubit at a time |

### 4.2 Modifiers (wrap a `body` node)

| Concept | `op` | Semantics | Lowering |
|---|---|---|---|
| Control | `control` | run `body` only when all `controls` are 1 | Flip→`CX`/`MCX`; Phase→`CP`/`MCP` (π → `CZ`); Rotate→`CRX/CRY/CRZ`; Swap→`CSWAP`; composite body → control every gate of its expansion (optimize later) |
| Correct | `correct` | run `body` if `condition: {clbit, equals}` | Aer: `with qc.if_test((clbit, v))` (**not** `c_if` — removed in Qiskit 2.x). IonQ: deferred-measurement rewrite (section 6) |

Control's `body` may be any unitary node. Control around Measure/Reset/Correct is a validation error.

### 4.3 Composites

| Concept | `op` | Params | Expansion | Tested property |
|---|---|---|---|---|
| Entangle | `entangle` | 2 targets, `style: cx\|cz` (default cx) | `control(targets[0]) { flip targets[1] }` | Bell state after Shake |
| Encode | `encode` | `method: basis\|angle`, `data`, `scaling` | basis → `set(value)`; angle → `rotate y` per qubit with `scaling: "pi_x"` (RY(πx)) or `"arcsin_sqrt"` (RY(2·asin√x), so P(1)=x) | prob of 1 matches scaling rule |
| Compare | `compare` | `operator: eq\|neq` (lt/gt later), `value: int`, 1 ancilla | eq: X on targets whose bit of `value` is 0 → `MCX(targets → ancilla)` → undo X. neq: eq + X on ancilla | flag = 1 iff register == value, **all 2ⁿ inputs** |
| Mark | `mark` | either `value: int` (direct) or `via: compare_id` | direct: X-sandwich + `MCZ` (current behavior, keep). via: Compare → Phase(π) on ancilla → Uncompute | phase −1 on exactly the marked basis state, ancilla restored |
| Boost | `boost` | targets | `H, X, MCZ, X, H` (diffuser) | Grover on 3 qubits, 2 iterations, P(target) > 0.9 (got 0.944) |
| Fourier | `fourier` | `inverse: bool`, `swaps: bool` (default true) | standard QFT: for j high→low: H(j), CP(π/2^(j−k)) for k<j; then swaps. Inverse = dagger. | equals `QFTGate(n)` up to global phase; forward∘inverse = I |
| Add | `add` | `value: int`, `modulus: 2^n` required (v1 supports only 2ⁿ) | Draper constant adder: Fourier → `P(2π·value·2^k / 2^n)` on each qubit → inverse Fourier | (v + c) mod 2ⁿ for **all** inputs |
| Uncompute | `uncompute` | `ref: op id` | dagger of the ref's full expansion, reverse order | see rules below |

**Uncompute rules (validator):**
- ref must exist, come earlier, and be unitary (no Measure/Reset/Correct anywhere in its expansion).
- Any op between ref and Uncompute that touches the ref's qubits must be **diagonal in the computational basis** (Phase, Control-Phase, Mark) — otherwise `E_UNCOMPUTE_INTERFERENCE`. This is exactly what makes compute → phase → uncompute restore the ancilla.

**Note on Add:** Cuccaro adds two *quantum* registers. Adding a classical constant is a different circuit; use Draper (Fourier-basis) for v1. It reuses Fourier and needs only single-qubit P in the middle. Quantum + quantum addition is a later concept (`add_register`).

---

## 5. Compiler passes

Each pass is pure and separately tested.

1. **parse** JSON → typed nodes (dataclasses / TS types, match repo language)
2. **validate** (section 3.4) → list of errors/warnings, abort on errors
3. **expand** composites recursively → primitives + modifiers only, keeping a parent chain for the trace
4. **lower** → L2 gate list + trace map `{gate_index: [op_id, parent_id, ...]}`
5. **emit** Qiskit circuit / OpenQASM 3 / pseudocode from L2 (one emitter each)
6. **backend lower** (section 6)

The "How is this implemented?" view shows one concept node as: concept → pseudocode → L2 gates → Qiskit code → transpiled hardware circuit, using the trace map to highlight that node's gates.

## 6. Backend constraints

From [IonQ OpenQASM 3 docs](https://docs.ionq.com/api-reference/v0.4/openqasm3) (re-check at implementation time):

| Feature | Aer | IonQ |
|---|---|---|
| Classical feed-forward (`if`) | yes (`if_test`) | **not supported on any target, incl. simulator** |
| Mid-circuit measurement | yes | target-dependent |
| Reset | yes | per qubit |
| MCX / MCZ | yes | not native → transpile to cx/cz + 1q gates |

**IonQ rewrite for Correct (deferred measurement):**
`measure q_a → c; correct(c==1){ U on q_t }` becomes `control(q_a){ U on q_t }`, and `measure q_a → c` moves to the end.
Valid only if q_a is not used again between its measurement and the end of the circuit. Otherwise emit `W_BACKEND_UNSUPPORTED` and refuse the IonQ submit, with a plain explanation.
**Test:** teleportation compiled for IonQ (rewritten) and for Aer (if_test) give the same output distribution for a random input state.

If mid-circuit Measure/Reset hits an IonQ target that rejects it, surface IonQ's error as a learner-readable message rather than a stack trace.

## 7. Tests

Port `validate_concepts.py` into the repo's test framework (pytest if Python) as the seed suite. Note: when reading a single outcome from `probabilities_dict()`, take the max-probability key — the dict includes ~1e-37 numerical dust entries.

Required for every concept:
- **Unit:** lowered L2 for a fixed example matches an expected gate list.
- **Semantic:** operator equivalence (`Operator.equiv` for up-to-global-phase, exact `allclose` where phase matters, e.g., Phase) against a reference, **or** exhaustive basis-input check for classical-function concepts (Set, Flip, Compare, Add — all 2ⁿ inputs for n ≤ 4).
- **Under Control:** each unitary concept wrapped in Control equals `ref.control(1)` from Qiskit. This catches the P vs RZ class of bug.
- **Validator:** one passing and one failing case per error code.
- **Trace:** every L2 gate has a trace entry; the union of a node's gates is exactly what the "how" view highlights.
- **Determinism:** compiling the same IR twice gives byte-identical output.
- **Migration golden test** (section 3.5).

Regression tests from the fact-check (must exist by name):
- `test_rotate_75_percent_needs_2pi_over_3` (RY(π/3) → 0.25, RY(2π/3) → 0.75)
- `test_controlled_phase_is_cp_not_crz`
- `test_set_bit_order_non_palindrome` (value 6 → Qiskit label `110`)
- `test_uncompute_rejects_measure`
- `test_add_requires_modulus`
- `test_correct_uses_if_test_not_c_if`
- `test_teleport_ionq_rewrite_matches_aer`

## 8. Problem bank

Store problems as data so the UI can serve them and an auto-checker can grade them:

```json
{
  "id": "p_bias_075",
  "family": "state_preparation",
  "statement": "Prepare a qubit that has a 75% probability of being measured as 1.",
  "qubits": 1,
  "allowed_concepts": ["shake", "rotate", "flip", "phase", "measure"],
  "check": { "type": "distribution", "target": { "1": 0.75, "0": 0.25 }, "tolerance": 0.02 },
  "reference_solution": { /* Concept IR */ },
  "hint_ladder": ["Which concept changes probability by an amount you choose?", "P(1) = sin²(θ/2)"]
}
```

Check types: `distribution` (Aer, fixed seed), `statevector` (up to global phase), `unitary` (`Operator.equiv`), `classical_function` (all basis inputs).

Seed problems (each needs a reference solution that passes its own check in CI):

| # | Family | Statement | Reference concepts |
|---|---|---|---|
| 1 | State prep | Represent decimal 5 on 3 qubits | Set |
| 2 | State prep | 75% probability of 1 | Rotate Y 2π/3 |
| 3 | Correlation | Two qubits that always measure the same | Shake, Entangle |
| 4 | Correlation | Two qubits that always measure opposite | Shake, Entangle, Flip |
| 5 | Manipulation | Flip q1 only when q0 is 1 | Control{Flip} |
| 6 | Manipulation | Move q0's state to q2, rest unchanged | Swap |
| 7 | Phase | Change the state without changing probabilities (then reveal it with Shake) | Shake, Phase, Shake |
| 8 | Search | Flag whether a 3-qubit register holds 5 | Compare |
| 9 | Search | Make 5 the most likely outcome from a uniform start | Shake, Compare, Mark/Phase, Uncompute, Boost ×2 |
| 10 | Arithmetic | Add 3 (mod 8) without measuring | Add |
| 11 | Phase algorithms | Transform into phase representation and back | Fourier, Fourier(inverse) |
| 12 | Communication | Teleport an unknown qubit state using a Bell pair | Shake, Entangle ×2, Shake, Measure ×2, Correct ×2 |
| 13 | Dynamic | Reuse a qubit after measuring it | Measure, Reset |
| 14 | Data encoding | Encode [0.2, 0.8] as probabilities of 1 | Encode(angle, arcsin_sqrt) |

## 9a. Math layer (verification between compile and explanation)

**Seed implementation:** `math_layer.py` + `test_math_layer.py`, already working on run `f9e60a7115d2`. Port it into the repo; don't rewrite from scratch.

**Why:** run `f9e60a7115d2` executed correctly, but its pseudocode made two false claims: that Shake gives 50/50, and that Boost makes the marked answer more likely. Nothing checked them. The math layer is that check.

It runs after every execution and produces a **step log** (JSON, stored with the run):

| Check | What it computes | Catches |
|---|---|---|
| Code ↔ IR | Parses the emitted Qiskit **without `exec`** (`ast.literal_eval` per `qc.gate(...)` line). Splits it into blocks by the `# CONCEPT` comments and checks that each block's operator equals an **independent** reference lowering of its IR node. | compiler/emitter bugs, trace misalignment |
| Step facts | Per node: per-qubit P(1) before/after, single-qubit entanglement entropy | the raw material for every explanation |
| Counterfactual | Re-simulates with each node removed and reports the TVD shift of the measured distribution → `affects_result` | "4 of 6 steps did nothing to what you measured" |
| Contracts | Each concept's explanation claim, tested numerically (table below) | unfaithful pseudocode/LLM text |
| Result check | Exact predicted distribution vs observed counts. Chi-square, with p < 1e-3 → flag; any observed outcome with predicted probability 0 → flag | backend/result-path bugs (e.g. stub data, simulator-instead-of-QPU routing), plus hardware-noise reporting on real QPUs |

**Concept contracts** (each claim the UI makes must be listed here, with its precondition):

| Concept | Claim | Holds only if |
|---|---|---|
| Encode(angle) | P(1) = data | target fresh |
| Shake | target becomes 50/50 | target was a definite 0/1 |
| Entangle | entanglement increases | control in superposition |
| Mark, Phase | probabilities unchanged | always (if not, it's a compiler bug) |
| Boost | P(marked) increases | ≥2 qubits, and iteration count not past optimum |
| Compare | flag = (register == value) | ancilla fresh |
| Uncompute | ref's ancillas back to \|0⟩ | section 4.3 rules |
| Fourier/Add | matches QFTGate / (v+c) mod 2ⁿ | — |

When a contract is broken, the explanation must say so and give the precondition ("Shake only gives 50/50 from a definite 0 or 1; this qubit was already tilted by Encode"). A broken contract is a teaching moment, not an error.

**Limits:** statevector facts up to 20 qubits (configurable). Above that, the log records `skipped: too large` plus the facts that don't need a statevector (code↔IR on small blocks, light cones, warnings). Never fake numbers.

**Tests (required):**
- Bell pair: all contracts hold.
- 2-qubit Grover: Boost contract holds.
- Run `f9e60a7115d2` golden log: Shake and Boost contracts broken; N1, N4, N5 and N6 have no effect on the result; p ≈ 0.53.
- Impossible-outcome counts → flagged; 80/20 on a Bell pair → flagged.
- Set 6 → `110`.

## 9b. Explanation layer

1. **Template explanation (deterministic, always shown first).** It is rendered *from the step log*, not from the IR alone. Every sentence is backed by a log field (e.g. "Removing this step wouldn't change your result" ⇐ `affects_result: false`).
2. **LLM explanation (optional, clearly labelled "AI explanation, grounded in simulation").**
   - Input: the step log, IR, pseudocode, and counts. **Not** raw amplitudes for large circuits.
   - System rule: cite only step-log facts; every numeric claim must reference a step id.
   - **Claim checker** (deterministic): extract numbers and direction words ("more likely", "50/50", "no effect") per step, and compare them to the log. On any mismatch, discard the LLM text, show the template, and log the failure (this is research data).
   - Cache by `sha256(ir_json + results)`.
3. **Providers.** Use an OpenAI-compatible client, so providers are config, not code. Fallback chain: primary → secondary → template-only. Hitting a quota must never break the page.

| Provider | Card needed | Free allowance (verify at build time) | Role |
|---|---|---|---|
| Cloudflare Workers AI | No (only to go past the daily allowance) | 10k Neurons/day, resets 00:00 UTC; ≈120 explanations/day on Llama 3.1 8B, ~3–4× more on the fp8-fast variant | primary candidate |
| Groq | No | per-model daily caps (e.g. gpt-oss-120b ≈1k req, 200k tokens/day) | primary candidate: bigger models |
| Google AI Studio (Gemini) | No | daily request caps per model; free-tier prompts may be used by Google to improve products | only if consented / non-sensitive |
| OpenRouter free models | No | ~50 req/day; free model list rotates | last-resort fallback |

The API key lives server-side only (env var). Never put it in the frontend bundle.

**Env vars (provider-neutral; switching provider = changing values, not code):**
```
LLM_BASE_URL   # e.g. https://api.cloudflare.com/client/v4/accounts/<id>/ai/v1  or  https://api.groq.com/openai/v1
LLM_API_KEY    # secret
LLM_MODEL      # e.g. @cf/meta/llama-3.1-8b-instruct
# optional fallback, same shape:
LLM_FALLBACK_BASE_URL, LLM_FALLBACK_API_KEY, LLM_FALLBACK_MODEL
```
If `LLM_BASE_URL` or `LLM_API_KEY` is unset, the explanation layer runs template-only. It must not crash.

## 9c. Logging

**Evidence that logging is incomplete today** (run `f9e60a7115d2`):
- `canvas_json` has empty `ops` even though the IR has 7 operations, so the run can't be reopened.
- `raw` is `null`, so there's no provider response.
- There is no transpiled circuit, seed, versions, timing, job id, or record of which backend actually executed.
- Deleted node N7 left no trace.

Principle: **a run record must be enough to reproduce and audit the run without the live app.**

### Run record v2 (one per execution, append-only, validated against a JSON Schema before save)

| Group | Fields |
|---|---|
| Identity | `run_id`, `session_id`, `user` (or `anonymous`), `created_at`, `finished_at`, `parent_run_id` (if re-run/edited) |
| Versions | app git SHA, compiler version, IR schema version, `math_layer` version, qiskit / qiskit-aer / provider SDK versions |
| Input | `canvas_json` (**must round-trip to the same IR — test it**), `ir_json`, validator errors + warnings |
| Compile | L2 gate IR, trace map, pseudocode, `qiskit_py`, OpenQASM 3, IR hash |
| Execution | `backend_requested` **and** `backend_executed` (from the provider's response, not our request — mismatch = flag; this catches the QPU→simulator routing bug), provider job id, provider status, transpiled circuit + basis gates + depth + 2-qubit count, shots, seed, queue / execution time, cost estimate vs billed, **full raw provider response** |
| Results | counts, math-layer step log, result-check outcome |
| Explanation | template text; if an LLM was used: provider, model, prompt hash, full prompt + response, claim-check pass/fail + which claims failed, tokens, latency, cache hit, fallback taken |
| Errors | stage (`validate`/`compile`/`submit`/`fetch`/`math`/`explain`/`save`), error code, message. Stack traces go to server logs only, never to the client |

### Other logs
- **Server logs:** structured JSON lines (`ts`, `level`, `run_id`, `stage`, `event`, `duration_ms`), so every log line joins to a run.
- **Canvas edit history:** node added/removed/edited with timestamps, so gaps like N7 are explained. Store it with the run as a compact diff list.
- **Research interaction events** (Paper A: "How is this implemented?" opened, explanation viewed, time per step, re-runs after a broken contract). **Off by default.** Collect only with explicit consent and a study id, pseudonymous, stored separately from run records. Confirm IRB requirements before any study use.

### Rules
- A save that fails schema validation is an **error surfaced to the user**, never silently dropped.
- Never log API keys, auth tokens, or emails; redact them before write (add a test with a fake key).
- Size: raw provider responses and statevectors can be large. Store them compressed or in object storage, with a pointer from the record. Don't truncate silently.

### Tests
- **Replay:** load a stored run record → recompile → identical `qiskit_py`, and math layer predicted distribution identical.
- **Round-trip:** `canvas_json → IR` equals the stored `ir_json` (would have failed on `f9e60a7115d2`).
- A backend mismatch (requested QPU, executed simulator) is flagged in the record.
- An injected compile error produces a record with `stage: compile`, not a missing run.
- The redaction test passes.

## 9. Milestones

| M | Scope | Done when |
|---|---|---|
| **M0** | Recon report (section 0.1). No code changes. | Report delivered with proposed file layout |
| **M0.3** | Logging (9c): run record v2 schema + validation, canvas↔IR round-trip fix, `backend_executed` + raw response capture, structured server logs, edit history, redaction | Replay, round-trip, backend-mismatch, compile-error and redaction tests pass |
| **M0.5** | Port `math_layer.py` + `test_math_layer.py`. Run it on every Aer run, store the step log with the run, and show broken contracts / no-effect steps in the UI. Also fix the empty `canvas_json` bug and the Q1/Q2 vs q0/q1 label mismatch seen in run `f9e60a7115d2`. | Golden log for `f9e60a7115d2` matches; all math-layer tests pass |
| **M1** | Schema v0.3, conventions, validator, primitives (Set, Shake, Flip, Phase, Rotate, Swap, Measure, Reset), Control modifier, trace map, migration of existing 5 | Seed tests + migration golden test pass; existing circuits unchanged |
| **M2** | Composites: Entangle, Encode, Compare (eq/neq), Mark (both modes), Boost, Uncompute | Problems 1–9, 14 pass checks |
| **M3** | Fourier, Add (Draper, mod 2ⁿ) | Problems 10–11 pass; exhaustive Add test |
| **M4** | Correct (Aer `if_test`), IonQ deferred-measurement rewrite, backend warnings | Problems 12–13 pass; teleport Aer ≡ IonQ-rewrite |
| **M5** | UI: palette grouped by family, param forms (angle as π-fractions, integer values with live binary preview showing LSB→q0), validator messages inline, "How is this implemented?" panel driven by the trace | Manual walkthrough of problems 1–14 in the UI |
| **M6** | Problem bank UI + auto-checker | A learner can pick a problem, build, run, get pass/fail + hint ladder |
| **M7** | Explanation layer (9b): template rendered from step log, provider-agnostic LLM client with fallback chain, claim checker, cache, UI label | LLM text that contradicts the log is never shown (test with a deliberately wrong mocked response); quota exhaustion falls back to template |

Note: the math layer comes **before** the new concepts (M0.5). Every new concept in M1–M4 must ship with its contract row and contract test.

Each milestone ends with a short summary: what changed, test results, anything deviating from this plan and why.

## 10. Open decisions (ask Shivani; don't decide silently)

- **D1 — Set vs Encode(basis):** they compile identically. Keep both (Set = "I know the value", Encode = "I'm loading data") or fold Set into Encode? *Default if unanswered: keep both; Encode(basis) expands to Set.*
- **D2 — Correct naming:** "Correct" (teleportation framing) vs "If" (general dynamic-circuit framing). *Default: Correct.*
- **D3 — Rotate input:** angle only, or also "target probability" (compiles to RY(2·asin√p))? A probability input makes problem 2 trivial; consider unlocking it only after the learner solves it. *Default: angle only.*
- **D4 — Entangle as a named concept** even though it's Control{Flip}. *Default: keep it; it's the pedagogical entry point.*
- **D5 — Compare lt/gt** in v1 or later. *Default: later.*
