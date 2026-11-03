"""Report artifact renderers: JSON, CSV (tidy long format, formula-injection safe), HTML
(self-contained, every dynamic value escaped, no scripts). PDF is intentionally not supported."""
from __future__ import annotations

import csv
import io
import json
from html import escape
from typing import Any


_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")
CONTENT_TYPES = {"json": "application/json", "csv": "text/csv; charset=utf-8", "html": "text/html; charset=utf-8"}
EXTENSIONS = {"json": "json", "csv": "csv", "html": "html"}


def csv_cell(v: Any):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)) or v is None:
        return "" if v is None else v
    s = str(v)
    if s and s[0] in _FORMULA_PREFIXES:
        return "'" + s
    return s


def to_json(doc: dict) -> bytes:
    return json.dumps(doc, indent=2, sort_keys=False, default=str, ensure_ascii=False, allow_nan=False).encode("utf-8")


def to_csv(doc: dict) -> bytes:
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["section", "kind", "id", "row", "column", "value", "unit", "note"])
    rep = doc["report"]
    for k in ("id", "title", "template", "generated_at", "definition_version"):
        w.writerow(["report", "meta", k, "", "", csv_cell(rep.get(k)), "", ""])
    win = rep["window"]
    for k in ("start", "end", "bucket", "time_basis", "timezone", "interval"):
        w.writerow(["report", "window", k, "", "", csv_cell(win.get(k)), "", ""])
    for k, v in rep["filters"].items():
        w.writerow(["report", "filter", k, "", "", csv_cell(v), "", ""])
    w.writerow(["report", "label", "automatic_findings", "", "", "", "", csv_cell(doc["automatic_findings_label"])])
    for sid, env in doc["sections"].items():
        w.writerow([sid, "status", "status", "", "", csv_cell(env["status"]), "", ""])
        for mid, v in env["values"].items():
            w.writerow([sid, "value", mid, "", "value", csv_cell(v["value"]), v["unit"], csv_cell(v["reason"] or "")])
            if v["n"] is not None:
                w.writerow([sid, "value", mid, "", "n", v["n"], "records", ""])
        for tid, t in env["tables"].items():
            for i, row in enumerate(t["rows"]):
                for col, val in zip(t["columns"], row):
                    w.writerow([sid, "table", tid, i, csv_cell(col), csv_cell(val), t["unit"], ""])
        for c in env["caveats"]:
            w.writerow([sid, "caveat", "", "", "", "", "", csv_cell(c)])
    if doc["analyst_commentary"]["text"]:
        w.writerow(["report", "analyst_commentary", "text", "", "", csv_cell(doc["analyst_commentary"]["text"]), "", "entered by a person; not verified by AEGIS"])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def _e(v: Any) -> str:
    return escape("" if v is None else str(v), quote=True)


def to_html(doc: dict) -> bytes:
    rep = doc["report"]
    p: list[str] = []
    a = p.append
    a("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">")
    a(f"<title>{_e(rep['title'])}</title><style>")
    a("body{font:14px/1.5 system-ui,sans-serif;margin:2rem auto;max-width:960px;padding:0 1rem;color:#111}h1{font-size:1.6rem}h2{margin-top:2rem;border-bottom:1px solid #ccc}"
      "table{border-collapse:collapse;width:100%;margin:.5rem 0 1rem}th,td{border:1px solid #bbb;padding:.25rem .5rem;text-align:left;font-size:13px}th{background:#f1f1f1}"
      ".note{background:#fff8e1;border:1px solid #e6c200;padding:.5rem .75rem;margin:.5rem 0}.cmt{white-space:pre-wrap;background:#f6f6f6;padding:.5rem .75rem}caption{text-align:left;font-weight:600;padding:.25rem 0}"
      "@media print{body{margin:0}}")
    a("</style></head><body>")
    a(f"<h1>{_e(rep['title'])}</h1>")
    a(f"<p>Template: {_e(rep['template_title'])} · Generated {_e(rep['generated_at'])} · Definitions v{_e(rep['definition_version'])} · Report ID {_e(rep['id'])}</p>")
    w = rep["window"]
    a(f"<p><strong>Window (UTC, {_e(w['interval'])}):</strong> {_e(w['start'])} to {_e(w['end'])} · bucket {_e(w['bucket'])} · time basis: {_e(w['time_basis'])} time</p>")
    a(f"<p><strong>Filters:</strong> {_e(json.dumps(rep['filters'], sort_keys=True))}</p>")
    a(f"<div class=\"note\">{_e(doc['automatic_findings_label'])}</div>")
    a("<h2>Automatic findings</h2>")
    for sid, f in doc["automatic_findings"].items():
        a(f"<h3>{_e(sid.replace('_', ' ').title())} <small>({_e(f['status'])})</small></h3><ul>")
        for line in f["text"]:
            a(f"<li>{_e(line)}</li>")
        a("</ul>")
    a("<h2>Analyst commentary</h2>")
    c = doc["analyst_commentary"]
    a(f"<div class=\"cmt\">{_e(c['text'])}</div><p><small>{_e(c['note'])}</small></p>" if c["text"] else "<p>No analyst commentary was added.</p>")
    a("<h2>Detail</h2>")
    for sid, env in doc["sections"].items():
        a(f"<h3>{_e(sid.replace('_', ' ').title())}</h3>")
        for tid, t in env["tables"].items():
            a(f"<table><caption>{_e(t['title'])} — unit: {_e(t['unit'])}</caption><thead><tr>" + "".join(f"<th>{_e(col)}</th>" for col in t["columns"]) + "</tr></thead><tbody>")
            for row in t["rows"]:
                a("<tr>" + "".join(f"<td>{_e(v)}</td>" for v in row) + "</tr>")
            if not t["rows"]:
                a(f"<tr><td colspan=\"{len(t['columns'])}\">No rows.</td></tr>")
            a("</tbody></table>")
        if env["caveats"]:
            a("<ul>" + "".join(f"<li><em>{_e(x)}</em></li>" for x in env["caveats"]) + "</ul>")
    a("<h2>Metric definitions</h2><table><thead><tr><th>Metric</th><th>Definition</th><th>Unit</th><th>Kind</th></tr></thead><tbody>")
    for mid, m in doc["metric_definitions"].items():
        a(f"<tr><td>{_e(m['label'])}<br><small>{_e(mid)}</small></td><td>{_e(m['definition'])}</td><td>{_e(m['unit'])}</td><td>{_e(m['kind'])}</td></tr>")
    a("</tbody></table><h2>Limitations</h2><ul>" + "".join(f"<li>{_e(x)}</li>" for x in doc["limitations"]) + "</ul></body></html>")
    return "".join(p).encode("utf-8")


RENDERERS = {"json": to_json, "csv": to_csv, "html": to_html}
