"""Fixture repos built in tmp dirs, isolated from the host git config."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

DAY = 86400
NOW = 1_790_000_000  # fixed "now" for deterministic tests (2026-09-21)

HUMAN = ("Dev Person", "dev.person@example.org")
CLAUDE_TRAILER = "Co-Authored-By: Claude Code <noreply@anthropic.com>"
DEVIN_BOT = ("devin-ai-integration[bot]", "158243242+devin-ai-integration[bot]@users.noreply.github.com")


def _env(ts: int, author: tuple[str, str]) -> dict:
    env = {
        k: v for k, v in os.environ.items()
        if not k.startswith("GIT_")
    }
    env.update({
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": author[0],
        "GIT_AUTHOR_EMAIL": author[1],
        "GIT_COMMITTER_NAME": author[0],
        "GIT_COMMITTER_EMAIL": author[1],
        "GIT_AUTHOR_DATE": f"@{ts} +0000",
        "GIT_COMMITTER_DATE": f"@{ts} +0000",
    })
    return env


class RepoBuilder:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self._git(["init", "-q", "-b", "main"], NOW - 400 * DAY, HUMAN)
        self._git(["config", "commit.gpgsign", "false"], NOW, HUMAN)

    def _git(self, args, ts, author) -> str:
        out = subprocess.run(
            ["git", "-C", str(self.root), *args],
            env=_env(ts, author), capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()

    def write(self, files: dict[str, str]) -> None:
        for rel, content in files.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)

    def commit(self, subject, files, days_ago=0.0, author=HUMAN, trailers=(), body="") -> str:
        ts = int(NOW - days_ago * DAY)
        self.write(files)
        self._git(["add", "-A"], ts, author)
        message = subject
        if body:
            message += "\n\n" + body
        if trailers:
            message += "\n\n" + "\n".join(trailers)
        self._git(["commit", "-q", "-m", message], ts, author)
        return self._git(["rev-parse", "HEAD"], ts, author)

    def branch(self, name: str) -> None:
        self._git(["checkout", "-q", "-b", name], NOW, HUMAN)

    def checkout(self, name: str) -> None:
        self._git(["checkout", "-q", name], NOW, HUMAN)

    def merge(self, name: str, days_ago=0.0) -> str:
        ts = int(NOW - days_ago * DAY)
        self._git(["merge", "-q", "--no-ff", "-m", f"Merge pull request #1 from x/{name}", name], ts, HUMAN)
        return self._git(["rev-parse", "HEAD"], ts, HUMAN)


@pytest.fixture
def repo(tmp_path) -> RepoBuilder:
    return RepoBuilder(tmp_path / "fixture-repo")


@pytest.fixture
def repo_factory(tmp_path):
    def make(name: str) -> RepoBuilder:
        return RepoBuilder(tmp_path / name)
    return make
