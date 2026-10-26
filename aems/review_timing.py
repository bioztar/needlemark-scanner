"""Q1 review timing from `gh pr list --state merged --json ...,reviews` (review submittedAt). Pure.

Per merged PR in the window (formal reviews = APPROVED / CHANGES_REQUESTED / COMMENTED by
someone other than the author, as in pr_review.py):
  first review   earliest formal review submittedAt - createdAt, hours
  approval       earliest non-author APPROVED review submittedAt - createdAt, hours
  per 100 lines  approval hours / (changed lines / 100)
  rubber stamp   approved faster than max(min_seconds, lines / max_lines_per_hour hours);
                 thresholds come from aems/data/pack_rules.json. Open-to-approval also
                 contains waiting time, so this undercounts rubber stamps.
Rows are in-memory only; only the aggregates from summarise() are reported.
"""
from __future__ import annotations

from statistics import median

from .pr_review import FORMAL_STATES, _items, _login, _norm, _ts

HOUR = 3600


def rubber_stamp_seconds(size: int, rule: dict) -> float:
    return max(float(rule["min_seconds"]), size * HOUR / float(rule["max_lines_per_hour"]))


def _size(pr: dict) -> int:
    total = 0
    for key in ("additions", "deletions"):
        try:
            total += max(0, int(pr.get(key) or 0))
        except (TypeError, ValueError):
            pass
    return total


def _first(reviews, created: int | None, states) -> float | None:
    if created is None:
        return None
    times = [t for t in (_ts(r.get("submittedAt")) for r in reviews if r.get("state") in states)
             if t is not None and t >= created]
    return (min(times) - created) / HOUR if times else None


def _row(pr: dict, classify, rule: dict) -> dict:
    author = _norm(_login(pr.get("author")))
    reviews = tuple(r for r in _items(pr.get("reviews"))
                    if r.get("state") in FORMAL_STATES and _norm(_login(r.get("author"))) not in ("", author))
    approved = any(r.get("state") == "APPROVED" for r in reviews)
    created, size = _ts(pr.get("createdAt")), _size(pr)
    approval = _first(reviews, created, {"APPROVED"})
    group, vendor = classify(pr.get("author"))
    return {
        "group": group, "vendor": vendor, "person": author if group in ("human", "vendor") and author else None,
        "size": size, "reviewed": bool(reviews), "approved": approved,
        "first_h": _first(reviews, created, FORMAL_STATES), "approval_h": approval,
        "per100_h": approval / (size / 100) if approval is not None and size else None,
        "rubber": approval is not None and approval * HOUR < rubber_stamp_seconds(size, rule),
    }


def _in_window(pr: dict, since_ts: int | None) -> bool:
    merged = _ts(pr.get("mergedAt"))
    return merged is not None and (since_ts is None or merged >= since_ts)


def timing_rows(prs, since_ts: int | None, classify, rule: dict) -> tuple[dict, ...]:
    """One in-memory row per merged PR in the window. Never raises on malformed input."""
    if not isinstance(prs, list):
        return ()
    return tuple(_row(p, classify, rule) for p in _items(prs) if _in_window(p, since_ts))


def _median(values) -> float | None:
    vals = [v for v in values if v is not None]
    return median(vals) if vals else None


def summarise(rows: tuple[dict, ...]) -> dict:
    timed = sum(1 for r in rows if r["approval_h"] is not None)  # approvals with a usable timestamp
    stamped = sum(1 for r in rows if r["rubber"])
    return {
        "prs": len(rows), "reviewed": sum(1 for r in rows if r["reviewed"]),
        "approved": sum(1 for r in rows if r["approved"]),
        "rubber_stamped": stamped, "rubber_stamp_rate": stamped / timed if timed else None,
        "median_hours_first_review": _median(r["first_h"] for r in rows),
        "median_hours_approval": _median(r["approval_h"] for r in rows),
        "median_hours_per_100_lines": _median(r["per100_h"] for r in rows),
    }


def by_group(rows: tuple[dict, ...], key: str) -> dict[str, dict]:
    groups = sorted({r[key] for r in rows if r[key] is not None})
    return {g: summarise(tuple(r for r in rows if r[key] == g)) for g in groups}


def people(rows: tuple[dict, ...], key: str) -> dict[str, int]:
    groups = sorted({r[key] for r in rows if r[key] is not None})
    return {g: len({r["person"] for r in rows if r[key] == g and r["person"]}) for g in groups}
