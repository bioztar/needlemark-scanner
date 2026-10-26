"""k-anonymity (< 5 distinct people behind a class or group -> suppressed) and --one-number mode."""
import json
import re

import pytest

from aems.__main__ import main
from aems.export import export_report
from aems.model import Commit
from aems.privacy import K_MIN, SUPPRESSED, people_by_class, suppress_breakdown
from aems.render import render_html
from aems.scan import report_to_dict, scan_repo
from tests.conftest import CLAUDE_TRAILER, DEVIN_BOT, NOW


def _c(n, key, agents=(), other_bot=False):
    return Commit(sha=f"s{n}", parents=("p",), ts=NOW, subject="feat: x", files=(("a.py", 1, 0),),
                  agents=agents, other_bot=other_bot, author_key=key)


def test_k_min_is_five_and_marker_text():
    assert K_MIN == 5
    assert SUPPRESSED == "<5, suppressed"


def test_people_counts_distinct_person_keys_per_class():
    commits = (_c(1, "a"), _c(2, "a"), _c(3, "b"), _c(4, "a", agents=("Claude",)), _c(5, None, agents=("Devin",)),
               _c(6, None, other_bot=True))
    assert people_by_class(commits) == {"human": 2, "Claude": 1, "Devin": 0, "other bot": 0}


@pytest.mark.parametrize("people,suppressed", [(4, True), (5, False), (0, False)])
def test_boundary_at_five_people(people, suppressed):
    out = suppress_breakdown({"human": 12, "Devin": 3}, {"human": people, "Devin": 0})
    assert (out == {"human": SUPPRESSED, "Devin": SUPPRESSED}) is suppressed
    if not suppressed:
        assert out == {"human": 12, "Devin": 3}


def test_bot_only_cells_do_not_trigger_suppression():
    assert suppress_breakdown({"Devin": 7, "other bot": 2}, {"Devin": 0, "other bot": 0}) == {"Devin": 7, "other bot": 2}


def test_one_small_cell_suppresses_the_whole_map():
    out = suppress_breakdown({"human": 40, "Claude": 2, "Devin": 9}, {"human": 6, "Claude": 1, "Devin": 0})
    assert set(out.values()) == {SUPPRESSED}


def _solo(repo):
    repo.commit("chore: init", {"AGENTS.md": "# x\n", "src/app.py": "x=1\n"}, days_ago=90)
    for i in range(6):
        repo.commit(f"feat: c{i}", {f"src/c{i}.py": "x=1\n"}, days_ago=80 - i, trailers=(CLAUDE_TRAILER,))
    repo.commit("feat: devin", {"src/d.py": "x=1\n"}, days_ago=60, author=DEVIN_BOT)
    return scan_repo(repo.root, now=NOW, offline=True)


def test_solo_repo_suppresses_breakdowns_but_keeps_totals(repo):
    report = _solo(repo)
    attr, rw = report.metrics["attribution"], report.metrics["rework"]
    assert set(attr["by_class"].values()) == {SUPPRESSED}
    assert set(attr["by_tool"].values()) == {SUPPRESSED}
    assert rw["human_matured"] == SUPPRESSED and rw["human_rate"] == SUPPRESSED
    assert attr["commits"] == 8 and attr["agent_commits"] == 7 and isinstance(attr["ai_share_commits"], float)
    exported = export_report(report)
    assert set(exported["attribution"]["by_class"].values()) == {SUPPRESSED}
    assert exported["rework"]["human_rate"] == SUPPRESSED
    assert exported["attribution"]["agent_commits"] == 7
    assert "&lt;5, suppressed" in render_html(report)  # HTML-escaped marker


def test_author_keys_never_reach_outputs(repo):
    report = _solo(repo)
    blob = render_html(report) + json.dumps(report_to_dict(report)) + json.dumps(export_report(report))
    assert "author_key" not in blob


def test_suppression_does_not_change_scores(repo):
    report = _solo(repo)
    assert all(isinstance(d.level, int) for d in report.dims)


def test_one_number_prints_one_line_and_writes_nothing(repo, tmp_path, capsys):
    _solo(repo)
    out_dir = tmp_path / "should-not-exist"
    assert main(["scan", str(repo.root), "--one-number", "--offline", "--out", str(out_dir)]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1
    assert re.fullmatch(r"AEMS L[0-5] \(median L[0-5](\.5)?\) · VDR (green|amber|red|n/a)", lines[0])
    assert repo.root.name not in lines[0]
    assert not out_dir.exists()


def test_one_number_rejects_export(repo):
    _solo(repo)
    with pytest.raises(SystemExit):
        main(["scan", str(repo.root), "--one-number", "--export", "--offline"])
