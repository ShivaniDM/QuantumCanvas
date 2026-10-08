"""Deterministic template explanation, rendered FROM THE STEP LOG (plan 9b.1).

Every sentence here is backed by a field of the math layer's step log; nothing is asserted from the IR alone.
A broken concept contract is not an error: the sentence says what happened and which precondition was missing.
"""
from __future__ import annotations

EPS = 5e-3


def pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def _changes(step: dict, targets, label) -> str:
    bits = []
    for t in targets:
        a, b = step["p1_before"][t], step["p1_after"][t]
        if abs(a - b) > EPS:
            bits.append(f"{label(t)}: chance of 1 {pct(a)} → {pct(b)}")
    return "; ".join(bits)


def render_step(step: dict, node, label=lambda q: f"q{q}") -> dict:
    """-> {"effect": str, "plain": str|None, "claim_ok": bool|None}. `node` is the IR node (dict) of the step."""
    op = node["op"]
    ent_known = all(x is not None for x in step.get("entropy_after", [None]))
    if not ent_known:                       # after a measurement the state is a mixture; no per-step claim
        return {"effect": "", "plain": None, "claim_ok": None}
    T = list(node["targets"]) + list(node.get("controls", []))
    out = {"effect": "", "plain": None, "claim_ok": True}
    contracts = step.get("contracts", [])
    broken = [c for c in contracts if not c["held"]]

    if op == "shake":
        spoiled = [t for t in node["targets"] if step["p1_before"][t] > EPS]
        after = [step["p1_after"][t] for t in node["targets"]]
        if spoiled:
            out["claim_ok"] = False
            out["plain"] = ("Shake mixes each qubit with a half-turn, which only gives an even 50/50 split for a qubit "
                            f"that starts at 0. {', '.join(label(t) for t in spoiled)} did not start at 0, so its earlier "
                            "data is overwritten.")
            out["effect"] = _changes(step, node["targets"], label)
        else:
            out["effect"] = ("; ".join(f"{label(t)}: 50% / 50%" for t in node["targets"])
                             if all(abs(p - .5) < 1e-3 for p in after) else _changes(step, node["targets"], label))
    elif op == "entangle" and len(node["targets"]) == 2:
        c, t = node["targets"]
        s0, s1 = step["entropy_before"][c], step["entropy_after"][c]
        if s1 - s0 < 0.01:
            out["claim_ok"] = False
            out["plain"] = (f"Entangle did not link {label(c)} and {label(t)} here: {label(c)} is not in superposition, "
                            "so this only copies its plain 0 or 1.")
            out["effect"] = f"Entanglement of {label(c)} with the rest: {s1:.2f} bits (was {s0:.2f})."
        else:
            out["effect"] = (f"Entanglement of {label(c)} with the rest: {s0:.2f} → {s1:.2f} bits. "
                             + _changes(step, [t], label)).strip()
    elif op in ("mark",) or (op == "phase"):
        held = all(c["held"] for c in contracts) if contracts else True
        out["effect"] = ("The probabilities did not change (Mark only changes a hidden sign)." if op == "mark" and held
                         else "The probabilities did not change (Phase only turns a hidden angle)." if held
                         else "Heads-up: this step changed the probabilities, which it normally does not.")
        out["claim_ok"] = held
    elif op == "boost":
        out.update(_boost(step, node, label))
    elif op == "compare":
        c = contracts[0] if contracts else None
        out["effect"] = c["detail"] if c else ""
        if c and not c["held"]:
            out["claim_ok"] = False
            out["plain"] = ("Compare raises the flag only when the flag qubit starts at 0; it did not here, so the flag "
                            "does not mean what it should.")
    elif op == "uncompute":
        c = contracts[0] if contracts else None
        out["effect"] = ("The helper qubits are back to 0." if c and c["held"]
                         else "The helper qubits are NOT back to 0: something between the step and its Uncompute disturbed them."
                         if c else "")
        out["claim_ok"] = c["held"] if c else True
    else:
        qs = sorted(set(T) | set(node.get("ancillas", [])))
        ch = _changes(step, qs, label)
        out["effect"] = ch if ch else ("No qubit's chance of 1 changed." if qs else "")
        if broken:
            out["claim_ok"] = False
    return out


def _boost(step, node, label) -> dict:
    out = {"effect": "", "plain": None, "claim_ok": True}
    single = len(node["targets"]) == 1
    note = (" On a single qubit there are only two possible answers, so Mark followed by Boost just flips the qubit; "
            "Boost needs at least 2 qubits to amplify.")
    f = step.get("facts", {}).get("boost")
    if f is None:
        out["effect"] = "Nothing was marked before this Boost, so there is no answer for it to amplify."
        out["plain"] = ("Boost can only make a marked answer more likely, and no Mark or Compare came before it."
                        + (note if single else ""))
        out["claim_ok"] = False
        return out
    traj, rounds = f["trajectory"], f["rounds"]
    reg = ", ".join(label(q) for q in f["register"])
    ans = format(f["value"], f"0{len(f['register'])}b")
    out["effect"] = (f"Chance that [{reg}] = {ans}: " + " → ".join(pct(x) for x in traj)
                     + (" (after each round)." if rounds > 1 else "."))
    p0, p1, peak = traj[0], traj[-1], max(traj)
    if single:
        verb = "LOWERED" if p1 - p0 < -EPS else "raised" if p1 - p0 > EPS else "did not change"
        out["claim_ok"] = False
        out["plain"] = (f"Boost {verb} the chance of the marked answer"
                        + (f" from {pct(p0)} to {pct(p1)}." if verb != "did not change" else f" (still {pct(p1)}).") + note)
    elif rounds > 1 and peak - p1 > EPS:
        best = traj.index(peak)
        out["claim_ok"] = False
        out["plain"] = (f"Boost went past the best point: the marked answer peaks at {pct(peak)} after {best} "
                        f"round{'s' if best != 1 else ''} and then falls back to {pct(p1)}. "
                        "Use about √(number of answers) rounds, not more.")
    elif p1 - p0 > EPS:
        out["plain"] = f"Boost raised the chance of the marked answer from {pct(p0)} to {pct(p1)}."
    elif p1 - p0 < -EPS:
        out["claim_ok"] = False
        out["plain"] = (f"Boost LOWERED the chance of the marked answer from {pct(p0)} to {pct(p1)}. "
                        "Boost only helps with 2 or more qubits and about √(number of answers) rounds.")
    else:
        out["claim_ok"] = False
        out["plain"] = f"Boost did not change the chance of the marked answer (still {pct(p1)})."
    return out


UNMEASURED_WARNING = ("Taking this step out would leave your measured results exactly the same: it only touches "
                      "qubits that can't influence what you measure.")


def idle_steps(log: dict) -> list[str]:
    """Step ids flagged W_UNMEASURED_EFFECT: harmless alone AND together (the log says both)."""
    if log.get("ineffective_together") is not True:
        return []
    return [s["id"] for s in log["steps"] if s.get("affects_result") is False]
