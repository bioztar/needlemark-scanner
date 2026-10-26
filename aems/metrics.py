"""T1 metrics over Commit records. Pure functions, no I/O.

Rework proxy (adapted to commits):
  an agent commit A is "reworked" when a later fix-intent commit F (F != A,
  A.ts < F.ts <= A.ts + 30d) touches at least one code file A touched (docs,
  manifests, lockfiles and generated paths do not count as overlap).
  Only *matured* commits (A.ts + 30d <= now) enter the rate, so young commits
  cannot flatter it. Below `min_matured` the status is "insufficient".

Verification-debt ratio, one unit (changed lines):
  VDR = A / (T + G)
  A = non-test code lines (docs/manifests/lockfiles excluded) changed by agent-attributed commits; when fewer than
      25% of commits are attributed, A falls back to ALL non-test code lines
      (basis "total change volume"), because attribution is too thin to trust
  T = lines changed in test files (any author)
  G = A-basis lines that landed through a PR/merge path while CI runs tests
"""
from __future__ import annotations

from statistics import median

from .attribution import is_conventional, is_excluded_path, is_fix_intent, is_rework_relevant, is_test_path
from .model import Commit

DAY = 86400
REWORK_WINDOW_DAYS = 30
HEALTHY_REWORK_MAX = 0.20
VDR_GREEN_MAX = 1.0
VDR_AMBER_MAX = 3.0
MIN_ATTRIBUTION_COVERAGE = 0.25  # below this, agent attribution is too thin to be the VDR numerator


def _code_paths(commit: Commit) -> frozenset[str]:
    return frozenset(p for p in commit.paths if not is_excluded_path(p))


def _code_lines(commit: Commit) -> int:
    return sum(a + d for p, a, d in commit.files if not is_excluded_path(p))


def _rework_paths(commit: Commit) -> frozenset[str]:
    return frozenset(p for p in commit.paths if is_rework_relevant(p))


def _is_reworked(target: Commit, fixes: tuple[Commit, ...], window: int) -> bool:
    paths = _rework_paths(target)
    return any(
        f.sha != target.sha
        and target.ts < f.ts <= target.ts + window
        and paths & _rework_paths(f)
        for f in fixes
    )


def _rate(group: tuple[Commit, ...], fixes, now: int, window: int) -> tuple[int, int, int]:
    group = tuple(c for c in group if _rework_paths(c))  # docs-only commits cannot be reworked
    matured = tuple(c for c in group if c.ts + window <= now)
    reworked = sum(1 for c in matured if _is_reworked(c, fixes, window))
    return len(matured), reworked, len(group) - len(matured)


def rework(commits: tuple[Commit, ...], now: int, window_days: int = REWORK_WINDOW_DAYS,
           min_matured: int = 5) -> dict:
    window = window_days * DAY
    changes = tuple(c for c in commits if not c.is_merge)
    fixes = tuple(c for c in changes if is_fix_intent(c.subject))
    agent = tuple(c for c in changes if c.is_agent)
    human = tuple(c for c in changes if not c.is_agent)
    a_n, a_rw, a_open = _rate(agent, fixes, now, window)
    h_n, h_rw, _ = _rate(human, fixes, now, window)
    a_rate = a_rw / a_n if a_n else None
    if a_n < min_matured:
        status = "insufficient"
    else:
        status = "healthy" if a_rate <= HEALTHY_REWORK_MAX else "high"
    return {
        "window_days": window_days,
        "agent_matured": a_n,
        "agent_reworked": a_rw,
        "agent_open_window": a_open,
        "agent_rate": a_rate,
        "human_matured": h_n,
        "human_reworked": h_rw,
        "human_rate": h_rw / h_n if h_n else None,
        "min_matured": min_matured,
        "status": status,
    }


def _gated(commit: Commit) -> bool:
    return (not commit.on_first_parent) or commit.squash_pr


def _volume_lines(commit: Commit) -> int:
    """Changed lines that need verifying: code, not tests, docs, manifests or lockfiles."""
    return sum(a + d for p, a, d in commit.files if is_rework_relevant(p) and not is_test_path(p))


def vdr(commits: tuple[Commit, ...], ci_runs_tests: bool, min_coverage: float = MIN_ATTRIBUTION_COVERAGE) -> dict:
    changes = tuple(c for c in commits if not c.is_merge)
    agent = tuple(c for c in changes if c.is_agent)
    coverage = len(agent) / len(changes) if changes else 0.0
    thin = coverage < min_coverage
    basis_set = changes if thin else agent
    a_lines = sum(_volume_lines(c) for c in basis_set)
    t_lines = sum(a + d for c in changes for p, a, d in c.files if is_test_path(p) and not is_excluded_path(p))
    g_lines = sum(_volume_lines(c) for c in basis_set if _gated(c)) if ci_runs_tests else 0
    capacity = t_lines + g_lines
    if a_lines == 0:
        value, status = None, "n/a"
    elif capacity == 0:
        value, status = float("inf"), "red"
    else:
        value = a_lines / capacity
        status = "green" if value <= VDR_GREEN_MAX else "amber" if value <= VDR_AMBER_MAX else "red"
    note = (f"low attribution coverage: {coverage:.0%} of commits attributed; numerator falls back to "
            f"total change volume" if thin else f"{coverage:.0%} of commits attributed")
    return {
        "value": value, "status": status, "agent_lines": a_lines, "test_lines": t_lines,
        "gated_agent_lines": g_lines, "ci_runs_tests": ci_runs_tests,
        "basis": "total change volume" if thin else "agent-attributed",
        "coverage": coverage, "basis_note": note,
    }


def flow(commits: tuple[Commit, ...]) -> dict:
    fp = tuple(c for c in commits if c.on_first_parent)
    pr_landed = sum(1 for c in fp if c.is_merge or c.squash_pr)
    agent = tuple(c for c in commits if c.is_agent and not c.is_merge)
    gated = sum(1 for c in agent if _gated(c))
    return {
        "first_parent_changes": len(fp),
        "pr_landed": pr_landed,
        "direct": len(fp) - pr_landed,
        "pr_share": pr_landed / len(fp) if fp else None,
        "agent_commits": len(agent),
        "agent_gated": gated,
        "agent_gated_share": gated / len(agent) if agent else None,
    }


def attribution(commits: tuple[Commit, ...]) -> dict:
    changes = tuple(c for c in commits if not c.is_merge)
    agent = tuple(c for c in changes if c.is_agent)
    by_tool: dict[str, int] = {}
    for c in agent:
        for label in c.agents:
            by_tool = {**by_tool, label: by_tool.get(label, 0) + 1}
    by_class: dict[str, int] = {}
    for c in changes:
        by_class = {**by_class, c.identity_class: by_class.get(c.identity_class, 0) + 1}
    total_lines = sum(_code_lines(c) for c in changes)
    agent_lines = sum(_code_lines(c) for c in agent)
    return {
        "commits": len(changes),
        "agent_commits": len(agent),
        "ai_share_commits": len(agent) / len(changes) if changes else None,
        "ai_share_lines": agent_lines / total_lines if total_lines else None,
        "by_tool": dict(sorted(by_tool.items())),
        "by_class": by_class,
        "conventional_share": (sum(1 for c in changes if is_conventional(c.subject)) / len(changes)
                               if changes else None),
        "fix_commits": sum(1 for c in changes if is_fix_intent(c.subject)),
        "fix_commits_touching_tests": sum(
            1 for c in changes if is_fix_intent(c.subject) and any(is_test_path(p) for p in c.paths)),
    }


def batch(commits: tuple[Commit, ...], pr_sizes: tuple[int, ...] = ()) -> dict:
    sizes = sorted(_code_lines(c) for c in commits if not c.is_merge)
    agent_sizes = sorted(_code_lines(c) for c in commits if c.is_agent and not c.is_merge)

    def p90(xs):
        return xs[min(len(xs) - 1, int(0.9 * len(xs)))] if xs else None

    return {
        "commit_median_lines": median(sizes) if sizes else None,
        "commit_p90_lines": p90(sizes),
        "agent_commit_median_lines": median(agent_sizes) if agent_sizes else None,
        "pr_median_lines": median(pr_sizes) if pr_sizes else None,
        "pr_p90_lines": p90(sorted(pr_sizes)),
        "pr_sample": len(pr_sizes),
    }


def churn(commits: tuple[Commit, ...], retouch_days: int = 14) -> dict:
    changes = sorted((c for c in commits if not c.is_merge), key=lambda c: c.ts)
    added = sum(a for c in changes for p, a, _ in c.files if not is_excluded_path(p))
    deleted = sum(d for c in changes for p, _, d in c.files if not is_excluded_path(p))
    window = retouch_days * DAY
    last_touch: dict[str, int] = {}
    retouched = 0
    for c in changes:
        paths = _code_paths(c)
        if any(c.ts - last_touch.get(p, -10 * window) <= window for p in paths):
            retouched += 1
        last_touch = {**last_touch, **{p: c.ts for p in paths}}
    return {
        "lines_added": added,
        "lines_deleted": deleted,
        "delete_add_ratio": deleted / added if added else None,
        "retouch_days": retouch_days,
        "retouch_share": retouched / len(changes) if changes else None,
    }


def group_rework(group: tuple[Commit, ...], commits: tuple[Commit, ...], now: int,
                 window_days: int = REWORK_WINDOW_DAYS) -> tuple[int, int, int]:
    """(matured, reworked, open window) for any commit group, same rework proxy as rework()."""
    fixes = tuple(c for c in commits if not c.is_merge and is_fix_intent(c.subject))
    return _rate(tuple(c for c in group if not c.is_merge), fixes, now, window_days * DAY)
