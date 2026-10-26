"""Dimension 1 — Context & instructions (T0, with one T1 check for level 5)."""
from __future__ import annotations

import re
from pathlib import Path

from .attribution import is_fix_intent
from .model import Check, Commit, Evidence
from .repo_files import RepoFiles

ROOT_INSTRUCTION_FILES = (
    "AGENTS.md", "AGENT.md", "CLAUDE.md", "GEMINI.md", "CONVENTIONS.md", ".cursorrules",
    ".windsurfrules", ".clinerules", ".github/copilot-instructions.md",
)
SCOPED_RULES_RE = (
    r"^(.+/)(AGENTS|CLAUDE|GEMINI)\.md$"
    r"|^\.cursor/rules/|^\.claude/rules/|^\.github/instructions/.+\.instructions\.md$"
    r"|^\.clinerules/|^\.windsurf/rules/"
)
SKILLS_RE = r"(^|/)\.?(claude/|agents/|codex/)?(skills|commands)/.+\.md$|(^|/)SKILL\.md$"
MCP_RE = r"(^|/)\.?mcp\.json$|^\.(cursor|vscode|gemini)/(mcp|settings)\.json$"
INSTRUCTION_ANY_RE = SCOPED_RULES_RE + r"|^(AGENTS|AGENT|CLAUDE|GEMINI|CONVENTIONS)\.md$|^\.cursorrules$|copilot-instructions\.md$"

MAX_MINIMAL_LINES = 250  # design threshold; "keep minimal" per Evaluating AGENTS.md, arXiv 2602.11988
MAX_STALE_RATE = 0.10

_TICK_RE = re.compile(r"`([^`\s]{3,200})`")
_EXT_RE = re.compile(
    r"\.(md|mdx|py|js|mjs|cjs|ts|tsx|jsx|json|ya?ml|toml|sh|bash|go|rs|rb|java|kt|swift|css|scss|"
    r"html|sql|txt|cfg|ini|lock|env|conf|xml|csv|ipynb|vue|svelte|php|cs|c|h|cpp)$", re.I)
_FRAMEWORK_JS = {"node", "next", "vue", "nuxt", "express", "three", "d3", "chart", "react",
                 "ember", "backbone", "deno", "solid", "alpine", "p5", "socket", "moment"}
_SKIP_CHARS = set("<>{}*?[]|$=()@,;\"'")


def _looks_like_path(token: str) -> bool:
    if token.startswith(("/", "~", "-", ".", "#")) and not token.startswith(("./", "../", ".github", ".claude", ".cursor")):
        return False
    if "://" in token or any(ch in _SKIP_CHARS for ch in token):
        return False
    stem = token.rstrip("/")
    if "/" not in stem:
        if not _EXT_RE.search(stem):
            return False
        base = stem.rsplit(".", 1)[0]
        if stem.lower().endswith(".js") and base.lower() in _FRAMEWORK_JS:
            return False
    return True


def _is_candidate(root: Path, file_dir: Path, token: str) -> bool:
    """Path-like token worth checking. Extension-less tokens (`origin/main`,
    `owner/repo`) only count when their first segment is a real directory."""
    if not _looks_like_path(token):
        return False
    stem = token.rstrip("/")
    if _EXT_RE.search(stem) or token.endswith("/"):
        return True
    first = stem.split("/", 1)[0]
    return any(_inside(root, b / first) and (b / first).is_dir() for b in (file_dir, root))


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _ref_exists(root: Path, file_dir: Path, ref: str, basenames: frozenset[str]) -> bool:
    clean = re.sub(r":\d+(-\d+)?$", "", ref).rstrip("/")
    for base in (file_dir, root):
        candidate = base / clean
        if _inside(root, candidate) and candidate.exists():
            return True
    return "/" not in clean and clean in basenames


def stale_references(root: Path, file_rel: str, text: str,
                     basenames: frozenset[str] = frozenset()) -> tuple[tuple[str, ...], int]:
    """Repo-relative paths referenced in `backticks` that do not exist.

    Absolute paths, home paths, URLs, globs and placeholders are skipped (they
    are machine-specific or not literal). Returns (stale refs, refs checked).
    """
    file_dir = (root / file_rel).parent
    refs = tuple(dict.fromkeys(t for t in _TICK_RE.findall(text) if _is_candidate(root, file_dir, t)))
    stale = tuple(r for r in refs if not _ref_exists(root, file_dir, r, basenames))
    return stale, len(refs)


def _instruction_stats(files: RepoFiles) -> dict:
    roots = tuple(p for p in ROOT_INSTRUCTION_FILES if files.exists(p))
    scoped = files.matching_re(SCOPED_RULES_RE)
    basenames = frozenset(p.rsplit("/", 1)[-1] for p in files.paths)
    lines: dict[str, int] = {}
    stale: tuple[str, ...] = ()
    checked = 0
    for rel in roots + scoped:
        text = files.read_text(rel)
        if text is None:
            continue
        if rel in roots:
            lines = {**lines, rel: text.count("\n") + 1}
        s, n = stale_references(files.root, rel, text, basenames)
        stale = stale + tuple(f"{rel} -> {ref}" for ref in s)
        checked += n
    return {"roots": roots, "scoped": scoped, "lines": lines, "stale": stale, "checked": checked}


def instruction_files(files: RepoFiles) -> tuple[str, ...]:
    return files.matching_re(INSTRUCTION_ANY_RE)


def context_checks(files: RepoFiles, commits: tuple[Commit, ...], agent_commits: int) -> tuple[tuple[Check, ...], dict]:
    st = _instruction_stats(files)
    skills = files.matching_re(SKILLS_RE)
    mcp = files.matching_re(MCP_RE)
    instr = set(instruction_files(files))
    instr_commits = tuple(c for c in commits if c.paths & instr)
    instr_fix = tuple(c for c in instr_commits if is_fix_intent(c.subject))
    longest = max(st["lines"].values(), default=0)
    stale_rate = len(st["stale"]) / st["checked"] if st["checked"] else 0.0
    ev_roots = Evidence("root instruction files", ", ".join(st["roots"]) or "none", "git ls-files")
    checks = (
        Check(1, "Agent use is sanctioned or visible", bool(st["roots"] or st["scoped"]) or agent_commits > 0,
              (ev_roots, Evidence("agent-attributed commits", str(agent_commits), "git log trailers/authors"))),
        Check(2, "Root instruction file exists", bool(st["roots"]), (ev_roots,)),
        Check(3, f"Instruction files minimal (each <= {MAX_MINIMAL_LINES} lines)",
              bool(st["lines"]) and longest <= MAX_MINIMAL_LINES,
              tuple(Evidence(f"lines in {k}", str(v), k) for k, v in st["lines"].items())),
        Check(3, f"Stale-reference rate <= {int(MAX_STALE_RATE * 100)}%", stale_rate <= MAX_STALE_RATE,
              (Evidence("backtick path references checked", str(st["checked"]), "instruction files"),
               Evidence("stale references", str(len(st["stale"])) + (": " + "; ".join(st["stale"][:8]) if st["stale"] else ""),
                        "backtick paths resolved against file dir and repo root"))),
        Check(4, "Progressive disclosure: path-scoped rules or skills",
              bool(st["scoped"]) or bool(skills),
              (Evidence("path-scoped rule files", str(len(st["scoped"])), SCOPED_RULES_RE),
               Evidence("skill/command files", str(len(skills)), SKILLS_RE),
               Evidence("MCP config files", ", ".join(mcp) or "none", MCP_RE))),
        Check(5, "Instruction files evolve from evidence (>=3 edits, >=1 in a fix commit)",
              len(instr_commits) >= 3 and len(instr_fix) >= 1,
              (Evidence("commits touching instruction files", str(len(instr_commits)), "git log --numstat"),
               Evidence("of which fix-intent", str(len(instr_fix)), "conventional subject classification"))),
    )
    facts = {"stale_refs": len(st["stale"]), "instruction_lines_max": longest,
             "mcp_configs": len(mcp), "skills": len(skills)}
    return checks, facts
