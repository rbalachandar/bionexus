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
    """Fold provenance records into notebook entries, grouped as one flow per
    hypothesis (swimlanes) preceded by campaign-level events."""
    counts = {"hypotheses": 0, "validated": 0, "invalidated": 0,
              "inconclusive": 0, "gates": 0, "runs": 0}

    shared: list[str] = []                 # campaign-level entries
    lanes: dict[str, dict] = {}            # candidate -> {"hid", "statement", "entries"}
    hid_to_cand: dict[str, str] = {}

    def _lane(hid: str | None, cand: str, stmt: str = "") -> dict:
        if cand not in lanes:
            lanes[cand] = {"hid": hid, "statement": stmt, "entries": []}
        return lanes[cand]

    for r in records:
        ev = r.event_type.value
        d = r.decision or {}
        art = (r.artifact.metadata if r.artifact else {}) or {}
        art_id = r.artifact.artifact_id if r.artifact else None
        cand = art.get("candidate")
        if art_id and cand:
            hid_to_cand[art_id] = cand

        if ev == "problem_defined":
            cons = ", ".join(c.get("name", "?") for c in d.get("constraints", [])) or "—"
            shared.append(_entry("problem", d.get("objective", ""),
                                 f"constraints: {cons} · success metric: "
                                 f"{d.get('success_metric', '—')}"))
        elif ev == "hypothesis_proposed":
            stmt = (d.get("statement") or art.get("statement", "")) or ""
            counts["hypotheses"] += 1
            lane = _lane(art_id, cand or stmt[:24] or "?", stmt)
            bits = []
            if d.get("rationale"):
                bits.append(f"rationale: {d['rationale']}")
            if d.get("predicted"):
                bits.append(f"prediction: {d['predicted']}")
            lane["entries"].append(_entry("hypothesis proposed", stmt,
                                          " · ".join(bits) or "—"))
        elif ev == "hypotheses_filtered":
            dec = d.get("decisions", [])
            sel = sum(1 for x in dec if x.get("selected"))
            shared.append(_entry(
                "portfolio filter",
                f"{sel} of {len(dec)} hypotheses selected for the lab",
                "; ".join(f"{hid_to_cand.get(x['hypothesis_id'], x['hypothesis_id'])}: "
                          f"{'selected' if x.get('selected') else 'passed over'} "
                          f"({x.get('reason', '')})" for x in dec)[:400]))
        elif ev == "hypothesis_tested" and d.get("run_id"):
            lane = _lane(art_id, hid_to_cand.get(art_id, cand or "?"))
            counts["runs"] += 1
            rid = d.get("run_id", "?")
            lane["entries"].append(_entry(
                "lab run submitted", f"run `{rid}`",
                (f"protocol {d.get('protocol_id', '?')}"[:40]
                 + (f" · {d.get('assay_type', '')}" if d.get("assay_type") else ""))))
            lane["entries"].append(_run_output_html(rid, cand))
        elif ev in ("hypothesis_validated", "hypothesis_invalidated"):
            counts[ev.split("_")[1]] += 1
            lane = _lane(art_id, hid_to_cand.get(art_id, cand or "?"), art.get("statement", ""))
            bits = [f"observed {d.get('observed', '—')} µM",
                    f"threshold {d.get('threshold', '—')}"]
            if d.get("evidence_run_id"):
                bits.append(f"evidence run `{d['evidence_run_id']}`")
            lane["entries"].append(_entry(
                ev.replace("hypothesis_", "HYPOTHESIS ").upper(),
                lane.get("statement") or d.get("metric", ""),
                " · ".join(bits), cls=ev.split("_")[1]))
        elif ev == "gate_decision":
            counts["gates"] += 1
            approved = d.get("approved", d.get("pass", d.get("match")))
            shared.append(_entry(
                f"review gate — {d.get('gate', d.get('question', ''))}",
                "APPROVED" if approved else "REJECTED",
                f"by {d.get('approved_by', 'operator')} · "
                f"{d.get('reason', '')}", cls="gate"))
        elif ev == "stage_transition" and d.get("stage"):
            shared.append(_entry("stage", d.get("stage", ""), d.get("detail", "")))

    counts["validated_or_not"] = counts["validated"] + counts["invalidated"]

    def _lane_html(cand: str, lane: dict) -> str:
        status = ""
        for e in lane["entries"]:
            if "VALIDATED" in e:
                status = "✅ validated"
            elif "INVALIDATED" in e:
                status = "❌ refuted"
        head = (f"<div class='lane-head'><b>{_html.escape(cand)}</b>"
                f"<span class='mono'>{_html.escape(status)}</span></div>")
        return ("<div class='lane'>" + head + "".join(lane["entries"]) + "</div>")

    body = "\n".join(shared)
    if lanes:
        body += "<h2 class='lane-title'>Hypothesis flows</h2>" + "".join(
            _lane_html(c, l) for c, l in lanes.items())
    if not body:
        body = "<p class='sub'>no narrative events recorded yet</p>"

    stats = "".join(f"<div class='stat'><b>{v}</b><span>{k}</span></div>"
                    for k, v in counts.items()
                    if k != "validated_or_not")
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Campaign diary — {_html.escape(branch)}</title><style>{_CSS}
.lane{{border:1px solid #d8d2c2;border-radius:8px;padding:10px 14px;margin:10px 0;background:#faf8f2}}
.lane-head{{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}}
.lane-title{{margin:18px 0 6px;font-size:15px}}
.runout .title{{color:#1f7a86}}
.runout svg{{max-width:100%;height:auto;margin:6px 0}}
.pts{{display:flex;gap:10px;flex-wrap:wrap}}
.pt{{font-family:var(--mono);font-size:11px;color:var(--dim)}}
</style></head>
<body><div class="wrap">
<h1>Campaign diary</h1>
<p class="sub">branch <span class="mono">{_html.escape(branch)}</span> ·
{len(records)} provenance records · hash-chained — verify with
<span class="mono">bn prove</span></p>
<div class="stats">{stats}</div>
{body}
</div></body></html>"""


def _run_output_html(run_id: str, candidate: str | None) -> str:
    """Scientist-facing lab output for one run: dose-response points, fitted
    IC50, QC. Purely additive — missing instrument files degrade to a note."""
    try:
        from pathlib import Path
        f = Path(".data/inbox") / f"{run_id}.csv"
        if not f.exists():
            return _entry("instrument output", "pending",
                          "the instrument has not dropped its export yet")
        from bionexus.labread import read_plate
        from bionexus.plots import dose_response_svg
        result = read_plate(str(f))
        comp = result.analysis["compounds"].get(candidate or "")
        if not comp:
            sample = next(iter(result.analysis["compounds"]), None)
            comp = result.analysis["compounds"].get(sample, {}) if sample else {}
            candidate = candidate or sample
        ic50 = comp.get("ic50_um")
        pts = [(r["conc_um"], r["value"]) for r in result.records
               if r.get("sample") == candidate and not r.get("control")]
        svg = ""
        if pts:
            svg = dose_response_svg([(c, v) for c, v in pts], ic50=ic50,
                                    title=f"{candidate or 'sample'} — run {run_id}",
                                    width=380, height=220)
        rows = "".join(
            f"<span class='pt'>{_html.escape(_fmt_conc(c))}: {v:.1f} RFU</span>"
            for c, v in pts)
        bits = [f"fit IC50 <b>{ic50:.3f} µM</b>" if ic50 else "fit failed"]
        if result.z_prime is not None:
            bits.append(f"Z&#8242; = {result.z_prime:.3f} "
                        f"({'accept' if result.z_prime >= 0.5 else 'marginal'})")
        bits.append(f"{len(result.records)} wells")
        table = f"<div class='pts'>{rows}</div>" if rows else ""
        return ("<div class='entry runout'>"
                f"<div class='k'>instrument output</div>"
                f"<div class='title'>{' · '.join(bits)}</div>"
                f"{svg}"
                f"{table}</div>")
    except Exception as exc:  # never let cosmetics kill the diary
        return _entry("instrument output", "unavailable", str(exc)[:120])


def _fmt_conc(c: float) -> str:
    return f"{c:g} µM"


def _entry(kind: str, title: str, body: str, cls: str = "") -> str:
    return (f"<div class='entry {cls}'><div class='k'>{_html.escape(kind)}</div>"
            f"<div class='title'>{_html.escape(title or '')}</div>"
            f"<div class='body'>{_html.escape(body or '')}</div></div>")


def write_diary(records: list[Any], branch: str, path: str | Path) -> Path:
    p = Path(path)
    p.write_text(build_diary_html(records, branch))
    return p
