"""End-to-end scan on fixture repos: static detectors, report safety, portfolio."""
import json

from aems.portfolio import scan_portfolio
from aems.render import render_html
from aems.scan import report_to_dict, scan_repo
from aems.static_context import stale_references
from tests.conftest import CLAUDE_TRAILER, NOW

FAKE_SECRET = "zz-fake-secret-value-0000"
FAKE_AWS = "AKIA" + "ABCDEFGHIJKLMNOP"

WORKFLOW = """name: ci
on: [push, pull_request]
jobs:
  t:
    runs-on: ubuntu-latest
    steps:
      - run: python -m pytest
"""


def _harnessed_repo(repo):
    repo.commit("chore: init", {
        "AGENTS.md": "# Rules\nRun `tests/test_app.py` and see `docs/missing.md` and `/Users/someone/x.md`.\n",
        ".gitignore": ".env*\n",
        "pyproject.toml": "[tool.pytest.ini_options]\n[tool.ruff]\n",
        "tests/test_app.py": "def test_x():\n    assert True\n",
        ".github/workflows/ci.yml": WORKFLOW,
        ".pre-commit-config.yaml": "repos: []\n",
        "docs/adr/0001-record.md": "# ADR\n",
        "src/app.py": f"KEY = '{FAKE_AWS}'\n",
    }, days_ago=200)
    repo.write({".env": f"TOKEN={FAKE_SECRET}\n"})  # untracked, must never be read
    for i in range(6):
        repo.commit(f"feat: step {i}", {f"src/m{i}.py": "x = 1\n" * (i + 1)}, days_ago=150 - i, trailers=(CLAUDE_TRAILER,))
    repo.commit("fix: step 0", {"src/m0.py": "x = 2\n"}, days_ago=140)


def test_stale_references_skip_absolute_home_and_placeholders(repo):
    repo.write({"AGENTS.md": "x", "tests/a.py": "x", "sub/README.md": "x"})
    text = ("see `tests/a.py`, `docs/gone.md`, `/Users/a/b.md`, `~/x/y.md`, "
            "`https://x.org/a.md`, `fleet/<slug>.md`, `src/*.py`, `{x}/y.md`, `README.md`")
    stale, checked = stale_references(repo.root, "sub/AGENTS.md", text)
    assert stale == ("docs/gone.md",)
    assert checked == 3


def test_scan_repo_end_to_end(repo):
    _harnessed_repo(repo)
    report = scan_repo(repo.root, now=NOW, offline=True)
    dims = {d.dim: d for d in report.dims}
    assert set(dims) == set(range(1, 10))
    assert dims[1].raw_level >= 2
    assert dims[3].raw_level >= 3
    assert dims[3].capped  # offline: no CI run evidence -> presence, not maturity
    assert not dims[4].assessed and not dims[6].assessed and not dims[7].assessed
    assert report.overall == min(d.level for d in report.dims if d.assessed)
    assert report.metrics["attribution"]["agent_commits"] == 6
    assert report.metrics["secrets"]["pattern_hits"] >= 1
    assert 1 <= len(report.recommendations) <= 3


def test_report_never_leaks_secrets_or_people(repo):
    _harnessed_repo(repo)
    report = scan_repo(repo.root, now=NOW, offline=True)
    html = render_html(report)
    blob = json.dumps(report_to_dict(report)) + html
    assert FAKE_SECRET not in blob
    assert FAKE_AWS not in blob
    assert "dev.person@example.org" not in blob
    assert "Dev Person" not in blob
    assert "feat: step" not in blob  # commit subjects are not rendered
    assert "<script" not in html.lower()
    assert "@media print" in html


def test_portfolio_isolates_failures(tmp_path, repo_factory):
    good = repo_factory("alpha")
    good.commit("feat: a", {"a.py": "1\n"}, days_ago=5)
    other = repo_factory("beta")
    other.commit("feat: b", {"AGENTS.md": "# x\n"}, days_ago=5)
    (tmp_path / "not-a-repo").mkdir()
    broken = tmp_path / "gamma"
    broken.mkdir()
    (broken / ".git").write_text("gitdir: /nonexistent/path\n")
    summary = scan_portfolio(tmp_path, now=NOW, offline=True)
    names = [row["repo"] for row in summary["rows"]]
    assert names == ["alpha", "beta", "gamma"]
    gamma = summary["rows"][2]
    assert gamma["error"]
    assert summary["rows"][0]["overall"] is not None
