"""
QuantumCanvas — IonQ Runner
Handles all IonQ API communication.
API key is read from config (env var), never from the request.

IonQ circuit format: ionq.circuit.v0
  - Converts Qiskit-generated gate list to IonQ JSON circuit
  - Submits to simulator (instant) or hardware (async, poll for result)
"""

import json
import time
import re
from dataclasses import dataclass, field
from typing import Optional
import requests

from logger import ArtifactLogger


# ── Data classes ──────────────────────────────────────────────────────

@dataclass
class JobStatus:
    job_id:       str
    status:       str          # submitted | running | completed | failed | canceled | ready
    counts:       Optional[dict] = None
    raw_response: Optional[dict] = None

    @property
    def is_terminal(self) -> bool:
        return self.status in ("completed", "ready", "failed", "canceled")


# ── Gate translation: Qiskit Python source → IonQ circuit JSON ────────

def qiskit_source_to_ionq_circuit(qiskit_code: str, n_qubits: int) -> dict:
    """
    Parse the generated Qiskit Python source and produce an IonQ circuit dict.
    This is a pattern-match translator — it handles exactly the gates
    QuantumCanvas generates: h, x, z, cx, cz, ccx, measure.
    """
    gates = []

    # Strip comments and blank lines
    code_lines = [
        l.split('#')[0].strip()
        for l in qiskit_code.split('\n')
        if l.strip() and not l.strip().startswith('#')
    ]

    for line in code_lines:
        # qc.h(0)  or  qc.h([0,1])
        m = re.match(r'qc\.h\((\[[\d,\s]+\]|\d+)\)', line)
        if m:
            targets = _parse_targets(m.group(1))
            for t in targets:
                gates.append({"gate": "h", "target": t})
            continue

        # qc.x(0)
        m = re.match(r'qc\.x\((\[[\d,\s]+\]|\d+)\)', line)
        if m:
            targets = _parse_targets(m.group(1))
            for t in targets:
                gates.append({"gate": "x", "target": t})
            continue

        # qc.z(0)
        m = re.match(r'qc\.z\((\[[\d,\s]+\]|\d+)\)', line)
        if m:
            targets = _parse_targets(m.group(1))
            for t in targets:
                gates.append({"gate": "z", "target": t})
            continue

        # qc.cx(ctrl, tgt)
        m = re.match(r'qc\.cx\((\d+),\s*(\d+)\)', line)
        if m:
            gates.append({"gate": "cnot", "control": int(m.group(1)), "target": int(m.group(2))})
            continue

        # qc.cz(0, 1)
        m = re.match(r'qc\.cz\((\d+),\s*(\d+)\)', line)
        if m:
            # IonQ doesn't have native CZ — decompose: H target, CNOT, H target
            ctrl, tgt = int(m.group(1)), int(m.group(2))
            gates.append({"gate": "h",    "target": tgt})
            gates.append({"gate": "cnot", "control": ctrl, "target": tgt})
            gates.append({"gate": "h",    "target": tgt})
            continue

        # qc.ccx(a, b, c)  — Toffoli: decompose into IonQ native gates
        m = re.match(r'qc\.ccx\((\d+),\s*(\d+),\s*(\d+)\)', line)
        if m:
            a, b, c = int(m.group(1)), int(m.group(2)), int(m.group(3))
            # Standard Toffoli decomposition using H, CNOT, T, Tdg
            gates.extend(_toffoli(a, b, c))
            continue

        # qc.measure(q, c) — IonQ measures all at end; skip individual measure calls
        # Measurement is implicit in IonQ shots

    return {
        "format":  "ionq.circuit.v0",
        "qubits":  n_qubits,
        "circuit": gates,
    }


def _parse_targets(s: str) -> list[int]:
    """Parse '0' or '[0, 1]' into a list of ints."""
    s = s.strip()
    if s.startswith('['):
        return [int(x) for x in s.strip('[]').split(',') if x.strip()]
    return [int(s)]


def _toffoli(a: int, b: int, c: int) -> list[dict]:
    """Decompose CCX(a,b,c) into H, CNOT, T, Tdg gates for IonQ."""
    # Standard Toffoli decomposition (Nielsen & Chuang)
    return [
        {"gate": "h",    "target": c},
        {"gate": "cnot", "control": b, "target": c},
        {"gate": "ti",   "target": c},          # Tdg
        {"gate": "cnot", "control": a, "target": c},
        {"gate": "t",    "target": c},
        {"gate": "cnot", "control": b, "target": c},
        {"gate": "ti",   "target": c},
        {"gate": "cnot", "control": a, "target": c},
        {"gate": "t",    "target": b},
        {"gate": "t",    "target": c},
        {"gate": "h",    "target": c},
        {"gate": "cnot", "control": a, "target": b},
        {"gate": "t",    "target": a},
        {"gate": "ti",   "target": b},
        {"gate": "cnot", "control": a, "target": b},
    ]


# ── Runner ────────────────────────────────────────────────────────────

class IonQRunner:
    JOBS_URL    = "/v0.3/jobs"
    STATUS_URL  = "/v0.3/jobs/{job_id}"
    RESULTS_URL = "/v0.3/jobs/{job_id}/results"   # separate endpoint for counts

    def __init__(self, api_key: str, endpoint: str, logger: ArtifactLogger):
        self.api_key  = api_key
        self.endpoint = endpoint.rstrip('/')
        self.logger   = logger
        self.session  = requests.Session()
        self.session.headers.update({
            "Authorization": f"apiKey {self.api_key}",
            "Content-Type":  "application/json",
        })

    def _n_qubits(self, qiskit_code: str) -> int:
        """Extract qubit count from QuantumCircuit(n, n) line."""
        m = re.search(r'QuantumCircuit\((\d+)', qiskit_code)
        return int(m.group(1)) if m else 2

    def _submit_job(self, circuit: dict, shots: int, backend: str, name: str) -> str:
        """Submit a circuit to IonQ and return the job_id."""
        payload = {
            "input":   circuit,
            "shots":   shots,
            "backend": backend,
            "name":    name,
        }
        self.logger.save("ionq_request.json", payload)
        self.logger.log(f"Submitting to IonQ backend={backend} shots={shots}")

        resp = self.session.post(
            self.endpoint + self.JOBS_URL,
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self.logger.log(f"IonQ response: job_id={data.get('id')} status={data.get('status')}")
        return data["id"]

    def run_simulator(self, qiskit_code: str, shots: int) -> dict:
        """
        Submit to IonQ cloud simulator, poll until done, return counts dict.
        The IonQ simulator is fast — usually returns in < 10 seconds.
        """
        n       = self._n_qubits(qiskit_code)
        circuit = qiskit_source_to_ionq_circuit(qiskit_code, n)
        job_id  = self._submit_job(circuit, shots, "simulator", "qc-simulator")

        # Poll until terminal
        for attempt in range(60):
            time.sleep(2)
            status = self.get_job_status(job_id)
            self.logger.log(f"Poll {attempt+1}: job={job_id} status={status.status}")
            if status.is_terminal:
                if status.counts:
                    return status.counts
                raise RuntimeError(f"Job failed: {status.status}")

        raise TimeoutError(f"Simulator job {job_id} did not complete in 120s")

    def submit_hardware(self, qiskit_code: str, shots: int) -> str:
        """Submit to IonQ simulator (async). Returns job_id for polling.
        NOTE: Using 'simulator' backend — NOT qpu.forte-1 (costs $168/run + 340 day queue).
        Change backend to 'qpu.forte-1' only when QPU access is confirmed.
        """
        n       = self._n_qubits(qiskit_code)
        circuit = qiskit_source_to_ionq_circuit(qiskit_code, n)
        return self._submit_job(circuit, shots, "simulator", "qc-ionq-sim")

    def get_job_status(self, job_id: str) -> JobStatus:
        """Poll a job and return its current status + counts if ready."""
        resp = self.session.get(
            self.endpoint + self.STATUS_URL.format(job_id=job_id),
            timeout=15,
        )
        resp.raise_for_status()
        data   = resp.json()
        self.logger.log(f"IonQ job response: {data}")

        # IonQ status values: submitted | ready | running | completed | failed | canceled
        # Both 'ready' and 'completed' mean results are available
        status = data.get("status", "unknown")

        counts = None
        if status in ("completed", "ready"):
            shots  = data.get("shots", 1000)
            counts = self._extract_counts(data, shots)

        return JobStatus(
            job_id       = job_id,
            status       = status,
            counts       = counts,
            raw_response = data,
        )

    def _extract_counts(self, data: dict, shots: int) -> dict:
        """
        Fetch results from the dedicated /results endpoint.
        IonQ v0.3: job body has metadata only; counts are at /v0.3/jobs/{id}/results
        Response: {"histogram": {"0": 0.5, "3": 0.5}} (integer state keys, probabilities)
        """
        job_id = data.get("id", "")
        n_qubits = data.get("qubits", 2)

        try:
            resp = self.session.get(
                self.endpoint + self.RESULTS_URL.format(job_id=job_id),
                timeout=15,
            )
            resp.raise_for_status()
            results = resp.json()
            self.logger.log(f"Results response: {results}")

            # IonQ returns histogram with integer keys as strings
            # e.g. {"histogram": {"0": 0.5, "3": 0.5}}
            histogram = results.get("histogram", {})
            if histogram:
                counts = {}
                for int_state, prob in histogram.items():
                    # Convert integer state to binary bitstring
                    # e.g. "3" with 2 qubits → "11"
                    bitstring = format(int(int_state), f"0{n_qubits}b")
                    counts[bitstring] = round(float(prob) * shots)
                self.logger.log(f"Counts extracted: {counts}")
                return counts

            # Fallback: try direct probabilities dict
            if isinstance(results, dict) and results:
                counts = {str(k): round(float(v) * shots)
                          for k, v in results.items()
                          if k != "histogram"}
                if counts:
                    self.logger.log(f"Counts from flat results: {counts}")
                    return counts

        except Exception as e:
            self.logger.error(f"Failed to fetch results for {job_id}: {e}")

        return {}
        return counts