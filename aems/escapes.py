"""Q2 escaped-defect trace: defect fixes -> blamed originating commits -> rates by class. Numbers only.

Defect fixes in the window:
  - non-merge commits whose subject matches a pattern in pack_rules.json
    (conventional fix / hotfix / bugfix, git's default `Revert "..."`), plus
  - merge or squash commits of merged PRs linked to a bug (PR label, or a closing issue
    with a bug label when gh exposes closingIssuesReferences). A true merge is skipped
    when its branch already contains a subject-matched fix, so a defect counts once.
Each fix is ONE defect, split across its originating commits by share of blamed lines.
  defects_N[g]  sum of those shares for origins of group g that the fix followed within
                N days, counting only origins old enough to have had N days to escape
  lines_N[g]    changed code lines (no tests, docs, manifests, lockfiles) of group g's
                commits in the window that are at least N days old
  per_1k_N[g]   defects_N / lines_N * 1000
Fixes that only add lines have nothing to blame and are counted as untraceable. A fix and an
origin that landed through the same first-parent merge (a fix made on the branch before it
merged) did not escape: those lines are dropped, and a fix left with none counts as
caught_before_merge.
"""
from __future__ import annotations

import re
from pathlib import Path
from statistics import median

from .attribution import is_rework_relevant, is_test_path
from .escape_trace import trace_fix
from .model import Commit
from .runner import git

DAY = 86400
MAX_MERGES_MAPPED = 300


def is_defect_fix(subject: str, patterns) -> bool:
    text = subject.strip()
    return any(re.search(p, text, re.I) for p in patterns)


def _branch_has_fix(root: Path, merge: Commit, by_sha: dict, patterns) -> bool:
    out = git(root, "rev-list", f"{merge.parents[0]}..{merge.sha}") or ""
    return any(sha in by_sha and is_defect_fix(by_sha[sha].subject, patterns) for sha in out.split())


def select_fixes(root: Path, commits: tuple[Commit, ...], bug_shas: frozenset[str], patterns) -> dict:
    by_sha = {c.sha: c for c in commits}
    subject = tuple(c for c in commits if not c.is_merge and is_defect_fix(c.subject, patterns))
    chosen = {c.sha for c in subject}
    linked = tuple(
        by_sha[s] for s in sorted(bug_shas)
        if s in by_sha and s not in chosen
        and not (by_sha[s].is_merge and _branch_has_fix(root, by_sha[s], by_sha, patterns))
    )
    fixes = tuple(sorted(subject + linked, key=lambda c: c.ts))
    return {"fixes": fixes, "from_subjects": len(subject), "from_bug_prs": len(linked)}


def code_lines(commit: Commit) -> int:
    return sum(a + d for p, a, d in commit.files if is_rework_relevant(p) and not is_test_path(p))


def _share(trace: dict, origin: str) -> float:
    total = sum(trace["lines"].values())
    return trace["lines"][origin] / total if total else 0.0


def _defects(traces, by_sha: dict, now: int, group_of, group: str, days: int) -> float:
    span = days * DAY
    return sum(
        _share(t, sha)
        for t in traces for sha in t["lines"]
        if sha in by_sha and group_of(by_sha[sha]) == group and by_sha[sha].ts + span <= now
        and 0 <= t["fix_ts"] - by_sha[sha].ts <= span
    )


def escape_rates(traces, by_sha: dict, now: int, group_of, windows=(30, 90)) -> dict[str, dict]:
    changes = tuple(c for c in by_sha.values() if not c.is_merge)
    groups = sorted({g for g in (group_of(c) for c in changes) if g is not None})
    out = {}
    for g in groups:
        row = {}
        for n in windows:
            lines = sum(code_lines(c) for c in changes if group_of(c) == g and c.ts + n * DAY <= now)
            defects = _defects(traces, by_sha, now, group_of, g, n)
            row = {**row, f"lines_{n}": lines, f"defects_{n}": round(defects, 4),
                   f"per_1k_{n}": defects / lines * 1000 if lines else None}
        out = {**out, g: row}
    return out


def escape_ages(traces) -> tuple[float, ...]:
    return tuple((t["fix_ts"] - ts) / DAY for t in traces for sha, ts in t["times"].items()
                 if sha in t["lines"] and t["fix_ts"] >= ts)


def landing_map(root: Path, commits: tuple[Commit, ...]) -> dict[str, str]:
    """sha -> first-parent merge that landed it, for commits that arrived through a merge."""
    merges = [c for c in commits if c.is_merge and c.on_first_parent][:MAX_MERGES_MAPPED]
    landed: dict[str, str] = {}
    for m in merges:
        out = git(root, "rev-list", f"{m.parents[0]}..{m.sha}") or ""
        landed = {**landed, **{sha: m.sha for sha in out.split() if sha != m.sha}}
    return landed


def drop_pre_merge(trace: dict, landed: dict[str, str]) -> dict:
    """Remove origins that landed through the same merge as the fix (caught before merge)."""
    gate = landed.get(trace["sha"])
    if gate is None:
        return trace
    keep = {sha: n for sha, n in trace["lines"].items() if landed.get(sha) != gate}
    return {**trace, "lines": keep}


def collect(root: Path, commits: tuple[Commit, ...], bug_shas: frozenset[str], rules: dict) -> dict:
    """Select fixes and blame them (git I/O). Traces stay in memory; only summaries are reported."""
    limits = rules["limits"]
    sel = select_fixes(root, commits, bug_shas, rules["fix_subject_patterns"])
    fixes = sel["fixes"][-limits["max_fixes"]:]
    raw = tuple(t for t in (trace_fix(root, f, limits["max_files_per_fix"]) for f in fixes) if t and t["lines"])
    landed = landing_map(root, commits) if raw else {}
    traces = tuple(drop_pre_merge(t, landed) for t in raw)
    return {**sel, "fixes": fixes, "truncated": len(sel["fixes"]) > len(fixes),
            "traces": tuple(t for t in traces if t["lines"]),
            "caught_before_merge": sum(1 for t in traces if not t["lines"])}


def summary(collected: dict, by_sha: dict, now: int, group_of, windows) -> dict:
    traces = collected["traces"]
    ages = escape_ages(traces)
    fixes = len(collected["fixes"])
    return {
        "fix_commits": fixes, "from_subjects": collected["from_subjects"], "from_bug_prs": collected["from_bug_prs"],
        "traced": len(traces), "caught_before_merge": collected["caught_before_merge"],
        "untraceable": fixes - len(traces) - collected["caught_before_merge"], "truncated": collected["truncated"],
        "median_escape_age_days": median(ages) if ages else None,
        "overall": escape_rates(traces, by_sha, now, lambda c: "all", windows).get("all"),
        "by_class": escape_rates(traces, by_sha, now, group_of, windows),
    }
