"""HTML section for the query pack. Renders aggregates, class labels and the client's own vendor
labels only; never logins, domains, paths, subjects or line content."""
from __future__ import annotations

from .render import e, num, pct
from .privacy import SUPPRESSED

_CLASS_ORDER = ("human", "agent", "vendor", "other bot", "unknown")


def _hours(x) -> str:
    return x if isinstance(x, str) else "n/a" if x is None else f"{x:,.2f} h"


def _table(head: tuple[str, ...], rows: list[tuple]) -> str:
    th = "".join(f"<th{' class=num' if i else ''}>{e(h)}</th>" for i, h in enumerate(head))
    body = "".join("<tr>" + "".join(f"<td{' class=num' if i else ''}>{e(c)}</td>" for i, c in enumerate(r)) + "</tr>"
                   for r in rows)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"


def _ordered(breakdown: dict) -> list:
    return sorted(breakdown.items(), key=lambda kv: (_CLASS_ORDER.index(kv[0]) if kv[0] in _CLASS_ORDER else 99, kv[0]))


def _timing_cells(s) -> tuple:
    if s == SUPPRESSED:
        return (SUPPRESSED,) * 7
    return (num(s["prs"]), num(s["reviewed"]), num(s["approved"]), _hours(s["median_hours_first_review"]),
            _hours(s["median_hours_approval"]), _hours(s["median_hours_per_100_lines"]),
            f"{num(s['rubber_stamped'])} ({pct(s['rubber_stamp_rate'])})")


def _timing(pack: dict) -> str:
    rt, rule = pack["review_timing"], pack["rubber_stamp_rule"]
    head = ("Author class", "Merged PRs", "Reviewed", "Approved", "Open → first review", "Open → approval",
            "Approval per 100 lines", "Rubber-stamp")
    if not rt["available"]:
        return f"<h3>Q1 · Review timing</h3><p>not observed ({e(rt['note'])}).</p>"
    rows = [("all",) + _timing_cells(rt["overall"])] + [(g,) + _timing_cells(s) for g, s in _ordered(rt["by_class"])]
    return ("<h3>Q1 · Review timing</h3>" + _table(head, rows)
            + f"<p class='src'>Medians. Rubber-stamp = approved faster than max({rule['min_seconds']} s, lines ÷ "
            f"{rule['max_lines_per_hour']} lines per hour); rate over approvals with a timestamp. Open → approval also "
            f"contains waiting time, so rubber stamps are undercounted. Rules {e(pack['rules_version'])}.</p>")


def _rate_cells(r, windows) -> tuple:
    if r == SUPPRESSED:
        return (SUPPRESSED,) * (2 * len(windows))
    return tuple(c for n in windows for c in (num(r[f"defects_{n}"]), num(r[f"per_1k_{n}"])))


def _escapes(pack: dict) -> str:
    esc, windows = pack["escapes"], pack["escape_windows_days"]
    head = ("Originating class",) + tuple(h for n in windows for h in (f"Escaped defects ≤{n}d", f"per 1K lines ≤{n}d"))
    rows = ([("all",) + _rate_cells(esc["overall"], windows)] if esc.get("overall") else []) + \
        [(g,) + _rate_cells(r, windows) for g, r in _ordered(esc["by_class"])]
    facts = (f"{num(esc['fix_commits'])} defect fixes ({num(esc['from_subjects'])} by subject, "
             f"{num(esc['from_bug_prs'])} via bug-linked PRs; links: {esc['bug_links']}) · {num(esc['traced'])} traced · "
             f"{num(esc['caught_before_merge'])} caught on the branch before merge · "
             f"{num(esc['untraceable'])} untraceable (pure additions) · median escape age "
             f"{num(esc['median_escape_age_days'])} days" + (" · truncated" if esc["truncated"] else ""))
    return (f"<h3>Q2 · Escaped defects</h3><p>{e(facts)}</p>" + _table(head, rows)
            + "<p class='src'>Each fix is one defect, split across the commits that last wrote the lines it changed or "
            "removed (git blame on the fix's parent). Only origins old enough to have had the full window count.</p>")


def _vendor_cells(r, windows) -> tuple:
    return (num(r["commits"]), num(r["lines"]), pct(r["agent_share"]), num(r["prs"]), pct(r["formal_review_share"]),
            pct(r["rubber_stamp_rate"]), f"{pct(r['rework_rate'])} ({r['rework_status']})",
            *(num(r[f"escaped_per_1k_{n}"]) for n in windows))


def _vendors(pack: dict) -> str:
    ven, windows = pack["vendors"], pack["escape_windows_days"]
    if not ven["configured"]:
        return f"<h3>Q3 · Vendor lens</h3><p>not configured ({e(ven.get('note', ''))}).</p>"
    head = ("Vendor", "Commits", "Code lines", "Agent share", "PRs", "Formal review", "Rubber-stamp", "Rework (30d)") + \
        tuple(f"Escapes per 1K ≤{n}d" for n in windows)
    rows = [(r["label"],) + _vendor_cells(r, windows) for r in ven["rows"]]
    if ven["pooled"]:
        rows.append((f"{ven['pooled']['vendors']} small vendor(s), pooled",) + _vendor_cells(ven["pooled"], windows))
    notice = ("<div class='callout warn'>--allow-small-vendors: vendors with fewer than 5 people are listed; their "
              "figures may describe individuals.</div>" if ven["small_vendors_allowed"] else "")
    return "<h3>Q3 · Vendor lens</h3>" + notice + _table(head, rows) + (
        "<p class='src'>Vendor membership comes from your local vendors file, which never leaves your environment. "
        "The export carries salted vendor ids unless --keep-vendor-names.</p>")


def render_pack(pack: dict | None) -> str:
    if not pack:
        return ""
    return ("<h2>Query pack (Diagnostic)</h2>" + _timing(pack) + _escapes(pack) + _vendors(pack))
