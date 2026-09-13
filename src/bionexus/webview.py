"""Shared rendering for the experiment detail page."""
from __future__ import annotations

import re
import time
from pathlib import Path

import streamlit as st

def render_experiment_pipeline(logf: Path, problem_id: str | None,
                                running: bool, store, eid: str) -> None:
    """Live view: when the experiment is running the whole block refreshes
    every 3s (provenance, cards, log), so stages move without user action."""
    if running:
        @st.fragment(run_every=3)
        def _live():
            _pipeline_body(logf, problem_id, running, store, eid)
        _live()
    else:
        _pipeline_body(logf, problem_id, running, store, eid)


def _pipeline_body(logf: Path, problem_id: str | None,
                   running: bool, store, eid: str) -> None:
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    branch = f"problem/{problem_id}" if problem_id else None
    recs = []
    if branch and Path("bionexus.db").exists():
        try:
            recs = SqliteProvenanceStore("bionexus.db").branch_records(branch)
        except Exception:
            recs = []

    proposed: dict[str, dict] = {}
    filtered: dict[str, dict] = {}
    run_map: dict[str, list[str]] = {}   # hypothesis_id -> run ids (provenance)
    tested: dict[str, dict] = {}
    refused: dict[str, str] = {}
    gates = 0
    run_ts: dict[str, float] = {}
    run_instr: dict[str, str] = {}
    for r in recs:
        d = r.decision or {}
        et = r.event_type.value
        art_id = r.artifact.artifact_id if r.artifact else None
        art_meta = r.artifact.metadata if r.artifact else {}
        ts = getattr(getattr(r, "envelope", None), "created_at", None)
        if et == "lab_run" and d.get("run_id"):
            run_ts[d["run_id"]] = ts or 0
        if et == "hypothesis_proposed":
            hid = d.get("hypothesis_id") or art_id or d.get("candidate", "?")
            proposed[hid] = {**d, "candidate": d.get("candidate") or art_meta.get("candidate"),
                             "predicted": d.get("predicted") or art_meta.get("predicted"),
                             "ts": ts}
        elif et == "hypotheses_filtered":
            for dec in d.get("decisions", []):
                if dec.get("hypothesis_id"):
                    filtered[dec["hypothesis_id"]] = dec
        elif et == "lab_run" and d.get("run_id"):
            run_ts[d["run_id"]] = ts or 0
            run_instr[d["run_id"]] = d.get("instrument", "")
        elif et == "hypothesis_tested" and d.get("run_id"):
            hid = d.get("hypothesis_id") or art_id
            if hid:
                run_map.setdefault(hid, []).append(d["run_id"])
        elif et in ("hypothesis_validated", "hypothesis_invalidated"):
            hid = d.get("hypothesis_id") or d.get("id") or art_id
            if hid:
                tested[hid] = {"verdict": d.get("verdict", et),
                               "observed": d.get("observed") or d.get("ic50_um"),
                               "ci": d.get("observed_ci"),
                               "derivation": d.get("derivation"),
                               "evidence": d.get("evidence_run_id")}
        elif et == "gate_decision":
            if d.get("kind") in ("safety_refusal", "operator_declined",
                                  "advisory_escalation"):
                for sm in d.get("samples", []):
                    refused[sm] = d.get("reason", "refused")
            else:
                gates += 1

    if proposed:
        st.markdown("**Hypothesis pipeline**")
        for hid, hp in proposed.items():
            sel = filtered.get(hid)
            verd = tested.get(hid, {})
            v = (verd.get("verdict") or "").lower()
            ci = verd.get("ci")
            ci_txt = (f" (95% CI {ci[0]}–{ci[1]})" if ci else "")
            _margin = ""
            _thr = (hp.get("criteria") or {}).get("threshold")
            if ci and _thr and None not in ci and ci[1] > ci[0]:
                width = ci[1] - ci[0]
                edge = min(abs(ci[0] - _thr), abs(ci[1] - _thr))
                _margin = (" · ⚠ borderline: CI spans the gate"
                           if ci[0] <= _thr <= ci[1] else
                           (" · narrow margin" if edge < width else " · clear margin"))
            if v == "confirmed":
                icon, stage = "✅", ("confirmed by orthogonal assay"
                                     + (f" — fitted {verd.get('observed')} µM{ci_txt}"
                                        if verd.get("observed") is not None else "")
                                     + _margin)
            elif v == "validated":
                icon, stage = "✅", ("validated (preliminary)"
                                     + (f" — fitted {verd.get('observed')} µM{ci_txt}"
                                        if verd.get("observed") is not None else "")
                                     + _margin)
            elif v == "inconclusive":
                icon, stage = "❔", ("inconclusive — CI straddles the threshold"
                                     + (f" ({verd.get('observed')} µM{ci_txt})"
                                        if verd.get("observed") is not None else ""))
            elif v in ("refuted", "invalidated"):
                icon, stage = "❌", ("refuted"
                                     + (f" ({verd.get('observed')} µM{ci_txt})"
                                        if verd.get("observed") is not None else "")
                                     + _margin)
            elif refused.get(str(hp.get("candidate"))):
                icon, stage = "🚫", ("refused by gate — "
                                      + refused[str(hp.get("candidate"))][:70])
            elif run_map.get(hid):
                icon, stage = "🔬", "in lab"
            elif sel and sel.get("selected"):
                icon, stage = "⏳", "selected — awaiting submission"
            elif sel:
                icon, stage = "✂️", "not selected"
            else:
                icon, stage = "💡", "proposed"
            with st.container(border=True):
                c1, c2 = st.columns([4, 2])
                c1.markdown(f"{icon} **{hp.get('candidate', hid)}** — "
                            f"{hp.get('statement', '')}")
                c2.caption(stage)
                crit = hp.get("criteria") or {}
                _cit = ""
                if hp.get("citation"):
                    _st = hp.get("citation_status", "unverified")
                    _icon = {"verified": "📚✓", "invalid": "📚⚠️ FABRICATED",
                             "check-failed": "📚?",
                             "unverified": "📚"}.get(_st, "📚")
                    _cit = f" · {_icon} {hp['citation']}" + (
                        f" ({hp['citation_detail']})"
                        if hp.get("citation_detail") else "")
                if hp.get("mechanism"):
                    st.caption(f"⚙️ mechanism: {hp['mechanism']}{_cit}")
                elif _cit:
                    st.caption(_cit[3:])
                if hp.get("refutation_condition"):
                    st.caption(f"☠️ refuted if: {hp['refutation_condition']}")
                meta_bits = [f"predicted: {hp.get('predicted', '—')}"]
                if crit.get("threshold") is not None:
                    meta_bits.append(f"threshold: {crit['threshold']} µM "
                                     f"({crit.get('metric', '?')})")
                if hp.get("rationale"):
                    meta_bits.append(f"rationale: {hp['rationale']}")
                if sel and sel.get("selected"):
                    meta_bits.append(f"selected: {sel.get('reason', '')}")
                if verd:
                    bits = [f"fitted: {verd.get('observed')} µM"
                            if verd.get("observed") is not None else ""]
                    if verd.get("evidence"):
                        bits.append(f"evidence: `{verd['evidence']}`")
                    meta_bits.append(" · ".join(b for b in bits if b))
                _m = ((verd.get("derivation") or {}).get("derived")
                      or {}).get("method")
                if _m:
                    meta_bits.append(f"method: {_m}")
                if hp.get("ts"):
                    meta_bits.append("proposed "
                                     + time.strftime("%m-%d %H:%M",
                                                     time.localtime(hp["ts"])))
                st.caption(" · ".join(meta_bits))
                if run_map.get(hid):
                    run_bits = []
                    for rid in run_map[hid]:
                        t = run_ts.get(rid)
                        when = time.strftime("%H:%M", time.localtime(t)) if t else "?"
                        inst = run_instr.get(rid) or "lab"
                        run_bits.append(f"`{rid}` ({when} · {inst})")
                    st.caption("🧪 runs: " + " · ".join(run_bits))
        unlinked = [r for r in recs if r.event_type.value == "lab_run"
                    and r.decision and r.decision.get("run_id")
                    and r.decision["run_id"] not in
                    {x for v in run_map.values() for x in v}]
        if unlinked:
            st.caption(f"🧪 {len(unlinked)} run(s) awaiting result analysis: "
                       + ", ".join(f"`{u.decision['run_id']}`" for u in unlinked[-4:]))

    if gates:
        st.caption(f"🚦 {gates} gate decision(s)")

    with st.expander("Trace log", expanded=True):
        if logf.exists():
            tail = logf.read_text(errors="replace").splitlines()[-30:]
            st.code("\n".join(tail) or "(waiting for output...)", language=None)
        else:
            st.caption("(no log written yet)")



def resume_wizard(e: dict) -> None:
    from bionexus.readiness import (ExperimentReadinessReview, ReviewVerdict)
    p = e["payload"]
    st.session_state["exp_id"] = e["id"]
    st.session_state["problem"] = p.get("problem")
    if p.get("exp_def"):
        ed = p["exp_def"]
        st.session_state["exp_def"] = (
            ed if isinstance(ed, ExperimentDefinition)
            else ExperimentDefinition.model_validate(ed))
    if p.get("readiness"):
        rd = dict(p["readiness"])
        rd["verdict"] = ReviewVerdict(rd["verdict"])
        st.session_state["readiness"] = (
            rd if isinstance(rd, ExperimentReadinessReview)
            else ExperimentReadinessReview.model_validate(rd))
    st.session_state["selected"] = p.get("selected", [])
    st.session_state["plate_data"] = None
    st.session_state["step"] = STATUS_STEP.get(e["status"], 1)
