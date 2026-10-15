from __future__ import annotations

import ast
import math

from qiskit import QuantumCircuit

MAX_SOURCE_CHARS = 200_000
MAX_LOOP_ITERATIONS = 4096

GATE_METHODS = {
    "h", "x", "y", "z", "s", "sdg", "t", "tdg", "sx", "id",
    "p", "rx", "ry", "rz", "u",
    "cx", "cy", "cz", "ch", "cp", "crx", "cry", "crz", "ccx", "mcx", "swap", "cswap",
    "measure", "measure_all", "reset", "barrier",
}
SUPPORTED_SUMMARY = ("qc = QuantumCircuit(n) or QuantumCircuit(n, m); calls like qc.h(0), qc.cx(0, 1), qc.rz(np.pi/4, 2), "
                     "qc.measure(0, 0) and qc.measure_all(); numbers, pi arithmetic and lists of qubits; "
                     "for loops over range(...) whose body only calls qc methods")


class SubsetError(ValueError):
    def __init__(self, message: str, line: int | None = None, construct: str | None = None):
        super().__init__(message)
        self.line = line
        self.construct = construct


class _Eval:
    def __init__(self, env: dict):
        self.env = env

    def __call__(self, node, line):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in self.env:
                return self.env[node.id]
            if node.id == "pi":
                return math.pi
            raise SubsetError(f"'{node.id}' is not defined here", line, "name")
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in ("np", "numpy", "math") \
                and node.attr == "pi":
            return math.pi
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            v = self(node.operand, line)
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)):
            a, b = self(node.left, line), self(node.right, line)
            if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and b == 0:
                raise SubsetError("division by zero", line, "arithmetic")
            if isinstance(node.op, ast.Pow) and abs(b) > 64:
                raise SubsetError("exponent too large", line, "arithmetic")
            return {ast.Add: lambda: a + b, ast.Sub: lambda: a - b, ast.Mult: lambda: a * b, ast.Div: lambda: a / b,
                    ast.FloorDiv: lambda: a // b, ast.Mod: lambda: a % b, ast.Pow: lambda: a ** b}[type(node.op)]()
        if isinstance(node, (ast.List, ast.Tuple)):
            return [self(e, line) for e in node.elts]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("range", "list"):
            args = [self(a, line) for a in node.args]
            if node.func.id == "list" and len(args) == 1 and isinstance(args[0], list):
                return args[0]
            if node.func.id == "range" and all(isinstance(a, int) for a in args) and 1 <= len(args) <= 3:
                r = range(*args)
                if len(r) > MAX_LOOP_ITERATIONS:
                    raise SubsetError("range is too large", line, "range")
                return list(r)
        raise SubsetError(f"this expression isn't supported ({type(node).__name__})", line, type(node).__name__)


def _is_qc_ctor(value) -> bool:
    return isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "QuantumCircuit"


def parse(source: str) -> tuple[QuantumCircuit, list[dict]]:
    if len(source) > MAX_SOURCE_CHARS:
        raise SubsetError(f"the code is longer than {MAX_SOURCE_CHARS} characters")
    marker = source.find("# ── Run on Aer simulator")
    if marker != -1:
        source = source[:marker]
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as e:
        raise SubsetError(f"not valid Python: {e.msg}", e.lineno, "syntax") from e
    state = {"qc": None, "prov": []}

    def call(stmt_call: ast.Call, line: int, env: dict, loop: str | None):
        f = stmt_call.func
        if isinstance(f, ast.Name) and f.id == "print":
            return
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "qc" and f.attr == "draw":
            return
        if not (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "qc"):
            raise SubsetError("only methods of `qc` can be called", line, "call")
        if state["qc"] is None:
            raise SubsetError("a gate is applied before `qc = QuantumCircuit(...)`", line, "order")
        if f.attr not in GATE_METHODS:
            raise SubsetError(f"qc.{f.attr}(...) isn't in the supported subset", line, f"qc.{f.attr}")
        if stmt_call.keywords:
            raise SubsetError("keyword arguments aren't supported", line, "keywords")
        ev = _Eval(env)
        args = [ev(a, line) for a in stmt_call.args]
        qc = state["qc"]
        before = len(qc.data)
        try:
            getattr(qc, f.attr)(*args)
        except Exception as e:
            raise SubsetError(f"qc.{f.attr}: {str(e)[:200]}", line, f"qc.{f.attr}") from e
        for _ in range(len(qc.data) - before):
            state["prov"].append({"line": line, **({"loop": loop} if loop else {})})

    def run(stmts, env: dict, loop: str | None):
        for st in stmts:
            line = getattr(st, "lineno", None)
            if isinstance(st, (ast.Import, ast.ImportFrom, ast.Pass)):
                continue
            if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name) \
                    and st.targets[0].id == "qc" and _is_qc_ctor(st.value):
                if state["qc"] is not None:
                    raise SubsetError("`qc` is created more than once", line, "QuantumCircuit")
                if loop:
                    raise SubsetError("`qc` can't be created inside a loop", line, "QuantumCircuit")
                ev = _Eval(env)
                if st.value.keywords:
                    raise SubsetError("QuantumCircuit(...) keyword arguments aren't supported", line, "QuantumCircuit")
                sizes = [ev(a, line) for a in st.value.args]
                if not 1 <= len(sizes) <= 2 or not all(isinstance(x, int) and x >= 0 for x in sizes):
                    raise SubsetError("QuantumCircuit(...) needs one or two whole numbers", line, "QuantumCircuit")
                state["qc"] = QuantumCircuit(*sizes)
                continue
            if isinstance(st, ast.Expr) and isinstance(st.value, ast.Call):
                call(st.value, line, env, loop)
                continue
            if isinstance(st, ast.For) and isinstance(st.target, ast.Name) and not st.orelse:
                values = _Eval(env)(st.iter, line)
                if not isinstance(values, list):
                    raise SubsetError("loops must run over range(...) or a list", line, "for")
                for v in values:
                    inner = dict(env)
                    inner[st.target.id] = v
                    run(st.body, inner, f"{st.target.id}={v}" if loop is None else f"{loop}, {st.target.id}={v}")
                continue
            if isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant) and isinstance(st.value.value, str):
                continue
            kind = type(st).__name__
            if isinstance(st, ast.Assign) and _is_qc_ctor(st.value):
                raise SubsetError("the circuit must be named `qc`", line, "QuantumCircuit")
            raise SubsetError(f"{kind} statements aren't in the supported subset", line, kind)

    run(tree.body, {}, None)
    if state["qc"] is None:
        raise SubsetError("no `qc = QuantumCircuit(...)` found")
    return state["qc"], state["prov"]
