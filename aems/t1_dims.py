"""Dimensions 5 (autonomy & review line) and 9 (measurement), plus outcome
checks and presence hints for the T2-only dims 4, 6, 7."""
from __future__ import annotations

import re

from .model import Check, Evidence, OutcomeCheck
from .repo_files import RepoFiles
from .runner import git

MAX_BATCH_LINES = 400
AUTONOMY_RE = re.compile(r"\b(local-only|direct-PR|full-gate|no-mistakes|yolo|autonomy (level|mode)|blast radius|"
                         r"risk[- ]tier|requires? (human )?approval|human review)\b", re.I)
MEASURE_RE = (r"(^|/)(metrics|dora|scorecards?|kpis?|retros?|retrospectives|insights)(/|\.md$|\.json$)"
              r"|(^|/)[^/]*(metrics|dora|scorecard)[^/]*\.(md|json|csv|py|sh|js|ts)$")


def _pct(x) -> str:
    if isinstance(x, str):  # k-anonymity marker
        return x
    return "n/a" if x is None else f"{x:.0%}"


PR_SRC = "gh pr list --state merged --json reviews,reviewDecision,comments,author"


def _hours(x) -> str:
    return "n/a" if x is None else f"{x:.1f}"


def pr_evidence(prs: dict | None) -> tuple[Evidence, ...]:
    """Dim-5 review-line evidence from merged PRs; 'not observed' when gh evidence is missing."""
    prs = prs or {}
    if not prs.get("available"):
        return (Evidence("merged PRs with a formal review", f"not observed ({prs.get('note') or 'no GitHub evidence'})", PR_SRC),)
    n = prs["merged"]
    if not n:
        return (Evidence("merged PRs with a formal review", "0 merged PRs in window", PR_SRC),)
    return (
        Evidence("merged PRs with a formal review", f"{prs['reviewed']}/{n} ({_pct(prs['reviewed_share'])})",
                 "non-author APPROVED/CHANGES_REQUESTED/COMMENTED review, or decision APPROVED/CHANGES_REQUESTED"),
        Evidence("PRs merged unreviewed (of them agent-authored)", f"{prs['unreviewed']} ({prs['agent_unreviewed']})", PR_SRC),
        Evidence("review comments per PR (mean)", "n/a" if prs["review_comments_mean"] is None else f"{prs['review_comments_mean']:.2f}",
                 "non-author conversation comments + reviews, non-agent bots excluded; inline diff comments not visible"),
        Evidence("median time to merge (hours)", _hours(prs["median_hours_to_merge"]), "mergedAt - createdAt"),
    )


MIN_PRS_FOR_GATE = 5
GATE_LABEL = "No agent-authored PR merged without a formal review (when >= 5 merged PRs observed)"


def unreviewed_agent_pr_check(prs: dict | None) -> Check:
    """An unreviewed agent PR blocks dim-5 L3. Not applied without enough PR data."""
    prs = prs or {}
    n = prs.get("merged") if prs.get("available") else None
    if n is None or n < MIN_PRS_FOR_GATE:
        why = "PR data not observed" if n is None else f"{n} merged PRs < {MIN_PRS_FOR_GATE}"
        return Check(3, GATE_LABEL, True, (Evidence("agent PRs merged unreviewed", f"rule not applied ({why})", PR_SRC),))
    bad, agent = prs["agent_unreviewed"], prs["agent_authored"]
    return Check(3, GATE_LABEL, bad == 0, (Evidence("agent PRs merged unreviewed", f"{bad} of {agent}", PR_SRC),))


def autonomy_checks(flow: dict, batch: dict, gh: dict, files: RepoFiles, instr_paths: tuple[str, ...],
                    prs: dict | None = None) -> tuple[Check, ...]:
    prot = gh.get("protection", {}) if gh.get("available") else {}
    protected = bool(prot.get("visible") and (prot.get("required_reviews") or prot.get("required_status_checks")))
    owners = bool(files.matching_re(r"(^|/)CODEOWNERS$"))
    policy_hits = sum(len(AUTONOMY_RE.findall(files.read_text(p) or "")) for p in instr_paths)
    size = batch["pr_median_lines"] if batch["pr_median_lines"] is not None else batch["commit_median_lines"]
    size_src = "gh pr list additions+deletions" if batch["pr_median_lines"] is not None else "git numstat per commit"
    agent_gated = flow["agent_gated"]
    ev_pr = pr_evidence(prs)
    ev_flow = (Evidence("first-parent changes landed via PR/merge", f"{flow['pr_landed']}/{flow['first_parent_changes']} ({_pct(flow['pr_share'])})",
                        "git rev-list --first-parent; merge commits + '(#N)' squash subjects"),
               Evidence("agent commits landed via PR/merge", f"{agent_gated}/{flow['agent_commits']} ({_pct(flow['agent_gated_share'])})",
                        "commits off first-parent or squash-PR"))
    return (
        Check(1, "Agent-attributed changes present", flow["agent_commits"] > 0, ev_flow[1:]),
        Check(2, "At least one agent change landed through a PR/merge", agent_gated > 0, ev_flow),
        Check(3, ">= 60% of changes land via PR/merge", (flow["pr_share"] or 0) >= 0.6, ev_flow[:1] + ev_pr[:1]),
        Check(3, ">= 60% of agent commits land via PR/merge", (flow["agent_gated_share"] or 0) >= 0.6, ev_flow[1:]),
        unreviewed_agent_pr_check(prs),
        Check(3, f"Small batches (median <= {MAX_BATCH_LINES} changed lines)", size is not None and size <= MAX_BATCH_LINES,
              (Evidence("median batch size (lines)", "n/a" if size is None else f"{size:g}", size_src),)),
        Check(4, "Explicit autonomy/review policy in instruction files", policy_hits > 0,
              (Evidence("autonomy-policy keyword hits (counted)", str(policy_hits), "instruction files; modes, approval, risk tiers"),)),
        Check(4, "Enforced review line (branch protection or CODEOWNERS)", protected or owners,
              (Evidence("branch protection", "requires reviews/checks" if protected else prot.get("note", "not checked"), "gh api GET .../protection"),
               Evidence("CODEOWNERS", "present" if owners else "absent", "git ls-files")) + ev_pr),
        Check(5, "Per-step earned autonomy with measured outcomes", False,
              (Evidence("observable at T1", "no", "needs T2 logs"),)),
    )


def measurement_checks(attr: dict, files: RepoFiles, commits) -> tuple[Check, ...]:
    artefacts = files.matching_re(MEASURE_RE)
    art_set = set(artefacts)
    art_updates = sum(1 for c in commits if c.paths & art_set)
    tools = ", ".join(f"{k} {v}" for k, v in attr["by_tool"].items()) or "none"
    return (
        Check(1, "Agent attribution present in history", attr["agent_commits"] > 0,
              (Evidence("agent-attributed commits (lower bound)", f"{attr['agent_commits']}/{attr['commits']}", "Co-authored-by trailers, bot authors, footer grep"),
               Evidence("by tool", tools, "attribution classifier"))),
        Check(2, "Commit intent is classifiable (>= 50% conventional subjects)", (attr["conventional_share"] or 0) >= 0.5,
              (Evidence("conventional-commit share", _pct(attr["conventional_share"]), "subject prefix classifier (subjects not rendered)"),)),
        Check(3, "Measurement artefacts tracked in repo", bool(artefacts),
              (Evidence("metrics/retro/scorecard files", ", ".join(artefacts[:5]) or "none", MEASURE_RE),)),
        Check(4, "Measurement reviewed on a cadence (artefacts updated >= 3x in window)", art_updates >= 3,
              (Evidence("commits updating measurement artefacts", str(art_updates), "git log --numstat"),)),
        Check(5, "Measured first-pass/rework trends drive changes", False,
              (Evidence("observable at T1", "no", "needs T2 logs + outcome join"),)),
    )


def rework_outcome(rw: dict) -> OutcomeCheck:
    rate = "n/a" if rw["agent_rate"] is None else f"{rw['agent_rate']:.0%}"
    human = _pct(rw["human_rate"])
    ev = (Evidence("agent rework rate (matured commits)", f"{rate} of {rw['agent_matured']}", f"fix/revert/hotfix within {rw['window_days']}d on same files"),
          Evidence("human-only baseline (contains unattributed agent work)", f"{human} of {rw['human_matured']}", "same rule"),
          Evidence("agent commits with open window (excluded)", str(rw["agent_open_window"]), f"younger than {rw['window_days']}d"))
    if rw["status"] == "insufficient":
        return OutcomeCheck(False, f"insufficient outcome evidence (< {rw['min_matured']} matured agent commits)", ev)
    return OutcomeCheck(rw["status"] == "healthy", f"agent rework {rw['status']} (healthy <= 20%)", ev)


def ci_outcome(gh: dict) -> OutcomeCheck:
    runs = gh.get("runs", {}) if gh.get("available") else {}
    if not runs.get("available"):
        note = gh.get("note") or runs.get("note") or "unavailable"
        return OutcomeCheck(False, f"no CI run evidence ({note})", (Evidence("gh run list", note, "gh run list"),))
    share = runs["success_share"]
    ok = runs["decided"] >= 5 and share is not None and share >= 0.7
    return OutcomeCheck(ok, "gates observed running and mostly green (>= 5 runs, >= 70% success)",
                        (Evidence("CI runs in window", f"{runs['runs']} ({runs['pr_triggered']} on pull_request)", "gh run list"),
                         Evidence("success share of decided runs", f"{_pct(share)} of {runs['decided']}", "gh run list --json conclusion")))


def hints(files: RepoFiles, attr: dict) -> dict[int, tuple[Evidence, ...]]:
    wt = git(files.root, "worktree", "list", "--porcelain") or ""
    worktrees = wt.count("\nworktree ") + (1 if wt.startswith("worktree ") else 0)

    def ev(label, rx):
        hits = files.matching_re(rx)
        return Evidence(label, f"{len(hits)}" + (f": {', '.join(hits[:3])}" if hits else ""), rx)

    return {
        4: (Evidence("git worktrees registered", str(worktrees), "git worktree list"),
            ev("subagent/crew definitions", r"(^|/)\.claude/agents/|(^|/)(fleet|crew|missions)/"),
            ev("loop/orchestration scripts", r"(^|/)(PROMPT\.md|ralph[^/]*|dispatch[^/]*|orchestrat[^/]*)$"),
            Evidence("distinct agent tools attributed", str(len(attr["by_tool"])), "attribution classifier")),
        6: (ev("eval/golden/benchmark dirs", r"(^|/)(evals?|golden|benchmarks?)/"),
            ev("agent-reviewer configs", r"(^|/)(\.coderabbit\.ya?ml|\.cubic[^/]*|\.github/copilot-review[^/]*|\.greptile[^/]*)$")),
        7: (ev("handover/memory files", r"(^|/)(HANDOVER|MEMORY|LESSONS|LEARNINGS)[^/]*\.md$|(^|/)memory/"),
            ev("retro/decision logs", r"(^|/)(retros?|decisions|adr)/|(^|/)(CHANGELOG|DECISIONS)[^/]*\.md$")),
    }
