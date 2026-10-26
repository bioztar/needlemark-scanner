"""Read-only gh evidence for the query pack: merged PRs with review timestamps, labels and
merge commits; closing-issue links when the installed gh exposes them. Degrades, never raises."""
from __future__ import annotations

import json
import re

from .runner import gh

PACK_PR_FIELDS = "number,additions,deletions,createdAt,mergedAt,reviews,author,labels,mergeCommit"
CLOSING_FIELD = "closingIssuesReferences"


def _json_list(out: str | None):
    try:
        data = json.loads(out) if out else None
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def _labels(item: dict) -> tuple[str, ...]:
    raw = item.get("labels") if isinstance(item, dict) else None
    return tuple(str(x.get("name") or "") for x in raw if isinstance(x, dict)) if isinstance(raw, list) else ()


def _is_bug(item: dict, pattern: re.Pattern) -> bool:
    return any(pattern.search(name.lower()) for name in _labels(item))


def _bug_issues(slug: str, pattern: re.Pattern) -> frozenset[int] | None:
    out, _ = gh("issue", "list", "-R", slug, "--state", "all", "--limit", "1000", "--json", "number,labels")
    data = _json_list(out)
    if data is None:
        return None
    return frozenset(i["number"] for i in data if isinstance(i, dict) and isinstance(i.get("number"), int)
                     and _is_bug(i, pattern))


def _closes_bug(pr: dict, bug_issues: frozenset[int]) -> bool:
    refs = pr.get(CLOSING_FIELD)
    return isinstance(refs, list) and any(isinstance(r, dict) and r.get("number") in bug_issues for r in refs)


def _merge_sha(pr: dict) -> str | None:
    mc = pr.get("mergeCommit")
    oid = mc.get("oid") if isinstance(mc, dict) else None
    return oid if isinstance(oid, str) and re.fullmatch(r"[0-9a-f]{40}", oid) else None


def _pr_list(slug: str, fields: str):
    out, note = gh("pr", "list", "-R", slug, "--state", "merged", "--limit", "200", "--json", fields)
    return _json_list(out), note


def unavailable(note: str) -> dict:
    return {"available": False, "note": note, "prs": None, "bug_shas": frozenset(), "bug_links": "not observed"}


def fetch_pack_prs(slug: str | None, offline: bool, bug_label_pattern: str) -> dict:
    if slug is None:
        return unavailable("no GitHub remote")
    if offline:
        return unavailable("offline mode")
    prs, note = _pr_list(slug, f"{PACK_PR_FIELDS},{CLOSING_FIELD}")
    closing = prs is not None
    if prs is None:  # older gh does not know closingIssuesReferences
        prs, note = _pr_list(slug, PACK_PR_FIELDS)
    if prs is None:
        return unavailable(note if note != "ok" else "unparseable gh pr list output")
    pattern = re.compile(bug_label_pattern)
    issues = _bug_issues(slug, pattern) if closing else None
    bug = [p for p in prs if isinstance(p, dict)
           and (_is_bug(p, pattern) or (issues is not None and _closes_bug(p, issues)))]
    return {
        "available": True, "note": "gh pr list --state merged (last 200, filtered to window)", "prs": prs,
        "bug_shas": frozenset(s for s in (_merge_sha(p) for p in bug) if s),
        "bug_links": "PR labels + closing issues" if issues is not None else "PR labels",
    }
