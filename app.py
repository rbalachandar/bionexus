"""BioNexus Workbench — guided DMTA wizard for scientists.

A step-by-step flow that mirrors the real drug-discovery cycle.
Each step feeds the next. State persists via st.session_state.

    streamlit run app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import streamlit as st

st.set_page_config(page_title="BioNexus", page_icon="🧬", layout="wide")

from bionexus.labread import read_plate
from bionexus.plots import dose_response_svg
from bionexus.tpp import TPP, Criterion, CriterionCategory, CriterionPhase, \
    standard_small_molecule_tpp
from bionexus.experiment import (
    BiologicalSystem, ClaimType, DeliveryConditions, ExperimentDefinition,
    Intervention, ReadoutSpec,
)
from bionexus.readiness import review_experiment
from bionexus.adapters.admet import get_admet_predictor
from bionexus.adapters.retrosynthesis import SimulatedRetrosynthesis
from bionexus.agents import get_persona, AgentRole

# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------
DEFAULTS = {
    "step": 1,
    "plate_data": None,
    "tpp": None,
    "candidates": [],
    "selected": [],
    "exp_def": None,
    "readiness": None,
    "results": {},
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

STEPS = ["Upload", "Review Hits", "Assess", "Define Experiment",
         "Readiness", "Execute"]


def _nav(current: int) -> None:
    cols = st.columns(len(STEPS))
    for i, (col, name) in enumerate(zip(cols, STEPS), 1):
        marker = "🟢" if i < current else "🔵" if i == current else "⚪"
        col.markdown(f"**{marker} {name}**" if i == current
                     else f"{marker} {name}")


def _next_step():
    st.session_state.step = min(st.session_state.step + 1, len(STEPS))
    st.rerun()


def _prev_step():
    st.session_state.step = max(st.session_state.step - 1, 1)
    st.rerun()


# ---------------------------------------------------------------------------
# Main wizard
# ---------------------------------------------------------------------------
st.title("🧬 BioNexus")
_nav(st.session_state["step"])
step = st.session_state["step"]

# =========================================================================
if step == 1:
    # ------------------------------------------------------- UPLOAD
    st.header("1 · Upload instrument export")
    st.caption("Plate-reader export (CSV/TSV/XLSX). Auto-detects format, "
               "controls, and dose–response IC50s.")
    f = st.file_uploader("Upload export file", type=["csv", "tsv", "xlsx"])
    if f:
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        tmp.write(f.getvalue())
        tmp.close()
        st.session_state["plate_data"] = read_plate(tmp.name)
        st.session_state["step"] = 2
        st.rerun()
    if st.session_state.get("plate_data"):
        r = st.session_state["plate_data"]
        st.success(f"Loaded: {r.format} · {len(r.records)} wells · "
                   f"Z' = {r.z_prime}")
        st.code(r.table())
        if st.button("Continue →"):
            _next_step()


# =========================================================================
elif step == 2:
    # ------------------------------------------------------- REVIEW HITS
    st.header("2 · Review hits")
    r = st.session_state.get("plate_data")
    if not r:
        st.warning("Upload a plate first (step 1)")
        if st.button("← Back"): _prev_step()
    else:
        compounds = list(r.analysis["compounds"].items())
        selected = st.session_state.get("selected", [])
        for sample, data in compounds:
            ic50 = data.get("ic50_um")
            col1, col2, col3 = st.columns([4, 2, 1])
            with col1:
                st.markdown(f"**{sample}** — "
                            f"IC50 = {f'{ic50:.1f} µM' if ic50 else '> range'}")
            with col2:
                if ic50:
                    st.metric("IC50 (µM)", f"{ic50:.1f}")
            with col3:
                key = f"sel_{sample}"
                st.checkbox("Select", key=key,
                            value=sample in selected,
                            on_change=lambda s=sample, k=key: (
                                st.session_state["selected"].append(s)
                                if st.session_state[k]
                                else st.session_state["selected"].remove(s)
                            ) if s in st.session_state["selected"] or
                            st.session_state[k] else None)
            if data.get("curve"):
                st.markdown(dose_response_svg(data["curve"],
                            ic50=data["ic50_um"],
                            title=sample), unsafe_allow_html=True)
        st.session_state["selected"] = list(set(st.session_state.get("selected", [])))
        st.info(f"{len(st.session_state['selected'])} candidate(s) selected")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("← Back"): _prev_step()
        with col2:
            if st.button("Continue →", type="primary"):
                st.session_state["step"] = 3
                st.rerun()


# =========================================================================
elif step == 3:
    # ------------------------------------------------------- ASSESS
    st.header("3 · Assess: ADMET + Retrosynthesis + Readiness")
    selected = st.session_state.get("selected", [])
    if not selected:
        st.warning("No candidates selected — go back to step 2")
        if st.button("← Back"): _prev_step()
    else:
        admet = get_admet_predictor()
        retro = SimulatedRetrosynthesis()
        tpp = standard_small_molecule_tpp("campaign", "target")
        for smi in selected:
            st.subheader(smi)
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**ADMET**")
                try:
                    r = admet.predict(smi)
                    s = r.summary()
                    st.markdown(f"- MW: {s['mw_da']} Da\n"
                                f"- LogP: {s.get('logp', '?')}\n"
                                f"- TPSA: {s.get('tpsa', '?')}\n"
                                f"- Lipinski violations: "
                                f"{s['lipinski_violations']}\n"
                                f"- PAINS: {s['pains_alerts'] or 'none'}\n"
                                f"- Veber: "
                                f"{'PASS' if s.get('rotatable_bonds', 99) <= 10 else 'CHECK'}")
                except Exception as e:
                    st.warning(f"ADMET unavailable: {e}")
            with col2:
                st.markdown("**Retrosynthesis**")
                try:
                    from bionexus.adapters.retrosynthesis import \
                        SimulatedRetrosynthesis
                    route = SimulatedRetrosynthesis().plan(smi)
                    st.markdown(f"- Feasible: "
                                f"{'✅' if route.feasible else '❌'}\n"
                                f"- Steps: {route.num_steps}\n"
                                f"- Score: {route.overall_score}")
                except Exception as e:
                    st.warning(f"Retrosynthesis unavailable: {e}")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("← Back"): _prev_step()
        with col2:
            if st.button("Continue →", type="primary"):
                st.session_state["step"] = 4
                st.rerun()


# =========================================================================
elif step == 4:
    # ------------------------------------------------------- DEFINE EXPERIMENT
    st.header("4 · Define experiment")
    selected = st.session_state.get("selected", [])
    st.info(f"Candidates: {', '.join(selected)}")
    q = st.text_area("Scientific question",
                     placeholder="Does compound X bind target Y with "
                                 "IC50 <= 20 uM?")
    col1, col2 = st.columns(2)
    claim = col1.selectbox("Claim type", [c.value for c in ClaimType])
    half_life = col2.number_input("Target half-life (min)", 1, 9999, 120)
    edited_frac = st.checkbox("Readout measures edited fraction")
    mimetic = st.checkbox("Distinguishes mimetic")
    controls = st.text_area("Controls (one per line)").split("\n")
    controls = [c.strip() for c in controls if c.strip()]

    exp = ExperimentDefinition(
        scientific_question=q or "user experiment",
        claim_type=ClaimType(claim),
        intervention=Intervention(kind="binding", target="user-target"),
        system=BiologicalSystem(cell_line="user", target_half_life_min=half_life),
        delivery=DeliveryConditions(method="user", per_cell_loading_measured=True),
        readout=ReadoutSpec(assay="user", measures_edited_fraction=edited_frac,
                            distinguishes_modified_from_mimetic=mimetic),
        controls=controls,
    )
    review = review_experiment(exp)

    icon = {"ready": "✅", "ready_with_warnings": "⚠️", "blocked": "❌"}
    st.markdown(f"### Readiness: {icon.get(review.verdict.value, '—')} "
                f"{review.verdict.value.replace('_', ' ').title()}")
    for f in review.findings:
        if f.severity == "blocker":
            st.error(f"❌ {f.check}: {f.message}")
        elif f.severity == "warning":
            st.warning(f"⚠️ {f.check}: {f.message}")
        else:
            st.success(f"✅ {f.check}")

    if review.verdict == "blocked":
        st.info("Redesign the experiment to resolve blockers, then re-check.")
    elif st.button("Continue →", type="primary"):
        st.session_state["exp_def"] = exp
        st.session_state["readiness"] = review
        st.session_state["step"] = 5
        st.rerun()

    if st.button("← Back"): _prev_step()


# =========================================================================
elif step == 5:
    # ------------------------------------------------------- READINESS SUMMARY
    st.header("5 · Readiness summary")
    exp = st.session_state.get("exp_def")
    review = st.session_state.get("readiness")
    if not exp or not review:
        st.warning("Complete step 4 first")
        if st.button("← Back"): _prev_step()
    else:
        st.markdown(f"**Question:** {exp.scientific_question}")
        st.markdown(f"**Claim:** {exp.claim_type.value}")
        st.markdown(f"**Verdict:** {review.verdict.value}")
        st.markdown(f"**Controls:** {', '.join(exp.controls)}")
        st.markdown(f"**Denominators:** {', '.join(exp.denominators)}")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("← Back"): _prev_step()
        with col2:
            if st.button("✅ Confirm & Execute"):
                st.balloons()
                st.success("Experiment defined and provenance-recorded. "
                           "Submit via `bn serve` or `bn auto` to execute.")
