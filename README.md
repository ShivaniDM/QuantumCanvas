# QuantumCanvas 
Link to website : https://blue-sea-0f9bdf510.7.azurestaticapps.net/
Canvas → Pseudocode → Qiskit → IonQ


## What it does

Build a quantum circuit from **concepts** (named groups of gates such as Superposition, Entangle, Oracle and Amplitude amplification) or from individual gates, and see exactly what it becomes: the gates inside every concept, the Qiskit, OpenQASM 3 and pseudocode for the circuit, the state after every step, and a run on a simulator or IonQ with the result checked against an exact prediction.

- **Build** — palette (Concepts | Gates), qubit wires `q0, q1…`, double-click a block to see its gates, undo/redo. The panel under the wires has tabs **Qiskit | OpenQASM 3 | Pseudocode | Math**. Qiskit and OpenQASM are editable and the canvas follows; code you don't change keeps its concept blocks. Errors are shown with their line numbers, with optional AI help whose suggested code is checked before it can be used.
- **Bring code** — paste or upload Qiskit or OpenQASM 2/3. The code is read, never executed. Every gate is kept exactly, unsupported lines are reported by line number, and familiar patterns are offered as concepts, each verified to be the same operation.
- **Run and explain** — the built-in Qiskit Aer simulator and IonQ cloud simulators (ideal, or with Forte and Aria device noise models) when an IonQ key is configured. A circuit needs a Measure step to run; without one, Results shows the probabilities calculated from the final state. Every step is checked by exact simulation; the explanation is generated from those checks, and an optional AI explanation is thrown away if it contradicts them.
- **Practice problems** — 14 problems on the home page, checked automatically.
- **My runs** — run history in the browser, with share links for runs stored on the server.

## Project structure

```
quantumcanvas/
├── frontend/                 Static site, no build step
│   ├── index.html            App shell
│   ├── css/app.css           Styles (light and dark)
│   └── js/app/               Router, Build, code panel, Bring code, runs, help
├── backend/                  FastAPI service
│   ├── app.py                HTTP API
│   ├── concepts/             Concept IR: schema, validation, lowering to gates, Qiskit / OpenQASM 3 / IonQ output
│   ├── mathlayer/            Exact simulation, per-step facts and checks, notation
│   ├── explain/              Template and AI explanations, claim checking, AI code help
│   ├── codeimport/           Qiskit / OpenQASM import and concept suggestions
│   ├── engine_bridge/        Backend catalog (simulators offered) and IonQ request building
│   ├── problems/             Practice problems and checker
│   ├── runlog/               Versioned run records, redaction, replay
│   └── tests/                pytest suite (python -m pytest -q from backend/)
├── logs/runs/                One folder per unique circuit, keyed by circuit hash (see Logging)
└── .env.example              Copy to backend/.env and fill in what you need
```

## Setup

### 1. Copy and fill `.env`

```bash
cp .env.example backend/.env
# Everything is optional: IonQ key and AI provider. Without them the built-in simulator still works.
```

### 2. Install backend dependencies

```bash
cd backend
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Start the backend

```bash
python -m uvicorn app:app --port 8000
# Starts on http://localhost:8000
# Check: http://localhost:8000/health
```

### 4. Open the frontend

Serve the static frontend (no build step):

```bash
cd frontend
python -m http.server 5500
# Open http://localhost:5500
```

## Execution pipeline

```
Concepts or gates on the canvas  (or edited / imported Qiskit and OpenQASM)
  ↓ POST /compile — validate, lower to gates, emit Qiskit, OpenQASM 3 and pseudocode, check every step
Run ▶  (choose a backend)
  ↓ POST /execute — API keys stay server-side; only simulators are offered
Simulator or IonQ
  ↓
Counts compared with the exact prediction, run record saved to logs/runs/
  ↓
Results and explanation in Build, history in My runs
```

## Logging

Logs used to live only on Azure's ephemeral disk (lost on redeploy, not
shareable). They are now **version-controlled in this repo** under `logs/runs/`.

**One folder per unique circuit**, not per execution — the folder name is a
hash of the circuit's IR, so running Aer and then IonQ Sim against the exact
same circuit lands both results in the same folder, and editing the canvas
afterward always creates a *new* folder rather than overwriting the old one.

Two ways a circuit ends up logged:
1. **Running any backend** — saves the circuit, then adds that backend's results
   and a versioned run record (`runrecord_<id>.vN.json`).
2. **POST /log-circuit** — an explicit snapshot without running.

No login, no username-based sharing step — it's just what the backend does.
To get a run into GitHub: run the backend from your own clone (so `logs/runs/`
lands inside your working copy), then `git add logs/ && git commit && git push`
as usual. See `logs/README.md` for the full layout.

Each run also keeps a copy in your browser (My runs), with a share link when the server stored the run.

## Log artifacts

Every circuit's folder accumulates:

| File | Contents |
|------|----------|
| `canvas.json` | Raw canvas state |
| `ir.json` | Internal Representation (validated) |
| `pseudocode.txt` | Human-readable pseudocode steps |
| `qiskit.py` | Generated Qiskit Python code |
| `results_aer.json` / `results_ionq.json` / `results_qpu.json` | Shot count histogram, per backend run |
| `ionq_request_*.json` / `ionq_response_*.json` | Payload sent to / raw response from IonQ, per backend |
| `metadata.json` | Circuit hash, git commit, and one entry per backend that ran |
| `runrecord_<id>.vN.json` | Full run record: input, compiled gates, seed, backend, counts, checks, explanation (secrets redacted) |
| `execution.log` | Timestamped run log |
| `errors.log` | Errors only |

## IonQ backend notes

QuantumCanvas offers IonQ's cloud simulator only:

| Option | What it runs |
|--------|--------------|
| IonQ simulator · ideal | No noise. IonQ returns exact probabilities, shown as counts for the chosen number of shots |
| IonQ simulator · Forte 1 / Forte Enterprise 1 noise model | Each shot simulated with that device's noise |
| IonQ simulator · Aria 1 / Aria 2 noise model | Noise models of retired devices |

Each run record stores the noise model IonQ reports it used, and the run is flagged if that differs from the one requested.

## Acknowledgements
This effort is supported via compute credits from Qollab and IonQ.

## License
Released under the MIT License. See [LICENSE](LICENSE) for details.
