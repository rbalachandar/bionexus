"""BioNexus Workbench — guided DMTA wizard for scientists.

Flow mirrors the scientific method: define the problem and hypothesis
FIRST, design + readiness-check the experiment, execute it, then analyze
the instrument export the experiment produced. Each step feeds the next.

    streamlit run Overview.py
"""
from __future__ import annotations

import re
import sys
import time
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
from bionexus.wizard_store import WizardStore

DEFAULTS = {
    "step": 0,              # 0 = overview (ongoing experiments)
    "exp_id": None,         # persistent experiment record id
    "problem": None,        # step 1 output: question + claim
    "exp_def": None,        # step 2 output: ExperimentDefinition
    "readiness": None,      # step 2 output: review verdict
    "plate_data": None,     # step 4 output: PlateReadResult
    "selected": [],         # step 5 output: chosen hit(s)
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

STEPS = ["Overview", "Define Problem", "Design Experiment", "Readiness",
         "Execute", "Upload Results", "Analyze & Verdict"]
STATUS_STEP = {  # status -> wizard step to resume at
    "defining": 1, "designing": 2, "readiness_ok": 4, "ready_blocked": 3,
    "executing": 4, "results_uploaded": 6, "verdict_recorded": 6,
}

store = WizardStore()


def _save(status: str, **fields) -> None:
    eid = st.session_state.get("exp_id")
    if eid:
        store.update(eid, status, **fields)


def _nav(current: int) -> None:
    cols = st.columns(len(STEPS))
    for i, (col, name) in enumerate(zip(cols, STEPS), 1):
        marker = "🟢" if i < current else "🔵" if i == current else "⚪"
        col.markdown(f"**{marker} {name}**" if i == current else f"{marker} {name}")


def _goto(n: int) -> None:
    st.session_state.step = n
    st.rerun()


# ---------------------------------------------------------------------------
def _campaign_start_form() -> None:
    from bionexus.templates import (build_campaign, fill, load_template,
                                    list_templates, save_user_template)
    from bionexus.serve import save_campaign_index
    from bionexus.paths import ensure_dirs
    import subprocess
    import sys as _sys

    tpl_names = [t["name"] for t in list_templates()] + ["✏️ Custom…"]
    c1, c2 = st.columns(2)
    tpl = c1.selectbox("Template", tpl_names,
                       format_func=lambda n: n if not n.endswith("…") else n)
    autonomy = c2.selectbox(
        "Autonomy",
        ["act — autonomous within safety rules",
         "gate — I approve each experiment",
         "observe — analysis only"])

    custom = tpl == "✏️ Custom…"
    if custom:
        st.caption("No template — describe the problem yourself. Compounds "
                   "become one hypothesis each with your potency criterion.")
    objective_default = "Rank compounds by binding potency and identify those with IC50 <= {threshold} uM"
    objective = st.text_input(
        "Objective", value="" if custom else "",
        placeholder=objective_default if custom else None,
        disabled=not custom)
    c3, c4 = st.columns(2)
    compounds = c3.text_input(
        "Compounds (comma-separated)", "gefitinib,erlotinib,lapatinib,osimertinib")
    threshold = c4.number_input("Potency threshold (µM)", 0.1, 1000.0, 20.0)
    k = st.slider("How many hypotheses may go to the lab (top-k)", 1, 6, 2)

    save_as = None
    if custom:
        save_as = st.text_input("Save as reusable template (optional name)",
                                placeholder="my-kinase-screen")

    if st.button("🚀 Start campaign", type="primary", disabled=not compounds.strip()):
        threshold_s = str(int(threshold)) if threshold == int(threshold) else str(threshold)
        if custom:
            objective_text = (objective.strip() or objective_default).replace(
                "{threshold}", threshold_s)
            problem = {"objective": objective_text,
                       "constraints": [{"name": "potency",
                                        "description": f"IC50 <= {threshold_s} uM",
                                        "kind": "hard",
                                        "limit": float(threshold), "unit": "uM"}],
                       "success_metric": "IC50 ranking consistent across replicates"}
            if save_as and save_as.strip():
                p = save_user_template(save_as.strip(), objective_text, problem,
                                       {"type": "binding"})
                st.toast(f"Template saved: {p}")
            cfg = {"problem": problem,
                   "hypotheses": [
                       {"statement": f"{c.strip()} binds with IC50 <= {threshold_s} uM",
                        "candidate": c.strip(), "assay_type": "binding",
                        "predicted": f"IC50 <= {threshold_s}",
                        "predicted_value": float(threshold),
                        "rationale": "custom"}
                       for c in compounds.split(",") if c.strip()],
                   "k": k, "autonomy": autonomy.split(" —")[0],
                   "concentrations": ["0.5uM", "2uM", "10uM", "40uM"]}
        else:
            tpl_doc = load_template(tpl)
            cfg = build_campaign(fill(tpl_doc, {"compounds": compounds,
                                                "threshold": threshold_s},
                                      prompt_missing=False))
            cfg["k"] = k
        cfg["autonomy"] = autonomy.split(" —")[0]
        ensure_dirs()
        cid = f"cmp-{int(time.time())}"
        cfgpath = CAMPAIGN_DIR / f"{cid}.json"
        cfgpath.write_text(json.dumps(cfg, indent=1))
        logf = CAMPAIGN_DIR / f"{cid}.log"
        import sys as _sys
        proc = subprocess.Popen(
            [_sys.executable, "-m", "bionexus.cli", "auto", str(cfgpath),
             "--db", "bionexus.db", "--inbox", ".data/approvals.jsonl", "--yes"],
            stdout=open(logf, "ab", buffering=0), stderr=subprocess.STDOUT,
            cwd=str(Path.cwd()))
        store.register_agent(cid, cfg["problem"]["objective"], str(logf),
                             autonomy=cfg["autonomy"], pid=proc.pid)
        idx = campaign_index()
        idx[cid] = {"pid": proc.pid, "autonomy": cfg["autonomy"],
                    "objective": cfg["problem"]["objective"], "log": str(logf)}
        save_campaign_index(idx)
        st.session_state["view_experiment"] = cid
        st.switch_page("pages/Experiments.py")

st.title("🧬 BioNexus")
step = st.session_state["step"]
if step == 0:
    st.caption("BioNexus workbench — where hypotheses become experiments, "
               "experiments run in the lab, and every result is recorded.")
else:
    _nav(step)
    if st.button("← Overview"):
        st.session_state["step"] = 0
        st.rerun()

# =========================================================================
# STEP 0 — OVERVIEW: approvals → live agents → experiments → start
# =========================================================================
if step == 0:
    from bionexus.serve import (campaign_index, campaign_running, CAMPAIGN_DIR,
                                save_campaign_index)
    from bionexus.webview import resume_wizard as _resume_wizard
    from bionexus.approvals import ApprovalInbox

    inbox = ApprovalInbox(".data/approvals.jsonl")
    pending = inbox.pending()

    # ---------------------------------------------------- 1. approvals
    st.header("Awaiting your decision")
    if pending:
        for p in pending:
            with st.container(border=True):
                st.markdown(f"**{p['title']}**")
                if p.get("detail"):
                    st.caption(p["detail"])
                c1, c2, _ = st.columns([1, 1, 3])
                if c1.button("✅ Approve", key=f"ok_{p['id']}", type="primary"):
                    inbox.decide(p["id"], True)
                    st.rerun()
                if c2.button("❌ Deny", key=f"no_{p['id']}"):
                    inbox.decide(p["id"], False)
                    st.rerun()
        st.caption("The campaign is paused until you decide.")

        @st.fragment(run_every=3)
        def _wait_approvals():
            if not ApprovalInbox(".data/approvals.jsonl").pending():
                st.rerun()
        _wait_approvals()
    else:
        st.caption("Nothing pending.")

    # ------------------------------------------------ 2. experiments (ONE list)
    all_rows = store.ongoing() + store.finished(50)
    st.header("Experiments")
    if not all_rows:
        st.info("Nothing yet — start your first experiment below.")

    def _agent_row_status(e: dict) -> tuple[str, Path]:
        ag = e["payload"].get("agent") or {}
        logf = Path(ag.get("log", ""))
        if logf.exists() and "CAMPAIGN COMPLETE" in logf.read_text(errors="replace"):
            return "completed", logf
        pid = ag.get("pid")
        if pid:
            try:
                import os as _os
                _os.kill(pid, 0)
                return "running", logf          # process alive, not finished yet
            except OSError:
                pass
            return "interrupted", logf          # process died without completing
        if e["status"] == "executing":
            # no pid recorded (older record): fall back to log recency
            if logf.exists():
                import time as _t
                age = _t.time() - logf.stat().st_mtime
                if age > 300:
                    return "interrupted", logf  # no output for 5+ minutes
                return "running", logf
            return "interrupted", logf
        return e["status"].replace("_", " "), logf

    for e in all_rows:
        agent = e["payload"].get("agent")
        if agent:
            status, _ = _agent_row_status(e)
            icon = "🤖"
            action = "View pipeline"
        else:
            status = e["status"].replace("_", " ")
            icon = "🧑"
            action = "Resume →"
        c1, c2, c3 = st.columns([6, 2, 2])
        c1.markdown(f"{icon} **{e['question'][:78]}**")
        c2.caption(f"{status} · "
                   f"{time.strftime('%m-%d %H:%M', time.localtime(e['updated_at']))}")
        with c3:
            if st.button(action, key=f"v_{e['id']}",
                         disabled=(status == "verdict recorded")):
                if agent:
                    st.session_state["view_experiment"] = e["id"]
                    st.switch_page("pages/Experiments.py")
                else:
                    _resume_wizard(e)
                    st.rerun()

    # ------------------------------------------------ 3. start new work
    st.header("Start new work")
    mode = st.radio("How do you want to run it?",
                    ["🤖 Agent-driven — agent proposes and tests hypotheses",
                     "🧑 Manual — Define and test hypotheses"],
                    horizontal=True, label_visibility="collapsed")
    if mode.startswith("🤖"):
        _campaign_start_form()
    else:
        if st.button("＋ Define experiment", type="primary"):
            st.session_state["step"] = 1
            st.rerun()

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

    if st.button("Continue →", type="primary", disabled=not q.strip()):
            st.session_state["problem"] = {
                "question": q.strip(), "target": target,
                "claim": ClaimType(claim),
            }
            st.session_state["exp_id"] = store.create(q.strip(), claim, target)
            _save("designing", problem=st.session_state["problem"])
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
        review = review_experiment(exp)
        st.session_state["readiness"] = review
        _save("designing", exp_def=exp.model_dump(mode="json"),
              readiness={"verdict": review.verdict.value,
                         "findings": [f.model_dump(mode="json")
                                      for f in review.findings]})
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
                _save("readiness_ok" if not blocked else "ready_blocked")
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
            _save("executing")
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
        r = read_plate(tmp.name)
        st.session_state["plate_data"] = r
        _save("results_uploaded",
              plate={"format": r.format, "n_wells": len(r.records),
                     "z_prime": r.z_prime,
                     "samples": list(r.analysis["compounds"])})
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
            _save("verdict_recorded", verdict=obs,
                  selected_hits=st.session_state["selected"])
            st.success(f"Recorded: **{obs}** — provenance-chained to the "
                       f"experiment definition from step 2. "
                       f"Full audit: `bn prove --html` or `bn diary`.")
            if st.button("← Back to overview"):
                st.session_state["step"] = 0
                st.rerun()
        if st.button("← Back"):
            _goto(5)
