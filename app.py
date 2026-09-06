"""BioNexus Workbench — guided DMTA wizard for scientists.

Flow mirrors the scientific method: define the problem and hypothesis
FIRST, design + readiness-check the experiment, execute it, then analyze
the instrument export the experiment produced. Each step feeds the next.

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
from bionexus.experiment import (
    BiologicalSystem, ClaimType, DeliveryConditions, ExperimentDefinition,
    Intervention, ReadoutSpec,
)
from bionexus.readiness import review_experiment
from bionexus.adapters.admet import get_admet_predictor
from bionexus.adapters.retrosynthesis import SimulatedRetrosynthesis

DEFAULTS = {
    "step": 1,
    "problem": None,        # step 1 output: question + claim
    "exp_def": None,        # step 2 output: ExperimentDefinition
    "readiness": None,      # step 2 output: review verdict
    "plate_data": None,     # step 4 output: PlateReadResult
    "selected": [],         # step 5 output: chosen hit(s)
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

STEPS = ["Define Problem", "Design Experiment", "Readiness", "Execute",
         "Upload Results", "Analyze & Verdict"]


def _nav(current: int) -> None:
    cols = st.columns(len(STEPS))
    for i, (col, name) in enumerate(zip(cols, STEPS), 1):
        marker = "🟢" if i < current else "🔵" if i == current else "⚪"
        col.markdown(f"**{marker} {name}**" if i == current else f"{marker} {name}")


def _goto(n: int) -> None:
    st.session_state.step = n
    st.rerun()


# ---------------------------------------------------------------------------
st.title("🧬 BioNexus")
_nav(st.session_state["step"])
step = st.session_state["step"]

# =========================================================================
# STEP 1 — DEFINE PROBLEM
# =========================================================================
if step == 1:
    st.header("1 · Define the problem")
    st.caption("What are you trying to show? A good claim is specific: "
               "what intervention, in what system, measured how.")

    q = st.text_area(
        "Scientific question",
        placeholder="Does S62 phosphorylation cause c-Myc degradation?",
        key="q",
    )
    col1, col2 = st.columns(2)
    target = col1.text_input("Target (protein/pathway)", "c-Myc")
    claim = col2.selectbox("Claim type", [c.value for c in ClaimType],
                           help="What kind of statement would a successful "
                                "experiment support?")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("← Reset wizard"):
            for k in DEFAULTS:
                st.session_state[k] = DEFAULTS[k] if isinstance(DEFAULTS[k], (int, list)) else None
            st.session_state["step"] = 1
            st.rerun()
    with col2:
        if st.button("Continue →", type="primary", disabled=not q.strip()):
            st.session_state["problem"] = {
                "question": q.strip(), "target": target,
                "claim": ClaimType(claim),
            }
            _goto(2)

# =========================================================================
# STEP 2 — DESIGN EXPERIMENT
# =========================================================================
elif step == 2:
    st.header("2 · Design the experiment")
    p = st.session_state.get("problem") or {}
    st.info(f"**Question:** {p.get('question', '—')}")

    col1, col2 = st.columns(2)
    site = col1.text_input("Site / variant (if relevant)", "S62")
    half_life = col2.number_input("Target half-life (min)", 1, 9999, 120)
    edited_frac = st.checkbox("Readout measures edited fraction",
                              help="Does the assay quantify the fraction of "
                                   "molecules actually modified?")
    mimetic = st.checkbox("Distinguishes real from mimetic phenotype",
                          help="Can the assay tell a true modification from "
                               "a look-alike artefact?")
    controls = st.text_area("Controls (one per line)",
                            placeholder="DMSO vehicle\nKnown inhibitor\n"
                                        "Kinase-dead mutant")
    controls = [c.strip() for c in controls.split("\n") if c.strip()]

    if st.button("← Back"):
        _goto(1)

    exp = ExperimentDefinition(
        scientific_question=p.get("question", "user experiment"),
        claim_type=p.get("claim", ClaimType.CAUSAL),
        intervention=Intervention(kind="user_defined",
                                  target=p.get("target", "user-target"),
                                  site=site or None),
        system=BiologicalSystem(cell_line="user", target_half_life_min=half_life),
        delivery=DeliveryConditions(method="user", per_cell_loading_measured=True),
        readout=ReadoutSpec(assay="user", measures_edited_fraction=edited_frac,
                            distinguishes_modified_from_mimetic=mimetic),
        controls=controls,
    )
    st.session_state["exp_def"] = exp
    if st.button("Check readiness →", type="primary"):
        st.session_state["readiness"] = review_experiment(exp)
        _goto(3)

# =========================================================================
# STEP 3 — READINESS GATE
# =========================================================================
elif step == 3:
    st.header("3 · Readiness check")
    exp = st.session_state.get("exp_def")
    review = st.session_state.get("readiness")
    if not exp or not review:
        st.warning("Design the experiment first (step 2)")
        if st.button("← Back"):
            _goto(2)
    else:
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

        col1, col2 = st.columns(2)
        with col1:
            if st.button("← Redesign"):
                _goto(2)
        with col2:
            blocked = review.verdict.value == "blocked"
            if st.button("Proceed to execution →", type="primary",
                         disabled=blocked,
                         help="Resolve blockers before running the experiment"):
                _goto(4)

# =========================================================================
# STEP 4 — EXECUTE
# =========================================================================
elif step == 4:
    st.header("4 · Execute")
    exp = st.session_state.get("exp_def")
    st.info(f"**Question:** {exp.scientific_question}\n\n"
            f"**Claim:** {exp.claim_type.value} · "
            f"**Controls:** {len(exp.controls)}")
    st.markdown(
        "Run the experiment at the bench (or submit it to a configured lab "
        "via `bn serve` → Approve, or `bn auto` for simulated runs). When the "
        "instrument finishes, continue to step 5 with its export file.")
    lab = st.selectbox("Execution route",
                       ["Bench (manual — bring back the export)",
                        "Simulated lab (`bn auto`)",
                        "Connected lab (`bn serve` approval queue)"])
    col1, col2 = st.columns(2)
    with col1:
        if st.button("← Back"):
            _goto(3)
    with col2:
        if st.button("I have results →", type="primary"):
            _goto(5)

# =========================================================================
# STEP 5 — UPLOAD RESULTS
# =========================================================================
elif step == 5:
    st.header("5 · Upload instrument export")
    st.caption("Plate-reader export (CSV/TSV/XLSX) produced by the experiment "
               "you just defined. Auto-detects format, controls, and "
               "dose–response IC50s.")
    f = st.file_uploader("Export file", type=["csv", "tsv", "xlsx"])
    if f:
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        tmp.write(f.getvalue())
        tmp.close()
        st.session_state["plate_data"] = read_plate(tmp.name)
        _goto(6)
    r = st.session_state.get("plate_data")
    if r:
        st.success(f"Loaded: {r.format} · {len(r.records)} wells · "
                   f"Z' = {r.z_prime}")
    if st.button("← Back"):
        _goto(4)

# =========================================================================
# STEP 6 — ANALYZE & VERDICT
# =========================================================================
elif step == 6:
    st.header("6 · Analyze hits & verdict")
    r = st.session_state.get("plate_data")
    exp = st.session_state.get("exp_def")
    if not r:
        st.warning("Upload the instrument export (step 5)")
        if st.button("← Back"):
            _goto(5)
    else:
        selected = st.session_state["selected"]
        for sample, data in r.analysis["compounds"].items():
            ic50 = data.get("ic50_um")
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**{sample}** — "
                            f"IC50 = {f'{ic50:.1f} µM' if ic50 else '> range'}")
            with col2:
                if ic50 and st.checkbox("Hit", key=f"sel_{sample}",
                                        value=sample in selected):
                    if sample not in selected:
                        selected.append(sample)
                elif sample in selected:
                    selected.remove(sample)
            if data.get("curve"):
                st.markdown(dose_response_svg(data["curve"],
                            ic50=ic50, title=sample), unsafe_allow_html=True)
        st.session_state["selected"] = selected

        # secondary assessment of the selected hit(s)
        if selected:
            st.subheader("Hit assessment")
            admet = get_admet_predictor()
            for smi in selected:
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**ADMET — {smi}**")
                    try:
                        s = admet.predict(smi).summary()
                        st.markdown(
                            f"- MW: {s['mw_da']} Da · LogP: {s.get('logp', '?')} · "
                            f"TPSA: {s.get('tpsa', '?')}\n"
                            f"- Lipinski violations: {s['lipinski_violations']}\n"
                            f"- PAINS: {s['pains_alerts'] or 'none'}")
                    except Exception as e:
                        st.caption(f"ADMET unavailable: {e}")
                with col2:
                    st.markdown("**Retrosynthesis**")
                    try:
                        route = SimulatedRetrosynthesis().plan(smi)
                        st.markdown(f"- Feasible: "
                                    f"{'✅' if route.feasible else '❌'} · "
                                    f"Steps: {route.num_steps}")
                    except Exception as e:
                        st.caption(f"Retrosynthesis unavailable: {e}")

        st.subheader("Verdict")
        st.markdown(
            f"Record the predicted-vs-observed comparison against the "
            f"hypothesis from step 1:\n\n> **{exp.scientific_question}**")
        obs = st.radio("Observed outcome vs prediction",
                       ["supports hypothesis", "refutes hypothesis",
                        "inconclusive"], horizontal=True)
        if st.button("Record verdict", type="primary"):
            st.success(f"Recorded: **{obs}** — provenance-chained to the "
                       f"experiment definition from step 2. "
                       f"Full audit: `bn prove --html` or `bn diary`.")
        if st.button("← Back"):
            _goto(5)
