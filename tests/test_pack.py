"""Query pack end to end: Q2 escaped-defect trace on a fixture repo, Q1/Q3 with fake gh, privacy, export, CLI."""
import json
from pathlib import Path

import pytest

from aems import github, pack_github
from aems.__main__ import main
from aems.export import SCHEMA, export_report
from aems.pack import PackOptions
from aems.privacy import SUPPRESSED
from aems.render import render_html
from aems.scan import report_to_dict, scan_repo
from aems.vendors import load_vendors
from tests.conftest import CLAUDE_TRAILER, DEVIN_BOT, NOW

FIX = Path(__file__).parent / "fixtures"
VENDORS = FIX / "vendors.json"
HUMANS = tuple((f"Human {n}", f"h{n}@inhouse.example") for n in range(1, 6))
ACME = tuple((f"Vendor {n}", f"v{n}@acme.example") for n in range(1, 6))
TEN = "".join(f"line{i}\n" for i in range(1, 11))


def _edit(text: str, changes: dict[int, str]) -> str:
    lines = text.splitlines(keepends=True)
    return "".join(changes.get(i, ln) for i, ln in enumerate(lines, 1))


def _build(repo):
    """Five people per class; five defect fixes with known origins and ages (see test asserts)."""
    repo.commit("feat: core", {"src/core.py": TEN}, days_ago=170, author=HUMANS[0])
    repo.commit("feat: vendor module", {"src/vendor_mod.py": TEN}, days_ago=165, author=ACME[0])
    repo.commit("feat: agent module", {"src/agent_mod.py": TEN}, days_ago=160, author=DEVIN_BOT)
    for i in range(1, 5):
        repo.commit(f"feat: h{i}", {f"src/h{i}.py": "x=1\n"}, days_ago=158, author=HUMANS[i])
        trailers = (CLAUDE_TRAILER,) if i == 2 else ()
        repo.commit(f"feat: v{i}", {f"src/v{i}.py": "x=1\n"}, days_ago=158, author=ACME[i], trailers=trailers)
    (repo.root / "src/agent_mod.py").unlink()
    repo.commit('Revert "feat: agent module"', {}, days_ago=155, author=HUMANS[2])  # agent origin, age 5
    core = _edit(TEN, {2: "fixed2\n", 3: "fixed3\n"})
    repo.commit("fix: core bug", {"src/core.py": core}, days_ago=140, author=HUMANS[1])  # human, age 30
    vend = _edit(TEN, {4: "v4\n", 5: "v5\n", 6: "v6\n"})
    repo.commit("fix(vendor): off by one", {"src/vendor_mod.py": vend}, days_ago=105, author=HUMANS[1])  # age 60
    core = _edit(core, {10: "fixed10\n"})
    repo.commit("hotfix: mixed", {"src/core.py": core, "src/vendor_mod.py": _edit(vend, {10: "v10\n"})},
                days_ago=90, author=HUMANS[3])  # human age 80 + vendor age 75, half each
    core = _edit(core, {5: "tidy5\n"})
    tidy = repo.commit("chore: tidy", {"src/core.py": core}, days_ago=50, author=HUMANS[0])  # fix only via a bug PR
    repo.commit("fix: add guard", {"src/core.py": core + "guard\n"}, days_ago=20, author=HUMANS[4])  # pure add
    repo._git(["remote", "add", "origin", "https://github.com/fake-owner/fake-repo.git"], NOW, ("x", "x@x"))
    return repo, tidy


def _prs(extra=()):
    return json.dumps(json.loads((FIX / "pack_prs.json").read_text()) + list(extra))


def _fake_gh(pr_json, closing=False, issues="[]"):
    def fake(*args, **_):
        if args[:2] == ("run", "list"):
            return "[]", "ok"
        if args[:2] == ("pr", "list"):
            fields = args[args.index("--json") + 1]
            if "closingIssuesReferences" in fields and not closing:
                return None, "gh exit 1"  # gh 2.46 does not know the field
            return pr_json, "ok"
        if args[:2] == ("issue", "list"):
            return issues, "ok"
        return None, "not found or not visible (404)"
    return fake


def _patch(monkeypatch, fake):
    monkeypatch.setattr(github, "gh", fake)
    monkeypatch.setattr(pack_github, "gh", fake)


def _scan(root, offline=False, allow_small=False, vendors=VENDORS):
    opts = PackOptions(vendors=load_vendors(vendors) if vendors else None, allow_small_vendors=allow_small)
    return scan_repo(root, now=NOW, offline=offline, pack=opts)


def test_escaped_defect_trace_offline(repo):
    report = _scan(_build(repo)[0].root, offline=True)
    esc = report.metrics["pack"]["escapes"]
    assert (esc["fix_commits"], esc["traced"], esc["untraceable"]) == (5, 4, 1)
    assert esc["bug_links"] == "not observed"
    assert esc["median_escape_age_days"] == pytest.approx(60)
    by = esc["by_class"]
    assert by["human"]["defects_30"] == pytest.approx(1) and by["agent"]["defects_30"] == pytest.approx(1)
    assert by["vendor"]["defects_30"] == pytest.approx(0)
    assert by["human"]["defects_90"] == pytest.approx(1.5) and by["vendor"]["defects_90"] == pytest.approx(1.5)
    assert by["vendor"]["lines_90"] == 14
    assert by["vendor"]["per_1k_90"] == pytest.approx(1.5 / 14 * 1000)
    assert report.metrics["pack"]["review_timing"]["available"] is False


def test_bug_labelled_pr_adds_its_merge_commit_as_a_fix(repo, monkeypatch):
    built, tidy = _build(repo)
    bug_pr = {"number": 300, "additions": 1, "deletions": 1, "createdAt": "2026-08-01T00:00:00Z",
              "mergedAt": "2026-08-02T00:00:00Z", "author": {"login": "fake-h1"}, "labels": [{"name": "Type: Bug"}],
              "mergeCommit": {"oid": tidy}, "reviews": []}
    _patch(monkeypatch, _fake_gh(_prs([bug_pr])))
    esc = _scan(built.root).metrics["pack"]["escapes"]
    assert esc["fix_commits"] == 6 and esc["from_bug_prs"] == 1 and esc["traced"] == 5
    assert esc["bug_links"] == "PR labels"


def test_closing_issue_references_used_when_gh_supports_them(repo, monkeypatch):
    built, tidy = _build(repo)
    pr = {"number": 301, "additions": 1, "deletions": 1, "createdAt": "2026-08-01T00:00:00Z",
          "mergedAt": "2026-08-02T00:00:00Z", "author": {"login": "fake-h1"}, "labels": [],
          "mergeCommit": {"oid": tidy}, "reviews": [], "closingIssuesReferences": [{"number": 7}]}
    issues = json.dumps([{"number": 7, "labels": [{"name": "bug"}]}, {"number": 8, "labels": []}])
    _patch(monkeypatch, _fake_gh(_prs([pr]), closing=True, issues=issues))
    esc = _scan(built.root).metrics["pack"]["escapes"]
    assert esc["from_bug_prs"] == 1 and esc["bug_links"] == "PR labels + closing issues"


def test_review_timing_and_vendor_lens_with_gh(repo, monkeypatch):
    _patch(monkeypatch, _fake_gh(_prs()))
    pack = _scan(_build(repo)[0].root).metrics["pack"]
    rt = pack["review_timing"]
    assert rt["available"] is True and rt["overall"]["rubber_stamped"] == 5
    assert rt["by_class"]["vendor"]["approved"] == 3
    rows = pack["vendors"]["rows"]
    assert [r["label"] for r in rows] == ["Acme Dev"]
    acme = rows[0]
    assert acme["commits"] == 5 and acme["lines"] == 14
    assert acme["agent_share"] == pytest.approx(1 / 5)
    assert acme["prs"] == 5 and acme["formal_review_share"] == pytest.approx(4 / 5)
    assert acme["rubber_stamp_rate"] == pytest.approx(2 / 3)
    assert acme["rework_rate"] == pytest.approx(0) and acme["rework_status"] == "healthy"
    assert acme["escaped_per_1k_90"] == pytest.approx(1.5 / 14 * 1000)
    assert pack["vendors"]["pooled"] is None


def test_no_mapping_login_or_domain_leaks(repo, monkeypatch):
    _patch(monkeypatch, _fake_gh(_prs()))
    report = _scan(_build(repo)[0].root)
    blob = render_html(report) + json.dumps(report_to_dict(report)) + json.dumps(export_report(report))
    for secret in ("acme.example", "^acme-", "acme-v1", "fake-h1", "fake-rev-a", "inhouse.example",
                   "fake-review-body", "Human 1", "Vendor 1", "line1"):
        assert secret not in blob, secret
    assert "Acme Dev" in render_html(report)  # the client's own report names the vendor


def test_export_schema_4_hashes_vendor_labels(repo, monkeypatch):
    _patch(monkeypatch, _fake_gh(_prs()))
    report = _scan(_build(repo)[0].root)
    data = export_report(report)
    assert SCHEMA == "aems-export-4" and data["schema"] == "aems-export-4"
    rows = data["pack"]["vendors"]["rows"]
    assert len(rows) == 1 and rows[0]["vendor_id"] != "Acme Dev" and len(rows[0]["vendor_id"]) == 12
    assert "Acme Dev" not in json.dumps(data)
    assert export_report(report, keep_vendor_names=True)["pack"]["vendors"]["rows"][0]["vendor_id"] == "Acme Dev"
    assert data["pack"]["escapes"]["by_class"]["vendor"]["defects_90"] == pytest.approx(1.5)
    assert data["pack"]["review_timing"]["overall"]["rubber_stamped"] == 5


def test_small_vendor_is_pooled_and_suppressed_by_default(repo, monkeypatch):
    built, _ = _build(repo)
    built.commit("feat: tiny", {"src/tiny.py": "x=1\n"}, days_ago=100, author=("Tiny One", "t1@tiny.example"))
    _patch(monkeypatch, _fake_gh(_prs()))
    pack = _scan(built.root).metrics["pack"]
    assert [r["label"] for r in pack["vendors"]["rows"]] == ["Acme Dev"]
    pooled = pack["vendors"]["pooled"]
    assert pooled["vendors"] == 1 and pooled["commits"] == SUPPRESSED
    # the vendor class total minus the visible Acme row would reveal the pooled vendor: suppress it
    assert set(pack["escapes"]["by_class"].values()) == {SUPPRESSED}
    assert "Tiny Co" not in render_html(_scan(built.root))


def test_allow_small_vendors_overrides_with_notice(repo, monkeypatch, capsys, tmp_path):
    built, _ = _build(repo)
    built.commit("feat: tiny", {"src/tiny.py": "x=1\n"}, days_ago=100, author=("Tiny One", "t1@tiny.example"))
    _patch(monkeypatch, _fake_gh(_prs()))
    rc = main(["pack", str(built.root), "--vendors", str(VENDORS), "--out", str(tmp_path / "o"),
               "--allow-small-vendors", "--window-days", "400"])
    assert rc == 0
    assert "small vendors" in capsys.readouterr().err.lower()
    data = json.loads(next((tmp_path / "o").glob("*.aems.json")).read_text())
    labels = [r["label"] for r in data["metrics"]["pack"]["vendors"]["rows"]]
    assert labels == ["Acme Dev", "Tiny Co"] and data["metrics"]["pack"]["vendors"]["small_vendors_allowed"]


def test_too_few_people_suppresses_class_breakdowns(repo):
    repo.commit("feat: a", {"src/a.py": TEN}, days_ago=100)
    repo.commit("fix: a", {"src/a.py": _edit(TEN, {1: "z\n"})}, days_ago=90)
    pack = _scan(repo.root, offline=True, vendors=None).metrics["pack"]
    assert set(pack["escapes"]["by_class"].values()) == {SUPPRESSED}
    assert pack["escapes"]["traced"] == 1  # totals stay
    assert pack["vendors"]["configured"] is False


def test_cli_pack_writes_report_and_export(repo, tmp_path):
    built, _ = _build(repo)
    out = tmp_path / "out"
    # the CLI uses the wall clock, not NOW: widen the window so every fixture commit is inside it
    assert main(["pack", str(built.root), "--vendors", str(VENDORS), "--out", str(out), "--offline",
                 "--window-days", "400"]) == 0
    html = next(out.glob("*.aems.html")).read_text()
    assert "Query pack" in html and "Escaped defects" in html and "Rubber-stamp" in html
    export = json.loads(next(out.glob("*.export.json")).read_text())
    assert export["pack"]["review_timing"]["available"] is False
    assert export["pack"]["escapes"]["fix_commits"] == 5


def test_cli_pack_rejects_bad_vendor_file(repo, tmp_path, capsys):
    bad = tmp_path / "v.json"
    bad.write_text("{not json")
    repo.commit("feat: a", {"src/a.py": "x\n"}, days_ago=1)
    assert main(["pack", str(repo.root), "--vendors", str(bad), "--out", str(tmp_path / "o"), "--offline"]) == 2
    assert "vendors" in capsys.readouterr().err


def test_scan_without_pack_has_no_pack_section(repo):
    repo.commit("feat: a", {"src/a.py": "x\n"}, days_ago=1)
    report = scan_repo(repo.root, now=NOW, offline=True)
    assert "pack" not in report.metrics
    assert export_report(report)["pack"] is None


def test_portfolio_pack_adds_headline_columns(repo_factory, tmp_path):
    root = tmp_path / "fleet"
    one = repo_factory("fleet/one")
    one.commit("feat: a", {"src/a.py": TEN}, days_ago=10)
    one.commit("fix: a", {"src/a.py": _edit(TEN, {1: "z\n"})}, days_ago=5)
    out = tmp_path / "pf"
    assert main(["portfolio", str(root), "--out", str(out), "--offline", "--export", "--pack"]) == 0
    assert "Rubber-stamp" in (out / "portfolio.aems.html").read_text()
    row = json.loads((out / "portfolio.export.json").read_text())["repos"][0]
    assert row["pack_fix_commits"] == 1
    assert json.loads(next((out / "export").glob("*.export.json")).read_text())["pack"] is not None


def test_pack_export_strings_are_safe(repo, monkeypatch):
    from tests.test_export import _leaves
    import re
    _patch(monkeypatch, _fake_gh(_prs()))
    data = export_report(_scan(_build(repo)[0].root), keep_vendor_names=True)["pack"]
    allowed = re.compile(r"^[A-Za-z0-9 ._:+()\-≥<>=%,]*$")
    for path, value in _leaves(data):
        if isinstance(value, str):
            assert "/" not in value and "@" not in value and len(value) <= 64, path
            assert allowed.match(value), (path, value)
        else:
            assert value is None or isinstance(value, (int, float, bool)), path


def test_fix_inside_the_same_branch_is_caught_before_merge_not_escaped(repo):
    repo.commit("feat: base", {"src/a.py": TEN}, days_ago=100)
    repo.branch("feature")
    repo.commit("feat: thing", {"src/b.py": TEN}, days_ago=99)
    repo.commit("fix: thing", {"src/b.py": _edit(TEN, {1: "z\n"})}, days_ago=98)
    repo.checkout("main")
    repo.merge("feature", days_ago=97)
    repo.commit("fix: base", {"src/a.py": _edit(TEN, {2: "y\n"})}, days_ago=50)
    esc = _scan(repo.root, offline=True, vendors=None).metrics["pack"]["escapes"]
    assert esc["fix_commits"] == 2
    assert esc["caught_before_merge"] == 1  # origin and fix landed through the same merge
    assert esc["traced"] == 1
    assert esc["untraceable"] == 0
