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
import time
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

    labrun_info: dict[str, dict] = {}      # run_id -> lab_run decision
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
            if d.get("mechanism"):
                bits.append(f"mechanism: {d['mechanism']}")
            if d.get("rationale"):
                bits.append(f"rationale: {d['rationale']}")
            if d.get("citation"):
                _cs = d.get("citation_status", "unverified")
                _tag = {"verified": "verified",
                        "invalid": "UNVERIFIABLE — penalized",
                        "check-failed": "? check failed (offline)"}.get(_cs, "")
                bits.append(f"citation: {d['citation']}"
                            + (f" ({_tag})" if _tag else ""))
            if d.get("predicted"):
                bits.append(f"prediction: {d['predicted']}")
            if d.get("refutation_condition"):
                bits.append(f"refuted if: {d['refutation_condition']}")
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
            info = labrun_info.get(rid, {})
            lane["entries"].append(_entry(
                *_run_submission_entry(rid, cand, info,
                                       ts=getattr(getattr(r, "envelope", None),
                                                  "created_at", None))))
            lane["entries"].append(_run_output_html(
                rid, cand, assay=info.get("assay"),
                instrument=info.get("instrument")))
        elif ev == "lab_run" and d.get("run_id"):
            labrun_info[d["run_id"]] = d
        elif (ev in ("hypothesis_validated", "hypothesis_invalidated",
                     "hypothesis_inconclusive")
              or (ev == "hypothesis_tested" and d.get("verdict"))):
            # every verdict — including refuted confirmations and honest
            # abstentions — renders here; nothing decides in silence
            _v = str(d.get("verdict") or ev.split("_")[1])
            _bucket = {"validated": "validated", "confirmed": "validated",
                       "invalidated": "invalidated", "refuted": "invalidated",
                       "inconclusive": "inconclusive"}.get(_v)
            if _bucket:
                counts[_bucket] += 1
            lane = _lane(art_id, hid_to_cand.get(art_id, cand or "?"), art.get("statement", ""))
            bits = [f"observed {d.get('observed', '—')} µM",
                    f"threshold {d.get('threshold', '—')}"]
            if d.get("observed_ci"):
                lo, hi = d["observed_ci"]
                bits.append(f"95% CI {lo}–{hi}")
            if _v == "inconclusive":
                bits.append("CI straddles threshold — honest abstention")
            if d.get("evidence_run_id"):
                bits.append(f"evidence run `{d['evidence_run_id']}`")
            _conf = d.get("confirmation") or {}
            head = {"confirmed": "HYPOTHESIS CONFIRMED (ORTHOGONAL)",
                    "refuted": "HYPOTHESIS REFUTED (ORTHOGONAL)",
                    "inconclusive": "HYPOTHESIS INCONCLUSIVE",
                    "validated": "HYPOTHESIS VALIDATED",
                    "invalidated": "HYPOTHESIS INVALIDATED"}.get(
                        _v, ev.replace("hypothesis_", "HYPOTHESIS ").upper())
            if _conf:
                bits.append(f"agreement rule: {_conf.get('rule', '—')}")
            lane["entries"].append(_entry(
                head,
                lane.get("statement") or d.get("metric", ""),
                " · ".join(bits), cls=_bucket or "tested"))
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
            if "CONFIRMED" in e:
                status = "confirmed"
            elif "REFUTED" in e or "INVALIDATED" in e:
                status = "refuted"
            elif "INCONCLUSIVE" in e:
                status = "inconclusive"
            elif "VALIDATED" in e:
                status = "validated (unconfirmed)"
        head = (f"<div class='lane-head'><b>{_html.escape(cand)}</b>"
                f"<span class='mono'>{_html.escape(status)}</span></div>")
        return ("<div class='lane'>" + head + "".join(lane["entries"]) + "</div>")

    body = "\n".join(shared)
    if lanes:
        body += "<h2 class='lane-title'>Hypothesis flows</h2>" + "".join(
            _lane_html(c, l) for c, l in lanes.items())
    from bionexus.series import series_summary
    multi = [s for s in series_summary(records)
             if s["kind"] != "ungrouped" and s["n_members"] > 1]
    if multi:
        body += "<h2 class='lane-title'>Series view</h2>"
        for s in multi:
            rows = "".join(
                f"<div class='pt'>{_html.escape(str(m['candidate']))}: "
                f"{_html.escape(str(m['verdict']))}"
                + (f" IC50 {m['observed']} uM"
                   if isinstance(m.get('observed'), (int, float)) else "")
                + "</div>" for m in s["members"][:8])
            pairs = "; ".join(
                f"{p['a']} vs {p['b']}: {p['call']} ({p['fold_a_over_b']}x)"
                for p in s["matched_pairs"][:6])
            body += (
                "<div class='lane'><div class='lane-head'><b>"
                f"{_html.escape(str(s['key'])[:40])}</b>"
                f"<span class='mono'>{_html.escape(str(s['kind']))}</span>"
                "</div>"
                f"<p class='sub'>{_html.escape(s['label'])} · grouping: "
                f"{_html.escape(s['backend'])}</p>"
                f"<div class='pts'>{rows}</div>"
                + (f"<p class='sub'>matched pairs — ΔIC50 with CI: "
                   f"{_html.escape(pairs)}</p>" if pairs else "")
                + "</div>")
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


def _run_submission_entry(run_id: str, candidate: str | None,
                          info: dict, ts: float | None) -> tuple[str, str, str]:
    """Scientist-readable description of what was sent to the lab, and why."""
    assay = info.get("assay", "assay")
    inst = info.get("instrument", "lab instrument")
    concs = info.get("concentrations") or []
    conc_txt = (", ".join(str(c) for c in concs[:-1]) + f" and {concs[-1]}"
                if len(concs) > 1 else (str(concs[0]) if concs else ""))
    title = str(info.get("title", ""))
    purpose = ("orthogonally confirm the initial hit"
               if "confirmation" in title.lower()
               else "test the potency hypothesis")
    bits = []
    if candidate:
        bits.append(f"{candidate} at {conc_txt} µM" if concs
                    else f"{candidate}")
    if info.get("n_controls"):
        bits.append(f"{info['n_controls']} buffer control"
                    if info["n_controls"] == 1 else f"{info['n_controls']} buffer controls")
    if info.get("replicates"):
        bits.append(f"{info['replicates']} replicates")
    bits.append(f"on {inst}")
    when = time.strftime("%H:%M", time.localtime(ts)) if ts else ""
    head = f"{assay.capitalize()} run — to {purpose}"
    body = " · ".join(bits) + (f" · submitted {when}" if when else "")
    return ("lab run submitted", head, body)


def _run_output_html(run_id: str, candidate: str | None,
                     assay: str | None = None,
                     instrument: str | None = None) -> str:
    """Scientist-facing lab output for one run. Device-aware: dispatches to
    the matching output renderer (dose-response, image, robot log, table)."""
    from pathlib import Path
    from bionexus.output_blocks import dispatch_output
    f = Path(".data/inbox") / f"{run_id}.csv"
    ctx = {"assay": assay, "instrument": instrument,
           "run_id": run_id, "candidate": candidate}
    return dispatch_output(f, ctx)


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
