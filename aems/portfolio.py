"""Portfolio mode: scan every git repo directly under a directory."""
from __future__ import annotations

import json
from pathlib import Path

from .model import DIM_NAMES
from .render import e, num, pct
from .render_css import CSS
from .safe_io import ensure_dir, safe_name, write_text_atomic
from .export import export_report, repo_id
from .render import render_html
from .scan import report_to_dict, scan_repo

SKIP_DIRS = {"_worktrees", "node_modules", ".git"}


def discover(root: Path) -> tuple[Path, ...]:
    return tuple(sorted(
        (p for p in root.iterdir()
         if p.is_dir() and not p.is_symlink() and p.name not in SKIP_DIRS and not p.name.startswith(".") and (p / ".git").exists()),
        key=lambda p: p.name.lower(),
    ))


def _prs(mt: dict) -> dict:
    return mt["github"].get("prs") or {}


def _row(report) -> dict:
    mt = report.metrics
    return {
        "repo": report.repo, "error": None, "overall": report.overall, "median": report.median,
        "levels": {str(d.dim): (d.level if d.assessed else None) for d in report.dims},
        "capped": [d.dim for d in report.dims if d.capped],
        "weakest": list(report.weakest),
        "vdr": mt["vdr"]["value"], "vdr_status": mt["vdr"]["status"], "vdr_basis": mt["vdr"]["basis"],
        "ai_share_commits": mt["attribution"]["ai_share_commits"],
        "agent_commits": mt["attribution"]["agent_commits"], "commits": mt["attribution"]["commits"],
        "rework_rate": mt["rework"]["agent_rate"], "rework_status": mt["rework"]["status"],
        "github": mt["github"].get("available", False),
        "pr_reviewed_share": _prs(mt).get("reviewed_share"), "prs_merged": _prs(mt).get("merged"),
        "prs_merged_unreviewed": _prs(mt).get("unreviewed"),
        "top_move": report.recommendations[0].rule_id if report.recommendations else None,
        **_pack_cells(mt.get("pack")),
    }


def _pack_cells(pack: dict | None) -> dict:
    """Two headline query-pack numbers per repo (None when the pack did not run)."""
    if not pack:
        return {"pack_rubber_stamp_rate": None, "pack_escaped_per_1k_90": None, "pack_fix_commits": None}
    overall = pack["escapes"].get("overall") or {}
    return {"pack_rubber_stamp_rate": pack["review_timing"]["overall"]["rubber_stamp_rate"],
            "pack_escaped_per_1k_90": overall.get("per_1k_90"), "pack_fix_commits": pack["escapes"]["fix_commits"]}


def scan_portfolio(root, now: int | None = None, offline: bool = False, out_dir: Path | None = None,
                   window_days: int = 180, export: bool = False, keep_name: bool = False, pack=None,
                   keep_vendor_names: bool = False) -> dict:
    root = Path(root)
    rows = []
    for repo in discover(root):
        try:
            report = scan_repo(repo, now=now, offline=offline, window_days=window_days, pack=pack)
        except Exception as exc:  # one broken repo must not stop the portfolio
            rows.append({"repo": repo.name, "error": f"{type(exc).__name__}: {exc}"[:200], "overall": None})
            continue
        rows.append(_row(report))
        if out_dir is not None:
            write_report(report, out_dir / "repos")
            if export:
                write_export(report, out_dir / "export", keep_name, keep_vendor_names)
    return {"root": root.name, "repos": len(rows), "rows": rows}


def write_report(report, out_dir: Path) -> tuple[Path, Path]:
    ensure_dir(out_dir)
    name = safe_name(report.repo)
    jpath, hpath = out_dir / f"{name}.aems.json", out_dir / f"{name}.aems.html"
    write_text_atomic(jpath, json.dumps(report_to_dict(report), indent=2))
    write_text_atomic(hpath, render_html(report))
    return jpath, hpath


def write_export(report, out_dir: Path, keep_name: bool = False, keep_vendor_names: bool = False) -> Path:
    ensure_dir(out_dir)
    path = out_dir / f"{safe_name(repo_id(report.repo, keep_name))}.export.json"
    write_text_atomic(path, json.dumps(export_report(report, keep_name, keep_vendor_names), indent=2))
    return path


def _lvl(v) -> str:
    return "—" if v is None else f"L{v}"


def _pr_cell(r: dict) -> str:
    if r.get("prs_merged") is None:
        return "—"
    return "0 PRs" if not r["prs_merged"] else f"{pct(r['pr_reviewed_share'])} of {r['prs_merged']}"


def _pack_td(r: dict) -> str:
    return f"<td class='num'>{pct(r.get('pack_rubber_stamp_rate'))}</td><td class='num'>{num(r.get('pack_escaped_per_1k_90'))}</td>"


def render_portfolio(summary: dict, now_label: str) -> str:
    ok = [r for r in summary["rows"] if not r.get("error")]
    ok_sorted = sorted(ok, key=lambda r: (-r["overall"], -r["median"], r["repo"].lower()))
    dims = ("1", "2", "3", "5", "8", "9")
    head = "".join(f"<th class='num' title='{e(DIM_NAMES[int(d)])}'>D{d}</th>" for d in dims)
    has_pack = any(r.get("pack_fix_commits") is not None for r in ok)
    pack_head = ("<th class='num' title='query pack: approvals faster than the review-rate threshold'>Rubber-stamp</th>"
                 "<th class='num' title='query pack: escaped defects per 1K changed lines within 90 days'>Escapes/1K</th>"
                 if has_pack else "")
    body = []
    for r in ok_sorted:
        cells = "".join(
            f"<td class='num'>{_lvl(r['levels'][d])}{'*' if int(d) in r['capped'] else ''}</td>" for d in dims)
        link = f"<a href='repos/{e(safe_name(r['repo']))}.aems.html'>{e(r['repo'])}</a>"
        body.append(f"<tr><td>{link}</td><td class='num'><strong>L{r['overall']}</strong></td><td class='num'>L{r['median']:g}</td>{cells}"
                    f"<td class='num'>{num(r['vdr'])}</td><td class='num'>≥{pct(r['ai_share_commits'])}</td>"
                    f"<td class='num'>{pct(r['rework_rate'])}</td><td class='num'>{_pr_cell(r)}</td>{_pack_td(r) if has_pack else ''}"
                    f"<td class='src'>{e(r['top_move'] or '-')}</td></tr>")
    errors = "".join(f"<li><strong>{e(r['repo'])}</strong>: {e(r['error'])}</li>" for r in summary["rows"] if r.get("error"))
    dist = {lvl: sum(1 for r in ok if r["overall"] == lvl) for lvl in range(6)}
    dist_txt = " · ".join(f"L{k}: {v}" for k, v in dist.items() if v)
    weak_counts: dict[int, int] = {}
    for r in ok:
        for d in r["weakest"]:
            weak_counts = {**weak_counts, d: weak_counts.get(d, 0) + 1}
    weak_txt = ", ".join(f"{DIM_NAMES[d]} ({n})" for d, n in sorted(weak_counts.items(), key=lambda x: -x[1])[:3])
    return (
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>AEMS portfolio · {e(summary['root'])}</title><style>{CSS} main{{max-width:1100px}}</style></head><body><main>"
        f"<header class='cover'><div class='eyebrow'>Agentic Engineering Maturity Score · portfolio</div>"
        f"<h1>{e(summary['root'])}: {len(ok)} repositories</h1><div class='meta'><span>Scanned {e(now_label)}</span>"
        f"<span>T0 static + T1 git/CI</span></div></header>"
        f"<div class='tiles'><div class='tile'><div class='k'>Overall distribution</div><div class='v' style='font-size:18px'>{e(dist_txt or '-')}</div>"
        f"<div class='s'>weakest-link level per repo</div></div><div class='tile'><div class='k'>Most common weakest dims</div>"
        f"<div class='v' style='font-size:16px'>{e(weak_txt or '-')}</div><div class='s'>count of repos</div></div></div>"
        "<div class='callout'>Overall = weakest link across dims 1, 2, 3, 5, 8, 9. <strong>*</strong> = capped at L2 for lack of outcome "
        "evidence (presence, not maturity). AI share is a lower bound (attributed commits only). VDR = verification-debt ratio. "
        "PRs reviewed = merged PRs with a formal non-author review (— = not observed).</div>"
        f"<table><thead><tr><th>Repo</th><th class='num'>Overall</th><th class='num'>Median</th>{head}<th class='num'>VDR</th>"
        f"<th class='num'>AI share</th><th class='num'>Rework</th><th class='num' title='merged PRs with a formal review'>PRs reviewed</th>{pack_head}<th>Top move</th></tr></thead><tbody>{''.join(body)}</tbody></table>"
        + (f"<h2>Not scanned</h2><ul>{errors}</ul>" if errors else "")
        + "<footer>needlemark AEMS scanner. Per-repo reports carry the evidence behind every number.</footer></main></body></html>"
    )
