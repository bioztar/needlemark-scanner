"""Allow-listed export of the query pack (part of schema aems-export-4). Numbers, class
labels, status enums and salted vendor ids only: no vendor mapping, logins or labels
(unless keep_vendor_names)."""
from __future__ import annotations

from .privacy import SUPPRESSED
from .vendors import vendor_id

TIMING_KEYS = ("prs", "reviewed", "approved", "rubber_stamped", "rubber_stamp_rate", "median_hours_first_review",
               "median_hours_approval", "median_hours_per_100_lines")
ESCAPE_KEYS = ("fix_commits", "from_subjects", "from_bug_prs", "traced", "caught_before_merge", "untraceable", "truncated",
               "median_escape_age_days", "bug_links")
VENDOR_KEYS = ("commits", "lines", "agent_share", "prs", "formal_review_share", "rubber_stamp_rate",
               "rework_matured", "rework_rate", "rework_status")


def _pick(src: dict | None, keys) -> dict | None:
    if src is None:
        return None
    return {k: src.get(k) for k in keys}


def _cells(breakdown: dict, keys) -> dict:
    return {str(g): v if v == SUPPRESSED else _pick(v, keys) for g, v in breakdown.items()}


def _rate_keys(windows) -> tuple[str, ...]:
    return tuple(f"{k}_{n}" for n in windows for k in ("lines", "defects", "per_1k"))


def _vendor_keys(windows) -> tuple[str, ...]:
    return VENDOR_KEYS + tuple(f"escaped_per_1k_{n}" for n in windows)


def export_pack(pack: dict | None, keep_vendor_names: bool = False) -> dict | None:
    if pack is None:
        return None
    windows = tuple(pack["escape_windows_days"])
    rt, esc, ven = pack["review_timing"], pack["escapes"], pack["vendors"]
    rates, vkeys = _rate_keys(windows), _vendor_keys(windows)
    return {
        "rules": pack["rules_version"], "rubber_stamp_rule": dict(pack["rubber_stamp_rule"]),
        "escape_windows_days": list(windows),
        "review_timing": {"available": bool(rt["available"]), "overall": _pick(rt["overall"], TIMING_KEYS),
                          "by_class": _cells(rt["by_class"], TIMING_KEYS)},
        "escapes": {**_pick(esc, ESCAPE_KEYS), "overall": _pick(esc.get("overall"), rates),
                    "by_class": _cells(esc["by_class"], rates)},
        "vendors": {
            "configured": bool(ven["configured"]), "small_vendors_allowed": bool(ven["small_vendors_allowed"]),
            "rows": [{"vendor_id": vendor_id(r["label"], keep_vendor_names), **_pick(r, vkeys)} for r in ven["rows"]],
            "pooled": None if ven["pooled"] is None else {"vendors": ven["pooled"]["vendors"],
                                                          **_pick(ven["pooled"], vkeys)},
        },
    }
