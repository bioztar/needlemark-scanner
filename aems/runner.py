"""Read-only subprocess wrappers for git and gh.

Safety properties:
- GIT_OPTIONAL_LOCKS=0 so no git command refreshes the scanned repo's index.
- core.fsmonitor, hooks, diff.external and the pager are overridden on every call, so a
  hostile repo config cannot run a program; diffs pass --no-ext-diff --no-textconv.
- gh is only ever invoked with read verbs (run list, pr list, issue list, repo view, api GET without -f/-F).
- Every call has a timeout; failures return None instead of raising.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

GIT_TIMEOUT = 120
GH_TIMEOUT = 25
# The scanned repo's own config must never make git run a program (fsmonitor, hooks,
# external diff, pager) or render through a textconv filter.
_GIT_HARDENING = ("-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "diff.external=",
                  "-c", "core.pager=cat", "--no-pager")
_GH_WRITE_FLAGS = {"-f", "-F", "--field", "--raw-field", "--input", "-X", "--method"}
_GH_READ_VERBS = {("run", "list"), ("pr", "list"), ("issue", "list"), ("api",), ("repo", "view")}


def _env() -> dict:
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GH_PROMPT_DISABLED"] = "1"
    env["NO_COLOR"] = "1"
    return env


def git(repo: Path, *args: str, timeout: int = GIT_TIMEOUT) -> str | None:
    try:
        out = subprocess.run(
            ["git", *_GIT_HARDENING, "-C", str(repo), *args],
            env=_env(), capture_output=True, text=True, timeout=timeout,
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def _gh_is_read_only(args: tuple[str, ...]) -> bool:
    if any(a in _GH_WRITE_FLAGS for a in args):
        return False
    return tuple(args[:2]) in _GH_READ_VERBS or tuple(args[:1]) in _GH_READ_VERBS


def gh(*args: str, timeout: int = GH_TIMEOUT) -> tuple[str | None, str]:
    """Run a read-only gh command. Returns (stdout or None, status-note)."""
    if not _gh_is_read_only(args):
        raise ValueError("refusing non-read-only gh invocation")
    if shutil.which("gh") is None:
        return None, "gh not installed"
    try:
        out = subprocess.run(
            ["gh", *args], env=_env(), capture_output=True, text=True,
            timeout=timeout, errors="replace",
        )
    except subprocess.TimeoutExpired:
        return None, "gh timed out"
    except OSError:
        return None, "gh failed to start"
    if out.returncode != 0:
        err = out.stderr.lower()
        if "404" in err or "not found" in err:
            return None, "not found or not visible (404)"
        if "403" in err:
            return None, "not visible to this token (403)"
        if "auth" in err or "login" in err:
            return None, "gh not authenticated"
        return None, f"gh exit {out.returncode}"
    return out.stdout, "ok"
