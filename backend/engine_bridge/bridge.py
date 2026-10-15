from __future__ import annotations

from dataclasses import dataclass, field

from . import client
from .client import EngineRequestError, EngineUnavailable

LEGACY_BACKENDS = ("aer", "simulator", "ionq", "qpu")
GROUP_LABELS = {"local_sim": "Locally run simulators", "remote_sim": "Remotely run simulators",
                "hardware": "Quantum hardware"}
BUILTIN = {"id": "aer", "label": "Built-in simulator", "group": "local_sim", "provider": "aer", "kind": "ideal",
           "qubits": 24, "native_gates": ["any Qiskit gate"], "connectivity": "all-to-all", "cost": "free",
           "device": None, "family": None, "mid_circuit_measure": True, "reset": True, "feed_forward": True,
           "note": "Qiskit Aer, ideal (no noise). Exact, instant: the best first check.", "aliases": ["builtin"],
           "runs_here": True}


def _row(id_, label, group, provider, kind, qubits, device=None, family=None, cost="free"):
    return {"id": id_, "label": label, "group": group, "provider": provider, "kind": kind, "qubits": qubits,
            "device": device, "family": family, "cost": cost, "aliases": [], "runs_here": group == "local_sim"}


IBM_DEVICES = (("boston", "FakeBoston", 156, "Heron r3"), ("kingston", "FakeKingston", 156, "Heron r2"),
               ("pittsburgh", "FakePittsburgh", 156, "Heron r3"), ("fez", "FakeFez", 156, "Heron r2"),
               ("marrakesh", "FakeMarrakesh", 156, "Heron r2"), ("miami", "FakeMiami", 120, "Nighthawk r1"),
               ("aachen", "FakeAachen", 156, "Heron r3"), ("berlin", "FakeBerlin", 120, "Nighthawk r1"))
OFFLINE_CATALOG = (
    [BUILTIN, _row("braket_local", "AWS Braket local simulator", "local_sim", "braket", "ideal", 25, "braket_sv")]
    + [_row(f"ibm_{d}", f"IBM {d.capitalize()}", "local_sim", "ibm", "noise_model", q, cls, fam)
       for d, cls, q, fam in IBM_DEVICES]
    + [_row(f"ionq_sim_{m}", label, "remote_sim", "ionq", "noise_model", q, m, fam)
       for m, label, q, fam in (("aria-1", "IonQ Aria 1", 25, "Aria"), ("aria-2", "IonQ Aria 2", 25, "Aria"),
                                ("forte-1", "IonQ Forte 1", 29, "Forte"),
                                ("forte-enterprise-1", "IonQ Forte Enterprise 1", 29, "Forte"))]
    + [{**_row("ionq_sim_ideal", "IonQ ideal simulator", "remote_sim", "ionq", "ideal", 29, "ideal", "Forte"),
        "aliases": ["simulator", "ionq"]},
       {**_row("ionq_qpu_forte-1", "IonQ Forte 1", "hardware", "ionq", "hardware", 36, "qpu.forte-1", "Forte",
               "credits"), "aliases": ["qpu"]},
       _row("ionq_qpu_forte-enterprise-1", "IonQ Forte Enterprise 1", "hardware", "ionq", "hardware", 36,
            "qpu.forte-enterprise-1", "Forte", "credits")])
NEEDS_ENGINE = "Needs the compile engine, which isn't running on this server."


class SourceError(ValueError):
    pass


class UnknownBackend(KeyError):
    pass


@dataclass(frozen=True)
class Spec:
    id: str
    label: str
    group: str
    provider: str
    kind: str
    qubits: int
    device: str | None = None
    family: str | None = None
    raw: dict = field(default_factory=dict, compare=False)


@dataclass
class Compiled:
    report: dict
    payload: dict | None = None
    measure_map: dict = field(default_factory=dict)
    n_clbits: int = 0

    @property
    def ok(self) -> bool:
        return bool(self.report.get("ok"))


def _listing() -> tuple[list[dict], str | None]:
    try:
        return client.backends()["backends"], None
    except (EngineUnavailable, EngineRequestError) as e:
        rows = [dict(r) if r["provider"] in ("aer", "ionq") else {**r, "unavailable": NEEDS_ENGINE}
                for r in OFFLINE_CATALOG]
        return rows, str(e)


def _spec(d: dict) -> Spec:
    return Spec(id=d["id"], label=d["label"], group=d["group"], provider=d["provider"], kind=d["kind"],
                qubits=int(d["qubits"]), device=d.get("device"), family=d.get("family"), raw=d)


def get(backend_id: str) -> Spec:
    if backend_id == "aer":
        return _spec(BUILTIN)
    for d in _listing()[0]:
        if d["id"] == backend_id or backend_id in (d.get("aliases") or []):
            return _spec(d)
    raise UnknownBackend(f"Unknown backend {backend_id!r}. GET /backends lists them.")


def availability(spec: Spec, settings) -> str | None:
    if spec.id == "aer":
        return None
    if spec.raw.get("unavailable"):
        return spec.raw["unavailable"]
    if spec.provider == "ionq":
        if not settings.IONQ_API_KEY:
            return "IonQ isn't set up on this server (no API key)."
        if spec.group == "hardware" and str(settings.ALLOW_QPU_SUBMIT).lower() != "on":
            return "Real hardware is switched off on this server."
    return None


def listing(settings) -> dict:
    rows, engine_note = _listing()
    out = []
    for d in rows:
        spec = _spec(d)
        row = {**d, "group_label": GROUP_LABELS.get(d["group"], d["group"]),
               "unavailable": availability(spec, settings)}
        out.append(row)
    return {"groups": GROUP_LABELS, "backends": out, "engine": {"ok": engine_note is None, "detail": engine_note}}


def details(spec: Spec, settings) -> dict:
    out = dict(spec.raw)
    out["unavailable"] = availability(spec, settings)
    if spec.provider == "ibm" and out["unavailable"] is None:
        try:
            out["device"] = client.backend(spec.id).get("device")
        except (EngineUnavailable, EngineRequestError):
            pass
    return out


def _has_feed_forward(qc) -> bool:
    return any(i.operation.name in ("if_else", "while_loop", "for_loop", "switch_case") for i in qc.data)


def build_request(req: dict, spec: Spec, concept=None) -> tuple[dict, object]:
    from qiskit import qasm3
    if concept is None and req.get("concept_ir") is not None:
        from concepts import compile_document
        concept = compile_document(req["concept_ir"], backend="ionq" if spec.provider == "ionq" else None,
                                   with_qasm=False)
        if not concept.ok:
            raise SourceError("; ".join(e.message for e in concept.errors))
    body = {"backend": spec.id, "optimization_level": int(req.get("optimization_level", 1)),
            "gateset": req.get("gateset") or "qis", "seed": int(req.get("seed") or 1234),
            "shots": int(req.get("shots") or 1000)}
    if concept is not None:
        from concepts.emit_qiskit import build_circuit
        from concepts.ionq_lower import BackendUnsupported, rewritten_lowered
        qc = build_circuit(concept.lowered)
        body["code"] = concept.qiskit_py
        try:
            body["deferred_circuit"] = {"format": "qasm3", "source": qasm3.dumps(
                build_circuit(rewritten_lowered(concept.lowered)))}
        except BackendUnsupported as e:
            body["deferred_unavailable"] = str(e)
        if concept.ionq is not None:
            body["ionq_qis"] = concept.ionq
            body["ionq_rewritten"] = _has_feed_forward(qc)
    else:
        from safe_qiskit import UnsafeSource, build_circuit_from_source
        try:
            qc = build_circuit_from_source(req.get("qiskit_py") or "")
        except UnsafeSource as e:
            raise SourceError(f"Generated code could not be built safely: {e}") from e
        body["code"] = req.get("qiskit_py") or ""
        if spec.provider == "ionq":
            from ionq_runner import qiskit_source_to_ionq_circuit
            body["ionq_qis"] = qiskit_source_to_ionq_circuit(req["qiskit_py"], qc.num_qubits)
    body["circuit"] = {"format": "qasm3", "source": qasm3.dumps(qc)}
    return body, qc


def _arrived_intact(report: dict, qc) -> None:
    got = report.get("received") or {}
    want = {"num_qubits": qc.num_qubits, "num_clbits": qc.num_clbits,
            "count_ops": {k: int(v) for k, v in sorted(qc.count_ops().items())}}
    if got != want:
        report["ok"] = False
        report.setdefault("blocking", []).append(
            "The circuit the compile engine received doesn't match this one, so its result was not used. "
            "Please report this with the run record.")
        report.setdefault("checks", []).append({"check": "engine received this exact circuit", "ok": False,
                                                "detail": f"sent {want}, engine read {got}"})
    else:
        report.setdefault("checks", []).append({"check": "engine received this exact circuit", "ok": True,
                                                "detail": "qubits, classical bits and every gate count match"})


def _compiled(report: dict) -> Compiled:
    mm = {int(c): int(q) for c, q in (report.get("measure_map") or {}).items()}
    payload = report.get("submit_payload")
    return Compiled(report=report, payload=payload, measure_map=mm, n_clbits=int(report.get("n_clbits") or 0))


def compile_request(req: dict, backend_id: str, concept=None) -> Compiled:
    spec = get(backend_id)
    body, qc = build_request(req, spec, concept)
    report = client.compile(body)
    _arrived_intact(report, qc)
    return _compiled(report)


def offline_ionq(req: dict, spec: Spec, concept=None) -> Compiled:
    body, qc = build_request(req, spec, concept)
    qis = body.get("ionq_qis")
    if qis is None:
        raise SourceError(body.get("deferred_unavailable")
                          or "This circuit can't be written as IonQ gates (it reuses a qubit after measuring it).")
    mm = measure_map(qc)
    report = {"backend": {"id": spec.id, "label": spec.label, "provider": "ionq", "kind": spec.kind,
                          "qubits": spec.qubits, "family": spec.family},
              "ok": True, "blocking": [], "seed": body["seed"], "gateset": "qis", "optimization_level": None,
              "checks": [{"check": f"fits on {spec.label} ({spec.qubits} qubits)", "ok": qc.num_qubits <= spec.qubits,
                          "detail": f"your circuit uses {qc.num_qubits} qubits"}],
              "changes": [{"stage": "translation", "title": "Sent as IonQ QIS gates",
                           "detail": "IonQ compiles these to its native gates on its side. The full step-by-step "
                                     "change log needs the compile engine."},
                          {"stage": "measure", "title": "Every qubit is measured once, at the end",
                           "detail": "IonQ returns every qubit; QuantumCanvas maps them back onto your classical bits."}],
              "measure_map": {str(c): q for c, q in mm.items()}, "n_clbits": qc.num_clbits,
              "compiled": {"qubits": qis["qubits"], "size": len(qis["circuit"])}, "run_code": ""}
    if qc.num_qubits > spec.qubits:
        report["ok"] = False
        report["blocking"].append(f"{spec.label} has {spec.qubits} qubits; this circuit needs {qc.num_qubits}.")
    return Compiled(report=report, payload=qis, measure_map=mm, n_clbits=qc.num_clbits)


def run_request(req: dict, backend_id: str, concept=None) -> tuple[Compiled, dict | None]:
    spec = get(backend_id)
    body, qc = build_request(req, spec, concept)
    out = client.run(body)
    _arrived_intact(out["report"], qc)
    compiled = _compiled(out["report"])
    return compiled, (out.get("result") if compiled.ok else None)


def measure_map(qc) -> dict:
    return {qc.find_bit(i.clbits[0]).index: qc.find_bit(i.qubits[0]).index
            for i in qc.data if i.operation.name == "measure"}


def remap_qubit_counts(counts: dict, n_qubits: int, mmap: dict, n_clbits: int) -> dict:
    out: dict[str, int] = {}
    for key, v in counts.items():
        bits = str(key).replace(" ", "").zfill(n_qubits)
        k = "".join(bits[n_qubits - 1 - mmap[c]] if c in mmap else "0" for c in reversed(range(n_clbits)))
        out[k] = out.get(k, 0) + int(v)
    return out
