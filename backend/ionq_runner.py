import time
import re
from dataclasses import dataclass
from typing import Optional
import requests

from logger import ArtifactLogger


@dataclass
class JobStatus:
    job_id:       str
    status:       str
    counts:       Optional[dict] = None
    raw_response: Optional[dict] = None

    @property
    def is_terminal(self) -> bool:
        return self.status in ("completed", "failed", "canceled", "cancelled")


def qiskit_source_to_ionq_circuit(qiskit_code: str, n_qubits: int) -> dict:
    gates = []

    code_lines = [
        l.split('#')[0].strip()
        for l in qiskit_code.split('\n')
        if l.strip() and not l.strip().startswith('#')
    ]

    for line in code_lines:
        m = re.match(r'qc\.h\((\[[\d,\s]+\]|\d+)\)', line)
        if m:
            for t in _parse_targets(m.group(1)):
                gates.append({"gate": "h", "target": t})
            continue

        m = re.match(r'qc\.x\((\[[\d,\s]+\]|\d+)\)', line)
        if m:
            for t in _parse_targets(m.group(1)):
                gates.append({"gate": "x", "target": t})
            continue

        m = re.match(r'qc\.z\((\[[\d,\s]+\]|\d+)\)', line)
        if m:
            for t in _parse_targets(m.group(1)):
                gates.append({"gate": "z", "target": t})
            continue

        m = re.match(r'qc\.cx\((\d+),\s*(\d+)\)', line)
        if m:
            gates.append({"gate": "cnot", "control": int(m.group(1)), "target": int(m.group(2))})
            continue

        m = re.match(r'qc\.cz\((\d+),\s*(\d+)\)', line)
        if m:
            ctrl, tgt = int(m.group(1)), int(m.group(2))
            gates.append({"gate": "h",    "target": tgt})
            gates.append({"gate": "cnot", "control": ctrl, "target": tgt})
            gates.append({"gate": "h",    "target": tgt})
            continue

        m = re.match(r'qc\.ccx\((\d+),\s*(\d+),\s*(\d+)\)', line)
        if m:
            a, b, c = int(m.group(1)), int(m.group(2)), int(m.group(3))
            gates.extend(_toffoli(a, b, c))
            continue

        m = re.match(r'qc\.mcx\(\[([\d,\s]+)\],\s*(\d+)\)', line)
        if m:
            controls = [int(x) for x in m.group(1).split(',') if x.strip()]
            target = int(m.group(2))
            gates.append({"gate": "mcx", "target": target, "controls": controls})
            continue


    return {"gateset": "qis", "qubits": n_qubits, "circuit": gates}


def _parse_targets(s: str) -> list:
    s = s.strip()
    if s.startswith('['):
        return [int(x) for x in s.strip('[]').split(',') if x.strip()]
    return [int(s)]


def _toffoli(a: int, b: int, c: int) -> list:
    return [
        {"gate": "h",    "target": c},
        {"gate": "cnot", "control": b, "target": c},
        {"gate": "ti",   "target": c},
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


class IonQRunner:
    JOBS_URL   = "/v0.4/jobs"
    STATUS_URL = "/v0.4/jobs/{job_id}"
    COST_URL   = "/v0.4/jobs/{job_id}/cost"

    def __init__(self, api_key: str, endpoint: str, logger: ArtifactLogger):
        self.api_key  = api_key
        self.endpoint = endpoint.rstrip('/')
        self.logger   = logger
        self.last_submit = None
        self.last_status = None
        self.session  = requests.Session()
        self.session.headers.update({
            "Authorization": f"apiKey {self.api_key}",
            "Content-Type":  "application/json",
        })

    def _n_qubits(self, qiskit_code: str) -> int:
        m = re.search(r'QuantumCircuit\((\d+)', qiskit_code)
        return int(m.group(1)) if m else 2

    def _circuit_for(self, qiskit_code: str, ionq_circuit: dict | None) -> dict:
        if ionq_circuit is not None:
            return ionq_circuit
        return qiskit_source_to_ionq_circuit(qiskit_code, self._n_qubits(qiskit_code))

    def _submit_job(self, ionq_input: dict, shots: int, backend: str,
                    name: str, dry_run: bool = False, noise: dict | None = None) -> str:
        label = name.replace('qc-', '')
        payload = {
            "type":    "ionq.circuit.v1",
            "backend": backend,
            "shots":   shots,
            "name":    name,
            "input":   ionq_input,
        }
        if dry_run:
            payload["dry_run"] = True
        if noise:
            payload["noise"] = noise

        self.logger.save(f"ionq_request_{label}.json", payload)
        self.logger.log(f"Submitting to IonQ backend={backend} shots={shots} dry_run={dry_run}")

        resp = self.session.post(self.endpoint + self.JOBS_URL, json=payload, timeout=30)
        if not resp.ok:
            body = resp.text
            self.logger.error(f"IonQ submit failed {resp.status_code}: {body}")
            self.logger.save(f"ionq_error_{label}.json", {"status": resp.status_code, "body": body})
            raise RuntimeError(f"IonQ {resp.status_code}: {body}")

        data = resp.json()
        self.last_submit = {"http_status": resp.status_code, "response": data}
        self.logger.save(f"ionq_response_{label}.json", data)
        self.logger.log(f"IonQ submitted job_id={data.get('id')} status={data.get('status')}")
        return data["id"]

    def run_simulator(self, qiskit_code: str, shots: int, ionq_circuit: dict | None = None) -> dict:
        circuit = self._circuit_for(qiskit_code, ionq_circuit)
        job_id  = self._submit_job(circuit, shots, "simulator", "qc-simulator")

        for attempt in range(90):
            time.sleep(2)
            status = self.get_job_status(job_id, backend_label="simulator")
            self.logger.log(f"Poll {attempt+1}: job={job_id} status={status.status}")
            if status.status in ("failed", "canceled", "cancelled"):
                raise RuntimeError(f"IonQ job {status.status}")
            if status.status == "completed":
                return status.counts or {}
        raise TimeoutError(f"Simulator job {job_id} did not complete in time")

    def submit_ionq_sim(self, qiskit_code: str, shots: int, ionq_circuit: dict | None = None) -> str:
        circuit = self._circuit_for(qiskit_code, ionq_circuit)
        return self._submit_job(circuit, shots, "simulator", "qc-ionq-sim")

    def submit_hardware(self, qiskit_code: str, shots: int) -> str:
        return self.submit_ionq_sim(qiskit_code, shots)

    def submit_qpu(self, qiskit_code: str, shots: int, ionq_circuit: dict | None = None) -> str:
        circuit = self._circuit_for(qiskit_code, ionq_circuit)
        return self._submit_job(circuit, shots, "qpu.forte-1", "qc-qpu")

    def submit_target(self, ionq_input: dict, shots: int, backend: str, label: str,
                      noise_model: str | None = None, seed: int | None = None) -> str:
        noise = None
        if backend == "simulator" and noise_model and noise_model != "ideal":
            noise = {"model": noise_model}
            if seed is not None:
                noise["seed"] = max(1, int(seed) % (2 ** 31))
        return self._submit_job(ionq_input, shots, backend, f"qc-{label}", noise=noise)

    def estimate_cost(self, qiskit_code: str, shots: int, ionq_circuit: dict | None = None,
                      backend: str = "qpu.forte-1") -> dict:
        circuit = self._circuit_for(qiskit_code, ionq_circuit)
        job_id  = self._submit_job(circuit, shots, backend, "qc-cost-estimate", dry_run=True)

        data = {}
        for _ in range(30):
            time.sleep(1)
            r = self.session.get(self.endpoint + self.STATUS_URL.format(job_id=job_id), timeout=15)
            r.raise_for_status()
            data = r.json()
            if data.get("status") in ("completed", "failed", "canceled", "cancelled"):
                break
        self.logger.save("ionq_cost_response.json", data)

        cost_usd = None
        try:
            cr = self.session.get(self.endpoint + self.COST_URL.format(job_id=job_id), timeout=15)
            if cr.ok:
                ec = (cr.json() or {}).get("estimated_cost") or {}
                cost_usd = ec.get("value")
            else:
                self.logger.error(f"Cost endpoint {cr.status_code}: {cr.text}")
        except Exception as e:
            self.logger.error(f"Cost fetch failed: {e}")

        stats = data.get("stats") or {}
        self.logger.log(f"Estimate: cost_usd={cost_usd} status={data.get('status')}")
        return {
            "cost_usd":    cost_usd,
            "queue_days":  340,
            "target":      data.get("backend", backend),
            "gate_counts": stats.get("gate_counts"),
        }

    def get_job_status(self, job_id: str, backend_label: str = "", shots: int | None = None) -> JobStatus:
        resp = self.session.get(self.endpoint + self.STATUS_URL.format(job_id=job_id), timeout=15)
        resp.raise_for_status()
        data   = resp.json()
        self.last_status = data
        status = data.get("status", "unknown")
        self.logger.log(f"IonQ job {job_id} status={status}")

        counts = None
        if status == "completed":
            counts = self._extract_counts(data, data.get("shots") or shots or 1000, backend_label)

        return JobStatus(job_id=job_id, status=status, counts=counts, raw_response=data)

    def _extract_counts(self, data: dict, shots: int, backend_label: str = "") -> dict:
        results  = data.get("results") or {}
        stats    = data.get("stats") or {}
        n_qubits = stats.get("qubits") or data.get("qubits") or 2

        prob = results.get("probabilities")
        url  = prob.get("url") if isinstance(prob, dict) else None
        if not url:
            self.logger.error(f"No probabilities url in results: {results}")
            return {}

        full = self.endpoint + url if url.startswith("/") else url
        try:
            resp = self.session.get(full, timeout=15)
            resp.raise_for_status()
            payload = resp.json()
            suffix = f"_{backend_label}" if backend_label else ""
            self.logger.save(f"ionq_results_raw{suffix}.json", payload)
        except Exception as e:
            self.logger.error(f"Failed to fetch probabilities: {e}")
            return {}

        probs = payload.get("probabilities", payload) if isinstance(payload, dict) else {}
        if isinstance(probs, dict) and "registers" in probs:
            merged = {}
            for reg in probs["registers"].values():
                if isinstance(reg, dict):
                    for st, p in reg.items():
                        merged[st] = merged.get(st, 0.0) + float(p)
            probs = merged

        state_probs = {}
        for state, p in (probs or {}).items():
            try:
                bits = format(int(str(state), 0), f"0{int(n_qubits)}b")
            except (ValueError, TypeError):
                bits = str(state)
            try:
                state_probs[bits] = state_probs.get(bits, 0.0) + float(p)
            except (ValueError, TypeError):
                continue

        counts = _probs_to_counts(state_probs, shots)
        self.logger.log(f"Counts extracted: {counts}")
        return counts


def _probs_to_counts(state_probs: dict, shots: int) -> dict:
    if not state_probs or shots <= 0:
        return {}
    raw    = {s: p * shots for s, p in state_probs.items()}
    counts = {s: int(v) for s, v in raw.items()}
    remainder = shots - sum(counts.values())
    if remainder > 0:
        for s in sorted(raw, key=lambda s: raw[s] - counts[s], reverse=True)[:remainder]:
            counts[s] += 1
    return {s: c for s, c in counts.items() if c > 0}
