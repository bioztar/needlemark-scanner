"""Output safety: no writes through symlinks, atomic replace, file-name-safe repo names."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


class UnsafeOutput(OSError):
    pass


def safe_name(name: str) -> str:
    """A single path component: no separators, never '.'/'..' or hidden."""
    cleaned = _UNSAFE_CHARS.sub("_", str(name))
    if not cleaned:
        return "repo"
    return "_" + cleaned if cleaned.startswith(".") else cleaned


def ensure_dir(path: Path) -> Path:
    """Create an output directory; refuse it if it is a symlink. (Parents are the user's
    choice: on macOS even /tmp is a symlink.)"""
    path = Path(path)
    if path.is_symlink():
        raise UnsafeOutput(f"refusing symlinked output directory: {path.name}")
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_text_atomic(path: Path, text: str) -> Path:
    """Write via a temp file in the same directory, then rename. Never follows a symlink."""
    path = Path(path)
    ensure_dir(path.parent)
    if path.is_symlink():
        raise UnsafeOutput(f"refusing to write through a symlink: {path.name}")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path
