"""Rule-based 'next three moves', driven by aems/data/rules.json.

Selection:
1. A rule is a candidate when its dim is assessed and its condition holds:
   - "when": {"fact": <name>, "gt": <x>}  fact from the scan exceeds x
   - "when": {"capped": true}              the dim was capped by the outcome rule
   - "levels": [...]                       the dim's effective level is listed
2. Headline rules (e.g. the verification-debt rule) go first.
3. Remaining candidates are ordered weakest dim first (weakest link),
   ties broken by DIM_PRIORITY, then condition-specific rules before
   level-generic ones.
4. At most one move per dim, at most three moves in total.
"""
from __future__ import annotations

import json
from pathlib import Path

from .model import DimScore, Recommendation

RULES_PATH = Path(__file__).parent / "data" / "rules.json"
# Review is the bottleneck (Faros AI; Chen & Stratton 2026), so sensors and the review line break ties.
DIM_PRIORITY = (3, 5, 9, 1, 8, 2)


def load_rules(path: Path | None = None) -> dict:
    return json.loads((path or RULES_PATH).read_text())


def _holds(rule: dict, dim: DimScore, facts: dict) -> bool:
    when = rule.get("when")
    if when is None:
        return dim.level in rule.get("levels", ())
    if "capped" in when:
        return dim.capped == when["capped"]
    value = facts.get(when.get("fact"))
    return value is not None and value > when["gt"]


def _candidates(dims: tuple[DimScore, ...], facts: dict, rules: dict):
    by_dim = {d.dim: d for d in dims if d.assessed}
    for order, rule in enumerate(rules["rules"]):
        for target in rule["dims"]:
            dim = by_dim.get(target)
            if dim is not None and _holds(rule, dim, facts):
                yield rule, dim, order


def _rank(item) -> tuple:
    rule, dim, order = item
    specific = 0 if "when" in rule else 1
    priority = DIM_PRIORITY.index(dim.dim) if dim.dim in DIM_PRIORITY else len(DIM_PRIORITY)
    return (0 if rule.get("headline") else 1, dim.level, priority, specific, order)


def _to_rec(rule: dict, dim: int) -> Recommendation:
    return Recommendation(
        rule_id=rule["id"], dim=dim, move=rule["move"], rationale=rule["rationale"],
        source=rule["source"], expected_effect=rule["expected_effect"],
        not_yet=rule["not_yet"], confidence=rule["confidence"], review_by=rule["review_by"],
    )


def select(dims: tuple[DimScore, ...], facts: dict, rules: dict, k: int = 3) -> tuple[Recommendation, ...]:
    picked: list[Recommendation] = []
    used_dims: set[int] = set()
    for rule, dim, _ in sorted(_candidates(dims, facts, rules), key=_rank):
        if len(picked) == k:
            break
        if dim.dim in used_dims:
            continue
        picked = [*picked, _to_rec(rule, dim.dim)]
        used_dims = used_dims | {dim.dim}
    return tuple(picked)
