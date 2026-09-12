"""Run narrative — the story structure of one campaign, rendered live.

Sections (mirroring what made the demo run convincing as documentation):
hypotheses as proposed → who got lab slots and why → what the gates did →
verdicts and the honesty of them. Works on any provenance branch's records,
so the Experiment page tells YOUR run this way, not a canned one.
"""
from __future__ import annotations

import streamlit as st


def _proposed(recs):
    return [r for r in recs if r.event_type.value == "hypothesis_proposed"
            and (r.artifact.metadata if r.artifact else {})
            and (r.artifact.metadata or {}).get("candidate")]


def _candidate(r):
    return ((r.artifact.metadata if r.artifact else {}) or {}).get("candidate")


def render_hypotheses(recs) -> None:
    props = _proposed(recs)
    if not props:
        return
    st.markdown("The hypotheses, as proposed")
    st.dataframe([
        {"candidate": _candidate(r),
         "mechanism": ((r.decision or {}).get("mechanism") or "—")[:70],
         "refuted if": ((r.decision or {}).get("refutation_condition")
                        or "—")[:48],
         "citation": (r.decision or {}).get("citation") or "—",
         "citation check": (r.decision or {}).get("citation_status")
         or "unverified"}
        for r in props], hide_index=True)


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
    st.markdown("Who got the lab slots, and why")
    st.dataframe([
        {"hypothesis": id2cand.get(d.get("hypothesis_id"),
                                   d.get("hypothesis_id", "?")),
         "score": d.get("score"),
         "selected": "✅" if d.get("selected") else "—",
         "recorded reason": d.get("reason", "")}
        for d in (filt.decision or {}).get("decisions", [])], hide_index=True)


def render_gates(recs, log_lines=()) -> None:
    refusals = [l for l in log_lines if "rejected" in l]
    advs = [r for r in recs
            if (r.decision or {}).get("kind") == "advisory"]
    durc = [r for r in recs if (r.decision or {}).get("kind") == "durc_refusal"]
    if not (refusals or advs or durc):
        return
    st.markdown("What the gates did")
    for l in refusals:
        st.error(l.replace("[campaign] ", "").replace("[agent] ", ""),
                 icon="🚫")
    for a in advs:
        flags = (a.decision or {}).get("flags", [])
        st.warning("Advisory tier flagged (not blocked): " + "; ".join(
            f"{f.get('sample')} — {f.get('alert')}"
            + (f" (declared intent: {f['declared_intent']})"
               if f.get("declared_intent") else "") for f in flags),
            icon="⚠️")
    for d in durc:
        st.error("DURC refusal: " + ", ".join(
            (d.decision or {}).get("agents", [])), icon="🚫")


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
    st.markdown("Verdicts — and the honesty of them")
    st.dataframe([
        {"candidate": c, "verdict": d.get("verdict"),
         "observed IC50 (µM)": d.get("observed"),
         "95% CI": "–".join(str(x) for x in d.get("observed_ci") or []) or "—",
         "gate (pre-registered)": d.get("threshold"),
         "evidence run": d.get("evidence_run_id") or "never ran"}
        for c, d in sorted(last.items())], hide_index=True)
    st.caption("Decided by: the analysis agent fitted the curve (Hill + "
               "bootstrap CI from the instrument's raw wells); the verdict is "
               "the pre-registered criteria applied to that fit — not the "
               "agent's opinion. 'never ran' = refused upstream by a gate.")
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


def render_trust(recs, log_lines=()) -> None:
    """Per-run trust summary: what was checked, refused, flagged, abstained."""
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
    rules = "—"
    for l in refusals:
        if "safety-rules-" in l:
            rules = l.split("[rules ")[1].split("]")[0]
            break
    st.markdown("### Trust summary for this run")
    c1, c2, c3, c4 = st.columns(4)
    ver = cstates.count("verified")
    c1.metric("Citations verified", f"{ver}/{len(cstates)}" if cstates
              else "none cited")
    c2.metric("Gate refusals", len(refusals) + len(durc))
    c3.metric("Advisory flags", n_flags)
    c4.metric("Verdicts abstained", abstained)
    st.caption(f"rule set: {rules} · a fabricated citation costs portfolio "
               "score · a CI straddling the gate abstains — "
               "abstention is a verdict, not a failure")
    with st.expander("Evidence panel: what a verdict is made of"):
        from bionexus import figures
        st.markdown(figures.get("evidence"), unsafe_allow_html=True)
        st.caption("A 3-parameter Hill fit (plateau profiled, not assumed), "
                   "residual-bootstrap 95% CI shown as the shaded band, Z′ "
                   "QC from the plate. The verdict reads the band against the "
                   "pre-registered gate — left panel passes, middle "
                   "abstains, right fails. Same rendering as the "
                   "instrument-output blocks in the pipeline above.")


def render(recs, log_lines=()) -> None:
    st.markdown("### The record of this run")
    render_hypotheses(recs)
    render_portfolio(recs)
    render_gates(recs, log_lines)
    render_verdicts(recs)
    render_trust(recs, log_lines)
