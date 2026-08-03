# QuantumCanvas 
Link to website : https://blue-sea-0f9bdf510.7.azurestaticapps.net/
Canvas → Pseudocode → Qiskit → IonQ


## Project structure

```
quantumcanvas/
├── frontend/
│   ├── index.html          # Canvas + all UI
│   ├── css/
│   │   ├── main.css        # Layout, canvas, toolbar, nodes
│   │   └── pseudocode.css  # Pseudocode panel, Qiskit panel, Execute panel
│   └── js/
│       ├── state.js         # Canvas state, primitives, rendering
│       ├── ir.js            # IR extractor + validator
│       ├── pseudocode.js    # Pseudocode generator
│       ├── ui.js            # Pseudocode panel renderer
│       ├── qiskit-generator.js  # Qiskit code generator
│       ├── qiskit-panel.js      # Qiskit panel renderer
│       └── execute.js           # Execute panel (calls backend)
│
├── backend/
│   ├── app.py              # FastAPI server (POST /log-circuit, /execute, /cost, GET /job/{id})
│   ├── config.py           # Settings from .env
│   ├── ionq_runner.py      # IonQ API client + circuit translator
│   ├── logger.py           # Artifact logger (circuit-hash-keyed folders)
│   └── requirements.txt
│
├── logs/
│   └── runs/               # One folder per unique circuit, keyed by IR hash
│       └── <circuit_hash>/
│           ├── canvas.json
│           ├── ir.json
│           ├── pseudocode.txt
│           ├── qiskit.py
│           ├── results_aer.json      # only if you ran Aer
│           ├── results_ionq.json     # only if you ran IonQ Sim
│           ├── results_qpu.json      # only if you ran IonQ Hardware
│           ├── metadata.json         # one entry per backend that ran
│           ├── execution.log
│           └── errors.log
│
├── .env.example            # Copy to .env and fill in keys
├── .gitignore              # .env and logs/ are ignored
└── README.md
```

## Setup

### 1. Copy and fill `.env`

```bash
cp .env.example .env
# Edit .env and set IONQ_API_KEY
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
python app.py
# Starts on http://localhost:8000
# Check: http://localhost:8000/health
```

### 4. Open the frontend

Open `frontend/index.html` in a browser directly (no build step needed).

For local CORS to work, serve via a simple HTTP server:

```bash
cd frontend
python -m http.server 3000
# Open http://localhost:3000
```

## Execution pipeline

```
Canvas
  ↓ (user builds circuit)
{ } Pseudocode
  ↓ (review + approve)
Generate Qiskit ▶
  ↓ (see generated Python)
Execute ⚡
  ↓ (choose Simulator or IonQ)
Backend POST /execute
  ↓ (API key stays server-side)
IonQ API
  ↓
Results saved to logs/runs/
  ↓
Displayed in Execute panel
```

## Logging

Logs used to live only on Azure's ephemeral disk (lost on redeploy, not
shareable). They are now **version-controlled in this repo** under `logs/runs/`.

**One folder per unique circuit**, not per execution — the folder name is a
hash of the circuit's IR, so running Aer and then IonQ Sim against the exact
same circuit lands both results in the same folder, and editing the canvas
afterward always creates a *new* folder rather than overwriting the old one.

Two ways a circuit ends up logged:
1. **💾 Save current state** (in the Execute panel) — an explicit snapshot,
   on your own timing, before running anything.
2. **Running any backend** — auto-saves the circuit first if step 1 hasn't
   happened yet, then adds that backend's results.

No login, no username-based sharing step — it's just what the backend does.
To get a run into GitHub: run the backend from your own clone (so `logs/runs/`
lands inside your working copy), then `git add logs/ && git commit && git push`
as usual. See `logs/README.md` for the full layout.

Separately, the Execute panel also offers two options for keeping a **personal**
copy of a completed run — unrelated to the shared `logs/runs/` folder above:

| Option | Where it goes | Needs backend? |
|--------|---------------|----------------|
| **A — Browser storage** | `localStorage` in your browser | No |
| **B — Download file** | Your file manager (a `.json` bundle) | No |

See `frontend/js/user-logger.js` for that, and `frontend/js/execute.js` for
the "Save current state" mechanism.

## Security

- `IONQ_API_KEY` lives only in `.env` on the server
- The frontend never sees the key — it only posts circuit data to `/execute`
- `.env` is in `.gitignore`
- `logs/` is version-controlled; only transient `execution.log` / `errors.log`
  debug files are git-ignored

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
| `execution.log` | Timestamped run log |
| `errors.log` | Errors only |

## IonQ backend notes

| Backend | Status |
|---------|--------|
| `simulator` | Available — 29 qubits, forte-1 noise model |
| `qpu.forte-1` | Queue ~340 days |
| `qpu.aria-1/2` | Retired |

Use `simulator` for all development and QA.

## Acknowledgements
This effort is supported via compute credits from Qollab and IonQ.

## License
Released under the MIT License. See [LICENSE](LICENSE) for details.
