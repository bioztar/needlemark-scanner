"""Q2 trace, git side: which earlier commits wrote the lines a defect fix changed or removed.

For a fix commit F with first parent P:
  git diff -U0 P F           -> old-side line ranges per code file (pure additions have none)
  git blame --porcelain P    -> for those ranges, the commit that last wrote each line
Only the 40-hex header lines and the numeric `author-time` of blame output are parsed.
Line contents, author names and mails in the porcelain stream are skipped, never stored.
"""
from __future__ import annotations

import re
from pathlib import Path

from .attribution import is_rework_relevant, is_test_path
from .model import Commit
from .runner import git

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")
_OLD_RE = re.compile(r"^--- (?:a/(?P<path>.+)|/dev/null)$")
_HEADER_RE = re.compile(r"^([0-9a-f]{40}) \d+ \d+(?: \d+)?$")
_TIME_RE = re.compile(r"^author-time (\d+)$")


def _flush(out: list, path: str | None, ranges: list) -> list:
    return out + [(path, tuple(ranges))] if path and ranges else out


def parse_hunks(diff: str) -> tuple[tuple[str, tuple[tuple[int, int], ...]], ...]:
    """(old path, ((start, count), ...)) for every file with removed/changed lines."""
    out: list = []
    path, ranges, in_header = None, [], False
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            out, path, ranges, in_header = _flush(out, path, ranges), None, [], True
            continue
        old = _OLD_RE.match(line) if in_header else None  # a removed "-- x" line is not a header
        if old:
            path = old.group("path")
            continue
        hunk = _HUNK_RE.match(line)
        if hunk:
            in_header = False
        if hunk and path:
            count = 1 if hunk.group(2) is None else int(hunk.group(2))
            if count > 0:
                ranges = ranges + [(int(hunk.group(1)), count)]
    return tuple(_flush(out, path, ranges))


def parse_blame(porcelain: str) -> tuple[dict[str, int], dict[str, int]]:
    """(origin sha -> blamed line count, origin sha -> author time)."""
    lines: dict[str, int] = {}
    times: dict[str, int] = {}
    current = None
    for row in porcelain.splitlines():
        if row.startswith("\t"):
            continue  # line content: never read
        header = _HEADER_RE.match(row)
        if header:
            current = header.group(1)
            lines = {**lines, current: lines.get(current, 0) + 1}
            continue
        stamp = _TIME_RE.match(row)
        if stamp and current:
            times = {**times, current: int(stamp.group(1))}
    return lines, times


def _traceable(path: str) -> bool:
    return not path.startswith('"') and is_rework_relevant(path) and not is_test_path(path)


def _merge_counts(a: dict[str, int], b: dict[str, int]) -> dict[str, int]:
    return {k: a.get(k, 0) + b.get(k, 0) for k in a.keys() | b.keys()}


def trace_fix(root: Path, fix: Commit, max_files: int) -> dict | None:
    """Blamed origins of one fix, or None for a root commit or a failed diff."""
    if not fix.parents:
        return None
    parent = fix.parents[0]
    diff = git(root, "diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--no-color", "-U0", parent, fix.sha)
    if diff is None:
        return None
    files = [(p, r) for p, r in parse_hunks(diff) if _traceable(p)][:max_files]
    lines: dict[str, int] = {}
    times: dict[str, int] = {}
    for path, ranges in files:
        spans = [arg for start, count in ranges for arg in ("-L", f"{start},+{count}")]
        out = git(root, "blame", "--no-textconv", "--porcelain", *spans, parent, "--", path)
        if out:
            got, ts = parse_blame(out)
            lines, times = _merge_counts(lines, got), {**times, **ts}
    return {"sha": fix.sha, "fix_ts": fix.ts, "lines": lines, "times": times}
