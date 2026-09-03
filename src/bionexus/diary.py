"""Campaign diary — provenance rendered as a lab notebook, not a log.

`bn diary <branch> --db campaign.db --html diary.html` turns the hash-chained
records into a dated narrative a scientist actually reads:

    Round 1 — hypothesis H4 (C-101 binds IC50<=20): proposed from covalent
    warhead precedent; tested by run sim-…; VALIDATED (measured 8.9 uM).
    Gate approve_wetlab_protocol: APPROVED by scripted-scientist.
    ...

Same light-blueprint style as the report.
"""
from __future__ import annotations

import html as _html
import json
from pathlib import Path
from typing import Any

_CSS = """
:root{--bg:#f3f1ea;--line:#c9c2b0;--paper:#faf8f2;--ink:#2a2823;--dim:#6b6558;
--green:#2f6b38;--red:#8a4034;--amber:#8a6a2c;
--mono:'IBM Plex Mono',ui-monospace,Consolas,monospace;}
body{margin:0;background:var(--bg);color:var(--ink);
font-family:ui-sans-serif,system-ui,sans-serif;padding:40px 20px}
.wrap{max-width:820px;margin:0 auto}
h1{font-size:22px;margin:0 0 2px} .sub{color:var(--dim);font-size:13px;margin:0 0 26px}
.entry{background:var(--paper);border:1px solid var(--line);padding:14px 18px;
margin:10px 0;border-left:3px solid var(--line)}
.entry.validated{border-left-color:var(--green)}
.entry.invalidated{border-left-color:var(--red)}
.entry.inconclusive{border-left-color:var(--amber)}
.entry.gate{border-left-color:#1f7a86}
.k{font-family:var(--mono);font-size:10.5px;letter-spacing:.08em;
text-transform:uppercase;color:var(--dim)}
.title{font-weight:600;font-size:14.5px;margin:2px 0 4px}
.body{font-size:13.5px;color:#4a463d;line-height:1.55}
.mono{font-family:var(--mono);font-size:12px}
.stats{display:flex;gap:14px;flex-wrap:wrap;margin:14px 0 24px}
.stat{background:var(--paper);border:1px solid var(--line);padding:10px 16px}
.stat b{display:block;font-size:18px} .stat span{font-family:var(--mono);
font-size:10.5px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em}
"""


def build_diary_html(records: list[Any], branch: str) -> str:
    """Fold provenance records into notebook entries."""
    entries: list[str] = []
    counts = {"hypotheses": 0, "validated": 0, "invalidated": 0,
              "inconclusive": 0, "gates": 0, "runs": 0}

    for r in records:
        ev = r.event_type.value
        d = r.decision or {}
        if ev == "problem_defined":
            cons = ", ".join(c.get("name", "?") for c in d.get("constraints", [])) or "—"
            entries.append(_entry("problem", d.get("objective", ""),
                                  f"constraints: {cons} · success metric: "
                                  f"{d.get('success_metric', '—')}"))
        elif ev == "hypothesis_proposed":
            stmt = (d.get("statement") or (r.artifact.metadata if r.artifact else {})
                    .get("statement", "")) or ""
            counts["hypotheses"] += 1
            entries.append(_entry(
                "hypothesis proposed", stmt,
                f"rationale: {d.get('rationale', '—')} · prediction: "
                f"{d.get('predicted', '—')}"))
        elif ev == "hypotheses_filtered":
            dec = d.get("decisions", [])
            sel = [x for x in dec if x.get("selected")]
            rej = [x for x in dec if not x.get("selected")]
            entries.append(_entry(
                "portfolio filter",
                f"{len(sel)} selected, {len(rej)} passed over",
                "; ".join(f"{x['hypothesis_id']}: {x['reason']}" for x in dec)[:300]))
        elif ev == "hypothesis_tested":
            entries.append(_entry("experiment run", "assay in progress",
                                  f"run {d.get('run_id', '?')}"))
            counts["runs"] += 1
        elif ev in ("hypothesis_validated", "hypothesis_invalidated"):
            counts[ev.split("_")[1]] += 1
            art = (r.artifact.metadata if r.artifact else {}) or {}
            entries.append(_entry(
                ev.replace("hypothesis_", "").upper(),
                art.get("statement", d.get("metric", "")),
                f"predicted {d.get('predicted', '—')} · observed {d.get('observed', '—')} "
                f"· threshold {d.get('threshold', '—')} · evidence run "
                f"{d.get('evidence_run_id', '—')}", cls=ev.split("_")[1]))
        elif ev == "gate_decision":
            counts["gates"] += 1
            approved = d.get("approved", d.get("pass", d.get("match")))
            entries.append(_entry(
                f"review gate — {d.get('gate', d.get('question', ''))}",
                "APPROVED" if approved else "REJECTED",
                f"by {d.get('approved_by', 'operator')} · "
                f"{d.get('reason', '')}", cls="gate"))
        elif ev == "stage_transition" and d.get("stage"):
            entries.append(_entry("stage", d.get("stage", ""), d.get("detail", "")))

    stats = "".join(f"<div class='stat'><b>{v}</b><span>{k}</span></div>"
                    for k, v in counts.items())
    body = "\n".join(entries) or "<p class='sub'>no narrative events recorded yet</p>"
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Campaign diary — {_html.escape(branch)}</title><style>{_CSS}</style></head>
<body><div class="wrap">
<h1>Campaign diary</h1>
<p class="sub">branch <span class="mono">{_html.escape(branch)}</span> ·
{len(records)} provenance records · hash-chained — verify with
<span class="mono">bn prove</span></p>
<div class="stats">{stats}</div>
{body}
</div></body></html>"""


def _entry(kind: str, title: str, body: str, cls: str = "") -> str:
    return (f"<div class='entry {cls}'><div class='k'>{_html.escape(kind)}</div>"
            f"<div class='title'>{_html.escape(title or '')}</div>"
            f"<div class='body'>{_html.escape(body or '')}</div></div>")


def write_diary(records: list[Any], branch: str, path: str | Path) -> Path:
    p = Path(path)
    p.write_text(build_diary_html(records, branch))
    return p
