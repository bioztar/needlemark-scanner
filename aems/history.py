"""Load commit history (T1) as immutable Commit records.

Only metadata is read: hashes, parents, timestamps, author identity (for
attribution, and as an opaque per-run hash to count distinct people for
k-anonymity — the identity itself is never stored), co-author trailers, subject
(classification only — never rendered) and numstat. Commit bodies are never
loaded into Python; the "Generated with Claude Code" footer is found with
`git log --grep`, which returns hashes only.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from .attribution import agents_for, is_bot
from .model import Commit
from .runner import git

_RS, _FS, _TS = "\x1e", "\x1f", "\x1d"
_FORMAT = _RS + _FS.join([
    "%H", "%P", "%at", "%an", "%ae", "%s",
    "%(trailers:key=Co-authored-by,valueonly,separator=%x1d)",
]) + _FS
_SQUASH_RE = re.compile(r"\(#\d+\)\s*$")
_FOOTER_GREP = r"Generated (with|by) \[?Claude Code"


def _hash_set(repo: Path, *args: str) -> frozenset[str]:
    out = git(repo, *args)
    return frozenset(out.split()) if out else frozenset()


def _parse_numstat(block: str) -> tuple[tuple[str, int, int], ...]:
    rows = []
    for line in block.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, deleted, path = parts
        rows.append((
            path,
            int(added) if added.isdigit() else 0,  # "-" for binary files
            int(deleted) if deleted.isdigit() else 0,
        ))
    return tuple(rows)


_RUN_SALT = os.urandom(8).hex()  # per-process: keys cannot be joined across runs


def _person_key(name: str, email: str) -> str | None:
    if is_bot(name, email) or agents_for(name, email, (), False):
        return None
    return hashlib.sha256((_RUN_SALT + email.strip().lower()).encode()).hexdigest()[:16]


def _parse_record(record: str, first_parent: frozenset[str], footers: frozenset[str],
                  vendor_of=None) -> Commit | None:
    fields = record.split(_FS)
    if len(fields) < 8:
        return None
    sha, parents, ts, an, ae, subject, trailers, numstat = fields[:8]
    coauthors = tuple(t.strip() for t in trailers.split(_TS) if t.strip())
    on_fp = sha in first_parent
    parent_tuple = tuple(parents.split())
    agents = agents_for(an, ae, coauthors, sha in footers)
    return Commit(
        sha=sha,
        parents=parent_tuple,
        ts=int(ts),
        subject=subject,
        files=_parse_numstat(numstat),
        agents=agents,
        on_first_parent=on_fp,
        squash_pr=on_fp and len(parent_tuple) < 2 and bool(_SQUASH_RE.search(subject)),
        other_bot=not agents and is_bot(an, ae),
        author_key=_person_key(an, ae),
        vendor=vendor_of(ae) if vendor_of else None,
    )


def load_commits(repo: Path, since_ts: int, max_count: int = 5000, vendor_of=None) -> tuple[Commit, ...]:
    """Commits reachable from HEAD with author time >= since_ts, newest first.

    vendor_of(email) -> vendor label or None (query pack); the email itself is not kept.
    """
    window = (f"--max-age={since_ts}", f"--max-count={max_count}")
    first_parent = _hash_set(repo, "rev-list", "--first-parent", *window, "HEAD")
    footers = _hash_set(repo, "log", *window, "-i", "-E", f"--grep={_FOOTER_GREP}", "--format=%H", "HEAD")
    out = git(repo, "log", *window, "--no-ext-diff", "--no-textconv", "--no-renames", "--numstat",
              f"--format={_FORMAT}", "HEAD")
    if not out:
        return ()
    records = (r for r in out.split(_RS) if r.strip())
    parsed = (_parse_record(r, first_parent, footers, vendor_of) for r in records)
    return tuple(c for c in parsed if c is not None)


def commit_count(repo: Path) -> int:
    out = git(repo, "rev-list", "--count", "HEAD")
    return int(out.strip()) if out and out.strip().isdigit() else 0
