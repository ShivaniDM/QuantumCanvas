"""Concept IR validator. Plain-language messages for learners, never stack traces."""
from __future__ import annotations

from dataclasses import dataclass

from .angles import AngleError, validate_angle
from .schema import ALL_OPS, Document, Node, NON_UNITARY_OPS, walk

ENCODE_SCALINGS = ("pi_x", "arcsin_sqrt")
MAX_REPEAT = 256


@dataclass
class Issue:
    code: str
    severity: str          # "error" | "warning"
    message: str
    op_id: str | None = None
    hint: str | None = None

    def to_dict(self):
        return {"code": self.code, "severity": self.severity, "message": self.message,
                "op_id": self.op_id, "hint": self.hint}


@dataclass
class Report:
    errors: list
    warnings: list

    @property
    def ok(self):
        return not self.errors

    def to_dict(self):
        return {"ok": self.ok, "errors": [e.to_dict() for e in self.errors],
                "warnings": [w.to_dict() for w in self.warnings]}


def qubits_of(n: Node) -> list[int]:
    out = list(n.targets) + list(n.controls) + list(n.ancillas)
    if n.body is not None:
        out += qubits_of(n.body)
    return out


def contains_nonunitary(n: Node, by_id: dict, _seen=None) -> bool:
    _seen = _seen or set()
    if n.id in _seen:
        return False
    _seen.add(n.id)
    if n.op in NON_UNITARY_OPS:
        return True
    if n.body is not None and contains_nonunitary(n.body, by_id, _seen):
        return True
    if n.op in ("uncompute", "mark") and n.ref and n.ref in by_id:
        return contains_nonunitary(by_id[n.ref], by_id, _seen)
    return False


def is_diagonal(n: Node) -> bool:
    """Diagonal in the computational basis (cannot disturb a computed value)."""
    if n.op in ("phase", "mark"):
        return True
    if n.op == "rotate" and n.params.get("axis") == "z":
        return True
    if n.op == "entangle" and n.params.get("style") == "cz":
        return True
    if n.op == "control" and n.body is not None:
        return is_diagonal(n.body)
    return False


def _fmt_q(qs):
    return ", ".join(f"q{q}" for q in sorted(set(qs)))


def validate(doc: Document) -> Report:
    errs: list[Issue] = []
    warns: list[Issue] = []
    E = lambda code, msg, op=None, hint=None: errs.append(Issue(code, "error", msg, op, hint))
    W = lambda code, msg, op=None, hint=None: warns.append(Issue(code, "warning", msg, op, hint))

    nq, nc = doc.qubits, doc.classical_bits
    by_id: dict[str, Node] = {}
    top_index: dict[str, int] = {}

    # ids: unique across the whole document, nested bodies included
    for n in walk(doc.operations):
        if n.id in by_id:
            E("E_DUP_ID", f"Two steps share the id '{n.id}'. Every step needs its own id.", n.id)
        by_id[n.id] = n
    for i, n in enumerate(doc.operations):
        top_index[n.id] = i

    nonzero: set[int] = set()        # qubits that may hold something other than |0>
    superposed: set[int] = set()     # qubits that may be in superposition
    written: set[int] = set()        # classical bits already measured into
    effects_of: dict[str, set] = {}  # op id -> qubits it made non-zero (for Uncompute)
    before_of: dict[str, set] = {}

    def check_range(n: Node, label: str, vals, limit):
        bad = [v for v in vals if v < 0 or v >= limit]
        if bad:
            what = "qubit" if label != "classical" else "classical bit"
            E("E_QUBIT_RANGE" if label != "classical" else "E_CLBIT_RANGE",
              f"Step '{n.id}' uses {what} {bad[0]}, but the circuit only has {limit} "
              f"({what}s 0 to {limit - 1}).", n.id,
              f"Add more {what}s to the circuit or pick one that exists.")

    def need(n: Node, cond: bool, msg: str, hint: str | None = None):
        if not cond:
            E("E_PARAM", msg, n.id, hint)
        return cond

    def int_ok(v):
        return isinstance(v, int) and not isinstance(v, bool)

    def check_angle(n: Node, key="angle"):
        a = n.params.get(key)
        try:
            validate_angle(a)
            return True
        except AngleError as e:
            E("E_PARAM", f"Step '{n.id}': {e}.", n.id, 'Use {"pi": [1, 2]} for pi/2 or {"rad": 0.5}.')
            return False

    def body_effects_sim(n: Node):
        """Update nonzero/superposed after n, and return qubits newly made non-zero."""
        pre = set(nonzero)
        op = n.op
        T, A = n.targets, n.ancillas
        if op == "shake":
            nonzero.update(T); superposed.update(T)
        elif op == "flip":
            nonzero.update(T)
        elif op == "set":
            v = n.params.get("value", 0)
            if int_ok(v):
                nonzero.update(t for i, t in enumerate(T) if (v >> i) & 1)
        elif op == "rotate":
            if n.params.get("axis") in ("x", "y"):
                nonzero.update(T); superposed.update(T)
        elif op == "swap" and len(T) == 2:
            a, b = T
            if a in nonzero or b in nonzero:
                nonzero.update((a, b))
            if a in superposed or b in superposed:
                superposed.update((a, b))
        elif op == "entangle" and len(T) == 2:
            if T[0] in nonzero and n.params.get("style", "cx") == "cx":
                nonzero.add(T[1])
            if T[0] in superposed:
                superposed.add(T[1])
        elif op == "encode":
            if n.params.get("method") == "angle":
                nonzero.update(T); superposed.update(T)
            else:
                v = n.params.get("data", 0)
                if int_ok(v):
                    nonzero.update(t for i, t in enumerate(T) if (v >> i) & 1)
        elif op == "compare":
            nonzero.update(A)
        elif op in ("boost", "fourier", "add"):
            nonzero.update(T); superposed.update(T)
        elif op == "measure":
            nonzero.update(T)
        elif op == "reset":
            nonzero.difference_update(T); superposed.difference_update(T)
        elif op == "control" and n.body is not None:
            if any(c in nonzero for c in n.controls):
                tmp = Node(id=n.body.id, op=n.body.op, targets=n.body.targets, ancillas=n.body.ancillas,
                           params=n.body.params, body=n.body.body)
                body_effects_sim(tmp)
        elif op == "correct" and n.body is not None:
            body_effects_sim(n.body)
        elif op == "mark" and n.params.get("via") in effects_of:
            # Mark(via) = Phase on the flag, then Uncompute the Compare: the ancilla is clean again
            via = n.params["via"]
            nonzero.difference_update(effects_of[via] - before_of.get(via, set()))
        elif op == "uncompute" and n.ref in effects_of:
            added = effects_of[n.ref] - before_of.get(n.ref, set())
            nonzero.difference_update(added)
        return nonzero - pre

    def check_node(n: Node, nested: bool, idx: int | None):
        # ── structure ──────────────────────────────────────────────
        if n.op not in ALL_OPS:
            E("E_UNKNOWN_OP", f"Step '{n.id}' uses '{n.op}', which isn't a concept QuantumCanvas knows.", n.id)
            return
        if not need(n, 1 <= n.repeat <= MAX_REPEAT, f"Step '{n.id}': repeat must be between 1 and {MAX_REPEAT}."):
            return

        check_range(n, "qubit", n.targets + n.controls + n.ancillas, nq)
        check_range(n, "classical", n.classical, nc)

        group = n.targets + n.controls + n.ancillas
        dup = sorted({q for q in group if group.count(q) > 1})
        if dup:
            E("E_OVERLAP", f"Step '{n.id}' uses {_fmt_q(dup)} more than once. "
              f"A qubit can't be, say, both a control and a target of the same step.", n.id,
              "Use different qubits for each role.")
        if n.body is not None and n.controls:
            clash = sorted(set(n.controls) & set(qubits_of(n.body)))
            if clash:
                E("E_OVERLAP", f"Step '{n.id}': {_fmt_q(clash)} is both a control and used inside the "
                  f"controlled step.", n.id, "Controls must be different from the qubits being acted on.")

        op, T, A, P = n.op, n.targets, n.ancillas, n.params

        # ── per-concept rules ───────────────────────────────────────
        if op in ("shake", "flip", "boost", "fourier"):
            need(n, len(T) >= 1, f"{op.capitalize()} needs at least one qubit.")
            if op == "fourier":
                for k in ("inverse", "swaps"):
                    if k in P:
                        need(n, isinstance(P[k], bool), f"Fourier '{k}' must be true or false.")
        elif op == "set":
            v = P.get("value")
            if need(n, int_ok(v) and v >= 0, "Set needs a whole number, 0 or more, as its value.") and T:
                need(n, v < (1 << len(T)),
                     f"Value {v} needs {max(v.bit_length(), 1)} qubits, but this Set only has {len(T)}.",
                     "Select more qubits or use a smaller value.")
            need(n, len(T) >= 1, "Set needs at least one qubit.")
            clash = sorted(set(T) & nonzero)
            if clash:
                E("E_SET_NOT_FRESH",
                  f"Set loads a value into qubits that start at 0, but {_fmt_q(clash)} may already hold "
                  f"something else.", n.id, "Reset the qubit first, or use Flip to change it relative to its current state.")
        elif op == "phase":
            need(n, len(T) >= 1, "Phase needs at least one qubit.")
            check_angle(n)
        elif op == "rotate":
            need(n, len(T) >= 1, "Rotate needs at least one qubit.")
            need(n, P.get("axis") in ("x", "y", "z"), "Rotate needs an axis: x, y or z.")
            check_angle(n)
        elif op == "swap":
            need(n, len(T) == 2, "Swap needs exactly two qubits.")
        elif op == "measure":
            need(n, len(T) >= 1, "Measure needs at least one qubit.")
            need(n, len(n.classical) == len(T),
                 "Measure needs one classical bit for each qubit it measures.")
            if len(set(n.classical)) != len(n.classical):
                E("E_OVERLAP", f"Step '{n.id}' writes two qubits into the same classical bit.", n.id)
        elif op == "reset":
            need(n, len(T) == 1, "Reset works on one qubit at a time.")
        elif op == "control":
            need(n, len(n.controls) >= 1, "Control needs at least one control qubit.")
            if need(n, n.body is not None, "Control needs a step to run when the control is 1."):
                if n.body.op in NON_UNITARY_OPS or n.body.op == "uncompute":
                    E("E_PARAM", f"Control can't wrap a {n.body.op.capitalize()}: it isn't a reversible quantum step.",
                      n.id, "Control works on gates like Flip, Phase, Rotate, Swap or Shake.")
                else:
                    check_node(n.body, True, idx)
        elif op == "correct":
            c = n.condition
            ok = (isinstance(c, dict) and int_ok(c.get("clbit")) and c.get("equals") in (0, 1))
            if need(n, ok, 'Correct needs a condition like {"clbit": 0, "equals": 1}.'):
                check_range(n, "classical", [c["clbit"]], nc)
                if c["clbit"] not in written:
                    E("E_COND_UNWRITTEN", f"Correct looks at classical bit {c['clbit']}, but nothing has "
                      f"measured into it yet.", n.id, "Measure a qubit into that bit before this Correct.")
            if need(n, n.body is not None, "Correct needs a step to apply when the condition holds."):
                if n.body.op in NON_UNITARY_OPS or n.body.op == "uncompute":
                    E("E_PARAM", f"Correct can't wrap a {n.body.op.capitalize()}.", n.id,
                      "Use a gate like Flip or Phase as the correction.")
                else:
                    check_node(n.body, True, idx)
        elif op == "entangle":
            need(n, len(T) == 2, "Entangle needs exactly two qubits: first the control, then the target.")
            need(n, P.get("style", "cx") in ("cx", "cz"), "Entangle style must be 'cx' or 'cz'.")
            if len(T) == 2:
                style = P.get("style", "cx")
                needed = [T[0]] if style == "cx" else list(T)
                if any(q not in superposed for q in needed):
                    W("W_NOOP_ENTANGLE",
                      "Entangle only creates a visible link when the qubit it starts from is already in "
                      "superposition. Right now it would just copy a plain 0 or 1.", n.id,
                      "Shake the first qubit before Entangle (CZ needs both qubits shaken).")
        elif op == "encode":
            m = P.get("method")
            if need(n, m in ("basis", "angle"), "Encode needs a method: 'basis' or 'angle'."):
                data = P.get("data")
                if m == "basis":
                    if need(n, int_ok(data) and data >= 0, "Basis encoding needs a whole number as data.") and T:
                        need(n, data < (1 << len(T)), f"Value {data} needs more qubits than this Encode has.")
                    clash = sorted(set(T) & nonzero)
                    if clash:
                        E("E_SET_NOT_FRESH", f"Encoding loads a value into qubits that start at 0, but "
                          f"{_fmt_q(clash)} may already hold something else.", n.id,
                          "Reset the qubit first.")
                else:
                    sc = P.get("scaling")
                    if sc not in ENCODE_SCALINGS:
                        E("E_ENCODE_SCALE", "Angle encoding needs a scaling rule: 'pi_x' (angle = pi*x) or "
                          "'arcsin_sqrt' (so that P(1) = x).", n.id, "Pick one of the two scalings.")
                    ok_list = isinstance(data, list) and all(
                        isinstance(x, (int, float)) and not isinstance(x, bool) for x in data)
                    if need(n, ok_list and len(data) == len(T) and len(T) >= 1,
                            "Angle encoding needs one number per qubit."):
                        if sc == "arcsin_sqrt" and any(x < 0 or x > 1 for x in data):
                            E("E_ENCODE_SCALE", "With 'arcsin_sqrt' every value must be between 0 and 1 "
                              "(it becomes a probability).", n.id)
        elif op == "compare":
            need(n, len(T) >= 1, "Compare needs at least one qubit to look at.")
            need(n, len(A) == 1, "Compare needs exactly one ancilla qubit to hold its yes/no answer.")
            opr = P.get("operator", "eq")
            if opr in ("lt", "gt"):
                E("E_PARAM", f"Compare '{opr}' isn't available yet; use 'eq' or 'neq'.", n.id)
            else:
                need(n, opr in ("eq", "neq"), "Compare operator must be 'eq' or 'neq'.")
            v = P.get("value")
            if need(n, int_ok(v) and v >= 0, "Compare needs a whole number to compare against.") and T:
                need(n, v < (1 << len(T)), f"Value {v} needs more qubits than the {len(T)} being compared.")
            dirty = sorted(set(A) & nonzero)
            if dirty:
                E("E_ANCILLA_DIRTY", f"The ancilla {_fmt_q(dirty)} must start at 0, but it may still hold an "
                  f"earlier answer.", n.id, "Uncompute the earlier Compare, or Reset the ancilla, or use a fresh qubit.")
        elif op == "mark":
            has_v, has_via = "value" in P, bool(P.get("via"))
            if need(n, has_v != has_via, "Mark needs either a value or a 'via' Compare, not both and not neither."):
                if has_v:
                    v = P["value"]
                    need(n, len(T) >= 1, "Mark needs at least one qubit.")
                    if need(n, int_ok(v) and v >= 0, "Mark needs a whole number as its value.") and T:
                        need(n, v < (1 << len(T)), f"Value {v} needs more qubits than this Mark has.")
                else:
                    ref = by_id.get(P["via"])
                    if ref is None or top_index.get(ref.id, 10**9) >= (idx if idx is not None else 0) \
                            or ref.op != "compare":
                        E("E_UNCOMPUTE_REF", "Mark 'via' must point at a Compare step placed earlier.", n.id,
                          "Add a Compare first, then Mark through it.")
        elif op == "add":
            v = P.get("value")
            need(n, int_ok(v) and v >= 0, "Add needs a whole number to add.")
            need(n, len(T) >= 1, "Add needs at least one qubit.")
            mod = P.get("modulus")
            if mod is None:
                E("E_ADD_OVERFLOW", "Add needs a modulus. Adding to a 3-qubit register wraps around at 8, "
                  "so 5 + 3 would overflow.", n.id, f"Set modulus to {1 << max(len(T), 1)} (2 to the number of qubits).")
            elif not (int_ok(mod) and T and mod == (1 << len(T))):
                E("E_ADD_OVERFLOW", f"Add currently supports only modulus {1 << max(len(T), 1)} "
                  f"(2 to the number of qubits).", n.id)
        elif op == "uncompute":
            ref = by_id.get(n.ref) if n.ref else None
            if ref is None:
                E("E_UNCOMPUTE_REF", "Uncompute needs the step it should undo, and that step wasn't found.", n.id)
            elif top_index.get(ref.id) is None or top_index[ref.id] >= (idx if idx is not None else 0):
                E("E_UNCOMPUTE_REF", f"Uncompute must come after the step it undoes ('{ref.id}').", n.id,
                  "Move Uncompute below the step it reverses.")
            else:
                if contains_nonunitary(ref, by_id):
                    E("E_UNCOMPUTE_NONUNITARY", f"'{ref.id}' contains a Measure, Reset or Correct, which can't be "
                      f"undone.", n.id, "Only reversible steps (gates) can be uncomputed.")
                rq = set(qubits_of(ref))
                for k in range(top_index[ref.id] + 1, idx):
                    mid = doc.operations[k]
                    if rq & set(qubits_of(mid)) and not is_diagonal(mid):
                        E("E_UNCOMPUTE_INTERFERENCE",
                          f"'{mid.id}' sits between '{ref.id}' and this Uncompute and changes the same qubits "
                          f"({_fmt_q(rq & set(qubits_of(mid)))}). Uncompute would no longer restore them.", n.id,
                          "Between a step and its Uncompute, only phase-type steps (Phase, Mark) may touch those qubits.")
                        break

    for i, node in enumerate(doc.operations):
        before_of[node.id] = set(nonzero)
        check_node(node, False, i)
        new = body_effects_sim(node)
        effects_of[node.id] = set(new) | {a for a in node.ancillas}
        if node.op == "measure":
            written.update(c for c in node.classical if 0 <= c < nc)
        if node.op == "compare":
            effects_of[node.id] = set(node.ancillas)
    return Report(errs, warns)
