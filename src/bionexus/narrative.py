"""Run narrative — the story structure of one campaign, rendered live.

Sections (mirroring what made the demo run convincing as documentation):
hypotheses as proposed → who got lab slots and why → what the gates did →
verdicts and the honesty of them. Works on any provenance branch's records,
so the Experiment page tells YOUR run this way, not a canned one.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st


def _proposed(recs):
    return [r for r in recs if r.event_type.value == "hypothesis_proposed"
            and (r.artifact.metadata if r.artifact else {})
            and (r.artifact.metadata or {}).get("candidate")]


def _candidate(r):
    return ((r.artifact.metadata if r.artifact else {}) or {}).get("candidate")


def render_portfolio(recs) -> None:
    filt = next((r for r in recs
                 if r.event_type.value == "hypotheses_filtered"), None)
    if not filt:
        return
    id2cand = {}
    for r in _proposed(recs):
        hid = (r.decision or {}).get("hypothesis_id")
        if hid:
            id2cand[hid] = _candidate(r)
        id2cand[r.artifact.artifact_id] = _candidate(r)
    st.markdown("Hypothesis scores")
    st.dataframe([
        {"hypothesis": id2cand.get(d.get("hypothesis_id"),
                                   d.get("hypothesis_id", "?")),
         "score": d.get("score"),
         "selected": "yes" if d.get("selected") else "—",
         "recorded reason": d.get("reason", "")}
        for d in (filt.decision or {}).get("decisions", [])], hide_index=True)


def render_gates(recs, log_lines=()) -> None:
    refusals = [l for l in log_lines if "rejected" in l]
    advs = [r for r in recs
            if (r.decision or {}).get("kind") == "advisory"]
    durc = [r for r in recs if (r.decision or {}).get("kind") == "durc_refusal"]
    if not (refusals or advs or durc):
        return
    st.markdown("Hypotheses at the gates")
    for l in refusals:
        st.error(l.replace("[campaign] ", "").replace("[agent] ", ""),
                 icon=":material/block:")
    for a in advs:
        flags = (a.decision or {}).get("flags", [])
        st.warning("Advisory tier flagged (not blocked): " + "; ".join(
            f"{f.get('sample')} — {f.get('alert')}"
            + (f" (declared intent: {f['declared_intent']})"
               if f.get("declared_intent") else "") for f in flags),
            icon=":material/report:")
    for d in durc:
        st.error("DURC refusal: " + ", ".join(
            (d.decision or {}).get("agents", [])), icon=":material/block:")


def render_make(recs) -> None:
    """Make: what actually crossed the gate into the lab — the submitted
    protocols and their runs. Design and Analyze without Make hides the
    physical action the whole framework exists to govern."""
    runs = [r for r in recs if r.event_type.value == "lab_run"
            and (r.decision or {}).get("run_id")]
    refusals = [r for r in recs if r.event_type.value == "gate_decision"
                and (r.decision or {}).get("kind") in
                ("safety_refusal", "halt_refusal", "authorization",
                 "durc_refusal", "operator_declined",
                 "synthesis_failed", "stability_failed")
                and (r.decision or {}).get("column") != "autonomous"]
    if not runs and not refusals:
        return
    st.markdown("### Make — what the gate allowed")
    synth = [r for r in recs
             if r.event_type.value == "synthesis_complete"]
    bio_qc = [r for r in recs
              if r.event_type.value == "stage_transition"
              and (r.decision or {}).get("kind") == "bioprocess_qc"]
    if bio_qc:
        st.dataframe([
            {"candidate": (r.decision or {}).get("candidate", "?"),
             "lot": (r.decision or {}).get("lot", "—"),
             "aggregation risk": (r.decision or {}).get(
                 "aggregation_risk", "—"),
             "t½ (h)": (r.decision or {}).get("t_half_h", "—"),
             "batch": "passed" if (r.decision or {}).get("ok")
                      else "REFUSED into Test"}
            for r in bio_qc], hide_index=True)
    if runs and not synth:
        st.caption("No synthesis batches recorded — this run predates "
                   "Make-synthesis; submissions went straight to the "
                   "gate.")
    if synth:
        st.dataframe([
            {"candidate": (r.decision or {}).get("candidate", "?"),
             "lot": (r.decision or {}).get("lot", "—"),
             "yield %": (r.decision or {}).get("yield_pct", "—"),
             "purity %": (r.decision or {}).get("purity", "—"),
             "batch": "passed" if (r.decision or {}).get("ok")
                      else "REFUSED into Test"}
            for r in synth], hide_index=True)
    if runs:
        st.dataframe([
            {"submission": ((r.decision or {}).get("title") or "—")[:48],
             "protocol": (r.decision or {}).get("assay", "—"),
             "samples": (r.decision or {}).get("n_samples", "—"),
             "doses (µM)": ", ".join(
                 str(c) for c in
                 (r.decision or {}).get("concentrations") or []) or "—",
             "replicates": (r.decision or {}).get("replicates", "—"),
             "controls": (r.decision or {}).get("n_controls", "—")}
            for r in runs], hide_index=True)
        st.caption("Every submission passed the SafetyEngine and the "
                   "governance gate — the lab executes these in the "
                   "Test section below.")

    # Test: the lab's side — what the protocol asks for, device, evidence
    if runs:
        st.markdown("### Test — the lab executes")
        d0 = runs[0].decision or {}
        conc = ", ".join(str(c) for c in d0.get("concentrations") or [])
        st.caption(
            f"the protocol asks: dispense {d0.get('n_samples', '?')} "
            f"sample well(s) at {d0.get('replicates', '?')} replicates per "
            f"concentration ({conc} µM) plus "
            f"{d0.get('n_controls', '?')} controls, incubate, then read "
            f"on {d0.get('instrument', 'the reader')}"
            + (f" ({d0.get('instrument_version')})"
               if d0.get("instrument_version") else "")
            + ". Each run's raw instrument export is recorded below and "
              "re-rendered as evidence.")
        import time as _t
        rows = []
        for r in runs:
            d = r.decision or {}
            ts = getattr(getattr(r, "envelope", None), "created_at", None)
            rows.append({
                "run": d.get("run_id", "?"),
                "device": d.get("instrument", "—")
                          + (f" ({d.get('instrument_version')})"
                             if d.get("instrument_version") else ""),
                "submitted": _t.strftime("%m-%d %H:%M", _t.localtime(ts))
                             if ts else "—"})
        st.dataframe(rows, hide_index=True)
    if refusals:
        st.caption(f"{len(refusals)} further submission(s) were refused "
                   "at the gate — see Hypotheses at the gates above.")


def render_verdicts(recs) -> None:
    last: dict[str, dict] = {}
    for r in recs:
        if r.event_type.value.startswith("hypothesis_"):
            d = r.decision or {}
            cand = _candidate(r)
            if cand and d.get("verdict"):
                last[cand] = d
    if not last:
        return
    st.markdown("### Analyze \u2014 verdicts")
    from bionexus.derivation import criteria_label, metric_label
    _metrics = [d.get("metric") for d in last.values() if d.get("metric")]
    mlabel = metric_label(_metrics[0] if _metrics else None)
    has_ci = any(d.get("observed_ci") for d in last.values())
    rows = []
    for c, d in sorted(last.items()):
        row: dict = {"candidate": c, "verdict": d.get("verdict"),
                     f"estimated {mlabel}": d.get("observed")}
        if has_ci:
            row["95% CI"] = ("–".join(str(x) for x in d["observed_ci"])
                             if d.get("observed_ci") else "—")
        if d.get("threshold") is not None:
            row["gate (pre-registered)"] = criteria_label(
                d.get("metric"), None, d.get("threshold")).replace("= ", "")
        row["evidence run"] = d.get("evidence_run_id") or "never ran"
        rows.append(row)
    st.dataframe(rows, hide_index=True)
    from bionexus.derivation import describe
    st.caption("'never ran' = refused upstream by a gate. How each number "
               "was made, as recorded by the analysis path that made it:")
    for c, d in sorted(last.items()):
        st.caption(f"- **{c}**: {describe(d.get('derivation'))}")
    claimed = sum(1 for d in last.values()
                  if d.get("verdict") in ("validated", "confirmed"))
    abstained = sum(1 for d in last.values()
                    if d.get("verdict") in ("inconclusive", "proposed"))
    if abstained and not claimed:
        st.success("No compound was claimed as a hit; "
                   f"{abstained} verdict(s) abstained or refused. The loop "
                   "abstains where evidence is thin — that is the point.")
    elif abstained:
        st.caption(f"{claimed} claimed · {abstained} abstained/refused — "
                   "each abstention is a CI that straddled the gate.")


def render_reviewer(recs) -> None:
    """The reviewer pass, surfaced: findings recorded by the independent
    audit (reviewer-v1). Critical findings contradict recorded evidence."""
    from bionexus import ui
    reviews = [r for r in recs
               if r.event_type.value == "stage_transition"
               and (r.decision or {}).get("kind") == "review_report"]
    if not reviews:
        return
    r = reviews[-1]
    d = r.decision or {}
    findings = d.get("findings") or []
    st.markdown("### Reviewer pass")
    if not findings:
        st.success(f"Independent review ({d.get('review', 'reviewer-v1')}): "
                   f"{d.get('verdicts_reviewed', 0)} verdict(s) audited — "
                   "no findings.")
        return
    icon = "critical" if d.get("critical") else "warning"
    color = "#a3402f" if d.get("critical") else "#b07d2b"
    st.markdown(f"#### Independent review — "
                f"<span style='color:{color}'>{d.get('critical', 0)} "
                f"critical / {d.get('warnings', 0)} warnings</span>",
                unsafe_allow_html=True)
    for f in findings:
        sev = f.get("severity", "?")
        icon_color = ("fault", "refused") if sev == "critical" \
            else ("clock", "human-action")
        ico = ui.icon(icon_color[0], 13, icon_color[1])
        cand = f" · {f['candidate']}" if f.get("candidate") else ""
        st.markdown(f"{ico} **{sev}** · {f.get('kind', '?')}{cand}"
                    f" — {f.get('detail', '')}",
                    unsafe_allow_html=True)
    st.caption("The reviewer audits the analysis (math consistency, "
               "evidence linkage, citations). It may demand revision — "
               "it can never clear a refusal.")


def render_trust(recs, log_lines=()) -> None:
    """Analyze, part 2 support: trust checks behind the verdicts."""
    props = _proposed(recs)
    cstates = [(r.decision or {}).get("citation_status")
               for r in props if (r.decision or {}).get("citation")]
    refusals = [l for l in log_lines if "rejected" in l]
    durc = [r for r in recs
            if (r.decision or {}).get("kind") == "durc_refusal"]
    advs = [r for r in recs if (r.decision or {}).get("kind") == "advisory"]
    n_flags = sum(len((a.decision or {}).get("flags", [])) for a in advs)
    last: dict[str, dict] = {}
    for r in recs:
        if r.event_type.value.startswith("hypothesis_"):
            d = r.decision or {}
            cand = _candidate(r)
            if cand and d.get("verdict"):
                last[cand] = d
    abstained = sum(1 for d in last.values()
                    if d.get("verdict") in ("inconclusive", "proposed"))
    from bionexus.adapters.bio.tox_alerts import RULES_VERSION
    rules = RULES_VERSION
    st.markdown("### Trust checks")
    checks = []
    if cstates:
        ok = sum(1 for c in cstates if c == "verified")
        bad = sum(1 for c in cstates if c == "invalid")
        checks.append(f"citations: {ok} verified, {bad} invalid, "
                      f"{len(cstates) - ok - bad} unverified")
    if durc:
        checks.append("dual-use screening refused this branch's work")
    if n_flags:
        checks.append(f"advisory flags raised (non-blocking): {n_flags}")
    if abstained:
        checks.append(f"{abstained} verdict(s) abstained \u2014 CI "
                      "straddled the gate; abstention is reported, not "
                      "hidden")
    checks.append(f"safety rules: {rules}")
    for c in checks:
        st.caption("\u2022 " + c)


def render_evidence(recs) -> None:
    """Analyze, part 1: the curves the verdicts will be read against."""
    st.markdown("### Analyze \u2014 evidence")
    with st.expander("Results"):
        from bionexus import figures
        # REAL evidence: re-plot this branch's recorded plate files,
        # labeled by candidate and its verdict — never a stock figure
        run2cand: dict[str, str] = {}
        run2file: dict[str, str] = {}
        for r in recs:
            d = r.decision or {}
            if r.event_type.value == "hypothesis_tested" and d.get("run_id"):
                cand = (d.get("candidate")
                        or (r.artifact.metadata or {}).get("candidate")
                        if r.artifact else None) or d.get("candidate")
                if cand:
                    run2cand[d["run_id"]] = cand
        import glob
        branch = ""
        if recs:
            env = getattr(recs[0], "envelope", None)
            branch = getattr(env, "experiment_branch_id", "") or ""
        pid = branch.split("/", 1)[1] if "/" in branch else branch
        run_ids = {d.get("run_id") for r in recs
                   if (d := r.decision or {})
                   and r.event_type.value == "lab_run"
                   and d.get("run_id")}
        for rid in run_ids:
            # scope to THIS branch's files: run ids collide across leaves
            hits = (glob.glob(f"**/{pid}/**/{rid}.csv", root_dir=".data",
                              recursive=True)
                    or glob.glob(f"**/{pid}/{rid}.csv", root_dir=".data",
                                 recursive=True)
                    or glob.glob(f"**/{rid}.csv", root_dir=".data",
                                 recursive=True))
            if hits:
                run2file[rid] = str(Path(".data") / hits[0])
        last: dict[str, dict] = {}
        for r in recs:
            if r.event_type.value.startswith("hypothesis_"):
                d = r.decision or {}
                cand = _candidate(r)
                if cand and d.get("verdict"):
                    last[cand] = d
        items = [{"path": run2file[rid],
                  "label": run2cand.get(rid, rid),
                  "verdict": (last.get(run2cand.get(rid, ""), {})
                              .get("verdict"))}
                 for rid in sorted(run2file)
                 if run2file.get(rid)]
        svg = figures.run_evidence_svg(items) if items else ""
        if svg:
            st.markdown(svg, unsafe_allow_html=True)
        else:
            st.caption("No recorded plate files found for these runs "
                       "— evidence curves unavailable (honestly shown, "
                       "not simulated).")
        legend = ("A 3-parameter Hill fit (plateau profiled, not assumed), "
                  "residual-bootstrap 95% CI shown as the shaded band, Z′ "
                  "QC from the plate. The verdict reads the band against "
                  "the pre-registered gate.")
        counts: dict[str, int] = {}
        for d in last.values():
            v = d.get("verdict")
            counts[v] = counts.get(v, 0) + 1
        if counts:
            tally = " · ".join(f"{n_} {v}" for v, n_ in sorted(counts.items()))
            legend += f" This run: {tally}."
        st.caption(legend)


def render(recs, log_lines=()) -> None:
    st.markdown("## The record of this run")
    # hypotheses-as-proposed is NOT repeated here: the Hypothesis pipeline
    # cards above already carry candidate/mechanism/refutation/citation
    render_portfolio(recs)
    render_gates(recs, log_lines)
    render_make(recs)
    render_evidence(recs)
    render_verdicts(recs)
    render_reviewer(recs)
    render_trust(recs, log_lines)
