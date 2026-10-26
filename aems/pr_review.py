"""PR review signals from `gh pr list --state merged --json ...`. Pure functions, no I/O.

Definitions (all over merged PRs in the history window):
  formal review   a review in state APPROVED / CHANGES_REQUESTED / COMMENTED submitted by
                  someone other than the PR author (logins compared after normalising
                  'app/' and '[bot]'), OR reviewDecision APPROVED / CHANGES_REQUESTED.
                  reviewDecision REVIEW_REQUIRED on a merged PR means it merged WITHOUT the
                  required approval, so it does not count. DISMISSED / PENDING do not count.
  review comments non-author conversation comments + non-author review submissions, excluding
                  non-agent bots (deploy previews, CI). Inline diff comments are not in
                  `gh pr list` output, so this is a lower bound.
  size            additions + deletions as reported by GitHub.
  time to merge   mergedAt - createdAt, hours.

Every identity is reduced to a class (human / agent label / other bot / unknown) inside
this module: no login, name or comment body ever leaves it.
"""
from __future__ import annotations

import re
from datetime import datetime
from statistics import median

from .attribution import agents_for

FORMAL_STATES = frozenset({"APPROVED", "CHANGES_REQUESTED", "COMMENTED"})
FORMAL_DECISIONS = frozenset({"APPROVED", "CHANGES_REQUESTED"})
HUMAN, OTHER_BOT, UNKNOWN = "human", "other bot", "unknown"

_LOGIN_AGENTS = (
    ("Claude", re.compile(r"^claude(-code)?$")),
    ("Devin", re.compile(r"devin-ai-integration")),
    ("Copilot", re.compile(r"^copilot$|copilot-swe-agent|github-copilot|copilot-pull-request-reviewer")),
    ("Cursor", re.compile(r"^cursor(-agent)?$|cursoragent")),
    ("Codex", re.compile(r"chatgpt-codex-connector|^codex$")),
    ("Jules", re.compile(r"google-labs-jules")),
    ("Gemini", re.compile(r"gemini-code-assist")),
)

UNOBSERVED_KEYS = (
    "available", "note", "merged", "reviewed", "reviewed_share", "unreviewed", "agent_authored",
    "agent_unreviewed", "human_reviewed", "agent_reviewed", "median_size_lines", "median_hours_to_merge",
    "review_comments_mean", "reviewed_lines_share", "by_author_class", "sizes",
    "author_people", "human_reviewers",  # distinct-person counts for k-anonymity; stripped by privacy.py
)


def unobserved(note: str) -> dict:
    """Fixed-shape result when PR evidence could not be read."""
    base = {k: None for k in UNOBSERVED_KEYS}
    return {**base, "available": False, "note": note, "by_author_class": {}, "sizes": (), "author_people": {}}


def _login(person) -> str:
    return str(person.get("login") or "") if isinstance(person, dict) else ""


def _norm(login: str) -> str:
    low = login.strip().lower()
    low = low[4:] if low.startswith("app/") else low
    return low[:-5] if low.endswith("[bot]") else low


def author_class(person) -> str:
    """human / agent label / 'other bot' / 'unknown'. Never returns the login."""
    raw = _login(person)
    if not raw:
        return UNKNOWN
    norm = _norm(raw)
    for label, pattern in _LOGIN_AGENTS:
        if pattern.search(norm):
            return label
    found = agents_for(raw, "", (), False)
    if found:
        return found[0]
    bot_flag = bool(person.get("is_bot"))
    return OTHER_BOT if bot_flag or raw.lower().startswith("app/") or raw.lower().endswith("[bot]") else HUMAN


def _ts(value) -> int | None:
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except (ValueError, TypeError):
        return None


def _int(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _items(value) -> tuple[dict, ...]:
    return tuple(x for x in value if isinstance(x, dict)) if isinstance(value, list) else ()


def _summarise(pr: dict) -> dict:
    """Reduce one PR to numbers and classes."""
    author = _norm(_login(pr.get("author")))
    reviews = tuple(r for r in _items(pr.get("reviews"))
                    if r.get("state") in FORMAL_STATES and _norm(_login(r.get("author"))) not in ("", author))
    reviewer_classes = frozenset(author_class(r.get("author")) for r in reviews)
    comments = tuple(c for c in _items(pr.get("comments")) if _norm(_login(c.get("author"))) not in ("", author))
    counted = sum(1 for x in reviews + comments if author_class(x.get("author")) != OTHER_BOT)
    created, merged = _ts(pr.get("createdAt")), _ts(pr.get("mergedAt"))
    cls = author_class(pr.get("author"))
    return {
        "cls": cls, "is_agent": cls not in (HUMAN, OTHER_BOT, UNKNOWN),
        "person": author if cls == HUMAN else None,
        "human_reviewers": frozenset(_norm(_login(r.get("author"))) for r in reviews
                                     if author_class(r.get("author")) == HUMAN),
        "reviewed": bool(reviews) or pr.get("reviewDecision") in FORMAL_DECISIONS,
        "human_reviewed": HUMAN in reviewer_classes,
        "agent_reviewed": bool(reviewer_classes - {HUMAN, UNKNOWN}),
        "size": _int(pr.get("additions")) + _int(pr.get("deletions")),
        "hours": (merged - created) / 3600 if created is not None and merged is not None and merged >= created else None,
        "comments": counted,
    }


def _in_window(pr: dict, since_ts: int | None) -> bool:
    if since_ts is None:
        return True
    merged = _ts(pr.get("mergedAt"))
    return merged is not None and merged >= since_ts


def _class_counts(rows: tuple[dict, ...]) -> dict[str, int]:
    labels = sorted({r["cls"] for r in rows})
    return {label: sum(1 for r in rows if r["cls"] == label) for label in labels}


def _ratio(num: int | float, den: int | float):
    return num / den if den else None


def pr_review_metrics(prs, since_ts: int | None = None, note: str = "gh pr list --state merged") -> dict:
    """Metrics dict from a parsed `gh pr list` JSON array. Never raises on bad input."""
    if not isinstance(prs, list):
        return unobserved("unexpected gh pr list output")
    rows = tuple(_summarise(p) for p in _items(prs) if _in_window(p, since_ts))
    n = len(rows)
    reviewed = tuple(r for r in rows if r["reviewed"])
    sizes = tuple(r["size"] for r in rows)
    hours = tuple(r["hours"] for r in rows if r["hours"] is not None)
    return {
        "available": True, "note": note, "merged": n,
        "reviewed": len(reviewed), "reviewed_share": _ratio(len(reviewed), n), "unreviewed": n - len(reviewed),
        "agent_authored": sum(1 for r in rows if r["is_agent"]),
        "agent_unreviewed": sum(1 for r in rows if r["is_agent"] and not r["reviewed"]),
        "human_reviewed": sum(1 for r in rows if r["human_reviewed"]),
        "agent_reviewed": sum(1 for r in rows if r["agent_reviewed"]),
        "median_size_lines": median(sizes) if sizes else None,
        "median_hours_to_merge": median(hours) if hours else None,
        "review_comments_mean": _ratio(sum(r["comments"] for r in rows), n),
        "reviewed_lines_share": _ratio(sum(r["size"] for r in reviewed), sum(sizes)),
        "by_author_class": _class_counts(rows),
        "sizes": sizes,
        "author_people": {k: len({r["person"] for r in rows if r["cls"] == k and r["person"]})
                          for k in _class_counts(rows)},
        "human_reviewers": len(frozenset().union(*(r["human_reviewers"] for r in rows))),
    }
