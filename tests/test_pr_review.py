"""PR review signals from `gh pr list --state merged` (pure) and their graceful degradation."""
import json
from pathlib import Path

import pytest

from aems import github
from aems.export import export_report
from aems.pr_review import UNOBSERVED_KEYS, author_class, pr_review_metrics, unobserved
from aems.render import render_html
from aems.scan import report_to_dict, scan_repo
from tests.conftest import CLAUDE_TRAILER, DAY, NOW

FIXTURE = Path(__file__).parent / "fixtures" / "merged_prs.json"
PRS = json.loads(FIXTURE.read_text())
SINCE = NOW - 180 * DAY
FAKE_IDENTS = ("fake-human-dev", "fake-reviewer-two", "fake-renovate", "fake-deploy-preview",
               "fake-review-text", "fake-comment-text")


def test_formal_review_share_and_unreviewed_count():
    m = pr_review_metrics(PRS, since_ts=SINCE)
    assert m["available"] is True
    assert m["merged"] == 7  # #107 merged before the window
    # reviewed: #101 non-author APPROVED, #104 non-author CHANGES_REQUESTED, #105 decision APPROVED,
    # #108 agent review by a non-author. Not: #102 self-review (other login spelling), #103
    # REVIEW_REQUIRED (merged without the required approval), #106 DISMISSED/PENDING only.
    assert m["reviewed"] == 4
    assert m["unreviewed"] == 3
    assert m["reviewed_share"] == pytest.approx(4 / 7)


def test_sizes_time_to_merge_and_comments():
    m = pr_review_metrics(PRS, since_ts=SINCE)
    assert m["median_size_lines"] == 50  # 4, 7, 10, 50, 60, 120, 300
    assert m["median_hours_to_merge"] == pytest.approx(7.5)  # 1, 2, 5, 10, 20, 30 (#105 bad createdAt)
    # non-author, non-(other bot) conversation comments + review submissions: #101 2, #104 1, #108 1
    assert m["review_comments_mean"] == pytest.approx(4 / 7)
    assert m["reviewed_lines_share"] == pytest.approx(197 / 551)
    assert sorted(m["sizes"]) == [4, 7, 10, 50, 60, 120, 300]


def test_authors_aggregated_into_classes():
    m = pr_review_metrics(PRS, since_ts=SINCE)
    assert m["by_author_class"] == {"human": 1, "Devin": 1, "Claude": 1, "Copilot": 1, "Cursor": 1,
                                    "other bot": 1, "unknown": 1}
    assert m["agent_authored"] == 4
    assert m["agent_unreviewed"] == 2  # Devin #102, Claude #103
    assert m["human_reviewed"] == 2  # #101, #104
    assert m["agent_reviewed"] == 1  # #108
    assert not any(ident in json.dumps(m) for ident in FAKE_IDENTS)


@pytest.mark.parametrize("login,is_bot,expected", [
    ("app/devin-ai-integration", True, "Devin"), ("devin-ai-integration[bot]", True, "Devin"),
    ("app/claude", True, "Claude"), ("claude[bot]", True, "Claude"), ("Copilot", True, "Copilot"),
    ("app/copilot-swe-agent", True, "Copilot"), ("app/cursor", True, "Cursor"), ("cursor[bot]", True, "Cursor"),
    ("dependabot[bot]", True, "other bot"), ("app/fake-renovate", True, "other bot"),
    ("some-person", False, "human"), (None, False, "unknown"),
    ("devin-smith", False, "human"), ("devin", False, "human"), ("codexfan", False, "human"),
    ("anthropic-fan", False, "human"), ("chatgpt-codex-connector[bot]", True, "Codex"),
])
def test_author_class(login, is_bot, expected):
    assert author_class({"login": login, "is_bot": is_bot} if login else None) == expected


def test_empty_observed_is_zero_not_unavailable():
    m = pr_review_metrics([], since_ts=SINCE)
    assert m["available"] is True and m["merged"] == 0
    assert m["reviewed_share"] is None and m["median_size_lines"] is None


@pytest.mark.parametrize("garbage", [None, "oops", 42, [None, "x", {"mergedAt": None}]])
def test_garbage_input_never_crashes(garbage):
    m = pr_review_metrics(garbage, since_ts=SINCE)
    assert set(m) == set(UNOBSERVED_KEYS)


def test_unobserved_has_fixed_shape():
    m = unobserved("gh not installed")
    assert set(m) == set(UNOBSERVED_KEYS)
    assert m["available"] is False and m["note"] == "gh not installed"
    assert m["merged"] is None and m["sizes"] == ()


def _github_repo(repo):
    repo.commit("chore: init", {"AGENTS.md": "# x\n", "src/app.py": "x=1\n"}, days_ago=90)
    repo.commit("feat: a", {"src/a.py": "x=1\n"}, days_ago=80, trailers=(CLAUDE_TRAILER,))
    repo._git(["remote", "add", "origin", "https://github.com/fake-owner/fake-repo.git"], NOW, ("x", "x@x"))
    return repo


def _fake_gh(pr_json):
    def fake(*args, **_):
        if args[:2] == ("run", "list"):
            return "[]", "ok"
        if args[:2] == ("pr", "list"):
            assert "--limit" in args and "200" in args
            return pr_json, "ok"
        return None, "not found or not visible (404)"
    return fake


def test_scan_renders_pr_signals_without_identities(repo, monkeypatch):
    monkeypatch.setattr(github, "gh", _fake_gh(FIXTURE.read_text()))
    report = scan_repo(_github_repo(repo).root, now=NOW)
    prs = report.metrics["github"]["prs"]
    assert prs["reviewed"] == 4 and "sizes" not in prs
    html = render_html(report)
    assert "Merged PRs with a formal review" in html and "4/7" in html
    dim5 = next(d for d in report.dims if d.dim == 5)
    assert any("formal review" in ev.label for c in dim5.checks for ev in c.evidence)
    exported = export_report(report)
    assert exported["github"]["prs_reviewed"] == 4
    assert exported["github"]["prs_merged_unreviewed"] == 3
    # one distinct human PR author (< 5): the class breakdown is suppressed as a whole
    assert set(exported["github"]["prs_by_author_class"].values()) == {"<5, suppressed"}
    blob = html + json.dumps(report_to_dict(report)) + json.dumps(exported)
    assert not any(ident in blob for ident in FAKE_IDENTS)


@pytest.mark.parametrize("gh_result", [(None, "gh not installed"), (None, "gh not authenticated"),
                                       (None, "gh timed out"), ("{not json", "ok")])
def test_gh_failure_degrades_to_not_observed(repo, monkeypatch, gh_result):
    monkeypatch.setattr(github, "gh", lambda *a, **k: gh_result)
    report = scan_repo(_github_repo(repo).root, now=NOW)
    html = render_html(report)
    assert "not observed" in html
    assert export_report(report)["github"]["prs_reviewed"] is None


def test_offline_and_no_remote_degrade_to_not_observed(repo):
    repo.commit("chore: init", {"src/app.py": "x=1\n"}, days_ago=10)
    for report in (scan_repo(repo.root, now=NOW, offline=True), scan_repo(repo.root, now=NOW)):
        assert "not observed" in render_html(report)
        assert export_report(report)["github"]["prs_merged_unreviewed"] is None


# Gate: unreviewed agent PRs hold dim 5 below L3 when >= 5 merged PRs are observed.
from aems.export import SCHEMA  # noqa: E402
from aems.t1_dims import MIN_PRS_FOR_GATE, unreviewed_agent_pr_check  # noqa: E402


def test_gate_fails_when_agent_pr_merged_unreviewed():
    check = unreviewed_agent_pr_check(pr_review_metrics(PRS, since_ts=SINCE))
    assert MIN_PRS_FOR_GATE == 5
    assert check.level == 3 and check.passed is False
    assert any(ev.label == "agent PRs merged unreviewed" and ev.value == "2 of 4" for ev in check.evidence)


def test_gate_passes_when_every_agent_pr_reviewed():
    reviewed_only = [p for p in PRS if p["number"] not in (102, 103)]
    check = unreviewed_agent_pr_check(pr_review_metrics(reviewed_only, since_ts=SINCE))
    assert check.passed is True
    assert any(ev.value == "0 of 2" for ev in check.evidence)


@pytest.mark.parametrize("prs", [unobserved("offline mode"), None,
                                 pr_review_metrics(PRS[:4], since_ts=SINCE)])
def test_gate_does_not_apply_without_enough_pr_data(prs):
    check = unreviewed_agent_pr_check(prs)
    assert check.passed is True
    assert "not applied" in check.evidence[0].value


def test_scan_dim5_carries_gate_and_cannot_reach_l3(repo, monkeypatch):
    monkeypatch.setattr(github, "gh", _fake_gh(FIXTURE.read_text()))
    report = scan_repo(_github_repo(repo).root, now=NOW)
    dim5 = next(d for d in report.dims if d.dim == 5)
    gate = [c for c in dim5.checks if "merged without a formal review" in c.label]
    assert len(gate) == 1 and gate[0].level == 3 and not gate[0].passed
    assert dim5.raw_level < 3
    assert "agent PRs merged unreviewed: <strong>2 of 4</strong>" in render_html(report)


def test_export_schema_bumped():
    assert SCHEMA == "aems-export-4"
