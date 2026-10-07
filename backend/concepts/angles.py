"""Angles are data, never code.

An angle is either {"pi": [num, den]} (a rational multiple of pi) or
{"rad": float}. No strings, no eval.
"""
from __future__ import annotations

import math
from fractions import Fraction


class AngleError(ValueError):
    pass


def validate_angle(a) -> None:
    if not isinstance(a, dict) or len(a) != 1:
        raise AngleError('angle must be {"pi": [num, den]} or {"rad": number}')
    if "pi" in a:
        v = a["pi"]
        if (not isinstance(v, (list, tuple)) or len(v) != 2
                or not all(isinstance(x, int) and not isinstance(x, bool) for x in v)):
            raise AngleError('"pi" angle must be two integers [num, den]')
        if v[1] == 0:
            raise AngleError("angle denominator cannot be 0")
    elif "rad" in a:
        v = a["rad"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise AngleError('"rad" angle must be a finite number')
    else:
        raise AngleError('angle must use the key "pi" or "rad"')


def to_rad(a) -> float:
    validate_angle(a)
    if "pi" in a:
        n, d = a["pi"]
        return math.pi * n / d
    return float(a["rad"])


def pi_multiple(a) -> Fraction | None:
    """The angle as an exact multiple of pi, or None if it is not (to 1e-12)."""
    validate_angle(a)
    if "pi" in a:
        n, d = a["pi"]
        return Fraction(n, d)
    x = float(a["rad"]) / math.pi
    f = Fraction(x).limit_denominator(64)
    return f if abs(float(f) - x) < 1e-12 else None


def pi(n: int, d: int = 1) -> dict:
    return {"pi": [n, d]}
