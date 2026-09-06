"""BioNexus Workbench — Streamlit wrapper for the core agentic engine.

    pip install streamlit
    streamlit run app.py

Calls the same core functions as `bn` CLI. No HTML/JS knowledge required.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import streamlit as st

st.set_page_config(page_title="BioNexus Workbench", page_icon="🧬", layout="wide")

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
from bionexus.agents import all_personas


# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------
st.title("🧬 BioNexus Workbench")
page = st.sidebar.radio(
    "Navigate",
    ["📊 Read Results", "🧪 Design Experiment", "🎯 TPP",
     "👥 Agent Personas", "🧱 ADMET + Synthesis"],
)


# ---------------------------------------------------------------------------
# 📊 Read Results
# ---------------------------------------------------------------------------
if page == "📊 Read Results":
    st.header("Analyze instrument export")
    st.caption("Upload a plate-reader export (CSV/TSV/XLSX). Auto-detects format, "
               "controls, and dose–response IC50s.")
    f = st.file_uploader("Upload export file", type=["csv", "tsv", "xlsx"])
    if f:
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        tmp.write(f.getvalue())
        tmp.close()
        result = read_plate(tmp.name)
        st.success(f"Format: {result.format} · Wells: {len(result.records)} · "
                   f"Controls: {result.analysis['controls_detected']} · "
                   f"Z': {result.z_prime}")
        st.code(result.table())
        for sample, data in result.analysis["compounds"].items():
            if data.get("curve"):
                pts = [(c, v) for c, v in data["curve"]]
                svg = dose_response_svg(pts, ic50=data["ic50_um"],
                                        title=f"{sample}")
                st.markdown(svg, unsafe_allow_html=True)
    else:
        st.info("Upload a CSV/TSV/XLSX export from your plate reader.")


# ---------------------------------------------------------------------------
# 🧪 Design Experiment
# ---------------------------------------------------------------------------
elif page == "🧪 Design Experiment":
    st.header("Define experiment + check readiness")
    st.caption("Checks whether the experiment, if successful, would produce an "
               "interpretable result.")

    q = st.text_area("Scientific question",
                     placeholder="Does S62 phosphorylation cause degradation?")
    col1, col2 = st.columns(2)
    claim = col1.selectbox("Claim type",
                           [c.value for c in ClaimType])
    target = col2.text_input("Target protein", "c-Myc")
    col3, col4 = st.columns(2)
    site = col3.text_input("Site (e.g. S62)")
    half_life = col4.number_input("Target half-life (min)", min_value=1, value=120)
    edited_frac = st.checkbox("Readout measures edited fraction")
    mimetic = st.checkbox("Readout distinguishes mimetic")
    controls = st.text_area("Controls (one per line)").split("\n")
    controls = [c.strip() for c in controls if c.strip()]

    if st.button("Check readiness"):
        exp = ExperimentDefinition(
            scientific_question=q, claim_type=ClaimType(claim),
            intervention=Intervention(kind="user_defined", target=target, site=site),
            system=BiologicalSystem(cell_line="user", target_half_life_min=half_life),
            delivery=DeliveryConditions(method="user", per_cell_loading_measured=True),
            readout=ReadoutSpec(assay="user", measures_edited_fraction=edited_frac,
                                distinguishes_modified_from_mimetic=mimetic),
            controls=controls,
        )
        review = review_experiment(exp)
        icon = {"ready": "✅", "ready_with_warnings": "⚠️", "blocked": "❌"}
        st.markdown(f"### {icon.get(review.verdict.value, '—')} "
                    f"{review.verdict.value.replace('_', ' ').title()}")
        for f in review.findings:
            if f.severity == "blocker":
                st.error(f"❌ **{f.check}**: {f.message}")
            elif f.severity == "warning":
                st.warning(f"⚠️ {f.check}: {f.message}")
            else:
                st.success(f"✅ {f.check}")


# ---------------------------------------------------------------------------
# 🎯 TPP
# ---------------------------------------------------------------------------
elif page == "🎯 TPP":
    st.header("Target Product Profile")
    program = st.text_input("Program name", "My-Program")
    target = st.text_input("Target", "MAP4K1")
    ic50 = st.number_input("IC50 threshold (nM)", value=50)
    tpp = standard_small_molecule_tpp(program, target, ic50_nm=ic50)
    for phase in CriterionPhase:
        cr = tpp.criteria_for_phase(phase)
        if cr:
            st.subheader(phase.value.title())
            for c in cr:
                direction = "≤" if c.direction == "min" else "≥"
                req = "required" if c.required else "optional"
                st.markdown(f"- **{c.name}**: {direction} {c.threshold} {c.unit} "
                            f"*({req})*")


# ---------------------------------------------------------------------------
# 👥 Agent Personas
# ---------------------------------------------------------------------------
elif page == "👥 Agent Personas":
    st.header("Agent Personas")
    st.caption("Named roles that map to ModelProvider configs and toolsets. "
               "Each persona declares a mandate and preferred tools.")
    for role, persona in all_personas().items():
        with st.expander(f"{persona.display_name} ({role.value})"):
            st.write(f"**Mandate:** {persona.system_mandate}")
            st.caption(f"Tools: {', '.join(persona.preferred_tools)} · "
                       f"temperature: {persona.temperature}")


# ---------------------------------------------------------------------------
# 🧱 ADMET + Synthesis
# ---------------------------------------------------------------------------
elif page == "🧱 ADMET + Synthesis":
    st.header("ADMET Prediction + Retrosynthesis")
    smi = st.text_input("SMILES", "CC(=O)Oc1ccccc1C(=O)O")
    if smi:
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("ADMET")
            try:
                predictor = get_admet_predictor()
                r = predictor.predict(smi)
                st.json(r.summary())
            except Exception as e:
                st.error(f"ADMET: {e}")
        with col2:
            st.subheader("Retrosynthesis")
            try:
                from bionexus.adapters.retrosynthesis import SimulatedRetrosynthesis
                route = SimulatedRetrosynthesis().plan(smi)
                st.json(route.summary())
            except Exception as e:
                st.error(f"Retrosynthesis: {e}")
