"""k-anonymity for every per-class / per-group figure in reports and exports.

A breakdown cell backed by 1..4 distinct PEOPLE (K_MIN = 5) would describe
individuals, so the WHOLE breakdown is replaced by SUPPRESSED (suppressing one
cell alone would let total - visible cells reveal it). Cells backed only by
bots or agent apps (0 people) describe no person and do not trigger
suppression. Repo-level totals (commits, agent commits, AI shares, agent
rework, VDR, PR totals) are kept. Applied after metrics are computed and
before scoring evidence is built; pass/fail logic reads totals only.
"""
from __future__ import annotations

from .model import Commit

K_MIN = 5
SUPPRESSED = "<5, suppressed"
_HUMAN_REWORK_KEYS = ("human_matured", "human_reworked", "human_rate")
_PR_PRIVATE_KEYS = ("author_people", "human_reviewers")


def is_small(people: int | None) -> bool:
    return people is not None and 0 < people < K_MIN


def _changes(commits: tuple[Commit, ...]) -> tuple[Commit, ...]:
    return tuple(c for c in commits if not c.is_merge)


def people_by_class(commits: tuple[Commit, ...]) -> dict[str, int]:
    changes = _changes(commits)
    classes = sorted({c.identity_class for c in changes})
    return {k: len({c.author_key for c in changes if c.identity_class == k and c.author_key}) for k in classes}


def people_by_tool(commits: tuple[Commit, ...]) -> dict[str, int]:
    changes = _changes(commits)
    tools = sorted({t for c in changes for t in c.agents})
    return {t: len({c.author_key for c in changes if t in c.agents and c.author_key}) for t in tools}


def suppress_breakdown(counts: dict, people: dict) -> dict:
    if any(is_small(people.get(k, 0)) for k in counts):
        return {k: SUPPRESSED for k in counts}
    return dict(counts)


def private_attribution(attr: dict, commits: tuple[Commit, ...]) -> dict:
    return {**attr, "by_class": suppress_breakdown(attr["by_class"], people_by_class(commits)),
            "by_tool": suppress_breakdown(attr["by_tool"], people_by_tool(commits))}


def private_rework(rw: dict, commits: tuple[Commit, ...]) -> dict:
    humans = len({c.author_key for c in _changes(commits) if not c.is_agent and c.author_key})
    return {**rw, **{k: SUPPRESSED for k in _HUMAN_REWORK_KEYS}} if is_small(humans) else dict(rw)


def private_prs(prs: dict) -> dict:
    public = {k: v for k, v in prs.items() if k not in _PR_PRIVATE_KEYS}
    by_class = suppress_breakdown(prs.get("by_author_class") or {}, prs.get("author_people") or {})
    if is_small(prs.get("human_reviewers")):
        public = {**public, "human_reviewed": SUPPRESSED, "agent_reviewed": SUPPRESSED}
    return {**public, "by_author_class": by_class}
