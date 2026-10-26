"""Agent attribution and commit-intent classification."""
from aems.attribution import agents_for, is_fix_intent, is_excluded_path, is_test_path
from aems.history import load_commits
from tests.conftest import CLAUDE_TRAILER, DEVIN_BOT, NOW


def test_claude_trailer_by_email_any_display_name():
    for name in ("Claude Code", "Claude Sonnet 5", "Claude Opus 5", "Claude Fable 5"):
        assert agents_for("Dev", "dev@x.org", (f"{name} <noreply@anthropic.com>",), False) == ("Claude",)


def test_devin_bot_author():
    assert agents_for(*DEVIN_BOT, (), False) == ("Devin",)


def test_devin_trailer():
    trailer = "Devin AI <158243242+devin-ai-integration[bot]@users.noreply.github.com>"
    assert agents_for("Dev", "dev@x.org", (trailer,), False) == ("Devin",)


def test_copilot_and_cursor_and_codex():
    assert agents_for("Copilot", "198982749+Copilot@users.noreply.github.com", (), False) == ("Copilot",)
    assert agents_for("Dev", "d@x.org", ("Cursor Agent <cursoragent@cursor.com>",), False) == ("Cursor",)
    assert agents_for("chatgpt-codex-connector[bot]", "x@users.noreply.github.com", (), False) == ("Codex",)


def test_generated_footer_counts_as_claude():
    assert agents_for("Dev", "dev@x.org", (), True) == ("Claude",)


def test_human_only_commit_has_no_agent():
    assert agents_for("Dev", "dev@x.org", ("Pair Person <pair@x.org>",), False) == ()


def test_multiple_agents_sorted_unique():
    trailers = ("Claude <noreply@anthropic.com>", "Claude Code <noreply@anthropic.com>",
                "Cursor Agent <cursoragent@cursor.com>")
    assert agents_for("Dev", "d@x.org", trailers, False) == ("Claude", "Cursor")


def test_fix_intent():
    assert is_fix_intent("fix: crash on start")
    assert is_fix_intent("fix(api): wrong ip")
    assert is_fix_intent("Revert \"feat: thing\"")
    assert is_fix_intent("hotfix: prod down")
    assert is_fix_intent("fixup! feat: thing")
    assert not is_fix_intent("feat: add fixture loader")
    assert not is_fix_intent("prefix handling")
    assert is_fix_intent("Fix login redirect loop")


def test_path_classes():
    assert is_test_path("tests/test_api.py")
    assert is_test_path("src/foo.test.ts")
    assert is_test_path("scripts/test/test-x.sh")
    assert is_test_path("pkg/foo_test.go")
    assert not is_test_path("src/attest.py")
    assert is_excluded_path("package-lock.json")
    assert is_excluded_path("web/pnpm-lock.yaml")
    assert is_excluded_path("dist/bundle.js")
    assert not is_excluded_path("src/app.py")


def test_history_reads_trailers_case_insensitive_and_footer(repo):
    repo.commit("feat: a", {"a.py": "1\n"}, days_ago=10, trailers=("Co-authored-by: Claude <noreply@anthropic.com>",))
    repo.commit("feat: b", {"b.py": "1\n"}, days_ago=9, trailers=(CLAUDE_TRAILER,))
    repo.commit("feat: c", {"c.py": "1\n"}, days_ago=8, body="Generated with [Claude Code](https://claude.com/claude-code)")
    repo.commit("feat: d", {"d.py": "1\n"}, days_ago=7, author=DEVIN_BOT)
    repo.commit("feat: e", {"e.py": "1\n2\n"}, days_ago=6)
    commits = load_commits(repo.root, since_ts=NOW - 100 * 86400)
    by_subject = {c.subject: c for c in commits}
    assert by_subject["feat: a"].agents == ("Claude",)
    assert by_subject["feat: b"].agents == ("Claude",)
    assert by_subject["feat: c"].agents == ("Claude",)
    assert by_subject["feat: d"].agents == ("Devin",)
    assert by_subject["feat: e"].agents == ()
    assert by_subject["feat: e"].files == (("e.py", 2, 0),)
