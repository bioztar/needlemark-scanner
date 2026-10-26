"""Self-contained HTML report for one repo. Renders only levels, counts, paths
and rule text — never file contents, commit subjects, or people."""
from __future__ import annotations

import math
from html import escape

from .model import DIM_NAMES, LEVEL_NAMES, DimScore, Report
from .render_css import CSS


def e(value) -> str:
    return escape(str(value), quote=True)


def pct(x) -> str:
    if isinstance(x, str):  # k-anonymity marker
        return x
    return "n/a" if x is None else f"{x:.0%}"


def _by_count(mapping: dict) -> list:
    return sorted(mapping.items(), key=lambda kv: -kv[1] if isinstance(kv[1], int) else 0)


def num(x) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, str):  # k-anonymity marker
        return x
    if isinstance(x, float) and math.isinf(x):
        return "unbounded"
    return f"{x:,.2f}" if isinstance(x, float) and not x.is_integer() else f"{int(x):,}"


def bar(dim: DimScore) -> str:
    cells = []
    for i in range(1, 6):
        cls = "on" if i <= dim.level else "raw" if i <= dim.raw_level else ""
        cells.append(f'<i class="{cls}"></i>')
    return f'<span class="bar" aria-label="level {dim.level} of 5">{"".join(cells)}</span>'


def status_pill(dim: DimScore, weakest: tuple[int, ...]) -> str:
    if not dim.assessed:
        return '<span class="pill na">not assessed (needs T2 logs)</span>'
    parts = []
    if dim.capped:
        parts.append(f'<span class="pill cap">presence, not maturity (raw L{dim.raw_level})</span>')
    if dim.dim in weakest:
        parts.append('<span class="pill weak">weakest link</span>')
    return " ".join(parts) or f'<span class="pill ok">{e(LEVEL_NAMES[dim.level])}</span>'


def src(value: str) -> str:
    """Short, readable source label; long regexes are summarised (full text stays in the JSON)."""
    text = str(value)
    if "(^|/)" in text or "|^" in text or len(text) > 90:
        return "path pattern (full regex in JSON)"
    return text


def tile(key: str, value: str, sub: str, tone: str = "") -> str:
    return f'<div class="tile {tone}"><div class="k">{e(key)}</div><div class="v">{e(value)}</div><div class="s">{e(sub)}</div></div>'


def _vdr_tile(v: dict) -> str:
    tone = {"green": "green", "amber": "amber", "red": "red"}.get(v["status"], "")
    who = "agent" if v["basis"] == "agent-attributed" else "all (low attribution)"
    sub = f"{who} lines {num(v['agent_lines'])} / verified {num(v['test_lines'] + v['gated_agent_lines'])}"
    return tile("Verification-debt ratio", num(v["value"]) if v["value"] is not None else "n/a", sub, tone)


def _headline(r: Report) -> str:
    mt = r.metrics
    tone = "red" if r.overall <= 1 else "amber" if r.overall == 2 else "green"
    attr, rw = mt["attribution"], mt["rework"]
    weakest = ", ".join(DIM_NAMES[d] for d in r.weakest) or "-"
    return "".join([
        '<div class="tiles">',
        tile("Overall (weakest link)", f"L{r.overall}", f"{LEVEL_NAMES[r.overall]} · weakest: {weakest}", tone),
        tile("Median level", f"L{r.median:g}", "across 6 assessed dimensions"),
        _vdr_tile(mt["vdr"]),
        tile("AI share of commits", f"≥ {pct(attr['ai_share_commits'])}", f"{attr['agent_commits']} attributed of {attr['commits']} (lower bound)"),
        tile("Agent rework (30d)", pct(rw["agent_rate"]), f"{rw['status']} · n={rw['agent_matured']} matured",
             {"healthy": "green", "high": "red"}.get(rw["status"], "")),
        "</div>",
    ])


def _profile(r: Report) -> str:
    rows = "".join(
        f"<tr><td>{d.dim}</td><td>{e(d.name)}</td><td>{bar(d) if d.assessed else '—'}</td>"
        f"<td class='num'>{'L' + str(d.level) if d.assessed else '—'}</td><td>{status_pill(d, r.weakest)}</td></tr>"
        for d in r.dims
    )
    return ("<h2>Maturity profile</h2><table><thead><tr><th>#</th><th>Dimension</th><th>Level</th>"
            f"<th class='num'>Score</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table>"
            '<p class="src">Solid cells = scored level. Hatched cells = artefacts present for a higher level but '
            "capped at L2 for lack of outcome evidence (outcome cap).</p>")


def _moves(r: Report) -> str:
    if not r.recommendations:
        return "<h2>Next three moves</h2><p>No rule fired.</p>"
    cards = "".join(
        f'<div class="move"><div><span class="n">{i}.</span><strong>{e(rec.move)}</strong></div>'
        f"<dl><dt>Dimension</dt><dd>{rec.dim} · {e(DIM_NAMES[rec.dim])}</dd>"
        f"<dt>Why</dt><dd>{e(rec.rationale)}</dd><dt>Evidence base</dt><dd>{e(rec.source)}</dd>"
        f"<dt>Expected effect</dt><dd>{e(rec.expected_effect)}</dd><dt>Not yet</dt><dd>{e(rec.not_yet)}</dd>"
        f"<dt>Confidence</dt><dd>{e(rec.confidence)} · rule <code>{e(rec.rule_id)}</code> · review by {e(rec.review_by)}</dd></dl></div>"
        for i, rec in enumerate(r.recommendations, 1)
    )
    return f"<h2>Next three moves</h2>{cards}"


def _dim_detail(d: DimScore) -> str:
    if not d.assessed:
        rows = "".join(f"<tr><td>{e(h.label)}</td><td>{e(h.value)}</td><td class='src'>{e(src(h.source))}</td></tr>" for h in d.hints)
        return (f'<div class="dimcard"><h3>{d.dim}. {e(d.name)} — not assessed (needs T2 logs)</h3>'
                "<p class='src'>Presence hints only; they do not score.</p>"
                f"<table><thead><tr><th>Hint</th><th>Observed</th><th>Source</th></tr></thead><tbody>{rows}</tbody></table></div>")
    rows = []
    for c in d.checks:
        ev = "<br>".join(f"{e(x.label)}: <strong>{e(x.value)}</strong> <span class='src'>[{e(src(x.source))}]</span>" for x in c.evidence)
        pill = '<span class="pill ok">met</span>' if c.passed else '<span class="pill no">not met</span>'
        rows.append(f"<tr><td class='num'>L{c.level}</td><td>{e(c.label)}</td><td>{pill}</td><td>{ev}</td></tr>")
    out = ""
    if d.outcome is not None:
        oev = "<br>".join(f"{e(x.label)}: <strong>{e(x.value)}</strong> <span class='src'>[{e(src(x.source))}]</span>" for x in d.outcome.evidence)
        pill = '<span class="pill ok">present</span>' if d.outcome.passed else '<span class="pill cap">absent</span>'
        out = f"<tr><td class='num'>≥L3</td><td>Outcome check: {e(d.outcome.label)}</td><td>{pill}</td><td>{oev}</td></tr>"
    return (f'<div class="dimcard"><h3>{d.dim}. {e(d.name)} — L{d.level} {e(d.label)}</h3>'
            "<table><thead><tr><th>Lvl</th><th>Evidence required</th><th>Result</th><th>Observed</th></tr></thead>"
            f"<tbody>{''.join(rows)}{out}</tbody></table></div>")


def _kv_table(title: str, rows: list[tuple[str, str, str]]) -> str:
    body = "".join(f"<tr><td>{e(k)}</td><td class='num'>{e(v)}</td><td class='src'>{e(s)}</td></tr>" for k, v, s in rows)
    return f"<h3>{e(title)}</h3><table><thead><tr><th>Measure</th><th class='num'>Value</th><th>How</th></tr></thead><tbody>{body}</tbody></table>"


def _observed(prs: dict, value: str) -> str:
    if not prs.get("available"):
        return "not observed"
    return "0 merged PRs" if not prs.get("merged") else value


def _pr_table(prs: dict) -> str:
    n = prs.get("merged")
    classes = ", ".join(f"{k}: {v}" for k, v in _by_count(prs.get("by_author_class") or {}))
    rows = [
        ("Merged PRs in window", _observed(prs, num(n)),
         prs.get("note") or "gh unavailable"),
        ("Merged PRs with a formal review", _observed(prs, f"{prs.get('reviewed')}/{n} ({pct(prs.get('reviewed_share'))})"),
         "non-author APPROVED / CHANGES_REQUESTED / COMMENTED review, or decision APPROVED / CHANGES_REQUESTED"),
        ("PRs merged unreviewed", _observed(prs, num(prs.get("unreviewed"))),
         f"of which agent-authored: {num(prs.get('agent_unreviewed'))}"),
        ("Reviewed by a human / by an agent or review bot", _observed(prs, f"{num(prs.get('human_reviewed'))} / {num(prs.get('agent_reviewed'))}"),
         "PR counts; reviewer identities aggregated"),
        ("Median PR size (lines)", _observed(prs, num(prs.get("median_size_lines"))), "additions + deletions"),
        ("Median time to merge (hours)", _observed(prs, num(prs.get("median_hours_to_merge"))), "mergedAt − createdAt"),
        ("Review comments per PR (mean)", _observed(prs, num(prs.get("review_comments_mean"))),
         "non-author conversation comments + reviews, non-agent bots excluded; inline diff comments not visible (lower bound)"),
        ("PR authors by class", _observed(prs, classes or "-"), "human / agent tool / other bot; no logins"),
    ]
    return _kv_table("PR review signals (dim 5, verification capacity)", rows)


def _t1(r: Report) -> str:
    mt = r.metrics
    a, rw, fl, b, ch, v = mt["attribution"], mt["rework"], mt["flow"], mt["batch"], mt["churn"], mt["vdr"]
    gh = mt["github"]
    prs = gh.get("prs") or {}
    runs = gh.get("runs", {}) if gh.get("available") else {}
    tools = ", ".join(f"{k}: {n}" for k, n in a["by_tool"].items()) or "none"
    classes = ", ".join(f"{k}: {n}" for k, n in _by_count(a["by_class"])) or "none"
    return "<h2>Delivery evidence (T1)</h2>" + "".join([
        _kv_table("Attribution (lower bound)", [
            ("Commits in window (non-merge)", num(a["commits"]), f"git log, last {mt['window_days']} days"),
            ("Agent-attributed commits", num(a["agent_commits"]), "trailers, bot authors, footer grep"),
            ("By agent tool", tools, "attribution classifier"),
            ("Identity classes (commits)", classes, "aggregated; no individual names or emails"),
            ("AI share of changed lines", pct(a["ai_share_lines"]), "numstat, lockfiles/generated excluded"),
            ("Conventional-commit share", pct(a["conventional_share"]), "subject prefix (not rendered)")]),
        _kv_table("Rework proxy (30-day fix overlap)", [
            ("Agent commits matured (≥30d old)", num(rw["agent_matured"]), "open windows excluded"),
            ("…reworked within 30 days", num(rw["agent_reworked"]), "later fix/revert/hotfix on same file"),
            ("Agent rework rate", pct(rw["agent_rate"]), f"status: {rw['status']}"),
            ("Human-only baseline", pct(rw["human_rate"]), "biased low: includes unattributed agent work"),
            ("Agent commits with open window", num(rw["agent_open_window"]), "too young to judge")]),
        _kv_table("Review line and batch size", [
            ("Changes landed via PR/merge", pct(fl["pr_share"]), f"{fl['pr_landed']}/{fl['first_parent_changes']} first-parent changes"),
            ("Agent commits via PR/merge", pct(fl["agent_gated_share"]), f"{fl['agent_gated']}/{fl['agent_commits']}"),
            ("Median commit size (lines)", num(b["commit_median_lines"]), f"p90 {num(b['commit_p90_lines'])}"),
            ("Median PR size (lines)", num(b["pr_median_lines"]), f"n={b['pr_sample']}, p90 {num(b['pr_p90_lines'])}"),
            ("Delete/add ratio", num(ch["delete_add_ratio"]), "churn proxy"),
            ("Commits re-touching a file within 14d", pct(ch["retouch_share"]), "churn proxy")]),
        _kv_table("Verification-debt ratio", [
            ("Basis", v["basis"], v["basis_note"]),
            ("A · changed code lines (non-test)", num(v["agent_lines"]), "basis commits, excl. tests, lockfiles, generated"),
            ("T · test-file lines changed", num(v["test_lines"]), "any author"),
            ("G · A-lines through a test-running CI path", num(v["gated_agent_lines"]), f"CI runs tests: {'yes' if v['ci_runs_tests'] else 'no'}"),
            ("VDR = A ÷ (T + G)", num(v["value"]), f"status: {v['status']} (≤1 green, ≤3 amber)"),
            ("Context: merged-PR lines under a formal review", _observed(prs, pct(prs.get("reviewed_lines_share"))),
             "not in the formula (would double-count G); reviewed PR lines ÷ all merged PR lines")]),
        _pr_table(prs),
        _kv_table("CI and GitHub", [
            ("GitHub evidence", "available" if gh.get("available") else "unavailable", gh.get("note") or "gh, read-only"),
            ("CI runs in window", num(runs.get("runs")), "gh run list"),
            ("Success share (decided runs)", pct(runs.get("success_share")), "gh run list --json conclusion"),
            ("Branch protection", "visible" if (gh.get("protection") or {}).get("visible") else "not visible",
             (gh.get("protection") or {}).get("note", "-"))]),
    ])


METHOD = """<h2>Method and limits</h2>
<p><strong>Levels.</strong> Each dimension climbs 1→5; a level is awarded only when <em>every</em> check at that level and all
levels below it is met. <strong>Overall</strong> is the weakest link (minimum) across the six assessed dimensions, shown with the median:
a team at L4 orchestration with L1 verification is in the autonomy trap and must not average to L2.5.
<strong>Outcome cap:</strong> a level ≥3 without outcome evidence (matured agent rework ≤20% on ≥5 commits; CI runs observed and ≥70%
green; no secret-shaped strings tracked) is capped at L2 and labelled <em>presence, not maturity</em>.</p>
<p><strong>Verification-debt ratio</strong> = agent-changed code lines ÷ (test-file lines changed + those agent lines that landed through a
PR while CI runs tests). Above 1, agents change more than the verification system covers. When fewer than 25% of commits carry agent
attribution, the numerator falls back to <em>total</em> change volume and is labelled so.</p>
<p><strong>Data handling.</strong> Classification is rule-based (regex on commit subjects, file paths and trailers), in memory, with no
LLM or network call on repository data. Identities are aggregated into human / agent class / other bot. The numbers-only export
(<code>python -m aems export</code>) carries no paths, subjects, names or slugs.</p>
<div class="callout warn"><strong>What this scan cannot see.</strong> Agent work committed without attribution (all AI shares are lower bounds);
whether reviewers actually read diffs; conversations and transcripts (dims 4, 6, 7 need T2 logs); production incidents and usage
(survival needs a 90-day outcome join); business value. Rework uses commit intent from subjects and file overlap — a proxy, not a defect count.</div>
"""


def render_html(r: Report) -> str:
    from .pack_render import render_pack  # pack_render reuses this module's helpers

    notes = "".join(f"<li>{e(n)}</li>" for n in r.notes)
    detail = "".join(_dim_detail(d) for d in r.dims)
    return (
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>AEMS report · {e(r.repo)}</title><style>{CSS}</style></head><body><main>"
        f"<header class='cover'><div class='eyebrow'>Agentic Engineering Maturity Score · T0/T1 scan</div>"
        f"<h1>{e(r.repo)}</h1><div class='meta'><span>Scanned {e(r.scanned_at)}</span><span>Tiers: {e(' + '.join(r.tiers))}</span>"
        f"<span>Model {e(r.model_version)}</span><span>Rules {e(r.metrics.get('rules_version', '-'))}</span></div></header>"
        f"{_headline(r)}<div class='callout'><ul style='margin:0;padding-left:18px'>{notes}</ul></div>"
        f"{_profile(r)}{_moves(r)}<h2>Evidence by dimension</h2>{detail}{_t1(r)}{render_pack(r.metrics.get('pack'))}{METHOD}"
        "<footer>Generated by the needlemark AEMS scanner. Every figure is reproducible from the listed source command or path. "
        "No file contents, commit messages, transcripts or personal identities are included.</footer></main></body></html>"
    )
