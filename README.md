# QuantumCanvas 

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
│   ├── app.py              # FastAPI server (POST /execute, GET /job/{id})
│   ├── config.py           # Settings from .env
│   ├── ionq_runner.py      # IonQ API client + circuit translator
│   ├── logger.py           # Artifact logger (saves per-run folders)
│   └── requirements.txt
│
├── logs/                   # Auto-created. Every run saved here.
│   └── 2026-06-16_22-41_SIMULATOR/
│       ├── canvas.json
│       ├── ir.json
│       ├── pseudocode.txt
│       ├── qiskit.py
│       ├── ionq_request.json
│       ├── ionq_response.json
│       ├── results.json
│       ├── execution.log
│       └── errors.log
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
Results saved to logs/
  ↓
Displayed in Execute panel
```

## Security

- `IONQ_API_KEY` lives only in `.env` on the server
- The frontend never sees the key — it only posts circuit data to `/execute`
- `.env` is in `.gitignore`
- `logs/` is in `.gitignore` (may contain circuit data)

## Log artifacts

Every run saves:

| File | Contents |
|------|----------|
| `canvas.json` | Raw canvas state at time of execution |
| `ir.json` | Internal Representation (validated) |
| `pseudocode.txt` | Human-readable pseudocode steps |
| `qiskit.py` | Generated Qiskit Python code |
| `ionq_request.json` | Exact payload sent to IonQ API |
| `ionq_response.json` | Raw IonQ API response |
| `results.json` | Shot count histogram |
| `execution.log` | Timestamped run log |
| `errors.log` | Errors only |

## IonQ backend notes

| Backend | Status |
|---------|--------|
| `simulator` | Available — 29 qubits, forte-1 noise model |
| `qpu.forte-1` | Queue ~340 days |
| `qpu.aria-1/2` | Retired |

Use `simulator` for all development and QA.
