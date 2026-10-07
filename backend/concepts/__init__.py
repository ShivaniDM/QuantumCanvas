"""QuantumCanvas concept compiler.

Concept IR (L1)  ->  validate  ->  expand composites  ->  Logical Gate IR (L2)
                 ->  backend lowering (L3: Qiskit / Aer, IonQ)

Compilation is deterministic: the same Concept IR always yields the same gates.
There is no AI/LLM anywhere in this path.
"""
from .schema import SCHEMA_VERSION, Document, Node, parse_document, to_dict
from .compiler import compile_document, CompileResult

__all__ = [
    "SCHEMA_VERSION", "Document", "Node", "parse_document", "to_dict",
    "compile_document", "CompileResult",
]
