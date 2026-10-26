"""Scoring rules (AEMS method, see README).

(a) Per-dimension level = highest level whose evidence is fully present, climbing
    from 1 with no gaps (a missing level-2 check stops the climb at 1).
(b) Overall = weakest link (min) over assessed dims, shown with the median.
(c) Outcome cap: a level >= 3 that lacks outcome evidence is capped at 2
    ("presence, not maturity").
"""
from __future__ import annotations

from statistics import median

from .model import CAP_LEVEL, Check, DimScore, Evidence, OutcomeCheck


def ladder_level(checks: tuple[Check, ...]) -> int:
    level = 0
    for target in range(1, 6):
        at_level = [c for c in checks if c.level == target]
        if not at_level or not all(c.passed for c in at_level):
            break
        level = target
    return level


def score_dim(dim: int, checks: tuple[Check, ...], outcome: OutcomeCheck | None,
              hints: tuple[Evidence, ...] = ()) -> DimScore:
    raw = ladder_level(checks)
    has_outcome = outcome is not None and outcome.passed
    capped = raw > CAP_LEVEL and not has_outcome
    return DimScore(
        dim=dim, raw_level=raw, level=CAP_LEVEL if capped else raw, capped=capped,
        checks=checks, outcome=outcome, assessed=True, hints=hints,
    )


def unassessed_dim(dim: int, hints: tuple[Evidence, ...]) -> DimScore:
    return DimScore(dim=dim, raw_level=0, level=0, capped=False, checks=(),
                    outcome=None, assessed=False, hints=hints)


def overall(dims: tuple[DimScore, ...]) -> tuple[int, float, tuple[int, ...]]:
    assessed = [d for d in dims if d.assessed]
    if not assessed:
        return 0, 0.0, ()
    levels = [d.level for d in assessed]
    low = min(levels)
    weakest = tuple(sorted(d.dim for d in assessed if d.level == low))
    return low, float(median(levels)), weakest
