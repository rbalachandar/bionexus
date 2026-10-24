"""Analysis report + export (generic shell, profile renderers).

The report must let a third party answer: what was the input, what
assumptions were confirmed, what decision rule produced each call, and
whether a human changed anything — without reading JSON. The generic shell
carries identity/digest/origin/config/dispositions; the plate profile
renderer adds QC, fits, and calls. Regeneration is deterministic from the
stored revision (source bytes + config + pinned versions).
"""
from __future__ import annotations

import html
from typing import Any


def _esc(v: Any) -> str:
    return html.escape(str(v), quote=True)


def generic_header(doc: dict, chain_status: str) -> list[str]:
    src = (doc.get("artifacts") or {}).get("source") or {}
    layout = (doc.get("artifacts") or {}).get("layout") or {}
    dispositions = doc.get("dispositions") or []
    cfg = doc.get("config") or {}
    origin = (cfg.get("evidence_origin")
              or (doc.get("result") or {}).get("evidence_origin")
              or "unknown")
    lines = [
        "<h1>Experiment analysis report</h1>",
        f"<p>Analysis <strong>{_esc(doc.get('id'))}</strong> · "
        f"profile <strong>{_esc(doc.get('profile'))}</strong> · "
        f"revision {doc.get('revision')} · state {_esc(doc.get('state'))}</p>",
        "<h2>Input</h2><ul>",
        f"<li>source: {_esc(src.get('original_name') or '(unnamed)')} "
        f"(sha256 <code>{_esc(src.get('sha256'))}</code>"
        + (f", layout {_esc(layout.get('original_name'))} "
           f"sha256 <code>{_esc(layout.get('sha256'))}</code>"
           if layout else "") + ")</li>",
        f"<li>evidence origin: <strong>{_esc(origin)}</strong></li>",
        f"<li>engine version: {_esc((doc.get('result') or {}).get('engine_version', 'unknown'))}</li>",
        "</ul>",
        "<h2>Confirmed analysis configuration</h2><ul>",
        "".join(f"<li><code>{_esc(k)}</code>: {_esc(v)}</li>"
                for k, v in sorted(cfg.items())),
        "</ul>",
        f"<p>Provenance chain: {_esc(chain_status)}</p>",
    ]
    if dispositions:
        lines.append("<h2>Scientist review</h2><ul>")
        for d in dispositions:
            lines.append(f"<li><strong>{_esc(d.get('action'))}</strong> by "
                         f"{_esc(d.get('actor'))}"
                         + (f" — {_esc(d.get('reason'))}" if d.get("reason")
                            else "") + "</li>")
        lines.append("</ul>")
    else:
        lines.append("<p><em>No human disposition recorded — the calls "
                     "are machine-derived only.</em></p>")
    return lines


def plate_section(result: dict) -> list[str]:
    compounds: dict[str, Any] = result.get("compounds") or {}
    calls = {c["entity"]: c for c in (result.get("calls") or [])}
    inst = result.get("instrument") or {}
    lines = [
        "<h2>Plate analysis</h2>",
        f"<p>{result.get('n_wells')} wells · format {_esc(result.get('format'))}"
        f" · unit {_esc(result.get('response_unit'))} · "
        f"Z' {_esc(result.get('z_prime'))}"
        + (" (heuristic)" if result.get("z_prime_kind") != "real" else " (real)")
        + "</p>",
    ]
    if inst:
        lines.append("<p class=muted>instrument: "
                     + _esc(" · ".join(f"{k}: {v}" for k, v in
                                       list(inst.items())[:5])) + "</p>")
    if result.get("regime_refused"):
        lines.append(f"<p><strong>REGIME REFUSED — no absolute claims:</strong> "
                     f"{_esc((result.get('regime') or {}).get('note'))}</p>")
    if result.get("threshold_registered"):
        lines.append(f"<p>Registered gate: metric {_esc(result.get('metric'))} "
                     f"({_esc(result.get('direction'))}); a 95% CI straddling "
                     f"the gate abstains.</p>")
    else:
        lines.append("<p><em>No threshold registered — estimates only, "
                     "no hit calls.</em></p>")
    lines.append("<table border=1 cellpadding=4 style='border-collapse:collapse;"
                 "font-size:13px'><tr><th>sample</th><th>IC50 (µM)</th>"
                 "<th>95% CI</th><th>fit</th><th>call</th><th>reason</th></tr>")
    for s, c in compounds.items():
        call = calls.get(s)
        lines.append(
            f"<tr><td>{_esc(s)}</td>"
            f"<td>{_esc(c.get('ic50_um') if c.get('ic50_um') is not None
                        else '> range')}</td>"
            f"<td>{_esc(c['ic50_ci']) if c.get('ic50_ci') else '—'}</td>"
            f"<td>{_esc(c.get('fit_method'))}"
            + (" · right-censored" if c.get("right_censored") else "")
            + (" · left-censored" if c.get("left_censored") else "")
            + "</td>"
            f"<td>{_esc(call['call']) if call else '—'}</td>"
            f"<td>{_esc(call['reason']) if call else ''}</td></tr>")
    lines.append("</table>")
    return lines


def render_report(doc: dict, chain_status: str) -> str:
    body = generic_header(doc, chain_status)
    result = doc.get("result")
    if result is None:
        body.append("<p><em>No analysis result stored for this revision "
                    "yet.</em></p>")
    elif doc.get("profile") == "plate_assay":
        body.extend(plate_section(result))
    else:  # unknown future profile: dump the generic summary honestly
        body.append(f"<p>Profile {doc.get('profile')}: state "
                    f"{_esc(doc.get('state'))}.</p>")
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            "<title>Analysis report</title>"
            "<style>body{font-family:system-ui;max-width:900px;margin:24px auto;"
            "padding:0 16px;color:#111}table{font-size:13px}code{background:#f4f4f4;"
            "padding:0 3px}.muted{color:#666}</style></head><body>"
            + "\n".join(body) + "</body></html>")


def export_csv(doc: dict, records: list[dict], result: dict) -> str:
    """Plate-profile CSV: raw + normalized values kept in separate columns,
    well mapping, units, fits, intervals, calls, evidence origin."""
    import csv
    import io

    calls = {c["entity"]: c for c in (result.get("calls") or [])}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["well", "sample", "conc_um", "value", "value_raw", "control",
                "batch", "channel", "response_unit", "evidence_origin",
                "engine_version",
                "ic50_um", "ic50_ci_low", "ic50_ci_high", "fit_method",
                "call", "call_reason"])
    for r in records:
        comp = (result.get("compounds") or {}).get(r["sample"], {})
        ci = comp.get("ic50_ci") or (None, None)
        call = calls.get(r["sample"], {})
        w.writerow([r.get("well", ""), r["sample"], r.get("conc_um", ""),
                    r["value"], r.get("value_raw", ""), r.get("control", False),
                    r.get("batch", ""), r.get("channel", ""),
                    result.get("response_unit", ""),
                    result.get("evidence_origin", "unknown"),
                    result.get("engine_version", "unknown"),
                    comp.get("ic50_um", ""), ci[0], ci[1],
                    comp.get("fit_method", ""),
                    call.get("call", ""), call.get("reason", "")])
    return buf.getvalue()
