from __future__ import annotations

import ast

from qiskit import QuantumCircuit

_RUN_MARKER = "# ── Run on Aer simulator"

_ALLOWED_METHODS = {"h", "x", "y", "z", "s", "sdg", "t", "tdg", "cx", "cz", "ccx", "mcx",
                    "swap", "measure", "measure_all", "barrier", "reset"}


class UnsafeSource(ValueError):
    pass


def strip_run_block(src: str) -> str:
    idx = src.find(_RUN_MARKER)
    return src[:idx] if idx != -1 else src


def _literal(node: ast.AST):
    try:
        return ast.literal_eval(node)
    except Exception as e:
        raise UnsafeSource(f"argument is not a literal value ({type(node).__name__})") from e


def build_circuit_from_source(qiskit_code: str) -> QuantumCircuit:
    src = strip_run_block(qiskit_code)
    try:
        tree = ast.parse(src, mode="exec")
    except SyntaxError as e:
        raise UnsafeSource(f"not parseable as Python: {e}") from e

    qc: QuantumCircuit | None = None
    for stmt in tree.body:
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            continue
        if (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name) and stmt.targets[0].id == "qc"
                and isinstance(stmt.value, ast.Call) and isinstance(stmt.value.func, ast.Name)
                and stmt.value.func.id == "QuantumCircuit"):
            if qc is not None:
                raise UnsafeSource("`qc` is assigned more than once")
            if stmt.value.keywords:
                raise UnsafeSource("QuantumCircuit(...) may not use keyword arguments here")
            args = [_literal(a) for a in stmt.value.args]
            if not args or not all(isinstance(a, int) and not isinstance(a, bool) for a in args):
                raise UnsafeSource("QuantumCircuit(...) needs plain integer qubit/clbit counts")
            qc = QuantumCircuit(*args)
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            call = stmt.value
            if not (isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == "qc"):
                raise UnsafeSource("only calls to methods of `qc` are allowed")
            if qc is None:
                raise UnsafeSource("a gate was called before `qc = QuantumCircuit(...)`")
            name = call.func.attr
            if name not in _ALLOWED_METHODS:
                raise UnsafeSource(f"'{name}' is not a recognised circuit method")
            if call.keywords:
                raise UnsafeSource("keyword arguments are not supported here")
            args = [_literal(a) for a in call.args]
            getattr(qc, name)(*args)
            continue
        raise UnsafeSource(f"unexpected statement ({type(stmt).__name__})")

    if qc is None:
        raise UnsafeSource("no `qc = QuantumCircuit(...)` assignment found")
    return qc
