"""Deterministic report text. Built only from the section envelopes (stored-record
statistics); it contains no model output and no inference. It is labelled
machine-generated in every artifact and is kept separate from analyst commentary."""
from __future__ import annotations

from app.reporting import definitions as defs

LABEL = "Generated automatically from stored records by fixed rules. It is not an analyst assessment."


def _fmt(v, unit: str) -> str:
    if v is None:
        return "not available"
    if unit == "proportion":
        return f"{v * 100:.1f}%"
    if isinstance(v, float):
        return f"{v:.2f} {unit}"
    return f"{v} {unit}"


def section_findings(env: dict) -> dict:
    lines, headline = [], []
    if env["status"] == "not_authorized":
        return {"status": "not_authorized", "headline": [], "text": ["This section was not included: you do not have permission to read its data."]}
    for mid, v in env["values"].items():
        meta = defs.CATALOG[mid]
        headline.append({"metric_id": mid, "label": meta["label"], "value": v["value"], "unit": v["unit"], "n": v["n"], "reason": v["reason"]})
        if v["value"] is None:
            lines.append(f"{meta['label']}: not available ({v['reason'] or 'no data'}).")
        else:
            n = f" (n={v['n']})" if v["n"] is not None and v["unit"] == "proportion" else ""
            lines.append(f"{meta['label']}: {_fmt(v['value'], v['unit'])}{n}.")
    if env["status"] == "empty":
        lines.append("No stored records matched this window and these filters. This does not show that nothing happened, only that nothing is recorded.")
    if env["status"] == "partial":
        lines.append("This section is partial; see its caveats for what was omitted or truncated.")
    fr = env.get("freshness") or {}
    if fr.get("stale"):
        lines.append(f"The most recent record is {fr.get('age_hours')} hours old, beyond the {fr.get('stale_after_hours')}-hour freshness threshold; the data may be stale.")
    return {"status": env["status"], "headline": headline, "text": lines}
