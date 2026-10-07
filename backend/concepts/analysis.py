"""Faithful explanations: facts computed from the circuit instead of template sentences.

For every step we simulate the circuit up to that step (exact statevector, small circuits only) and
report what actually happened to the qubits, so the explanation can never claim something the
circuit did not do. Also finds steps that cannot change anything that is measured.

Everything here is optional: without Qiskit, or for big / non-unitary circuits, analysis is skipped
and the plain template text stays (with no extra claims).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .lower import Lowered
from .schema import Document, Node, walk

try:
    from qiskit.quantum_info import Statevector, entropy, partial_trace
    from .emit_qiskit import build_circuit
except ImportError:                      # pragma: no cover
    Statevector = None

MAX_QUBITS = 12
MAX_STEPS_FOR_REMOVAL_TEST = 24
EPS = 5e-3                               # 0.5 percentage points


@dataclass
class StepFacts:
    effect: str = ""                     # one plain sentence about what really happened
    plain: str | None = None             # replacement for the template sentence when it would be false
    contradicted: bool = False


@dataclass
class Analysis:
    facts: dict = field(default_factory=dict)       # op id -> StepFacts
    ineffective: list = field(default_factory=list)  # op ids that cannot change the measured results


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def _prefix(low: Lowered, end: int) -> Lowered:
    return Lowered(low.gates[:end], low.trace[:end], low.qubits, low.clbits, {})


def _is_unitary_prefix(low: Lowered, end: int) -> bool:
    return all(g.name not in ("measure", "reset") and g.cond is None for g in low.gates[:end])


def _state(low: Lowered, end: int):
    return Statevector(build_circuit(_prefix(low, end)))


def _p1(sv, q: int) -> float:
    return float(sv.probabilities([q])[1])


def _reg_prob(sv, qubits: list, value: int) -> float:
    return float(sv.probabilities(list(qubits))[value])


def _entangle_bits(sv, n: int, q: int) -> float:
    others = [i for i in range(n) if i != q]
    if not others:
        return 0.0
    return float(entropy(partial_trace(sv, others), base=2))


def _changes(before, after, targets, labels) -> str:
    bits = []
    for t in targets:
        a, b = _p1(before, t), _p1(after, t)
        if abs(a - b) > EPS:
            bits.append(f"{labels(t)}: chance of 1 {_pct(a)} → {_pct(b)}")
    return "; ".join(bits)


def _marked_register(doc_ops: list[Node], k: int, by_id: dict) -> tuple[list, int, str] | None:
    """The register + value of the most recent Mark before step k (direct, or via a Compare)."""
    for n in reversed(doc_ops[:k]):
        if n.op != "mark":
            continue
        if n.params.get("via") and n.params["via"] in by_id:
            c = by_id[n.params["via"]]
            val = c.params["value"]
            if c.params.get("operator", "eq") == "neq":
                return None
            return list(c.targets), val, "compare"
        if "value" in n.params:
            return list(n.targets), n.params["value"], "value"
    return None


def analyse(doc: Document, low: Lowered, label=lambda q: f"q{q}") -> Analysis:
    out = Analysis()
    if Statevector is None or low.qubits > MAX_QUBITS or low.qubits == 0:
        return out
    ops = doc.operations
    by_id = {n.id: n for n in walk(ops)}
    prev_end = 0
    prev_sv = Statevector.from_label("0" * low.qubits)
    for k, node in enumerate(ops):
        idx = low.node_ranges.get(node.id, [])
        end = (max(idx) + 1) if idx else prev_end
        if not _is_unitary_prefix(low, end):
            break                                    # everything after a measurement / reset: no claims
        sv = _state(low, end) if end != prev_end else prev_sv
        f = StepFacts()
        T = list(node.targets) + [c for c in node.controls]
        if node.op == "boost":
            f = _boost_facts(node, ops, k, by_id, prev_sv, sv, label, low, idx, prev_end)
        elif node.op == "shake":
            f = _shake_facts(node, prev_sv, sv, label)
        elif node.op == "entangle" and len(node.targets) == 2:
            f = _entangle_facts(node, prev_sv, sv, low.qubits, label)
        elif node.op == "mark":
            f.effect = ("The probabilities did not change (Mark only changes a hidden sign)."
                        if all(abs(a - b) < 1e-9 for a, b in zip(prev_sv.probabilities(), sv.probabilities()))
                        else "Heads-up: this step changed the probabilities, which Mark normally does not.")
        else:
            qs = sorted(set(T) | set(node.ancillas))
            ch = _changes(prev_sv, sv, qs, label)
            f.effect = ch if ch else ("No qubit's chance of 1 changed." if qs else "")
        if f.effect or f.plain:
            out.facts[node.id] = f
        prev_end, prev_sv = end, sv
    out.ineffective = _ineffective_steps(doc)
    return out


# ── per-concept facts ───────────────────────────────────────────────────
def _shake_facts(node, before, after, label) -> StepFacts:
    f = StepFacts()
    spoiled = [t for t in node.targets if _p1(before, t) > EPS]
    after_ps = [round(_p1(after, t), 3) for t in node.targets]
    if spoiled:
        names = ", ".join(label(t) for t in spoiled)
        chg = _changes(before, after, node.targets, label)
        f.contradicted = True
        f.plain = (f"Shake mixes each qubit with a half-turn, which only gives an even 50/50 split for a qubit "
                   f"that starts at 0. {names} did not start at 0, so its earlier data is overwritten.")
        f.effect = chg
    else:
        f.effect = "; ".join(f"{label(t)}: 50% / 50%" for t in node.targets) if all(abs(p - .5) < 1e-3 for p in after_ps) \
            else _changes(before, after, node.targets, label)
    return f


def _entangle_facts(node, before, after, n, label) -> StepFacts:
    f = StepFacts()
    c, t = node.targets
    s0, s1 = _entangle_bits(before, n, c), _entangle_bits(after, n, c)
    if s1 - s0 < 0.01:
        f.contradicted = True
        f.plain = (f"Entangle did not link {label(c)} and {label(t)} here: {label(c)} is not in superposition, "
                   f"so this only copies its plain 0 or 1.")
        f.effect = f"Entanglement of {label(c)} with the rest: {s1:.2f} bits (was {s0:.2f})."
    else:
        f.effect = f"Entanglement of {label(c)} with the rest: {s0:.2f} → {s1:.2f} bits. " + _changes(before, after, [t], label)
    f.effect = f.effect.strip()
    return f


def _boost_facts(node, ops, k, by_id, before, after, label, low, idx, start) -> StepFacts:
    f = StepFacts()
    found = _marked_register(ops, k, by_id)
    T = list(node.targets)
    single = len(T) == 1
    single_note = (" On a single qubit there are only two possible answers, so Mark followed by Boost just flips "
                   "the qubit; Boost needs at least 2 qubits to amplify.")
    if found is None:
        f.effect = "Nothing was marked before this Boost, so there is no answer for it to amplify."
        f.plain = "Boost can only make a marked answer more likely, and no Mark or Compare came before it." + (single_note if single else "")
        f.contradicted = True
        return f
    reg, value, _ = found
    rounds = max(1, node.repeat)
    per = len(idx) // rounds if idx else 0
    traj = [_reg_prob(before, reg, value)]
    for r in range(1, rounds + 1):
        traj.append(_reg_prob(_state(low, start + r * per), reg, value) if rounds > 1 and r < rounds else _reg_prob(after, reg, value))
    p0, p1 = traj[0], traj[-1]
    names = ", ".join(label(q) for q in reg)
    ans = format(value, f"0{len(reg)}b")
    f.effect = f"Chance that [{names}] = {ans}: " + " → ".join(_pct(x) for x in traj) + (" (after each round)." if rounds > 1 else ".")
    peak = max(traj)
    if single:
        verb = ("LOWERED" if p1 - p0 < -EPS else "raised" if p1 - p0 > EPS else "did not change")
        f.contradicted = True
        f.plain = (f"Boost {verb} the chance of the marked answer"
                   + (f" from {_pct(p0)} to {_pct(p1)}." if verb != "did not change" else f" (still {_pct(p1)}).") + single_note)
        return f
    if rounds > 1 and peak - p1 > EPS:
        best = traj.index(peak)
        f.contradicted = True
        f.plain = (f"Boost went past the best point: the marked answer peaks at {_pct(peak)} after {best} "
                   f"round{'s' if best != 1 else ''} and then falls back to {_pct(p1)}. "
                   f"Use about √(number of answers) rounds, not more.")
    elif p1 - p0 > EPS:
        f.plain = f"Boost raised the chance of the marked answer from {_pct(p0)} to {_pct(p1)}."
    elif p1 - p0 < -EPS:
        f.contradicted = True
        f.plain = (f"Boost LOWERED the chance of the marked answer from {_pct(p0)} to {_pct(p1)}. "
                   f"Boost only helps with 2 or more qubits and about √(number of answers) rounds.")
    else:
        f.contradicted = True
        f.plain = f"Boost did not change the chance of the marked answer (still {_pct(p1)})."
    return f


# ── steps that cannot change what is measured ───────────────────────────
def _distribution_for(doc: Document):
    """Exact distribution over the measured qubits, or None if it cannot be computed."""
    from .lower import lower_document
    low = lower_document(doc)
    if any(g.name == "reset" or g.cond is not None for g in low.gates):
        return None
    seen_measure = False
    for g in low.gates:
        if g.name == "measure":
            seen_measure = True
        elif seen_measure:
            return None                              # a gate after a measurement: not a simple terminal measure
    meas = [g for g in low.gates if g.name == "measure"]
    if not meas:
        return None
    body = Lowered([g for g in low.gates if g.name != "measure"], [], low.qubits, low.clbits, {})
    sv = Statevector(build_circuit(Lowered(body.gates, low.trace[:len(body.gates)], low.qubits, 0, {})))
    qs = [g.targets[0] for g in meas]
    probs = sv.probabilities(qs)
    return [round(float(p), 9) for p in probs], tuple(qs)


def _without(doc: Document, remove_ids: set) -> Document:
    from copy import deepcopy
    d = deepcopy(doc)
    d.operations = [n for n in d.operations if n.id not in remove_ids]
    return d


def _ineffective_steps(doc: Document) -> list:
    from .validate import validate
    ops = [n for n in doc.operations if n.op != "measure"]
    if len(doc.operations) - len(ops) == 0 or len(ops) > MAX_STEPS_FOR_REMOVAL_TEST:
        return []
    try:
        base = _distribution_for(doc)
    except Exception:
        return []
    if base is None:
        return []
    cand = []
    for n in ops:
        try:
            d2 = _without(doc, {n.id})
            if not validate(d2).ok:
                continue                              # something depends on this step: it matters
            dist = _distribution_for(d2)
        except Exception:
            continue
        if dist is not None and dist[1] == base[1] and all(abs(a - b) < 1e-7 for a, b in zip(dist[0], base[0])):
            cand.append(n.id)
    if not cand:
        return []
    # each one alone is harmless; make sure they are harmless together too
    try:
        d_all = _without(doc, set(cand))
        if validate(d_all).ok:
            dist = _distribution_for(d_all)
            if dist is not None and all(abs(a - b) < 1e-7 for a, b in zip(dist[0], base[0])):
                return cand
    except Exception:
        pass
    return []
