"""QuantumCanvas math layer.

Sits between deterministic compilation and any explanation (template or LLM).
Input: a run (ir_json, qiskit_py, results). Output: a step log of computed facts that an explainer is
allowed to cite, plus verification checks.

  1. Code check     - the emitted Qiskit code (what actually ran) equals the IR's meaning, block by block,
                      against an INDEPENDENT reference semantics (never the compiler's own lowering).
  2. Step facts     - per concept: per-qubit P(1) before/after, entanglement entropy.
  3. Counterfactual - remove each step and re-simulate: did it change the measured result?
  4. Contracts      - does each concept do what its explanation claims?
  5. Result check   - are observed counts consistent with the exact predicted distribution?

Seed: math_layer.py (kept output-compatible: the golden log for run f9e60a7115d2 is a test).
Extensions over the seed: every concept in the catalog (Control, Compare, Mark via, Uncompute, Fourier, Add,
Reset, Correct), exact prediction for dynamic circuits (measurement branching), a safe AST parser for all
emitted code forms, and random-state equivalence so the code check scales past dense matrices.

The emitted code is never exec()d.
"""
from __future__ import annotations

import ast
import json
import re

import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit import library as qlib
from qiskit.quantum_info import Statevector, entropy, partial_trace

VERSION = "1.0"
TOL = 1e-9
MAX_SV_QUBITS = 20          # beyond this, skip statevector facts (and say so in the log)
MAX_LOCAL_QUBITS = 10       # largest register a dense reference matrix is built for
EQ_TOL = 1e-8


class Unsupported(Exception):
    """The math layer has no reference semantics for this node (the log says so; nothing is faked)."""


class NonUnitary(Exception):
    pass


# ───────────────────────────── helpers ─────────────────────────────────
def angle(a):
    if isinstance(a, dict):
        if "pi" in a:
            return np.pi * a["pi"][0] / a["pi"][1]
        return float(a["rad"])
    return float(a)


def _mcz(qc, qs):
    if len(qs) == 1:
        qc.z(qs[0])
    elif len(qs) == 2:
        qc.cz(qs[0], qs[1])
    else:
        qc.h(qs[-1]); qc.mcx(qs[:-1], qs[-1]); qc.h(qs[-1])


def _unitary_on(qc, matrix, qubits):
    if len(qubits) > MAX_LOCAL_QUBITS:
        raise Unsupported(f"register of {len(qubits)} qubits is too large for a dense reference matrix")
    qc.unitary(np.asarray(matrix, dtype=complex), list(qubits))


def _perm_matrix(dim, fn):
    m = np.zeros((dim, dim), dtype=complex)
    for i in range(dim):
        m[fn(i), i] = 1
    return m


def _bitrev(i, m):
    return int(format(i, f"0{m}b")[::-1], 2) if m else 0


# ───────────────────── independent reference semantics ─────────────────
def ref_circuit(node, n, by_id):
    """Unitary meaning of one IR node as a circuit on n qubits. Raises NonUnitary / Unsupported."""
    qc = QuantumCircuit(n)
    op, t, p = node["op"], list(node.get("targets", [])), node.get("params", {}) or {}
    reps = max(1, int(node.get("repeat", 1) or 1))
    one = QuantumCircuit(n)
    if op == "shake":
        for q in t: one.h(q)
    elif op == "flip":
        for q in t: one.x(q)
    elif op == "set" or (op == "encode" and p.get("method") == "basis"):
        val = p["value"] if op == "set" else int(p["data"])
        for i, q in enumerate(t):
            if (val >> i) & 1: one.x(q)
    elif op == "encode":                                          # angle
        for q, x in zip(t, p["data"]):
            th = 2 * np.arcsin(np.sqrt(x)) if p.get("scaling") == "arcsin_sqrt" else np.pi * x
            one.ry(th, q)
    elif op == "phase":
        for q in t: one.p(angle(p["angle"]), q)
    elif op == "rotate":
        for q in t: getattr(one, "r" + p["axis"])(angle(p["angle"]), q)
    elif op == "swap":
        one.swap(t[0], t[1])
    elif op == "entangle":
        (one.cz if p.get("style") == "cz" else one.cx)(t[0], t[1])
    elif op == "mark" and p.get("via"):
        # Mark(via) = Phase(pi) on the flag, then Uncompute the Compare. On its own that is  D . C^-1  (it undoes a
        # Compare an earlier step already applied); only Compare followed by Mark(via) is the diagonal D.
        cnode = by_id[p["via"]]
        one.compose(ref_circuit(cnode, n, by_id).inverse(), inplace=True)
        cm = cnode["targets"]; anc = cnode["ancillas"][0]; cv = cnode["params"]["value"]
        neq = cnode.get("params", {}).get("operator", "eq") == "neq"
        m = len(cm); dim = 2 ** (m + 1)
        diag = np.ones(dim, dtype=complex)
        for i in range(dim):
            flag = ((i & (2 ** m - 1)) == cv) != neq
            diag[i] = -1 if (((i >> m) & 1) ^ int(flag)) else 1
        _unitary_on(one, np.diag(diag), cm + [anc])
    elif op == "mark":
        zeros = [q for i, q in enumerate(t) if not (p["value"] >> i) & 1]
        for q in zeros: one.x(q)
        _mcz(one, t)
        for q in zeros: one.x(q)
    elif op == "boost":
        for q in t: one.h(q); one.x(q)
        _mcz(one, t)
        for q in t: one.x(q); one.h(q)
    elif op == "compare":
        m = len(t); anc = node["ancillas"][0]; v = p["value"]; neq = p.get("operator", "eq") == "neq"
        mat = _perm_matrix(2 ** (m + 1), lambda i: i ^ ((int(((i & (2 ** m - 1)) == v) != neq)) << m))
        _unitary_on(one, mat, t + [anc])
    elif op == "add":
        m = len(t); c = p["value"]; N = 2 ** m
        _unitary_on(one, _perm_matrix(N, lambda i: (i + c) % N), t)
    elif op == "fourier":
        m = len(t); N = 2 ** m
        j = np.arange(N)
        F = np.exp(2j * np.pi * np.outer(j, j) / N) / np.sqrt(N)
        if not p.get("swaps", True):
            F = _perm_matrix(N, lambda i: _bitrev(i, m)) @ F
        if p.get("inverse"):
            F = F.conj().T
        _unitary_on(one, F, t)
    elif op == "control":
        body = node["body"]
        bc = ref_circuit(body, n, by_id)
        ctrl = list(node["controls"])
        used = sorted({q for q in range(n) if _touches(bc, q)})
        if len(used) + len(ctrl) > MAX_LOCAL_QUBITS:
            raise Unsupported("controlled step touches too many qubits for a dense reference matrix")
        sub = QuantumCircuit(len(used))
        idx = {q: i for i, q in enumerate(used)}
        for ins in bc.data:
            sub.append(ins.operation, [idx[bc.find_bit(x).index] for x in ins.qubits])
        from qiskit.quantum_info import Operator
        Mb = Operator(sub).data
        K, B = len(ctrl), len(used)
        full = np.eye(2 ** (K + B), dtype=complex)
        allc = (1 << K) - 1
        for ib in range(2 ** B):
            for jb in range(2 ** B):
                full[(jb << K) | allc, (ib << K) | allc] = Mb[jb, ib]
        _unitary_on(one, full, ctrl + used)
    elif op == "uncompute":
        inner = ref_circuit(by_id[node["ref"]], n, by_id)
        return inner.inverse()
    elif op == "measure":
        return qc
    elif op in ("reset", "correct"):
        raise NonUnitary(op)
    else:
        raise Unsupported(f"math layer has no reference semantics for '{op}' yet")
    for _ in range(reps):
        qc.compose(one, inplace=True)
    return qc


def _touches(qc, q):
    return any(qc.find_bit(x).index == q for ins in qc.data for x in ins.qubits)


# ───────────────────── parse emitted Qiskit safely (no exec) ───────────
_HEADER = re.compile(r"^# [A-Z]+\b")
_NUM_FUNCS = {"np.pi": np.pi, "pi": np.pi}
_GATE_CLASSES = {k: getattr(qlib, k) for k in (
    "XGate", "YGate", "ZGate", "HGate", "SGate", "SdgGate", "TGate", "TdgGate", "PhaseGate",
    "RXGate", "RYGate", "RZGate", "SwapGate")}


def _ev(node):
    """Evaluate a tiny, whitelisted expression grammar from the emitted code."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _ev(node.operand)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
        a, b = _ev(node.left), _ev(node.right)
        return {ast.Add: a + b, ast.Sub: a - b, ast.Mult: a * b, ast.Div: a / b if b else float("nan")}[type(node.op)]
    if isinstance(node, ast.Attribute) and ast.unparse(node) in _NUM_FUNCS:
        return _NUM_FUNCS[ast.unparse(node)]
    if isinstance(node, ast.Name) and node.id in _NUM_FUNCS:
        return _NUM_FUNCS[node.id]
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_ev(e) for e in node.elts]
    if isinstance(node, ast.Call):                                    # PhaseGate(x) or <gate>.control(k)
        f = node.func
        if isinstance(f, ast.Name) and f.id in _GATE_CLASSES:
            return _GATE_CLASSES[f.id](*[_ev(a) for a in node.args])
        if isinstance(f, ast.Attribute) and f.attr == "control":
            return _ev(f.value).control(*[_ev(a) for a in node.args])
    raise ValueError(f"unsupported expression in emitted code: {ast.unparse(node)}")


def _cond_of(test_src):
    m = re.match(r"^with qc\.if_test\(\(qc\.clbits\[(\d+)\],\s*(\d+)\)\):$", test_src)
    return (int(m.group(1)), int(m.group(2))) if m else None


def parse_qiskit_blocks(src, n):
    """Split emitted code into per-concept blocks by its '# CONCEPT' header comments."""
    blocks, cur, cond = [], None, None
    for raw in src.splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.startswith("# ──"):
            break                                                     # runner footer
        if _HEADER.match(s):
            cur = {"header": s[2:], "qc": QuantumCircuit(n), "measures": [], "resets": [], "cond": []}
            blocks.append(cur); cond = None
            continue
        if s.startswith("#") or cur is None:
            continue
        if s.startswith("with "):
            c = _cond_of(s)
            if c is None:
                raise ValueError(f"unsupported block in emitted code: {s}")
            cond = (c, QuantumCircuit(n)); cur["cond"].append(cond)
            continue
        indented = raw[:1] in (" ", "\t")
        if not indented:
            cond = None
        tree = ast.parse(s, mode="eval").body
        if not (isinstance(tree, ast.Call) and isinstance(tree.func, ast.Attribute)
                and isinstance(tree.func.value, ast.Name) and tree.func.value.id == "qc"):
            continue                                                  # imports, print, etc.
        name, args = tree.func.attr, [_ev(a) for a in tree.args]
        target = cond[1] if (cond and indented) else cur["qc"]
        if name == "measure":
            cur["measures"].append(tuple(args))
        elif name == "reset":
            cur["resets"].append(tuple(args))
        else:
            getattr(target, name)(*args)
    return blocks


# ───────────────────────── exact simulation ───────────────────────────
def tvd(a, b):
    return 0.5 * sum(abs(a.get(k, 0) - b.get(k, 0)) for k in set(a) | set(b))


def _p1(sv, q):
    return float(sv.probabilities([q])[1])


def qubit_facts(sv, n):
    p1 = [_p1(sv, q) for q in range(n)]
    ent = [float(entropy(partial_trace(sv, [j for j in range(n) if j != q]), base=2)) if n > 1 else 0.0
           for q in range(n)]
    return p1, ent


class Sim:
    """Exact simulation of an IR, with measurement / reset branching for dynamic circuits."""

    def __init__(self, ir, skip=None):
        self.ir, self.n, self.nc = ir, ir["qubits"], ir.get("classical_bits", 0)
        self.by_id = {}
        stack = list(ir["operations"])
        while stack:
            x = stack.pop(); self.by_id[x["id"]] = x
            if x.get("body"): stack.append(x["body"])
        self.skip = skip
        ops = ir["operations"]
        # trailing measures are handled analytically (no 2^k branches)
        k = len(ops)
        while k > 0 and ops[k - 1]["op"] == "measure":
            k -= 1
        self.core, self.tail = list(range(k)), list(range(k, len(ops)))

    def initial(self):
        return [(1.0, Statevector.from_label("0" * self.n), (0,) * self.nc)]

    def step(self, branches, node):
        op = node["op"]
        out = []
        for pr, sv, cl in branches:
            if op == "measure":
                out += self._measure(pr, sv, cl, node)
            elif op == "reset":
                out += self._reset(pr, sv, cl, node["targets"][0])
            elif op == "correct":
                c = node["condition"]
                if cl[c["clbit"]] == c["equals"]:
                    sv = sv.evolve(ref_circuit(node["body"], self.n, self.by_id))
                out.append((pr, sv, cl))
            else:
                out.append((pr, sv.evolve(ref_circuit(node, self.n, self.by_id)), cl))
        return out

    def _project(self, sv, q, bit):
        idx = np.arange(2 ** self.n)
        mask = ((idx >> q) & 1) == bit
        d = np.where(mask, sv.data, 0)
        w = float(np.sum(np.abs(d) ** 2))
        return w, (Statevector(d / np.sqrt(w)) if w > TOL else None)

    def _measure(self, pr, sv, cl, node):
        res = [(pr, sv, cl)]
        for q, c in zip(node["targets"], node["classical"]):
            nxt = []
            for p0, s0, c0 in res:
                for bit in (0, 1):
                    w, s1 = self._project(s0, q, bit)
                    if s1 is not None:
                        cl1 = list(c0); cl1[c] = bit
                        nxt.append((p0 * w, s1, tuple(cl1)))
            res = nxt
        return res

    def _reset(self, pr, sv, cl, q):
        out = []
        for bit in (0, 1):
            w, s1 = self._project(sv, q, bit)
            if s1 is None:
                continue
            if bit == 1:
                qc = QuantumCircuit(self.n); qc.x(q); s1 = s1.evolve(qc)
            out.append((pr * w, s1, cl))
        return out

    def run(self, with_steps=False):
        """-> final distribution over classical bits (Qiskit order); optionally per-step branch lists."""
        branches, snaps = self.initial(), []
        for i in self.core:
            node = self.ir["operations"][i]
            if i != self.skip:
                branches = self.step(branches, node)
            snaps.append(branches)
        tail = [self.ir["operations"][i] for i in self.tail if i != self.skip]
        pairs = [(q, c) for nd in tail for q, c in zip(nd["targets"], nd["classical"])]
        dist = {}
        for pr, sv, cl in branches:
            if pairs:
                qs = [q for q, _ in pairs]
                probs = sv.probabilities(qs)
                for idx, w in enumerate(probs):
                    if w < TOL:
                        continue
                    bits = list(cl)
                    for k, (_, c) in enumerate(pairs):
                        bits[c] = (idx >> k) & 1
                    key = "".join(str(b) for b in reversed(bits))
                    dist[key] = dist.get(key, 0) + pr * w
            else:
                if any(nd["op"] in ("measure", "reset", "correct") for nd in self.ir["operations"]):
                    key = "".join(str(b) for b in reversed(cl))
                    dist[key] = dist.get(key, 0) + pr
        dist = {k: v for k, v in dist.items() if v > TOL}
        return (dist, snaps, branches) if with_steps else dist


# ───────────────────────────── contracts ───────────────────────────────
def _marked(history, boost_targets, by_id):
    """Most recent Mark before this Boost: -> (register, value) or None."""
    for h in reversed(history):
        if h["op"] != "mark":
            continue
        p = h.get("params", {})
        if p.get("via") and p["via"] in by_id:
            c = by_id[p["via"]]
            if c.get("params", {}).get("operator", "eq") == "neq":
                return None
            return list(c["targets"]), c["params"]["value"]
        if "value" in p and set(h["targets"]) <= set(boost_targets):
            return list(h["targets"]), p["value"]
    return None


def _reg_prob(sv, reg, value):
    return float(sv.probabilities(list(reg))[value])


def contracts(node, before, after, sv_before, sv_after, n, history, by_id, facts_out=None):
    """List of (claim, held, detail). Claims mirror the explanation text.
    facts_out (optional dict) receives structured facts a template can cite without parsing strings."""
    op, t, p = node["op"], node["targets"], node.get("params", {}) or {}
    out = []
    facts_out = facts_out if facts_out is not None else {}
    p1b, entb = before
    p1a, enta = after
    if op == "encode" and p.get("method") == "angle":
        for q, x in zip(t, p["data"]):
            fresh = not any(q in h["targets"] for h in history)
            ok = abs(p1a[q] - x) < 1e-6
            out.append((f"q{q} carries the data: P(1) = {x}", ok,
                        f"P(1)={p1a[q]:.3f}" + ("" if fresh else " (qubit was not fresh)")))
    if op == "shake":
        for q in t:
            ok = abs(p1a[q] - 0.5) < 1e-6
            out.append((f"q{q} becomes an even 50/50 mix", ok,
                        f"P(1) {p1b[q]:.3f} -> {p1a[q]:.3f}" +
                        ("" if ok else "; Shake only gives 50/50 from a definite 0 or 1")))
    if op == "entangle":
        ok = max(enta[q] - entb[q] for q in t) > 1e-6
        out.append(("the two qubits become correlated (entanglement increases)", ok,
                    f"entropy q{t[0]}: {entb[t[0]]:.3f} -> {enta[t[0]]:.3f}"))
    if op in ("mark", "phase"):
        ok = np.allclose(sv_before.probabilities(), sv_after.probabilities())
        out.append(("probabilities don't change", ok, ""))
    if op == "boost":
        m = _marked(history, t, by_id)
        if m:
            reg, v = m
            pb, pa = _reg_prob(sv_before, reg, v), _reg_prob(sv_after, reg, v)
            detail, ok = f"P(marked) {pb:.3f} -> {pa:.3f}", pa > pb + 1e-6
            rounds = max(1, int(node.get("repeat", 1) or 1))
            facts_out["boost"] = {"register": list(reg), "value": v, "trajectory": [round(pb, 6), round(pa, 6)], "rounds": rounds}
            if rounds > 1:
                qc1 = ref_circuit({**node, "repeat": 1}, n, by_id)
                s, traj = sv_before, [pb]
                for _ in range(rounds):
                    s = s.evolve(qc1); traj.append(_reg_prob(s, reg, v))
                facts_out["boost"]["trajectory"] = [round(x, 6) for x in traj]
                detail += " (rounds: " + " -> ".join(f"{x:.3f}" for x in traj) + ")"
                ok = ok and traj[-1] >= max(traj) - 1e-6
                if traj[-1] < max(traj) - 1e-6:
                    detail += "; past the best round"
            if len(t) < 2:
                detail += " (Boost needs >=2 qubits to amplify)"
            out.append((f"marked answer {v} becomes more likely", ok, detail))
    if op == "compare":
        reg, anc, v = t, node["ancillas"][0], p["value"]
        neq = p.get("operator", "eq") == "neq"
        pr_reg = _reg_prob(sv_before, reg, v)
        want = (1 - pr_reg) if neq else pr_reg
        got = _p1(sv_after, anc)
        fresh = _p1(sv_before, anc) < 1e-9
        out.append((f"flag = (register {'!=' if neq else '=='} {v})", abs(got - want) < 1e-6 and fresh,
                    f"P(flag=1) = {got:.3f}, expected {want:.3f}" + ("" if fresh else "; the flag qubit was not fresh")))
    if op == "uncompute":
        ref = by_id.get(node.get("ref"))
        anc = list(ref.get("ancillas", [])) if ref else []
        if anc:
            worst = max(_p1(sv_after, a) for a in anc)
            out.append(("the helper qubits are back to 0", worst < 1e-6,
                        "max P(1) on " + ", ".join(f"q{a}" for a in anc) + f" = {worst:.3f}"))
    if op == "add":
        m, c = len(t), p["value"]; N = 2 ** m
        pb, pa = sv_before.probabilities(t), sv_after.probabilities(t)
        ok = all(abs(pa[(v + c) % N] - pb[v]) < 1e-6 for v in range(N))
        out.append((f"the register value goes up by {c} (mod {N})", ok, ""))
    if op == "fourier":
        out.append(("matches the standard Fourier transform", True, "reference = DFT matrix"))
    return out


# ───────────────────────────── analysis ────────────────────────────────
def _equiv_random(a: QuantumCircuit, b: QuantumCircuit, n, k=4, seed=7):
    """Same unitary up to ONE global phase, tested on k random states (works for any n the simulator handles)."""
    rng = np.random.default_rng(seed)
    phase = None
    for _ in range(k):
        v = rng.normal(size=2 ** n) + 1j * rng.normal(size=2 ** n)
        v /= np.linalg.norm(v)
        x, y = Statevector(v).evolve(a).data, Statevector(v).evolve(b).data
        ov = np.vdot(y, x)
        if abs(abs(ov) - 1) > EQ_TOL:
            return False
        if phase is None:
            phase = ov
        elif abs(ov - phase) > 1e-6:
            return False
    return True


def _code_checks(ir, src, n, by_id, log):
    ops = ir["operations"]
    try:
        blocks = parse_qiskit_blocks(src, n)
    except Exception as e:
        log["checks"].append({"check": "emitted code can be parsed safely", "ok": False, "detail": str(e)})
        return
    if len(blocks) != len(ops):
        log["checks"].append({"check": "code blocks align with IR nodes", "ok": False,
                              "detail": f"{len(blocks)} code blocks vs {len(ops)} IR nodes"})
        return
    for node, b in zip(ops, blocks):
        name = f"code matches IR for {node['id']} ({node['op']})"
        try:
            if node["op"] == "measure":
                ok = [tuple(m) for m in b["measures"]] == list(zip(node["targets"], node["classical"]))
            elif node["op"] == "reset":
                ok = [tuple(r) for r in b["resets"]] == [(node["targets"][0],)]
            elif node["op"] == "correct":
                c = node["condition"]
                inner = ref_circuit(node["body"], n, by_id)
                ok = (len(b["cond"]) >= 1 and all(cc == (c["clbit"], c["equals"]) for cc, _ in b["cond"])
                      and len(b["qc"].data) == 0)
                if ok:
                    merged = QuantumCircuit(n)
                    for _, qq in b["cond"]:
                        merged.compose(qq, inplace=True)
                    ok = _equiv_random(merged, inner, n)
            else:
                ok = _equiv_random(ref_circuit(node, n, by_id), b["qc"], n) and not b["measures"] and not b["cond"]
            log["checks"].append({"check": name, "ok": bool(ok)})
        except Unsupported as e:
            log["checks"].append({"check": name, "ok": None, "detail": f"skipped: {e}"})


def _observed_check(obs, predicted, log):
    obs = {str(k).replace(" ", ""): int(v) for k, v in (obs or {}).items() if k != "circuit_hash"}
    if not (obs and predicted):
        return
    shots = sum(obs.values()); keys = sorted(set(obs) | set(predicted))
    exp = np.array([predicted.get(k, 0) * shots for k in keys])
    o = np.array([obs.get(k, 0) for k in keys])
    if np.any((exp == 0) & (o > 0)):
        log["checks"].append({"check": "observed counts consistent with prediction", "ok": False,
                              "detail": "observed an outcome with predicted probability 0"})
        return
    from scipy.stats import chisquare
    m = exp > 0
    pval = float(chisquare(o[m], exp[m]).pvalue) if m.sum() > 1 else 1.0
    log["checks"].append({"check": "observed counts consistent with prediction", "ok": pval > 1e-3,
                          "detail": f"chi-square p = {pval:.3f}"})


_DEFAULTS = {"targets": [], "controls": [], "ancillas": [], "classical": [], "params": {}, "condition": None,
             "body": None, "ref": None, "repeat": 1}


def _normal_node(n):
    out = {**_DEFAULTS, **{k: v for k, v in n.items() if v is not None or k in ("condition", "body", "ref")}}
    out["params"] = dict(out.get("params") or {})
    out["body"] = _normal_node(out["body"]) if out.get("body") else None
    return out


def normalise_ir(ir):
    """Fill in omitted node fields (the schema allows omitting unused ones)."""
    return {"version": ir.get("version", "0.3"), "qubits": ir["qubits"], "classical_bits": ir.get("classical_bits", 0),
            "operations": [_normal_node(n) for n in ir.get("operations", [])]}


def analyze(run, *, max_qubits=MAX_SV_QUBITS, code_check=True, counterfactual=True):
    ir = json.loads(run["ir_json"]) if isinstance(run.get("ir_json"), str) else run["ir_json"]
    ir = normalise_ir(ir)
    n, ops = ir["qubits"], ir["operations"]
    log = {"math_layer_version": VERSION, "run_id": run.get("run_id"), "n_qubits": n, "checks": [], "steps": []}
    if n > max_qubits:
        log["checks"].append({"check": "statevector", "ok": None,
                              "detail": f"{n} qubits > {max_qubits}: step facts skipped"})
        log["skipped"] = "too large"
        return log
    sim = Sim(ir)
    by_id = sim.by_id
    src = run.get("qiskit_py") or ""
    if code_check and src.strip():
        _code_checks(ir, src, n, by_id, log)

    try:
        predicted, snaps, final_branches = sim.run(with_steps=True)
    except (Unsupported, NonUnitary) as e:
        log["checks"].append({"check": "exact simulation", "ok": None, "detail": f"skipped: {e}"})
        return log
    pairs = [(q, c) for nd in ops if nd["op"] == "measure" for q, c in zip(nd["targets"], nd["classical"])]

    # 2-4. step facts, counterfactuals, contracts
    sv = Statevector.from_label("0" * n)
    branches = sim.initial()
    facts = qubit_facts(sv, n)
    history = []
    ineffective = []
    for i, node in enumerate(ops):
        if i in sim.core:
            nxt = snaps[sim.core.index(i)]
        else:
            nxt = branches                                           # trailing measure: state unchanged
        single = len(nxt) == 1
        if single:
            sv_next = nxt[0][1]
            facts_next = qubit_facts(sv_next, n)
        else:
            sv_next = None
            weights = [(b[0], b[1]) for b in nxt]
            facts_next = ([float(sum(w * _p1(s, q) for w, s in weights)) for q in range(n)], None)
        entb = facts[1] if facts[1] is not None else [None] * n
        enta = facts_next[1] if facts_next[1] is not None else [None] * n
        step = {"id": node["id"], "op": node["op"], "targets": node["targets"],
                "p1_before": np.round(facts[0], 4).tolist(), "p1_after": np.round(facts_next[0], 4).tolist(),
                "entropy_before": [None if x is None else round(x, 4) for x in entb],
                "entropy_after": [None if x is None else round(x, 4) for x in enta]}
        if node["op"] != "measure" and pairs and counterfactual:
            try:
                alt = Sim(ir, skip=i).run()
                d = tvd(alt, predicted)
                step["affects_result"] = bool(d > 1e-6)
                step["result_shift_if_removed"] = round(d, 4)
                if not step["affects_result"]:
                    ineffective.append(i)
            except (Unsupported, NonUnitary, KeyError):
                step["affects_result"] = None
                step["note"] = "other steps depend on this one"
        cs, sfacts = [], {}
        if single and facts[1] is not None and sv_next is not None and len(branches) == 1:
            try:
                cs = contracts(node, facts, facts_next, branches[0][1], sv_next, n, history, by_id, sfacts)
            except (Unsupported, NonUnitary, KeyError):
                cs = []
        step["contracts"] = [{"claim": c, "held": bool(ok), "detail": d} for c, ok, d in cs]
        if sfacts:
            step["facts"] = sfacts
        log["steps"].append(step)
        history.append(node)
        branches = nxt
        sv, facts = sv_next, facts_next

    # joint check: removing every flagged step together must also leave the result alone
    if ineffective and counterfactual:
        try:
            keep = {**ir, "operations": [o for k, o in enumerate(ops) if k not in set(ineffective)]}
            log["ineffective_together"] = bool(tvd(Sim(keep).run(), predicted) < 1e-6)
        except Exception:
            log["ineffective_together"] = None
    if log.get("ineffective_together") is False:                     # individually harmless but jointly needed
        for s in log["steps"]:
            if s.get("affects_result") is False:
                s["affects_result_note"] = "harmless alone, but not together with the other idle steps"

    # 5. observed vs predicted
    log["predicted"] = {k: round(v, 6) for k, v in predicted.items()}
    _observed_check(run.get("results"), predicted, log)
    return log


def analyze_document(doc, *, qiskit_py="", results=None, run_id=None, **kw):
    return analyze({"run_id": run_id, "ir_json": doc, "qiskit_py": qiskit_py, "results": results}, **kw)


def report(log):
    print(f"run {log.get('run_id')}  ({log['n_qubits']} qubits)\n")
    print("CHECKS")
    for c in log["checks"]:
        print(f"  {'PASS' if c['ok'] else 'FAIL' if c['ok'] is False else 'SKIP'}  {c['check']}  {c.get('detail', '')}")
    print("\nSTEPS  (P(1) per qubit q0,q1,...)")
    for s in log["steps"]:
        eff = "" if "affects_result" not in s else (
            "  affects result" if s["affects_result"] else "  NO effect on measured result" if s["affects_result"] is False else "")
        print(f"  {s['id']} {s['op']:<9} P(1) {s['p1_before']} -> {s['p1_after']}  entropy {s['entropy_after']}{eff}")
        for c in s["contracts"]:
            print(f"      {'held  ' if c['held'] else 'BROKEN'} claim: {c['claim']}  {c['detail']}")
    print(f"\nPREDICTED {log.get('predicted')}")


if __name__ == "__main__":
    import sys
    run = json.load(open(sys.argv[1], encoding="utf-8"))
    lg = analyze(run)
    report(lg)
    if "--json" in sys.argv:
        json.dump(lg, open(sys.argv[sys.argv.index("--json") + 1], "w", encoding="utf-8"), indent=2)
