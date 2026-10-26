"""Q3 vendor lens: per-vendor volume, agent share, review, rework and escape rates. Pure.

Vendor membership comes from the client-local vendors file (commit author email domain or
noreply login; PR author login). A vendor backed by 1-4 people is pooled with the other
small vendors into one row with no label; when the pool itself has fewer than 5 people its
numbers are suppressed and `leak_guard` is set, so the caller also suppresses the
human/agent/vendor class breakdowns (vendor class total minus visible vendor rows would
otherwise reveal the pool). --allow-small-vendors lists every vendor by label instead.
"""
from __future__ import annotations

from .escapes import code_lines, escape_rates
from .metrics import HEALTHY_REWORK_MAX, group_rework
from .privacy import K_MIN, SUPPRESSED, is_small
from .review_timing import summarise

POOLED = "small vendors (pooled)"
_MIN_MATURED = 5


def _ratio(num: int, den: int):
    return num / den if den else None


def _rework(group, commits, now) -> dict:
    matured, reworked, _ = group_rework(group, commits, now)
    rate = _ratio(reworked, matured)
    status = "insufficient" if matured < _MIN_MATURED else "healthy" if rate <= HEALTHY_REWORK_MAX else "high"
    return {"rework_matured": matured, "rework_rate": rate, "rework_status": status}


def _row(members: frozenset[str], ctx: dict) -> dict:
    vc = tuple(c for c in ctx["changes"] if c.vendor in members)
    prs = tuple(r for r in ctx["rows"] if r["vendor"] in members)
    rates = escape_rates(ctx["traces"], ctx["by_sha"], ctx["now"],
                         lambda c: "v" if c.vendor in members else None, ctx["windows"]).get("v", {})
    timing = summarise(prs)
    return {
        "commits": len(vc), "lines": sum(code_lines(c) for c in vc),
        "agent_share": _ratio(sum(1 for c in vc if c.is_agent), len(vc)),
        "prs": len(prs), "formal_review_share": _ratio(timing["reviewed"], len(prs)),
        "rubber_stamp_rate": timing["rubber_stamp_rate"],
        **_rework(vc, ctx["changes"], ctx["now"]),
        **{f"escaped_per_1k_{n}": rates.get(f"per_1k_{n}") for n in ctx["windows"]},
    }


def _people(members: frozenset[str], ctx: dict) -> int:
    commit_people = {c.author_key for c in ctx["changes"] if c.vendor in members and c.author_key}
    pr_people = {r["person"] for r in ctx["rows"] if r["vendor"] in members and r["person"]}
    return max(len(commit_people), len(pr_people))  # emails and logins cannot be joined: lower bound


def vendor_lens(labels, commits, rows, traces, now: int, windows, allow_small: bool) -> dict:
    changes = tuple(c for c in commits if not c.is_merge)
    ctx = {"changes": changes, "rows": rows, "traces": traces, "now": now, "windows": tuple(windows),
           "by_sha": {c.sha: c for c in commits}}
    active = tuple(lb for lb in sorted(labels)
                   if any(c.vendor == lb for c in changes) or any(r["vendor"] == lb for r in rows))
    small = frozenset(lb for lb in active if not allow_small and is_small(_people(frozenset({lb}), ctx)))
    visible = tuple({"label": lb, **_row(frozenset({lb}), ctx)} for lb in active if lb not in small)
    pooled, guard = None, False
    if small:
        row = _row(small, ctx)
        guard = _people(small, ctx) < K_MIN
        pooled = {"vendors": len(small), **({k: SUPPRESSED for k in row} if guard else row)}
    return {"configured": True, "small_vendors_allowed": allow_small, "rows": list(visible),
            "pooled": pooled, "leak_guard": guard}


def not_configured(note: str) -> dict:
    return {"configured": False, "note": note, "small_vendors_allowed": False, "rows": [], "pooled": None,
            "leak_guard": False}
