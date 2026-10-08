# QuantumCanvas — Logs

Run artifacts used to live only on the Azure Web App's ephemeral disk, so they
vanished on every redeploy and could not be shared. They now live **here, in the
git repo**, so every run is version-controlled, diff-able, and shareable via a
normal `git push`.

## Layout

Every unique circuit gets **one folder**, keyed by a stable hash of its IR —
not a timestamp. Saving the same circuit again, or running a different backend
against it, reuses that same folder instead of scattering results across new
ones each time:

```
logs/
├── README.md
└── runs/
    └── <circuit_hash>/
        ├── canvas.json           # raw canvas state
        ├── ir.json               # validated Internal Representation
        ├── pseudocode.txt        # human-readable pseudocode
        ├── qiskit.py             # generated Qiskit program
        ├── results_aer.json      # only if you ran Aer
        ├── results_ionq.json     # only if you ran IonQ Sim
        ├── results_qpu.json      # only if you ran IonQ Hardware
        ├── metadata.json         # accumulates one entry per backend that ran
        ├── circuit_hash.txt
        ├── execution.log
        └── errors.log
```

`<circuit_hash>` is a 12-character prefix of the SHA-256 hash of the circuit's
canonical IR. Same circuit content → same hash → same folder, always. Change
anything on the canvas and it becomes a *different* circuit with its own
folder — your earlier save is never touched or overwritten.

## How a circuit gets logged here

There's no login and no username-based sharing step — logging to this folder
is just something the backend does automatically:

1. **"💾 Save current state"** (in the Execute panel) — an explicit snapshot
   of the circuit's IR/pseudocode/Qiskit, on your own timing, independent of
   running anything. Calling it again with no changes is a no-op (nothing new
   to write).
2. **Running any backend** (Aer / IonQ Sim / IonQ Hardware) auto-saves the
   circuit state first if step 1 hasn't happened yet, then adds that
   backend's results into the same folder.

Because the folder name comes from the circuit's own content, running Aer and
then IonQ Sim against the identical circuit lands both results in the same
place — never in two disconnected folders.

To get a run into GitHub: run the backend from your own clone (so
`logs/runs/` lands inside your working copy), then the usual:
```bash
git add logs/
git commit -m "Add run <circuit_hash>"
git push
```

## Keeping a personal copy (unrelated to the above)

The Execute panel also offers two options for keeping your *own* copy of a
completed run, independent of the shared `logs/runs/` folder above:

| Option | Where it goes | Needs backend? |
|--------|---------------|----------------|
| **A — Browser storage** | `localStorage` in your browser | No |
| **B — Download file** | Your file manager (a `.json` bundle) | No |

See `frontend/js/user-logger.js` for that implementation, and
`frontend/js/execute.js` for the "Save current state" / auto-save-before-run
mechanism.
