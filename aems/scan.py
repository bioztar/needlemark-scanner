"""Scan one repo: T0 static + T1 git/CI history -> Report."""
from __future__ import annotations

import math
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from . import metrics as m
from .attribution import is_excluded_path
from .github import fetch
from .history import commit_count, load_commits
from .model import MODEL_VERSION, UNASSESSED_DIMS, Evidence, OutcomeCheck, Report
from .pack import PackOptions, run_pack
from .pr_review import unobserved
from .privacy import private_attribution, private_prs, private_rework
from .recommend import load_rules, select
from .repo_files import load_files
from .runner import git
from .scoring import overall, score_dim, unassessed_dim
from .static_context import context_checks, instruction_files
from .static_governance import governance_checks, governance_outcome_ok, secret_pattern_counts
from .static_harness import ci_runs_tests, guide_checks, sensor_checks
from .t1_dims import autonomy_checks, ci_outcome, hints, measurement_checks, rework_outcome

DAY = 86400
MAX_MERGES_SIZED = 60


class ScanError(Exception):
    pass


def _merge_sizes(root: Path, commits) -> tuple[int, ...]:
    sizes = []
    for c in [c for c in commits if c.is_merge and c.on_first_parent][:MAX_MERGES_SIZED]:
        out = git(root, "diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--numstat", c.parents[0], c.sha) or ""
        rows = (ln.split("\t") for ln in out.splitlines())
        sizes.append(sum(int(a) + int(d) for a, d, p in (r for r in rows if len(r) == 3)
                         if a.isdigit() and d.isdigit() and not is_excluded_path(p)))
    squash = [c.lines for c in commits if c.squash_pr]
    return tuple(sizes + squash)


def _json_safe(value):
    if isinstance(value, float) and math.isinf(value):
        return "inf"
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def report_to_dict(report: Report) -> dict:
    data = _json_safe(asdict(report))
    data["dims"] = [{**d, "name": dim.name, "label": dim.label} for d, dim in zip(data["dims"], report.dims)]
    return data


def _pr_signals(gh: dict) -> dict:
    """Fixed-shape PR review signals; 'not observed' whenever gh evidence is missing."""
    prs = gh.get("prs") if gh.get("available") else None
    return prs if isinstance(prs, dict) else unobserved(gh.get("note") or "GitHub evidence unavailable")


def _gather(root: Path, now: int, offline: bool, window_days: int, min_matured: int,
            pack: PackOptions | None = None) -> dict:
    since = now - window_days * DAY
    files = load_files(root)
    commits = load_commits(root, since_ts=since, vendor_of=pack.vendor_of() if pack else None)
    gh = fetch(root, since, offline)
    prs = _pr_signals(gh)
    pr_sizes = prs["sizes"] if prs["available"] else _merge_sizes(root, commits)
    ci_tests, _ = ci_runs_tests(files)
    return {
        "files": files, "commits": commits, "gh": gh, "prs": private_prs(prs), "since": since,
        "attr": private_attribution(m.attribution(commits), commits),
        "rework": private_rework(m.rework(commits, now=now, min_matured=min_matured), commits),
        "flow": m.flow(commits), "batch": m.batch(commits, pr_sizes), "churn": m.churn(commits),
        "vdr": m.vdr(commits, ci_runs_tests=ci_tests), "secrets": secret_pattern_counts(files),
    }


def _dims(g: dict) -> tuple:
    files, commits, attr = g["files"], g["commits"], g["attr"]
    rw_out = rework_outcome(g["rework"])
    ctx_checks, ctx_facts = context_checks(files, commits, attr["agent_commits"])
    gov_ok, gov_ev = governance_outcome_ok(files, g["secrets"])
    gov_out = OutcomeCheck(gov_ok, "hygiene outcome: no secret-shaped strings or secret-bearing files tracked", gov_ev)
    hint_map = hints(files, attr)
    dims = (
        score_dim(1, ctx_checks, rw_out),
        score_dim(2, guide_checks(files, commits), rw_out),
        score_dim(3, sensor_checks(files, commits), ci_outcome(g["gh"])),
        score_dim(5, autonomy_checks(g["flow"], g["batch"], g["gh"], files, instruction_files(files), g["prs"]), rw_out),
        score_dim(8, governance_checks(files, g["secrets"], attr["agent_commits"]), gov_out),
        score_dim(9, measurement_checks(attr, files, commits), rw_out),
    ) + tuple(unassessed_dim(d, hint_map[d]) for d in UNASSESSED_DIMS)
    return tuple(sorted(dims, key=lambda d: d.dim)), ctx_facts


def _notes(g: dict, window_days: int) -> tuple[str, ...]:
    notes = [
        f"History window: last {window_days} days ({len(g['commits'])} commits of {commit_count(g['files'].root)} total).",
        "Agent attribution is a lower bound: agent work committed without trailers or bot authors is invisible.",
        "T0/T1 only: dims 4, 6, 7 need T2 logs; levels >= 3 need outcome evidence or are capped at 2.",
    ]
    if not g["gh"].get("available"):
        notes.append(f"GitHub evidence unavailable: {g['gh'].get('note')}. CI outcome checks cannot pass.")
    if g["vdr"]["basis"] != "agent-attributed":
        notes.append(f"Verification-debt ratio: {g['vdr']['basis_note']}.")
    if g["secrets"]["truncated"]:
        notes.append("Secret-pattern scan truncated at the file limit.")
    return tuple(notes)


def _pack(g: dict, root: Path, now: int, offline: bool, pack: PackOptions | None) -> dict:
    if pack is None:
        return {}
    return {"pack": run_pack(root, g["commits"], g["gh"].get("slug"), offline, now, g["since"], pack)}


def scan_repo(path, now: int | None = None, offline: bool = False, window_days: int = 180,
              min_matured: int = 5, pack: PackOptions | None = None) -> Report:
    root = Path(path).resolve()
    if (git(root, "rev-parse", "--is-inside-work-tree") or "").strip() != "true":
        raise ScanError(f"not a readable git work tree: {root.name}")
    now = int(now if now is not None else time.time())
    g = _gather(root, now, offline, window_days, min_matured, pack)
    dims, ctx_facts = _dims(g)
    low, med, weakest = overall(dims)
    facts = {"vdr": g["vdr"]["value"], "stale_refs": ctx_facts["stale_refs"]}
    tiers = ("T0 static", "T1 git") + (("T1 GitHub",) if g["gh"].get("available") else ())
    gh_public = {**{k: v for k, v in g["gh"].items() if k != "prs"},
                 "prs": {k: v for k, v in g["prs"].items() if k != "sizes"}}
    return Report(
        repo=root.name,
        scanned_at=datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        model_version=MODEL_VERSION, tiers=tiers, dims=dims, overall=low, median=med, weakest=weakest,
        metrics={
            "window_days": window_days, "attribution": g["attr"], "rework": g["rework"], "flow": g["flow"],
            "batch": g["batch"], "churn": g["churn"], "vdr": g["vdr"], "secrets": g["secrets"],
            "github": gh_public, "context": ctx_facts, "rules_version": load_rules()["version"],
            **_pack(g, root, now, offline, pack),
        },
        recommendations=select(dims, facts, load_rules()),
        notes=_notes(g, window_days),
    )


__all__ = ["scan_repo", "report_to_dict", "ScanError", "Evidence"]
