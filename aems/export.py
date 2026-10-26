"""Numbers-only export: the only artefact meant to leave the client's environment.

Built from an explicit allow-list of fields (never by stripping a full dump), so
new report fields can never leak by default. Contains levels, ratios, counts,
status enums, agent-class labels and rule ids. It contains no file paths, no
commit subjects, no people, no remote slug, no branch or workflow names, and
the repo name is replaced by a hash unless keep_name is set.

Hashing note: sha256 of a short name is guessable by dictionary; set
AEMS_EXPORT_SALT for a stable, non-guessable id across runs.
"""
from __future__ import annotations

import hashlib
import math
import os

from .model import MODEL_ID, Report
from .pack_export import export_pack
from .privacy import SUPPRESSED

SCHEMA = "aems-export-4"
_SAFE_KEYS = {
    "attribution": ("commits", "agent_commits", "ai_share_commits", "ai_share_lines", "conventional_share",
                    "fix_commits", "fix_commits_touching_tests"),
    "rework": ("window_days", "agent_matured", "agent_reworked", "agent_open_window", "agent_rate",
               "human_matured", "human_reworked", "human_rate", "min_matured", "status"),
    "flow": ("first_parent_changes", "pr_landed", "direct", "pr_share", "agent_commits", "agent_gated",
             "agent_gated_share"),
    "batch": ("commit_median_lines", "commit_p90_lines", "agent_commit_median_lines", "pr_median_lines",
              "pr_p90_lines", "pr_sample"),
    "churn": ("lines_added", "lines_deleted", "delete_add_ratio", "retouch_days", "retouch_share"),
    "secrets": ("files_scanned", "files_with_hits", "pattern_hits", "truncated"),
    "context": ("stale_refs", "instruction_lines_max", "mcp_configs", "skills"),
}


def repo_id(name: str, keep_name: bool = False) -> str:
    if keep_name:
        return name
    salt = os.environ.get("AEMS_EXPORT_SALT", "")
    return hashlib.sha256((salt + name).encode()).hexdigest()[:12]


def _number(value):
    if isinstance(value, float) and math.isinf(value):
        return None
    return value


def _pick(src: dict, keys: tuple[str, ...]) -> dict:
    return {k: _number(src.get(k)) for k in keys}


def _counts(mapping: dict) -> dict:
    """Class -> count; the k-anonymity marker passes through unchanged."""
    return {str(k): v if v == SUPPRESSED else int(v) for k, v in mapping.items()}


def _vdr(v: dict) -> dict:
    unbounded = isinstance(v["value"], float) and math.isinf(v["value"])
    return {
        "value": None if unbounded else v["value"], "unbounded": unbounded, "status": v["status"],
        "basis": v["basis"], "coverage": v["coverage"], "numerator_lines": v["agent_lines"],
        "test_lines": v["test_lines"], "gated_lines": v["gated_agent_lines"], "ci_runs_tests": v["ci_runs_tests"],
    }


def _github(gh: dict) -> dict:
    runs = gh.get("runs") or {}
    prs = gh.get("prs") or {}
    prot = gh.get("protection") or {}
    return {
        "available": bool(gh.get("available")),
        "ci_runs": runs.get("runs"), "ci_decided": runs.get("decided"), "ci_success_share": runs.get("success_share"),
        "ci_pr_triggered": runs.get("pr_triggered"), "prs_merged": prs.get("merged"),
        "prs_agent_authored": prs.get("agent_authored"), "prs_observed": bool(prs.get("available")),
        "prs_reviewed": prs.get("reviewed"), "prs_reviewed_share": prs.get("reviewed_share"),
        "prs_merged_unreviewed": prs.get("unreviewed"), "prs_agent_unreviewed": prs.get("agent_unreviewed"),
        "prs_human_reviewed": prs.get("human_reviewed"), "prs_agent_reviewed": prs.get("agent_reviewed"),
        "pr_median_size_lines": prs.get("median_size_lines"), "pr_median_hours_to_merge": prs.get("median_hours_to_merge"),
        "pr_review_comments_mean": prs.get("review_comments_mean"), "pr_reviewed_lines_share": prs.get("reviewed_lines_share"),
        "prs_by_author_class": _counts(prs.get("by_author_class") or {}),
        "protection_visible": bool(prot.get("visible")), "required_reviews": prot.get("required_reviews"),
        "required_status_checks": prot.get("required_status_checks"),
    }


def _dim(d) -> dict:
    return {
        "dim": d.dim, "assessed": d.assessed, "level": d.level, "raw_level": d.raw_level, "capped": d.capped,
        "checks_met": sum(1 for c in d.checks if c.passed), "checks_total": len(d.checks),
        "checks": [{"level": c.level, "met": c.passed} for c in d.checks],
        "outcome_met": None if d.outcome is None else d.outcome.passed,
    }


def export_report(report: Report, keep_name: bool = False, keep_vendor_names: bool = False) -> dict:
    mt = report.metrics
    attr = mt["attribution"]
    return {
        "schema": SCHEMA, "model": MODEL_ID, "rules": mt.get("rules_version"),
        "scanned_at": report.scanned_at, "repo_id": repo_id(report.repo, keep_name),
        "tiers": list(report.tiers), "overall": report.overall, "median": report.median,
        "weakest": list(report.weakest), "dims": [_dim(d) for d in report.dims],
        "window_days": mt["window_days"],
        "attribution": {**_pick(attr, _SAFE_KEYS["attribution"]), "by_class": _counts(attr["by_class"]),
                        "by_agent": _counts(attr["by_tool"])},
        **{k: _pick(mt[k], _SAFE_KEYS[k]) for k in ("rework", "flow", "batch", "churn", "context")},
        "secrets": {**_pick(mt["secrets"], _SAFE_KEYS["secrets"]), "by_pattern": _counts(mt["secrets"]["by_pattern"])},
        "vdr": _vdr(mt["vdr"]), "github": _github(mt["github"]),
        "recommendations": [r.rule_id for r in report.recommendations],
        "pack": export_pack(mt.get("pack"), keep_vendor_names),
    }


def export_portfolio(summary: dict, keep_name: bool = False) -> dict:
    rows = []
    for r in summary["rows"]:
        base = {"repo_id": repo_id(r["repo"], keep_name), "error": bool(r.get("error"))}
        if r.get("error"):
            rows.append(base)
            continue
        vdr = r["vdr"]
        unbounded = isinstance(vdr, float) and math.isinf(vdr)
        rows.append({
            **base, "overall": r["overall"], "median": r["median"], "levels": r["levels"],
            "capped": r["capped"], "weakest": r["weakest"], "vdr": None if unbounded else vdr,
            "vdr_unbounded": unbounded, "vdr_status": r["vdr_status"], "vdr_basis": r.get("vdr_basis"),
            "ai_share_commits": r["ai_share_commits"], "agent_commits": r["agent_commits"], "commits": r["commits"],
            "rework_rate": r["rework_rate"], "rework_status": r["rework_status"], "github": r["github"],
            "top_move": r["top_move"], "pr_reviewed_share": r.get("pr_reviewed_share"),
            "prs_merged": r.get("prs_merged"), "prs_merged_unreviewed": r.get("prs_merged_unreviewed"),
            "pack_rubber_stamp_rate": r.get("pack_rubber_stamp_rate"),
            "pack_escaped_per_1k_90": r.get("pack_escaped_per_1k_90"), "pack_fix_commits": r.get("pack_fix_commits"),
        })
    return {"schema": SCHEMA, "model": MODEL_ID, "repos": rows}
