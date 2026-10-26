"""Shared inline stylesheet for AEMS HTML reports (no external assets, no JS)."""

CSS = """
:root{--ink:#14202b;--muted:#5b6b7a;--line:#dfe5eb;--bg:#ffffff;--panel:#f6f8fa;--accent:#0b5cad;
--accent-soft:#e7f0fa;--green:#1d7a46;--green-soft:#e5f4ec;--amber:#a15c00;--amber-soft:#fdf1df;
--red:#b3261e;--red-soft:#fbe9e7;--grey:#8a97a3}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16.5px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",
Roboto,"Helvetica Neue",Arial,sans-serif}
main{max-width:900px;margin:0 auto;padding:40px 20px 64px}
header.cover{border-bottom:3px solid var(--accent);padding-bottom:18px;margin-bottom:28px}
.eyebrow{text-transform:uppercase;letter-spacing:.12em;font-size:12px;color:var(--accent);font-weight:700}
h1{font-size:30px;line-height:1.2;margin:6px 0 8px}
h2{font-size:21px;margin:40px 0 12px;padding-left:12px;border-left:4px solid var(--accent)}
h3{font-size:17px;margin:22px 0 8px}
.meta{color:var(--muted);font-size:14px}
.meta span{margin-right:16px;white-space:nowrap}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.tile .k{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.tile .v{font-size:28px;font-weight:700;line-height:1.2;margin-top:4px}
.tile .s{font-size:13px;color:var(--muted)}
.tile.green{background:var(--green-soft);border-color:#b9e0c9}.tile.green .v{color:var(--green)}
.tile.amber{background:var(--amber-soft);border-color:#f2d3a6}.tile.amber .v{color:var(--amber)}
.tile.red{background:var(--red-soft);border-color:#f1c0bb}.tile.red .v{color:var(--red)}
table{width:100%;border-collapse:collapse;margin:8px 0 16px;font-size:14.5px}
th{text-align:left;font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);
border-bottom:2px solid var(--line);padding:8px 10px}
td{padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
tbody tr:nth-child(even){background:var(--panel)}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.bar{display:inline-flex;gap:3px;vertical-align:middle}
.bar i{display:inline-block;width:18px;height:10px;border-radius:2px;background:var(--line)}
.bar i.on{background:var(--accent)}.bar i.raw{background:repeating-linear-gradient(45deg,#9fbfe0,#9fbfe0 3px,#d6e5f5 3px,#d6e5f5 6px)}
.pill{display:inline-block;font-size:12px;font-weight:600;border-radius:999px;padding:1px 9px;white-space:nowrap}
.pill.ok{background:var(--green-soft);color:var(--green)}.pill.no{background:var(--red-soft);color:var(--red)}
.pill.cap{background:var(--amber-soft);color:var(--amber)}.pill.na{background:var(--panel);color:var(--grey);border:1px solid var(--line)}
.pill.weak{background:var(--red);color:#fff}
.move{border:1px solid var(--line);border-left:5px solid var(--accent);border-radius:8px;padding:14px 18px;margin:12px 0;
page-break-inside:avoid;break-inside:avoid}
.move .n{font-weight:800;color:var(--accent);margin-right:8px}
.move dl{display:grid;grid-template-columns:130px 1fr;gap:4px 12px;margin:10px 0 0;font-size:14px}
.move dt{color:var(--muted);font-weight:600}.move dd{margin:0}
.callout{background:var(--accent-soft);border:1px solid #c6dbf1;border-radius:8px;padding:12px 16px;font-size:14.5px;margin:14px 0}
.callout.warn{background:var(--amber-soft);border-color:#f2d3a6}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:13px}
.src{color:var(--muted);font-size:12.5px;word-break:break-word}
.dimcard{page-break-inside:avoid;break-inside:avoid}
footer{margin-top:48px;padding-top:14px;border-top:1px solid var(--line);color:var(--muted);font-size:13px}
@media (max-width:600px){main{padding:24px 16px}.move dl{grid-template-columns:1fr}h1{font-size:25px}}
@media print{body{font-size:12.5px;background:#fff;color:#000}main{max-width:none;padding:0}
.tile,.move,.callout{box-shadow:none}table,.move,.tile,.dimcard{page-break-inside:avoid;break-inside:avoid}
h2{page-break-after:avoid;break-after:avoid}a{color:#000;text-decoration:none}}
"""
