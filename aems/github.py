"""T1 GitHub evidence via read-only gh calls. Degrades to 'unavailable' offline."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from .pr_review import pr_review_metrics, unobserved
from .runner import gh, git

_REMOTE_RE = re.compile(r"(?:github\.com[:/]|^[\w.-]+:)(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?/?$")


def parse_remote(url: str) -> tuple[str, str] | None:
    """owner/repo from https, scp-style and ssh-alias ('my-alias:owner/repo.git') remotes."""
    url = url.strip()
    if not url or (url.startswith(("http://", "https://")) and "github.com" not in url):
        return None
    m = _REMOTE_RE.search(url)
    if not m or {m.group("owner"), m.group("repo")} & {".", ".."} or m.group("repo").strip(".") == "":
        return None
    return m.group("owner"), m.group("repo")


def remote_slug(repo: Path) -> tuple[str, str] | None:
    out = git(repo, "remote", "get-url", "origin")
    return parse_remote(out) if out else None


def _iso_ts(value: str) -> int:
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except (ValueError, AttributeError):
        return 0


def _json(out: str | None):
    try:
        return json.loads(out) if out else None
    except json.JSONDecodeError:
        return None


def _runs(slug: str, since_ts: int) -> dict:
    out, note = gh("run", "list", "-R", slug, "--limit", "100",
                   "--json", "conclusion,status,event,workflowName,createdAt")
    data = _json(out)
    if data is None:
        return {"available": False, "note": note}
    recent = [r for r in data if _iso_ts(r.get("createdAt", "")) >= since_ts]
    decided = [r for r in recent if r.get("conclusion") in ("success", "failure", "timed_out", "startup_failure")]
    ok = sum(1 for r in decided if r["conclusion"] == "success")
    return {
        "available": True, "note": "gh run list (last 100, filtered to window)",
        "runs": len(recent), "decided": len(decided), "success": ok,
        "success_share": ok / len(decided) if decided else None,
        "pr_triggered": sum(1 for r in recent if r.get("event") == "pull_request"),
        "workflows": len({r.get("workflowName") for r in recent}),
    }


PR_FIELDS = "number,additions,deletions,createdAt,mergedAt,reviews,reviewDecision,author,comments"


def _prs(slug: str, since_ts: int) -> dict:
    out, note = gh("pr", "list", "-R", slug, "--state", "merged", "--limit", "200", "--json", PR_FIELDS)
    data = _json(out)
    if data is None:
        return unobserved(note if note != "ok" else "unparseable gh pr list output")
    return pr_review_metrics(data, since_ts, "gh pr list --state merged (last 200, filtered to window)")


def _protection(slug: str) -> dict:
    out, note = gh("repo", "view", slug, "--json", "defaultBranchRef,visibility")
    meta = _json(out) or {}
    branch = (meta.get("defaultBranchRef") or {}).get("name")
    if not branch:
        return {"visible": False, "note": note, "visibility": None}
    out, note = gh("api", f"repos/{slug}/branches/{quote(branch, safe='')}/protection")
    data = _json(out)
    base = {"branch": branch, "visibility": meta.get("visibility")}
    if data is None:
        return {**base, "visible": False, "note": note}
    reviews = data.get("required_pull_request_reviews") or {}
    return {
        **base, "visible": True, "note": "gh api GET branches/<default>/protection",
        "required_reviews": int(reviews.get("required_approving_review_count", 0)) if reviews else 0,
        "required_status_checks": bool(data.get("required_status_checks")),
    }


def fetch(repo: Path, since_ts: int, offline: bool) -> dict:
    slug_parts = remote_slug(repo)
    if slug_parts is None:
        return {"available": False, "note": "no GitHub remote", "slug": None}
    slug = "/".join(slug_parts)
    if offline:
        return {"available": False, "note": "offline mode", "slug": slug}
    runs = _runs(slug, since_ts)
    if not runs["available"] and "not authenticated" in runs["note"]:
        return {"available": False, "note": runs["note"], "slug": slug}
    return {"available": True, "slug": slug, "runs": runs, "prs": _prs(slug, since_ts),
            "protection": _protection(slug)}
