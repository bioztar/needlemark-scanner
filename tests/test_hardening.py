"""Hardening: hostile repo config, symlinked outputs, path-like names, remote parsing, salt warning."""
import json
import os
import stat

import pytest

from aems import github
from aems.__main__ import main
from aems.github import parse_remote
from aems.pack import PackOptions
from aems.portfolio import discover, write_export, write_report
from aems.runner import git
from aems.safe_io import UnsafeOutput, safe_name, write_text_atomic
from aems.scan import scan_repo
from tests.conftest import NOW


def _hostile(repo, marker):
    """Repo whose own .git/config would run a command if git honoured fsmonitor / hooks / ext diff."""
    hook = repo.root / "evil.sh"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\nexit 0\n")
    hook.chmod(hook.stat().st_mode | stat.S_IEXEC)
    repo.commit("feat: a", {"src/a.py": "x=1\n", ".gitattributes": "* diff=evil\n"}, days_ago=10)
    repo.commit("fix: a", {"src/a.py": "x=2\n"}, days_ago=5)
    for key, value in (("core.fsmonitor", str(hook)), ("diff.external", str(hook)), ("core.pager", str(hook)),
                       ("diff.evil.textconv", str(hook))):
        repo._git(["config", key, value], NOW, ("x", "x@x"))
    return repo


def test_repo_config_cannot_run_commands(repo, tmp_path):
    marker = tmp_path / "pwned"
    _hostile(repo, marker)
    git(repo.root, "status")
    git(repo.root, "diff", "HEAD~1", "HEAD")
    scan_repo(repo.root, now=NOW, offline=True, pack=PackOptions())  # log --numstat, diff -U0, blame
    assert not marker.exists()


def test_symlinked_out_dir_is_refused(repo, tmp_path, capsys):
    repo.commit("feat: a", {"src/a.py": "x=1\n"}, days_ago=1)
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    assert main(["scan", str(repo.root), "--out", str(link), "--offline"]) == 2
    assert "symlink" in capsys.readouterr().err
    assert not any(real.iterdir())


def test_symlinked_output_file_is_not_followed(repo, tmp_path):
    repo.commit("feat: a", {"src/a.py": "x=1\n"}, days_ago=1)
    report = scan_repo(repo.root, now=NOW, offline=True)
    out = tmp_path / "out"
    out.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("keep")
    (out / f"{report.repo}.aems.html").symlink_to(victim)
    with pytest.raises(UnsafeOutput):
        write_report(report, out)
    assert victim.read_text() == "keep"


def test_atomic_write_leaves_no_temp_files(tmp_path):
    target = tmp_path / "a.json"
    write_text_atomic(target, "one")
    write_text_atomic(target, "two")
    assert target.read_text() == "two"
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]


@pytest.mark.parametrize("name,expected", [("ok-repo_1.x", "ok-repo_1.x"), ("../etc", "_.._etc"),
                                           ("a/b", "a_b"), ("..", "_.."), ("", "repo")])
def test_safe_name(name, expected):
    assert safe_name(name) == expected


def test_report_filenames_are_sanitised(repo, tmp_path):
    repo.commit("feat: a", {"src/a.py": "x=1\n"}, days_ago=1)
    report = scan_repo(repo.root, now=NOW, offline=True)
    hostile = report.__class__(**{**report.__dict__, "repo": "../escape"})
    out = tmp_path / "out"
    jpath, hpath = write_report(hostile, out)
    epath = write_export(hostile, out, keep_name=True)
    for path in (jpath, hpath, epath):
        assert path.parent == out


@pytest.mark.parametrize("url", ["https://github.com/../repo.git", "git@github.com:owner/...git",
                                 "https://github.com/./x", "git@github.com:owner/..git"])
def test_dot_slug_parts_rejected(url):
    assert parse_remote(url) is None


def test_protection_branch_is_url_quoted(monkeypatch):
    calls = []

    def fake(*args, **_):
        calls.append(args)
        if args[:2] == ("repo", "view"):
            return json.dumps({"defaultBranchRef": {"name": "feat/../x y"}, "visibility": "PRIVATE"}), "ok"
        return None, "not found or not visible (404)"
    monkeypatch.setattr(github, "gh", fake)
    github._protection("o/r")
    api = [a for a in calls if a[0] == "api"][0]
    assert api[1] == "repos/o/r/branches/feat%2F..%2Fx%20y/protection"


def test_discover_skips_symlinked_repos(repo_factory, tmp_path):
    real = repo_factory("fleet/real")
    real.commit("feat: a", {"a.py": "x\n"}, days_ago=1)
    outside = repo_factory("outside")
    outside.commit("feat: a", {"a.py": "x\n"}, days_ago=1)
    (tmp_path / "fleet" / "linked").symlink_to(outside.root)
    assert [p.name for p in discover(tmp_path / "fleet")] == ["real"]


def test_export_without_salt_warns(repo, tmp_path, capsys, monkeypatch):
    repo.commit("feat: a", {"src/a.py": "x=1\n"}, days_ago=1)
    monkeypatch.delenv("AEMS_EXPORT_SALT", raising=False)
    assert main(["export", str(repo.root), "--out", str(tmp_path / "o"), "--offline"]) == 0
    assert "AEMS_EXPORT_SALT" in capsys.readouterr().err
    monkeypatch.setenv("AEMS_EXPORT_SALT", "s")
    assert main(["export", str(repo.root), "--out", str(tmp_path / "o2"), "--offline"]) == 0
    assert "AEMS_EXPORT_SALT" not in capsys.readouterr().err
    monkeypatch.delenv("AEMS_EXPORT_SALT")
    assert main(["scan", str(repo.root), "--out", str(tmp_path / "o3"), "--offline"]) == 0
    assert "AEMS_EXPORT_SALT" not in capsys.readouterr().err  # no export, no warning
