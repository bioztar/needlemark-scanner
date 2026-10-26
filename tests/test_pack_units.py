"""Query pack, pure parts: vendors file, Q1 review timing, Q2 rates and parsers."""
import json
from pathlib import Path

import pytest

from aems import vendors as vmod
from aems.escape_trace import parse_blame, parse_hunks
from aems.escapes import escape_rates, is_defect_fix
from aems.model import Commit
from aems.pack_rules import load_pack_rules
from aems.review_timing import by_group, rubber_stamp_seconds, summarise, timing_rows
from tests.conftest import DAY, NOW

FIX = Path(__file__).parent / "fixtures"
PRS = json.loads((FIX / "pack_prs.json").read_text())
SINCE = NOW - 180 * DAY
RULES = load_pack_rules()
VENDORS = vmod.load_vendors(FIX / "vendors.json")


def _classify(person):
    return vmod.pr_class(person, VENDORS)


# ---- pack rules data file -------------------------------------------------------------

def test_pack_rules_are_versioned_and_cited():
    assert RULES["version"].startswith("pack-")
    rs = RULES["rubber_stamp"]
    assert rs["max_lines_per_hour"] == 500 and rs["min_seconds"] == 60
    assert "smartbear" in rs["source"].lower() and rs["rationale"]
    assert RULES["escape_windows_days"] == [30, 90]


@pytest.mark.parametrize("size,expected", [(0, 60), (5, 60), (100, 720), (1000, 7200)])
def test_rubber_stamp_threshold_scales_with_size(size, expected):
    assert rubber_stamp_seconds(size, RULES["rubber_stamp"]) == pytest.approx(expected)


# ---- vendors file ---------------------------------------------------------------------

def test_vendor_file_matches_email_domain_and_login_pattern():
    assert vmod.vendor_for_email(VENDORS, "dev@acme.example") == "Acme Dev"
    assert vmod.vendor_for_email(VENDORS, "dev@sub.acme.example") == "Acme Dev"
    assert vmod.vendor_for_email(VENDORS, "123+acme-bob@users.noreply.github.com") == "Acme Dev"
    assert vmod.vendor_for_email(VENDORS, "dev@notacme.example") is None
    assert vmod.vendor_for_login(VENDORS, "ACME-v1") == "Acme Dev"
    assert vmod.vendor_for_login(VENDORS, "fake-h1") is None


@pytest.mark.parametrize("payload", [
    {"vendors": [{"label": "a/b", "email_domains": ["x.example"]}]},
    {"vendors": [{"label": "ok", "email_domains": ["bad domain"]}]},
    {"vendors": [{"label": "ok", "logins": ["("]}]},
    {"vendors": [{"label": "x" * 41, "email_domains": ["x.example"]}]},
    {"vendors": "nope"},
])
def test_invalid_vendor_file_is_rejected(tmp_path, payload):
    path = tmp_path / "v.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(vmod.VendorFileError):
        vmod.load_vendors(path)


def test_vendor_ids_are_salted_hashes_unless_kept(monkeypatch):
    monkeypatch.setenv("AEMS_EXPORT_SALT", "s1")
    a = vmod.vendor_id("Acme Dev")
    monkeypatch.setenv("AEMS_EXPORT_SALT", "s2")
    assert vmod.vendor_id("Acme Dev") != a and len(a) == 12
    assert vmod.vendor_id("Acme Dev", keep=True) == "Acme Dev"


def test_pr_class_precedence_vendor_then_agent_then_human():
    assert _classify({"login": "acme-v1"}) == ("vendor", "Acme Dev")
    assert _classify({"login": "app/devin-ai-integration", "is_bot": True}) == ("agent", None)
    assert _classify({"login": "fake-h1"}) == ("human", None)
    assert _classify({"login": "app/dependabot", "is_bot": True}) == ("other bot", None)


# ---- Q1 review timing -----------------------------------------------------------------

def _rows():
    return timing_rows(PRS, SINCE, _classify, RULES["rubber_stamp"])


def test_timing_overall():
    s = summarise(_rows())
    assert s["prs"] == 14  # #214 merged before the window
    assert s["reviewed"] == 10 and s["approved"] == 9
    assert s["rubber_stamped"] == 5
    assert s["rubber_stamp_rate"] == pytest.approx(5 / 9)
    assert s["median_hours_first_review"] == pytest.approx((1 / 3 + 0.5) / 2)


def test_timing_by_author_class():
    g = by_group(_rows(), "group")
    h, v, a = g["human"], g["vendor"], g["agent"]
    assert (h["prs"], h["reviewed"], h["approved"], h["rubber_stamped"]) == (5, 4, 4, 2)
    assert h["median_hours_first_review"] == pytest.approx(1 / 3)
    assert h["median_hours_approval"] == pytest.approx(1 / 3)
    assert h["median_hours_per_100_lines"] == pytest.approx((1 / 12 + 0.3) / 2)
    assert (v["prs"], v["reviewed"], v["approved"], v["rubber_stamped"]) == (5, 4, 3, 2)
    assert v["median_hours_first_review"] == pytest.approx(2 / 3)
    assert v["median_hours_approval"] == pytest.approx(1 / 3)
    assert (a["prs"], a["approved"], a["rubber_stamped"]) == (3, 2, 1)
    assert g["other bot"]["prs"] == 1 and g["other bot"]["rubber_stamp_rate"] is None


def test_self_approval_is_not_a_review():
    g = by_group(_rows(), "group")
    assert g["vendor"]["prs"] - g["vendor"]["reviewed"] == 1  # #210 approved only by its author


def test_timing_degrades_on_bad_input():
    assert summarise(timing_rows("garbage", SINCE, _classify, RULES["rubber_stamp"]))["prs"] == 0
    broken = [{"number": 1, "createdAt": "nope", "mergedAt": "2026-09-01T00:00:00Z",
               "reviews": [{"author": {"login": "r"}, "state": "APPROVED", "submittedAt": None}]}]
    s = summarise(timing_rows(broken, SINCE, _classify, RULES["rubber_stamp"]))
    assert s["prs"] == 1 and s["median_hours_approval"] is None and s["rubber_stamped"] == 0


# ---- Q2 parsers and rates ---------------------------------------------------------------

DIFF = """diff --git a/src/a.py b/src/a.py
index 1..2 100644
--- a/src/a.py
+++ b/src/a.py
@@ -3,2 +3,2 @@ def f():
-x
-y
+x2
+y2
@@ -10 +10,0 @@
-z
@@ -20,0 +21,3 @@
+new
diff --git a/src/new.py b/src/new.py
new file mode 100644
--- /dev/null
+++ b/src/new.py
@@ -0,0 +1 @@
+n
"""


def test_parse_hunks_keeps_old_side_ranges_only():
    assert parse_hunks(DIFF) == (("src/a.py", ((3, 2), (10, 1))),)


SHA_A, SHA_B = "a" * 40, "b" * 40
BLAME = (f"{SHA_A} 3 3 2\nauthor Someone\nauthor-mail <someone@example.org>\nauthor-time 1700000000\n"
         "author-tz +0000\nsummary secret subject\nfilename src/a.py\n\tsecret line content\n"
         f"{SHA_A} 4 4\n\tmore content\n"
         f"{SHA_B} 10 10 1\nauthor-time 1700000500\nboundary\nfilename src/a.py\n\t{SHA_A} 1 1 fake\n")


def test_parse_blame_counts_lines_and_ignores_content():
    lines, times = parse_blame(BLAME)
    assert lines == {SHA_A: 2, SHA_B: 1}
    assert times == {SHA_A: 1700000000, SHA_B: 1700000500}
    assert "secret" not in repr((lines, times))


@pytest.mark.parametrize("subject,expected", [
    ("fix: x", True), ("fix(api)!: x", True), ("hotfix: x", True), ("bugfix: y", True),
    ('Revert "feat: thing"', True), ("feat: fix later", False), ("fixup! x", False), ("refactor: x", False),
])
def test_defect_fix_subjects(subject, expected):
    assert is_defect_fix(subject, RULES["fix_subject_patterns"]) is expected


def _commit(sha, days_ago, lines, group_vendor=None, agents=()):
    return Commit(sha=sha, parents=("p",), ts=NOW - days_ago * DAY, subject="feat: x",
                  files=(("src/m.py", lines, 0),), agents=agents, vendor=group_vendor)


def test_escape_rates_weight_defects_by_blamed_lines_and_mature_windows():
    origins = (_commit("h", 100, 1000), _commit("v", 100, 500, group_vendor="Acme Dev"),
               _commit("young", 10, 400))
    commits = {c.sha: c for c in origins}
    traces = (
        {"fix_ts": NOW - 80 * DAY, "lines": {"h": 3, "v": 1}, "times": {"h": NOW - 100 * DAY, "v": NOW - 100 * DAY}},
        {"fix_ts": NOW - 40 * DAY, "lines": {"v": 2}, "times": {"v": NOW - 100 * DAY}},
        {"fix_ts": NOW - 1 * DAY, "lines": {"young": 5}, "times": {"young": NOW - 10 * DAY}},
    )
    out = escape_rates(traces, commits, NOW, lambda c: "vendor" if c.vendor else "human", (30, 90))
    assert out["human"]["defects_30"] == pytest.approx(0.75)  # age 20d, weight 3/4
    assert out["vendor"]["defects_30"] == pytest.approx(0.25)
    assert out["vendor"]["defects_90"] == pytest.approx(1.25)  # second fix is 60 days later
    assert out["human"]["lines_30"] == 1000  # the 10-day-old commit has not matured for 30 days
    assert out["human"]["per_1k_90"] == pytest.approx(0.75)
    assert out["vendor"]["per_1k_90"] == pytest.approx(2.5)


def test_gh_guard_allows_issue_list_only():
    from aems.runner import _gh_is_read_only
    assert _gh_is_read_only(("issue", "list", "-R", "o/r"))
    assert not _gh_is_read_only(("issue", "create", "-R", "o/r"))
    assert not _gh_is_read_only(("issue", "list", "-F", "x"))
