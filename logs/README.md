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

1. **Running any backend** (built-in simulator, noise models, IonQ) saves the
   circuit state, then adds that backend's results and a versioned run record
   (`runrecord_<id>.vN.json`) into the same folder.
2. **`POST /log-circuit`** saves an explicit snapshot of the circuit without
   running it. Calling it again with no changes writes nothing new.

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

Every run is also kept in your browser under **My runs**, independent of the
shared `logs/runs/` folder above. From there you can reopen a run in Build,
download it as a `.json` file, or copy a share link when the server stored it.
