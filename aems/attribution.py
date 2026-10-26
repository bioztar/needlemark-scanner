"""Agent attribution and commit/path classification.

Attribution matches on emails and bot logins, never on human display names, and
is a LOWER BOUND: commits made with agents but without trailers are invisible.
"""
from __future__ import annotations

import re

# (label, compiled pattern) matched against "name <email>" of authors and co-authors.
_AGENT_PATTERNS = (
    ("Claude", re.compile(r"noreply@anthropic\.com|\bclaude\[bot\]", re.I)),
    ("Devin", re.compile(r"devin-ai-integration", re.I)),
    ("Copilot", re.compile(r"\+copilot@users\.noreply\.github\.com|copilot-swe-agent|github-copilot\[bot\]|^copilot\s*<", re.I)),
    ("Cursor", re.compile(r"cursoragent@cursor\.com|cursor-agent|\bcursor\[bot\]", re.I)),
    ("Codex", re.compile(r"codex[-\w]*\[bot\]|chatgpt-codex|codex@openai\.com", re.I)),
    ("Jules", re.compile(r"google-labs-jules", re.I)),
    ("Gemini", re.compile(r"gemini-code-assist|gemini-cli", re.I)),
    ("Aider", re.compile(r"\(aider\)", re.I)),
    ("Amp", re.compile(r"amp@ampcode\.com", re.I)),
)

_FIX_RE = re.compile(
    r"^(fix|hotfix|bugfix|revert)(\(.+?\))?!?:"  # conventional fix/hotfix/revert
    r"|^revert\b"                                 # git revert default subject
    r"|^(fixup|squash)!"                           # autosquash markers
    r"|^(fix|fixes|fixed|hotfix)\b",               # plain-English leading verb
    re.I,
)

_CONVENTIONAL_RE = re.compile(r"^[a-z]+(\(.+?\))?!?: ", re.I)

_TEST_RE = re.compile(
    r"(^|/)(tests?|__tests__|spec|specs|e2e|testing)/"
    r"|(^|/)test_[^/]+$|_test\.[a-z]+$|\.(test|spec)\.[a-z]+$|(^|/)conftest\.py$",
    re.I,
)

_EXCLUDED_RE = re.compile(
    r"(^|/)(package-lock\.json|pnpm-lock\.yaml|yarn\.lock|bun\.lockb?|poetry\.lock|uv\.lock"
    r"|Pipfile\.lock|Cargo\.lock|go\.sum|composer\.lock|Gemfile\.lock)$"
    r"|(^|/)(node_modules|dist|build|vendor|\.next|out|coverage|__pycache__)/"
    r"|\.min\.(js|css)$|\.map$|\.snap$",
    re.I,
)


# Shared, high-traffic files that every change touches; overlap on them is not rework.
_NON_CODE_RE = re.compile(
    r"\.(md|mdx|txt|rst|adoc)$"
    r"|(^|/)(package\.json|pyproject\.toml|requirements[^/]*\.txt|Cargo\.toml|go\.mod|Gemfile|composer\.json"
    r"|\.gitignore|\.env\.example|LICENSE[^/]*)$",
    re.I,
)


def is_rework_relevant(path: str) -> bool:
    """Code-ish paths whose overlap with a later fix suggests rework."""
    return not is_excluded_path(path) and not _NON_CODE_RE.search(path)


def agents_for(author_name: str, author_email: str, coauthors: tuple[str, ...],
               generated_footer: bool) -> tuple[str, ...]:
    """Return the sorted, unique agent labels attributable to one commit."""
    identities = (f"{author_name} <{author_email}>",) + tuple(coauthors)
    found = {
        label
        for ident in identities
        for label, pattern in _AGENT_PATTERNS
        if pattern.search(ident)
    }
    if generated_footer:
        found = found | {"Claude"}
    return tuple(sorted(found))


_BOT_RE = re.compile(r"\[bot\]|^(renovate|dependabot|github-actions|snyk-bot|pre-commit-ci)\b", re.I)


def is_bot(author_name: str, author_email: str) -> bool:
    return bool(_BOT_RE.search(author_name) or _BOT_RE.search(author_email))


def is_fix_intent(subject: str) -> bool:
    return bool(_FIX_RE.search(subject.strip()))


def is_conventional(subject: str) -> bool:
    return bool(_CONVENTIONAL_RE.match(subject.strip()))


def is_test_path(path: str) -> bool:
    return bool(_TEST_RE.search(path))


def is_excluded_path(path: str) -> bool:
    return bool(_EXCLUDED_RE.search(path))
