"""Safe, AST-only builder for classic-mode's generated Qiskit text (security fix: no exec()/eval()).

frontend/js/qiskit-generator.js only ever emits a closed, fixed shape: one
`qc = QuantumCircuit(n, n)` assignment, then calls to a small set of QuantumCircuit
methods with literal integer (or list-of-integer) arguments, followed by a fixed
simulate/print tail that we always strip. This module walks exactly that shape with
Python's `ast` module and refuses (raises UnsafeSource) at the first statement that
doesn't match it.

It never calls exec(), eval(), or compile(..., "exec") on the text. It only ever calls
whitelisted methods on a QuantumCircuit object we created ourselves, with arguments that
passed ast.literal_eval (which itself can only produce numbers/strings/lists/tuples —
never a call, a name lookup, or an attribute access). That is the whole safety boundary:
attacker-controlled text can select *which* gate is applied and *where*, never run code.
"""
from __future__ import annotations

import ast

from qiskit import QuantumCircuit

_RUN_MARKER = "# ── Run on Aer simulator"

# Every method frontend/js/qiskit-generator.js can emit, plus a few harmless extras
# (barrier, reset, measure_all) kept for forward compatibility. Nothing else is callable.
_ALLOWED_METHODS = {"h", "x", "y", "z", "s", "sdg", "t", "tdg", "cx", "cz", "ccx", "mcx",
                    "swap", "measure", "measure_all", "barrier", "reset"}


class UnsafeSource(ValueError):
    """The text isn't the closed shape the generator emits. Refused before anything ran."""


def strip_run_block(src: str) -> str:
    """Drop the trailing simulate/print block the generator appends (shots are set by the caller)."""
    idx = src.find(_RUN_MARKER)
    return src[:idx] if idx != -1 else src


def _literal(node: ast.AST):
    """A number, string, list/tuple of those, or a unary +/- of one. Never a call, name, or attribute —
    ast.literal_eval raises ValueError for anything else, which we re-raise as UnsafeSource."""
    try:
        return ast.literal_eval(node)
    except Exception as e:
        raise UnsafeSource(f"argument is not a literal value ({type(node).__name__})") from e


def build_circuit_from_source(qiskit_code: str) -> QuantumCircuit:
    """Build a QuantumCircuit by walking the generator's known statement shapes.

    Raises UnsafeSource for any statement outside that shape — including any attempt to
    call something other than a whitelisted method on `qc`, or to pass a non-literal
    argument. Nothing is executed; the circuit is built by this function calling real
    QuantumCircuit methods itself.
    """
    src = strip_run_block(qiskit_code)
    try:
        tree = ast.parse(src, mode="exec")
    except SyntaxError as e:
        raise UnsafeSource(f"not parseable as Python: {e}") from e

    qc: QuantumCircuit | None = None
    for stmt in tree.body:
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            continue                                            # imports are never executed; harmless to skip
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
