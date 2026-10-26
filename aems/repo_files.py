"""Tracked-file inventory and guarded reads.

T0 looks only at files tracked by git (what the team shares), never at
untracked personal files. Every read goes through `read_text`, which applies
the deny-list BEFORE opening: env files, keys, credential and token stores are
never opened, whatever their content.
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from .runner import git

MAX_READ_BYTES = 256 * 1024

_DENY_RE = re.compile(
    r"(^|/)\.env[^/]*$"
    r"|\.(pem|key|p12|pfx|jks|keystore|kdbx|gpg|asc|ovpn)$"
    r"|(^|/)id_(rsa|dsa|ecdsa|ed25519)[^/]*$"
    r"|(^|/)[^/]*(credential|secret|token|password|passwd|keychain)[^/]*$"
    r"|(^|/)(\.netrc|\.npmrc|\.pypirc|\.git-credentials|auth\.json|hosts\.yml)$"
    r"|(^|/)settings\.local\.json$"
    r"|(^|/)\.(ssh|gnupg|aws|docker)/",
    re.I,
)
_TEMPLATE_RE = re.compile(r"\.(example|sample|template|dist|tmpl)$|\.example\.", re.I)
# Narrower than the read deny-list: names that almost always carry live secrets.
_SECRET_FILE_RE = re.compile(
    r"(^|/)\.env(\.[^/]*)?$"
    r"|\.(pem|key|p12|pfx|jks|keystore|kdbx)$"
    r"|(^|/)id_(rsa|dsa|ecdsa|ed25519)$"
    r"|(^|/)(credentials?|secrets?|service[-_]account)[^/]*\.(json|ya?ml|toml|ini|txt)$"
    r"|(^|/)(\.git-credentials|\.pypirc|\.netrc)$",
    re.I,
)


def is_denied(rel_path: str) -> bool:
    """True when a path must never be opened (secret-bearing by name)."""
    return bool(_DENY_RE.search(rel_path))


def is_secret_like_tracked(rel_path: str) -> bool:
    """A tracked file whose name says it holds secrets (templates excluded)."""
    return bool(_SECRET_FILE_RE.search(rel_path)) and not _TEMPLATE_RE.search(rel_path)


@dataclass(frozen=True)
class RepoFiles:
    root: Path
    paths: tuple[str, ...]

    def exists(self, rel: str) -> bool:
        return rel in self._set

    @cached_property
    def _set(self) -> frozenset[str]:
        return frozenset(self.paths)

    def matching(self, *patterns: str) -> tuple[str, ...]:
        """Tracked paths matching any glob (fnmatch, '*' crosses '/')."""
        return tuple(p for p in self.paths if any(fnmatch.fnmatch(p, pat) for pat in patterns))

    def matching_re(self, pattern: str) -> tuple[str, ...]:
        rx = re.compile(pattern, re.I)
        return tuple(p for p in self.paths if rx.search(p))

    @cached_property
    def dirs(self) -> frozenset[str]:
        return frozenset(
            "/".join(p.split("/")[:i]) for p in self.paths for i in range(1, p.count("/") + 1)
        )

    def read_text(self, rel: str) -> str | None:
        if is_denied(rel):
            return None
        path = self.root / rel
        try:
            if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_READ_BYTES:
                return None
            data = path.read_bytes()
        except OSError:
            return None
        if b"\x00" in data[:4096]:
            return None
        return data.decode("utf-8", errors="replace")


def load_files(root: Path) -> RepoFiles:
    out = git(root, "ls-files", "-z")
    paths = tuple(sorted(p for p in (out or "").split("\0") if p))
    return RepoFiles(root=root, paths=paths)
