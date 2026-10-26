"""Query pack (`python -m aems pack`): client-run, read-only, counts-only measures for the
Diagnostic that the base scan does not compute.

  Q1 review timing      open -> first review / approval, per 100 lines, rubber-stamp rate
  Q2 escaped defects    defect fixes blamed back to originating commits, rates per 1K lines
  Q3 vendor lens        per-vendor volume, agent share, review, rework and escape rates

Groups (precedence): vendor (client-local vendors file) > agent (attributed) > human;
non-agent bots are "other bot". k-anonymity as in privacy.py: a class breakdown with a
human or vendor cell backed by 1-4 people is suppressed as a whole. No LLM calls; no
identity, login, domain, path, subject or line content reaches the result.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .escapes import collect, summary
from .pack_github import fetch_pack_prs
from .pack_rules import load_pack_rules
from .privacy import SUPPRESSED, is_small
from .review_timing import by_group, people, summarise, timing_rows
from .vendor_lens import not_configured, vendor_lens
from .vendors import Vendors, pr_class, vendor_for_email


@dataclass(frozen=True)
class PackOptions:
    vendors: Vendors | None = None
    allow_small_vendors: bool = False

    def vendor_of(self):
        return (lambda email: vendor_for_email(self.vendors, email)) if self.vendors else None


def change_group(commit) -> str:
    if commit.vendor:
        return "vendor"
    if commit.agents:
        return "agent"
    return "other bot" if commit.other_bot else "human"


def _commit_people(commits) -> dict[str, int]:
    changes = tuple(c for c in commits if not c.is_merge)
    groups = sorted({change_group(c) for c in changes})
    return {g: len({c.author_key for c in changes if change_group(c) == g and c.author_key}) for g in groups}


def private_breakdown(breakdown: dict, people_by: dict, exempt: frozenset[str], force: bool) -> dict:
    small = any(is_small(people_by.get(g, 0)) for g in breakdown if g not in exempt)
    return {g: SUPPRESSED for g in breakdown} if force or small else dict(breakdown)


def _review(gh: dict, rows, exempt, guard) -> dict:
    return {
        "available": gh["available"], "note": gh["note"], "overall": summarise(rows),
        "by_class": private_breakdown(by_group(rows, "group"), people(rows, "group"), exempt, guard),
    }


def run_pack(root: Path, commits, slug: str | None, offline: bool, now: int, since: int,
             options: PackOptions) -> dict:
    rules = load_pack_rules()
    windows = tuple(rules["escape_windows_days"])
    gh = fetch_pack_prs(slug, offline, rules["bug_label_pattern"])
    rows = timing_rows(gh["prs"], since, lambda p: pr_class(p, options.vendors), rules["rubber_stamp"])
    collected = collect(root, commits, gh["bug_shas"], rules)
    esc = summary(collected, {c.sha: c for c in commits}, now, change_group, windows)
    lens = (vendor_lens(options.vendors.labels, commits, rows, collected["traces"], now, windows,
                        options.allow_small_vendors)
            if options.vendors else not_configured("no vendors file"))
    exempt = frozenset({"vendor"}) if options.allow_small_vendors else frozenset()
    guard = lens["leak_guard"]
    stamp = rules["rubber_stamp"]
    return {
        "rules_version": rules["version"],
        "rubber_stamp_rule": {"max_lines_per_hour": stamp["max_lines_per_hour"], "min_seconds": stamp["min_seconds"]},
        "escape_windows_days": list(windows),
        "review_timing": _review(gh, rows, exempt, guard),
        "escapes": {**esc, "bug_links": gh["bug_links"],
                    "by_class": private_breakdown(esc["by_class"], _commit_people(commits), exempt, guard)},
        "vendors": {k: v for k, v in lens.items() if k != "leak_guard"},
    }
