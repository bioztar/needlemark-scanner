"""Dimension 8 — Governance, security & cost.

Secret detection is COUNT-ONLY: matches are counted per pattern family and
never stored, logged or rendered. Deny-listed files (.env*, keys, credential
stores) are never opened at all.
"""
from __future__ import annotations

import json
import re

from .model import Check, Evidence
from .repo_files import RepoFiles, is_secret_like_tracked

MAX_SCAN_FILES = 6000

SECRET_PATTERNS = {
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github_token": re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "slack_token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "private_key_block": re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "anthropic_key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    "openai_key": re.compile(r"\bsk-(proj-)?[A-Za-z0-9]{32,}\b"),
    "stripe_live_key": re.compile(r"\b[sr]k_live_[A-Za-z0-9]{20,}"),
}
_SCAN_SKIP_RE = re.compile(r"\.(png|jpe?g|gif|webp|ico|pdf|zip|gz|woff2?|ttf|mp4|mp3|lock)$|(^|/)node_modules/", re.I)

PERMISSION_FILES_RE = r"(^|/)\.claude/settings\.json$|^\.codex/config\.toml$|^\.gemini/settings\.json$|^\.cursor/cli\.json$|^\.aider\.conf\.ya?ml$"
SECRET_SCAN_RE = r"(^|/)(\.gitleaks\.toml|gitleaks\.toml|\.secrets\.baseline|\.trufflehog[^/]*|\.talismanrc|\.git-secrets[^/]*)$"
SECRET_TOOL_RE = re.compile(r"\b(gitleaks|detect-secrets|trufflehog|talisman|git-secrets|ggshield|secret-scan)", re.I)
CODEOWNERS = ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS", ".gitlab/CODEOWNERS")


def secret_pattern_counts(files: RepoFiles) -> dict:
    """Count secret-shaped strings in tracked text files. Values never leave this function."""
    hits: dict[str, int] = {}
    files_with_hits = 0
    scanned = 0
    for rel in files.paths[:MAX_SCAN_FILES]:
        if _SCAN_SKIP_RE.search(rel):
            continue
        text = files.read_text(rel)  # deny-listed paths return None, never opened
        if text is None:
            continue
        scanned += 1
        file_hits = {name: len(rx.findall(text)) for name, rx in SECRET_PATTERNS.items()}
        file_hits = {k: v for k, v in file_hits.items() if v}
        if file_hits:
            files_with_hits += 1
            hits = {k: hits.get(k, 0) + file_hits.get(k, 0) for k in set(hits) | set(file_hits)}
    return {
        "files_scanned": scanned,
        "files_with_hits": files_with_hits,
        "pattern_hits": sum(hits.values()),
        "by_pattern": dict(sorted(hits.items())),
        "truncated": len(files.paths) > MAX_SCAN_FILES,
    }


def _gitignore_covers_env(files: RepoFiles) -> bool:
    text = files.read_text(".gitignore") or ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    return any(re.fullmatch(r"/?(\*\*/)?\.env(\*|\.\*|\.local|\*\.local)?", ln) for ln in lines)


def _permission_entries(files: RepoFiles, paths: tuple[str, ...]) -> int:
    total = 0
    for rel in paths:
        if not rel.endswith(".json"):
            total += 1
            continue
        try:
            perms = json.loads(files.read_text(rel) or "{}").get("permissions", {})
        except (json.JSONDecodeError, AttributeError):
            continue
        if isinstance(perms, dict):
            total += sum(len(v) for k, v in perms.items() if k in ("allow", "deny", "ask") and isinstance(v, list))
    return total


def governance_checks(files: RepoFiles, secrets: dict, agent_commits: int) -> tuple[Check, ...]:
    tracked_secret_files = tuple(p for p in files.paths if is_secret_like_tracked(p))
    perm_files = files.matching_re(PERMISSION_FILES_RE)
    perm_entries = _permission_entries(files, perm_files)
    scan_cfg = files.matching_re(SECRET_SCAN_RE)
    hook_and_ci = files.matching_re(r"(^|/)\.pre-commit-config\.ya?ml$|^\.github/workflows/|^\.husky/")
    scan_tools = tuple(p for p in hook_and_ci if SECRET_TOOL_RE.search(files.read_text(p) or ""))
    owners = tuple(p for p in CODEOWNERS if files.exists(p))
    mcp = files.matching_re(r"(^|/)\.?mcp\.json$")
    return (
        Check(1, ".gitignore present", files.exists(".gitignore"), (Evidence(".gitignore", "present" if files.exists(".gitignore") else "absent", ".gitignore"),)),
        Check(2, ".gitignore covers .env files", _gitignore_covers_env(files), (Evidence("env ignore rule", "yes" if _gitignore_covers_env(files) else "no", ".gitignore"),)),
        Check(2, "No tracked secret-bearing files (.env, keys, credential files)", not tracked_secret_files,
              (Evidence("tracked secret-like files (names only)",
                       str(len(tracked_secret_files)) + (": " + ", ".join(tracked_secret_files[:5]) if tracked_secret_files else ""),
                       "git ls-files name classifier"),)),
        Check(3, "Agent tool permissions declared (allow/deny lists)", perm_entries > 0,
              (Evidence("permission config files", ", ".join(perm_files) or "none", PERMISSION_FILES_RE),
               Evidence("allow/deny/ask entries", str(perm_entries), "permissions keys (counted, not rendered)"))),
        Check(3, "Secret scanning configured (pre-commit or CI)", bool(scan_cfg or scan_tools),
              (Evidence("secret-scan configs/hooks", ", ".join(scan_cfg + scan_tools) or "none", SECRET_SCAN_RE),)),
        Check(4, "CODEOWNERS on the review path", bool(owners), (Evidence("CODEOWNERS", ", ".join(owners) or "absent", " | ".join(CODEOWNERS)),)),
        Check(4, "AI-share attribution present (receipts)", agent_commits > 0,
              (Evidence("agent-attributed commits", str(agent_commits), "git log trailers/authors"),
               Evidence("MCP configs", ", ".join(mcp) or "none", ".mcp.json"))),
        Check(5, "Audit receipts and per-task cost budgets", False,
              (Evidence("observable at T0/T1", "no", "needs T2 logs / T3 interview"),)),
    )


def governance_outcome_ok(files: RepoFiles, secrets: dict) -> tuple[bool, tuple[Evidence, ...]]:
    tracked = sum(1 for p in files.paths if is_secret_like_tracked(p))
    ok = tracked == 0 and secrets["pattern_hits"] == 0
    return ok, (
        Evidence("secret-shaped strings in tracked files (count only)", str(secrets["pattern_hits"]),
                 f"{len(SECRET_PATTERNS)} pattern families over {secrets['files_scanned']} files"),
        Evidence("tracked secret-like files", str(tracked), "git ls-files name classifier"),
    )
