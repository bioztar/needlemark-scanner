"""Zero-access guarantees: no identities in reports; numbers-only export."""
import json
import re

from aems.__main__ import main
from aems.export import export_portfolio, export_report
from aems.privacy import SUPPRESSED
from aems.portfolio import scan_portfolio
from aems.render import render_html
from aems.scan import report_to_dict, scan_repo
from tests.conftest import CLAUDE_TRAILER, DEVIN_BOT, NOW

PEOPLE = ("Dev Person", "dev.person@example.org", "Second Human", "second@example.org")
DEPENDABOT = ("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com")
SUBJECT = "feat: secret-project-codename"


def _repo(repo):
    repo.commit("chore: init", {"AGENTS.md": "# x\nsee `src/app.py`\n", "src/app.py": "x=1\n",
                                ".github/workflows/ci.yml": "on: [push]\njobs: {t: {steps: [{run: pytest}]}}\n"}, days_ago=90)
    repo.commit(SUBJECT, {"src/codename.py": "x=1\n"}, days_ago=80, trailers=(CLAUDE_TRAILER,))
    repo.commit("feat: by devin", {"src/d.py": "x=1\n"}, days_ago=70, author=DEVIN_BOT)
    repo.commit("chore(deps): bump", {"requirements.txt": "x==1\n"}, days_ago=60, author=DEPENDABOT)
    repo.commit("feat: second", {"src/s.py": "x=1\n"}, days_ago=50, author=("Second Human", "second@example.org"))
    return scan_repo(repo.root, now=NOW, offline=True)


def _leaves(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _leaves(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _leaves(v, f"{path}[{i}]")
    else:
        yield path, obj


def test_identities_are_aggregated_into_classes(repo):
    report = _repo(repo)
    classes = report.metrics["attribution"]["by_class"]
    # 2 distinct human authors (< 5): k-anonymity suppresses the whole breakdown, keys kept.
    assert classes == {k: SUPPRESSED for k in ("human", "Claude", "Devin", "other bot")}
    blob = render_html(report) + json.dumps(report_to_dict(report))
    for ident in PEOPLE + DEPENDABOT[:1]:
        assert ident not in blob
    assert "dependabot" not in blob.lower()


def test_export_is_numbers_only_and_hashes_repo_name(repo):
    report = _repo(repo)
    data = export_report(report)
    text = json.dumps(data)
    assert report.repo not in text
    assert re.fullmatch(r"[0-9a-f]{12}", data["repo_id"])
    assert SUBJECT not in text and "codename" not in text
    # ',' allowed only for the k-anonymity marker "<5, suppressed".
    allowed = re.compile(r"^[A-Za-z0-9 ._:+()\-≥<>=%,]*$")
    for path, value in _leaves(data):
        if isinstance(value, str):
            assert "/" not in value, path
            assert "@" not in value, path
            assert allowed.match(value), (path, value)
            assert len(value) <= 64, path
        else:
            assert value is None or isinstance(value, (int, float, bool)), path
    for forbidden in ("evidence", "paths", "slug", "notes", "branch", "source"):
        assert f'"{forbidden}"' not in text


def test_export_keep_name(repo):
    report = _repo(repo)
    assert export_report(report, keep_name=True)["repo_id"] == report.repo


def test_export_carries_scores(repo):
    report = _repo(repo)
    data = export_report(report)
    assert data["overall"] == report.overall
    assert data["median"] == report.median
    assert {d["dim"] for d in data["dims"]} == set(range(1, 10))
    assert data["vdr"]["basis"] in ("agent-attributed", "total change volume")


def test_export_cli_writes_numbers_only_file(repo, tmp_path):
    _repo(repo)
    out = tmp_path / "out"
    assert main(["export", str(repo.root), "--out", str(out), "--offline"]) == 0
    files = list(out.glob("*.export.json"))
    assert len(files) == 1
    assert repo.root.name not in files[0].name
    assert repo.root.name not in files[0].read_text()


def test_portfolio_export_hashes_every_name(tmp_path, repo_factory):
    for name in ("alpha-internal", "beta-internal"):
        repo_factory(name).commit("feat: a", {"a.py": "1\n"}, days_ago=5)
    summary = scan_portfolio(tmp_path, now=NOW, offline=True)
    text = json.dumps(export_portfolio(summary))
    assert "internal" not in text
    assert len(export_portfolio(summary)["repos"]) == 2
