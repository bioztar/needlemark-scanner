"""T1 metrics: rework proxy (with censoring), verification-debt ratio, review line."""
import math

from aems.history import load_commits
from aems.metrics import flow, rework, vdr
from aems.model import Commit
from tests.conftest import CLAUDE_TRAILER, DAY, NOW

AGENT = (CLAUDE_TRAILER,)


def _c(sha, days_ago, files, agents=(), subject="feat: x", first=True, squash=False, parents=("p",)):
    return Commit(sha=sha, parents=parents, ts=int(NOW - days_ago * DAY), subject=subject,
                  files=tuple(files), agents=agents, on_first_parent=first, squash_pr=squash)


# ---------- rework proxy ----------

def test_rework_counts_fix_within_30_days_on_overlapping_file(repo):
    repo.commit("feat: a", {"a.py": "1\n"}, days_ago=100, trailers=AGENT)
    repo.commit("fix: a bug", {"a.py": "2\n"}, days_ago=90)
    commits = load_commits(repo.root, since_ts=NOW - 365 * DAY)
    result = rework(commits, now=NOW, min_matured=1)
    assert result["agent_matured"] == 1
    assert result["agent_reworked"] == 1
    assert result["agent_rate"] == 1.0


def test_rework_ignores_fix_after_30_days(repo):
    repo.commit("feat: b", {"b.py": "1\n"}, days_ago=100, trailers=AGENT)
    repo.commit("fix: late", {"b.py": "2\n"}, days_ago=60)
    result = rework(load_commits(repo.root, since_ts=0), now=NOW, min_matured=1)
    assert result["agent_reworked"] == 0


def test_rework_ignores_fix_on_other_files(repo):
    repo.commit("feat: c", {"c.py": "1\n"}, days_ago=100, trailers=AGENT)
    repo.commit("fix: d", {"d.py": "2\n"}, days_ago=95)
    result = rework(load_commits(repo.root, since_ts=0), now=NOW, min_matured=1)
    assert result["agent_reworked"] == 0


def test_fix_commit_is_not_rework_of_itself():
    commits = (_c("f1", 100, [("a.py", 1, 1)], agents=("Claude",), subject="fix: thing"),)
    result = rework(commits, now=NOW, min_matured=1)
    assert result["agent_matured"] == 1
    assert result["agent_reworked"] == 0


def test_fix_before_agent_commit_does_not_count():
    commits = (
        _c("f0", 101, [("a.py", 1, 1)], subject="fix: earlier"),
        _c("a1", 100, [("a.py", 1, 1)], agents=("Claude",)),
    )
    assert rework(commits, now=NOW, min_matured=1)["agent_reworked"] == 0


def test_rework_censors_open_windows():
    commits = (
        _c("a1", 10, [("a.py", 1, 1)], agents=("Claude",)),
        _c("f1", 5, [("a.py", 1, 1)], subject="fix: x"),
    )
    result = rework(commits, now=NOW, min_matured=1)
    assert result["agent_matured"] == 0
    assert result["agent_open_window"] == 1
    assert result["agent_rate"] is None
    assert result["status"] == "insufficient"


def test_rework_needs_minimum_matured_sample():
    commits = tuple(_c(f"a{i}", 100 + i, [(f"f{i}.py", 1, 0)], agents=("Claude",)) for i in range(3))
    result = rework(commits, now=NOW, min_matured=5)
    assert result["status"] == "insufficient"
    assert result["agent_rate"] == 0.0


def test_rework_healthy_and_human_baseline():
    agent = tuple(_c(f"a{i}", 100, [(f"f{i}.py", 1, 0)], agents=("Claude",)) for i in range(10))
    human = tuple(_c(f"h{i}", 100, [(f"h{i}.py", 1, 0)]) for i in range(4))
    fix = (_c("fx", 95, [("f0.py", 1, 1), ("h0.py", 1, 1)], subject="fix: x"),)
    result = rework(agent + human + fix, now=NOW, min_matured=5)
    assert result["agent_rate"] == 0.1
    assert result["human_rate"] == 0.2  # h0 reworked of 5 (the fix itself is human, matured, not reworked)
    assert result["status"] == "healthy"


# ---------- verification-debt ratio ----------

def test_vdr_is_na_without_any_changes():
    result = vdr((), ci_runs_tests=True)
    assert result["value"] is None
    assert result["status"] == "n/a"


def test_vdr_falls_back_to_total_volume_when_attribution_is_thin():
    commits = (_c("a1", 5, [("src/a.py", 10, 0)], agents=("Claude",)),) + tuple(
        _c(f"h{i}", 5, [(f"src/h{i}.py", 10, 0)]) for i in range(9))
    commits = commits + (_c("t1", 5, [("tests/test_a.py", 25, 0)]),)
    result = vdr(commits, ci_runs_tests=False)
    assert result["basis"] == "total change volume"
    assert result["coverage"] == 1 / 11
    assert "low attribution coverage: 9% of commits attributed" in result["basis_note"]
    assert result["agent_lines"] == 100  # all code lines (tests excluded from the numerator)
    assert result["value"] == 100 / 25


def test_vdr_no_attribution_at_all_uses_total_volume():
    commits = (_c("h1", 5, [("src/a.py", 10, 0)]),)
    result = vdr(commits, ci_runs_tests=True)
    assert result["basis"] == "total change volume"
    assert math.isinf(result["value"])
    assert "0% of commits attributed" in result["basis_note"]


def test_vdr_unbounded_when_no_verification_capacity():
    commits = (_c("a1", 5, [("src/a.py", 10, 0)], agents=("Claude",)),)
    result = vdr(commits, ci_runs_tests=False)
    assert math.isinf(result["value"])
    assert result["status"] == "red"


def test_vdr_counts_test_lines_and_gated_agent_lines():
    commits = (
        _c("a1", 5, [("src/a.py", 60, 0), ("package-lock.json", 900, 0)], agents=("Claude",), first=False),
        _c("a2", 5, [("src/b.py", 40, 0)], agents=("Claude",)),
        _c("h1", 5, [("tests/test_a.py", 20, 0)]),
    )
    result = vdr(commits, ci_runs_tests=True)
    assert result["agent_lines"] == 100  # lockfile excluded
    assert result["test_lines"] == 20
    assert result["gated_agent_lines"] == 60  # a1 landed via a merged branch
    assert result["value"] == 100 / 80
    assert result["status"] == "amber"


def test_vdr_gating_needs_ci_that_runs_tests():
    commits = (_c("a1", 5, [("src/a.py", 60, 0)], agents=("Claude",), squash=True),
               _c("h1", 5, [("tests/test_a.py", 60, 0)]))
    assert vdr(commits, ci_runs_tests=False)["gated_agent_lines"] == 0
    assert vdr(commits, ci_runs_tests=False)["status"] == "green"


# ---------- review line ----------

def test_flow_pr_share_and_agent_gating(repo):
    repo.commit("chore: init", {"r.md": "x\n"}, days_ago=50)
    repo.branch("feature")
    repo.commit("feat: on branch", {"f.py": "1\n"}, days_ago=49, trailers=AGENT)
    repo.checkout("main")
    repo.merge("feature", days_ago=48)
    repo.commit("feat: direct (#12)", {"g.py": "1\n"}, days_ago=47)
    repo.commit("feat: direct agent", {"h.py": "1\n"}, days_ago=46, trailers=AGENT)
    commits = load_commits(repo.root, since_ts=0)
    result = flow(commits)
    assert result["first_parent_changes"] == 4  # init, merge, squash-PR, direct agent
    assert result["pr_landed"] == 2
    assert result["pr_share"] == 0.5
    assert result["agent_commits"] == 2
    assert result["agent_gated_share"] == 0.5


def test_rework_ignores_overlap_on_docs_and_manifests():
    commits = (
        _c("a1", 100, [("src/a.py", 5, 0), ("HANDOVER.md", 3, 1), ("package.json", 1, 1)], agents=("Claude",)),
        _c("f1", 95, [("HANDOVER.md", 1, 1), ("package.json", 1, 1), ("src/other.py", 2, 2)], subject="fix: x"),
    )
    assert rework(commits, now=NOW, min_matured=1)["agent_reworked"] == 0


def test_rework_overlap_on_code_still_counts_with_docs_present():
    commits = (
        _c("a1", 100, [("src/a.py", 5, 0), ("README.md", 3, 1)], agents=("Claude",)),
        _c("f1", 95, [("src/a.py", 1, 1), ("README.md", 1, 1)], subject="fix: x"),
    )
    assert rework(commits, now=NOW, min_matured=1)["agent_reworked"] == 1


def test_docs_only_agent_commits_are_not_in_rework_denominator():
    commits = (
        _c("a1", 100, [("docs/plan.md", 50, 0)], agents=("Claude",)),
        _c("a2", 100, [("src/a.py", 5, 0)], agents=("Claude",)),
    )
    result = rework(commits, now=NOW, min_matured=1)
    assert result["agent_matured"] == 1


def test_vdr_volume_ignores_docs():
    commits = (_c("a1", 5, [("src/a.py", 10, 0), ("docs/notes.md", 500, 0)], agents=("Claude",)),
               _c("t1", 5, [("tests/test_a.py", 10, 0)]))
    assert vdr(commits, ci_runs_tests=False)["agent_lines"] == 10
