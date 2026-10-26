"""CLI.

  python -m aems scan <repo> [--out dir] [--export] [--offline] [--one-number]
  python -m aems portfolio <dir-of-repos> --out dir [--export] [--offline]
  python -m aems export <repo> --out dir [--keep-name] [--offline]
  python -m aems pack <repo> [--vendors vendors.json] [--out dir] [--offline]
                       [--keep-name] [--keep-vendor-names] [--allow-small-vendors]

`scan`/`portfolio` write the full local reports (JSON + HTML, may show file
paths, for the client's own use). `export` / `--export` writes the
numbers-only JSON that is safe to send out. `pack` adds the query pack (review
timing, escaped-defect trace, vendor lens) and writes the report plus the export.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .export import export_portfolio
from .pack import PackOptions
from .portfolio import render_portfolio, scan_portfolio, write_export, write_report
from .safe_io import UnsafeOutput, ensure_dir, write_text_atomic
from .scan import ScanError, scan_repo
from .vendors import VendorFileError, load_vendors

SALT_WARNING = ("aems: warning: AEMS_EXPORT_SALT is not set; hashed repo and vendor ids in the export can be "
                "guessed from a list of names. Set it to a private value that stays with you.")
SMALL_VENDOR_NOTICE = ("aems: --allow-small-vendors: small vendors (fewer than 5 people) are listed by label; "
                       "their figures may describe individuals.")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aems", description="Agentic Engineering Maturity Score — T0/T1 scanner")
    sub = p.add_subparsers(dest="cmd", required=True)
    specs = (("scan", "scan one git repo", Path("aems-out"), False),
             ("portfolio", "scan every git repo directly under a directory", None, True),
             ("export", "scan one repo and write only the numbers-only export JSON", Path("aems-out"), False),
             ("pack", "scan one repo with the query pack; writes report and export", Path("aems-out"), False))
    for name, helptext, default_out, out_required in specs:
        s = sub.add_parser(name, help=helptext)
        s.add_argument("path", type=Path)
        s.add_argument("--out", type=Path, default=default_out, required=out_required)
        s.add_argument("--offline", action="store_true", help="skip GitHub (gh) evidence")
        s.add_argument("--window-days", type=int, default=180)
        s.add_argument("--keep-name", action="store_true", help="export: keep repo names instead of hashing them")
        if name in ("scan", "portfolio"):
            s.add_argument("--export", action="store_true", help="also write the numbers-only export JSON")
        if name in ("pack", "portfolio"):
            _pack_args(s, name == "portfolio")
        if name == "scan":
            s.add_argument("--one-number", action="store_true",
                           help="free teaser: print only the overall level, median and VDR band; write nothing")
    return p


def _pack_args(s, optional: bool) -> None:
    if optional:
        s.add_argument("--pack", action="store_true", help="also run the query pack on every repo")
    s.add_argument("--vendors", type=Path, help="client-local vendors.json (never leaves your environment)")
    s.add_argument("--keep-vendor-names", action="store_true", help="export: keep vendor labels instead of hashing")
    s.add_argument("--allow-small-vendors", action="store_true",
                   help="list vendors with fewer than 5 people instead of pooling them (prints a notice)")


def _pack_options(args) -> PackOptions | None:
    """PackOptions for pack / portfolio --pack; raises VendorFileError on a bad vendors file."""
    if args.cmd != "pack" and not getattr(args, "pack", False):
        return None
    vendors = load_vendors(args.vendors) if args.vendors else None
    if args.allow_small_vendors:
        print(SMALL_VENDOR_NOTICE, file=sys.stderr)
    return PackOptions(vendors=vendors, allow_small_vendors=args.allow_small_vendors)


def _scan_one(args, pack: PackOptions | None = None):
    try:
        return scan_repo(args.path, offline=args.offline, window_days=args.window_days, pack=pack)
    except ScanError as exc:
        print(f"aems: {exc}", file=sys.stderr)
        return None


def one_number(report) -> str:
    """Overall (weakest link) + median + VDR band only: no repo name, path or ratio."""
    return f"AEMS L{report.overall} (median L{report.median:g}) · VDR {report.metrics['vdr']['status']}"


def _scan(args) -> int:
    report = _scan_one(args)
    if report is None:
        return 2
    if args.one_number:
        print(one_number(report))
        return 0
    _, hpath = write_report(report, args.out)
    print(f"{report.repo}: overall L{report.overall} (median L{report.median:g}) -> {hpath}")
    if args.export:
        print(f"export -> {write_export(report, args.out, args.keep_name)}")
    return 0


def _export(args) -> int:
    report = _scan_one(args)
    if report is None:
        return 2
    print(f"export -> {write_export(report, args.out, args.keep_name)}")
    return 0


def _pack(args) -> int:
    try:
        options = _pack_options(args)
    except VendorFileError as exc:
        print(f"aems: {exc}", file=sys.stderr)
        return 2
    report = _scan_one(args, options)
    if report is None:
        return 2
    _, hpath = write_report(report, args.out)
    print(f"{report.repo}: query pack -> {hpath}")
    print(f"export -> {write_export(report, args.out, args.keep_name, args.keep_vendor_names)}")
    return 0


def _portfolio(args) -> int:
    now = int(time.time())
    out = ensure_dir(args.out)
    try:
        options = _pack_options(args)
    except VendorFileError as exc:
        print(f"aems: {exc}", file=sys.stderr)
        return 2
    summary = scan_portfolio(args.path, now=now, offline=args.offline, out_dir=out, window_days=args.window_days,
                             export=args.export, keep_name=args.keep_name, pack=options,
                             keep_vendor_names=args.keep_vendor_names)
    label = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ensure_dir(out)
    safe = json.loads(json.dumps(summary, default=str).replace("Infinity", '"inf"'))
    write_text_atomic(out / "portfolio.aems.json", json.dumps(safe, indent=2))
    write_text_atomic(out / "portfolio.aems.html", render_portfolio(summary, label))
    if args.export:
        write_text_atomic(out / "portfolio.export.json", json.dumps(export_portfolio(summary, args.keep_name), indent=2))
    for row in summary["rows"]:
        status = row["error"] or f"L{row['overall']} (median L{row['median']:g})"
        print(f"{row['repo']:<24} {status}")
    print(f"-> {out / 'portfolio.aems.html'}")
    return 0


def _writes_export(args) -> bool:
    return args.cmd in ("export", "pack") or bool(getattr(args, "export", False))


def main(argv=None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if getattr(args, "one_number", False) and args.export:
        parser.error("--one-number writes nothing; it cannot be combined with --export")
    if _writes_export(args) and not os.environ.get("AEMS_EXPORT_SALT"):
        print(SALT_WARNING, file=sys.stderr)
    try:
        return {"scan": _scan, "export": _export, "portfolio": _portfolio, "pack": _pack}[args.cmd](args)
    except UnsafeOutput as exc:
        print(f"aems: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
