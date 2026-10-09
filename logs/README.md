# QuantumCanvas — Logs

Run artifacts used to live only on the Azure Web App's ephemeral disk, so they
vanished on every redeploy and could not be shared. They now live **here, in the
git repo**, so every run is version-controlled, diff-able, and shareable via a
normal `git push`.

## Layout

```
logs/
├── README.md
├── <run_id>/                     # server runs (POST /execute) — backend-owned
│   ├── canvas.json               # raw canvas state at execution time
│   ├── ir.json                   # validated Internal Representation
│   ├── pseudocode.txt            # human-readable pseudocode
│   ├── qiskit.py                 # generated Qiskit program
│   ├── ionq_request.json         # payload sent to IonQ
│   ├── ionq_response.json        # raw IonQ response
│   ├── results.json              # shot-count histogram
│   ├── metadata.json             # circuit hash · git commit · backend · shots
│   └── circuit_hash.txt
│
└── <username>/                   # user-attributed runs (Option C, see below)
    └── <run_id>/
        ├── canvas.json
        ├── ir.json
        ├── pseudocode.txt
        ├── qiskit.py
        ├── results.json
        └── run.json              # full self-describing run record
```

`<run_id>` is `YYYY-MM-DD_HH-MM-SS_<BACKEND>` (e.g. `2026-06-16_22-41_IONQ_SIM`).

## Username convention (Option C — no login required)

To attribute a run to yourself, you only need a **username** — there is no
GitHub login, OAuth, or token involved. The username is just a folder name:

```
logs/<username>/<run_id>/...
```

Usernames are lower-cased and stripped to `[a-z0-9_.-]` (max 40 chars) so they
are always valid folder names. Pick anything stable — `ada`, `team-blue`,
`shivani` — and your runs will always sort together under `logs/<username>/`.

Two ways your run lands here:

1. **Local backend** — when you run `python app.py` from your own clone and use
   the in-app *Save to GitHub repo* option, the backend writes straight into
   this folder. Then just:
   ```bash
   git add logs/
   git commit -m "Add run <run_id> by <username>"
   git push
   ```
2. **Hosted site (no local backend)** — the *Save to GitHub repo* option instead
   hands you a ready-named file, `logs/<username>/<run_id>/run.json`. Drop it in
   at that path and commit it the same way.

## The three in-app logging options

The Execute panel lets each user choose where a run's log goes:

| Option | Where it goes | Needs backend? | Best for |
|--------|---------------|----------------|----------|
| **A — Browser storage** | `localStorage` in your browser | No | Quick personal history, offline |
| **B — Download file** | Your file manager (a `.json` bundle) | No | Keeping a private copy anywhere |
| **C — GitHub repo** | `logs/<username>/…` in this repo | Local backend (or manual drop) | Sharing runs with the team |

See `frontend/js/user-logger.js` for the implementation.
