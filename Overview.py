"""BioNexus Workbench — Streamlit app.

Router pattern (st.navigation): three views — Overview (approvals + the
experiment list + start new work), Wizard (the step-by-step DMTA flow), and
Experiment (live pipeline + lab narrative). Shared design language via
bionexus.ui_kit; theming in .streamlit/config.toml.

    streamlit run Overview.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import streamlit as st

st.set_page_config(page_title="BioNexus", page_icon="🧬", layout="wide")

from bionexus.adapters.admet import get_admet_predictor
from bionexus.adapters.retrosynthesis import SimulatedRetrosynthesis
from bionexus.approvals import ApprovalInbox
from bionexus.core.contracts import EventType
from bionexus.experiment import (
    BiologicalSystem, ClaimType, DeliveryConditions, ExperimentDefinition,
    Intervention, ReadoutSpec,
)
from bionexus.labread import read_plate
from bionexus.plots import dose_response_svg
from bionexus import program as program_cfg
from bionexus.readiness import review_experiment
from bionexus.serve import CAMPAIGN_DIR, campaign_index, campaign_running
from bionexus.tpp import CriterionPhase, standard_small_molecule_tpp
from bionexus.ui_kit import ago, chip, chip_html, inject_css
from bionexus.webview import render_experiment_pipeline, resume_wizard
from bionexus.wizard_store import WizardStore

store = WizardStore()

DEFAULTS = {
    "step": 1,
    "exp_id": None,
    "problem": None,
    "exp_def": None,
    "readiness": None,
    "plate_data": None,
    "selected": [],
    "view_experiment": None,
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

STATUS_STEP = {"defining": 1, "designing": 2, "readiness_ok": 4,
               "ready_blocked": 3, "executing": 4, "results_uploaded": 6,
               "verdict_recorded": 6}


# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------
def _go(page_key: str, **setvals):
    """Callback-safe navigation: mutate state; views consume `goto`."""
    def cb():
        st.session_state.update(setvals)
        st.session_state["goto"] = page_key
    return cb


def _consume_goto(current: str) -> None:
    g = st.session_state.pop("goto", None)
    if g and g != current:
        st.switch_page(PAGES[g])


def _save(status: str, **fields) -> None:
    eid = st.session_state.get("exp_id")
    if eid:
        store.update(eid, status, **fields)


def _wprove(event, decision: dict) -> None:
    eid = st.session_state.get("exp_id")
    if not eid:
        return
    try:
        from bionexus.wizard_chain import record_wizard_event
        record_wizard_event(eid, event, decision)
    except Exception as exc:
        st.caption(f"(provenance write failed: {exc})")


def _looks_like_smiles(text: str) -> bool:
    t = text.strip()
    return (" " not in t and len(t) > 4
            and any(ch in t for ch in "cnoS")
            and any(ch in t for ch in "#=("))


def _spawn_agent_experiment(cfg: dict, objective: str) -> str:
    import subprocess
    from bionexus.paths import ensure_dirs
    from bionexus.serve import save_campaign_index
    ensure_dirs()
    cid = f"cmp-{int(time.time())}"
    cfgpath = CAMPAIGN_DIR / f"{cid}.json"
    cfgpath.write_text(json.dumps(cfg, indent=1))
    logf = CAMPAIGN_DIR / f"{cid}.log"
    proc = subprocess.Popen(
        [sys.executable, "-m", "bionexus.cli", "auto", str(cfgpath),
         "--db", "bionexus.db", "--inbox", ".data/approvals.jsonl", "--yes"],
        stdout=open(logf, "ab", buffering=0), stderr=subprocess.STDOUT,
        cwd=str(Path.cwd()))
    store.register_agent(cid, objective, str(logf),
                         autonomy=cfg.get("autonomy", "act"), pid=proc.pid)
    idx = campaign_index()
    idx[cid] = {"pid": proc.pid, "autonomy": cfg.get("autonomy", "act"),
                "objective": objective, "log": str(logf)}
    save_campaign_index(idx)
    return cid


def agent_row_status(e: dict) -> tuple[str, Path]:
    ag = e["payload"].get("agent") or {}
    logf = Path(ag.get("log", ""))
    if logf.exists() and "CAMPAIGN COMPLETE" in logf.read_text(errors="replace"):
        return "completed", logf
    pid = ag.get("pid")
    if pid:
        import os
        try:
            os.kill(pid, 0)
            return "running", logf
        except OSError:
            return "interrupted", logf
    if e["status"] == "executing":
        if logf.exists() and time.time() - logf.stat().st_mtime < 300:
            return "running", logf
        return "interrupted", logf
    return e["status"].replace("_", " "), logf


def _resolve_problem(meta: dict, logf: Path) -> str | None:
    problem_id = meta.get("problem_id")
    if logf.exists():
        m = re.findall(r"problem (prob-\w+):", logf.read_text(errors="replace"))
        latest = m[-1] if m else None
        if latest and latest != problem_id:
            problem_id = latest
    return problem_id


# --------------------------------------------------------------------------
# start dialog (P2: modal over the list, no page displacement)
# --------------------------------------------------------------------------
@st.dialog("Start agent experiment", width="large")
def start_dialog() -> None:
    from bionexus.templates import (build_campaign, fill, load_template,
                                    list_templates, save_user_template)

    tpl_names = [t["name"] for t in list_templates()] + ["✏️ Custom…"]
    c1, c2 = st.columns(2)
    tpl = c1.selectbox("Template", tpl_names)
    autonomy = c2.selectbox(
        "Autonomy",
        ["act — autonomous within safety rules",
         "gate — I approve each experiment",
         "observe — analysis only"])

    custom = tpl == "✏️ Custom…"
    if custom:
        st.caption("No template — describe the problem yourself. Compounds "
                   "become one hypothesis each with your potency criterion.")
    objective_default = ("Rank compounds by binding potency and identify "
                         "those with IC50 <= {threshold} uM")
    objective = st.text_input("Objective", "",
                              placeholder=objective_default,
                              disabled=not custom)
    pdoc = program_cfg.load()
    st.caption(f"🎯 Inheriting program: {program_cfg.gate_summary(pdoc)}")
    c3, c4 = st.columns(2)
    compounds = c3.text_input("Compounds (comma-separated)",
                              "gefitinib,erlotinib,lapatinib,osimertinib")
    threshold = c4.number_input("Potency threshold (µM)", 0.001, 1000.0,
                                program_cfg.gate_threshold_um(pdoc))
    k = st.slider("How many hypotheses may go to the lab (top-k)", 1, 6, 2)

    extra_fields: dict[str, str] = {}
    missing_required = False
    tpl_doc = None if custom else load_template(tpl)
    if not custom and tpl_doc:
        for fname, spec in (tpl_doc.get("fields") or {}).items():
            if fname in ("compounds", "threshold"):
                continue
            label = spec.get("prompt", fname.replace("_", " ").title())
            default = str(spec.get("default") or "")
            star = " *" if spec.get("required") else ""
            val = st.text_input(label + star, value=default, key=f"fld_{fname}")
            if val.strip():
                extra_fields[fname] = val.strip()
            elif spec.get("required") and default == "":
                missing_required = True

    save_as = None
    if custom:
        save_as = st.text_input("Save as reusable template (optional name)",
                                placeholder="my-kinase-screen")

    if st.button("🚀 Start agent experiment", type="primary",
                 disabled=not compounds.strip() or missing_required):
        thr_s = f"{threshold:g}"
        if custom:
            objective_text = (objective.strip() or objective_default).replace(
                "{threshold}", thr_s)
            problem = {"objective": objective_text,
                       "constraints": [{"name": "potency",
                                        "description": f"IC50 <= {thr_s} uM",
                                        "kind": "hard",
                                        "limit": float(threshold), "unit": "uM"}],
                       "success_metric": "IC50 ranking consistent across replicates"}
            if save_as and save_as.strip():
                save_user_template(save_as.strip(), objective_text, problem,
                                   {"type": "binding"})
            cfg = {"problem": problem,
                   "hypotheses": [
                       {"statement": f"{c.strip()} binds with IC50 <= {thr_s} uM",
                        "candidate": c.strip(), "assay_type": "binding",
                        "predicted": f"IC50 <= {thr_s}",
                        "predicted_value": float(threshold),
                        "rationale": ""}
                       for c in compounds.split(",") if c.strip()],
                   "k": k, "autonomy": autonomy.split(" —")[0],
                   "concentrations": ["0.5uM", "2uM", "10uM", "40uM"]}
        else:
            cfg = build_campaign(fill(tpl_doc, {"compounds": compounds,
                                                "threshold": thr_s,
                                                **extra_fields},
                                      prompt_missing=False))
            cfg["k"] = k
            cfg["autonomy"] = autonomy.split(" —")[0]
        cid = _spawn_agent_experiment(cfg, cfg["problem"]["objective"])
        st.session_state["view_experiment"] = cid
        st.switch_page(PAGES["experiment"])


# --------------------------------------------------------------------------
# VIEW: overview
# --------------------------------------------------------------------------
def overview_view() -> None:
    _consume_goto("overview")
    inject_css()
    h1, h2, h3 = st.columns([5, 1.6, 1.6])
    h1.title("🧬 BioNexus")
    if h2.button("🤖 Agent experiment", type="primary"):
        start_dialog()
    if h3.button("🧑 Manual experiment"):
        st.session_state["step"] = 1
        st.switch_page(PAGES["wizard"])

    # consume keymap-initiated actions
    if st.session_state.pop("open_new", False):
        start_dialog()

    inbox = ApprovalInbox(".data/approvals.jsonl")
    pending = inbox.pending()

    # ---------------------------------------------------- approvals (only when
    # something is actually blocked — pinned at top while it lasts)
    if pending:
        st.header(f"⏸ Awaiting your decision ({len(pending)})")
        for p in pending:
            with st.container(border=True):
                st.markdown(f"**{p['title']}**")
                if p.get("detail"):
                    st.caption(p["detail"])
                m = re.search(r"\[(problem/prob-\w+)\]", p["title"])
                owner = None
                if m:
                    want = m.group(1)
                    for e in store.ongoing():
                        ag = e["payload"].get("agent") or {}
                        if f"problem/{ag.get('problem_id')}" == want:
                            owner = e
                            break
                        lg = Path(ag.get("log", ""))
                        if lg.exists() and want.split("/")[1] in lg.read_text(
                                errors="replace"):
                            store.link_problem(e["id"], want.split("/")[1])
                            owner = e
                            break
                    if owner:
                        if st.button(f"↗ {owner['question'][:40]}",
                                     key=f"own_{p['id']}"):
                            st.session_state["view_experiment"] = owner["id"]
                            st.switch_page(PAGES["experiment"])
                c1, c2, _ = st.columns([1, 1, 3])
                if c1.button("✅ Approve", key=f"ok_{p['id']}", type="primary"):
                    inbox.decide(p["id"], True)
                    st.toast(f"Approved — {p['title']} resumes", icon="✅")
                    st.rerun()
                if c2.button("❌ Deny", key=f"no_{p['id']}"):
                    inbox.decide(p["id"], False)
                    st.toast(f"Denied — {p['title']}", icon="❌")
                    st.rerun()
        st.caption("The experiment is paused until you decide.")

        @st.fragment(run_every=3)
        def _wait_approvals():
            if not ApprovalInbox(".data/approvals.jsonl").pending():
                st.rerun()
        _wait_approvals()

    # ---------------------------------------------------- Program & TPP
    doc = program_cfg.load()
    st.header("🎯 Program")
    st.markdown(f"**{doc['program']}** · target **{doc['target']}** · "
                f"screening gate: **{doc['gate']}** at IC50 ≤ "
                f"{program_cfg.gate_threshold_um(doc):g} µM")
    with st.expander("Program & target product profile — what winning looks like"):
        st.markdown("*Hierarchy:* 🎯 Program (TPP) ▸ Problem ▸ Hypothesis ▸ "
                    "Experiment. The gate below sets the potency bar that "
                    "wizard hypotheses and agent experiments inherit.")
        # apply a pending ChEMBL suggestion before the widgets instantiate
        sp = st.session_state.pop("suggest_profile", None)
        if sp:
            st.session_state["tpp_hit"] = sp["hit_ic50_nm"]
            st.session_state["tpp_lead"] = sp["lead_ic50_nm"]
            if sp["source"] == "chembl":
                st.session_state["tpp_gate"] = "hit"
        tp1, tp2 = st.columns(2)
        prog = tp1.text_input("Program", doc["program"], key="tpp_prog")
        tgt = tp2.text_input("Target", doc["target"], key="tpp_tgt")
        tp3, tp4, tp5 = st.columns(3)
        gate = tp3.selectbox("Screening gate", ["hit", "lead", "candidate",
                                                "clinical"],
                             index=["hit", "lead", "candidate", "clinical"]
                             .index(doc["gate"]), key="tpp_gate")
        if "suggest_basis" in st.session_state:
            st.caption("🧪 " + st.session_state.pop("suggest_basis"))
        hit = tp4.number_input("Hit IC50 (nM)", 1.0, 100000.0,
                               float(doc["hit_ic50_nm"]), key="tpp_hit")
        lead = tp5.number_input("Lead IC50 (nM)", 1.0, 100000.0,
                                float(doc["lead_ic50_nm"]), key="tpp_lead")
        sb1, sb2 = st.columns(2)
        if sb1.button("💾 Save program", type="primary"):
            program_cfg.save({"program": prog, "target": tgt, "gate": gate,
                              "hit_ic50_nm": hit, "lead_ic50_nm": lead})
            st.toast(f"Program saved — {gate} gate at IC50 ≤ "
                     f"{(hit if gate == 'hit' else lead) / 1000:g} µM",
                     icon="🎯")
            st.rerun()
        if sb2.button("✨ Suggest gates from ChEMBL published data"):
            from bionexus.adapters.databases.chembl_gates import suggest
            with st.spinner(f"Querying ChEMBL for {tgt}…"):
                prof = suggest(tgt)
            st.session_state["suggest_profile"] = prof.as_dict()
            st.session_state["suggest_basis"] = (
                f"suggested from {prof.n_activities} published activities — "
                f"{prof.basis}" if prof.source == "chembl"
                else f"using conventional defaults — {prof.basis}")
            st.rerun()
        st.markdown("**Full criteria by phase** (cumulative; required = "
                    "hard gate)")
        for phase in CriterionPhase:
            crs = program_cfg.tpp().criteria_for_phase(phase)
            if crs:
                st.markdown(f"**{phase.value.title()}**")
                for c in crs:
                    direction = "≤" if c.direction == "min" else "≥"
                    req = "required" if c.required else "optional"
                    st.caption(f"- {c.name}: {direction} {c.threshold} "
                               f"{c.unit} ({req})")



    # ---------------------------------------------------- experiments
    all_rows = store.ongoing() + store.finished(50)
    st.header("Experiments")
    if not all_rows:
        st.info("Nothing yet.")
        if st.button("🧪 Start your first experiment", type="primary"):
            start_dialog()
    for e in all_rows:
        ag = e["payload"].get("agent")
        if ag:
            status, _ = agent_row_status(e)
            icon, action = "🤖", "View pipeline"
        else:
            status = e["status"].replace("_", " ")
            icon, action = "🧑", "Resume →"
        with st.container(border=True):
            c1, c2 = st.columns([5, 4])
            c1.markdown(f"{icon} **{e['question'][:78]}**")
            c2.markdown(f"{chip_html(status)}  "
                        f"<span style='color:#6b6558;font-size:13px'>"
                        f"· {ago(e['updated_at'])}</span>",
                        unsafe_allow_html=True)
            c3, _ = st.columns([2, 6])
            with c3:
                if st.button(action, key=f"v_{e['id']}",
                             disabled=(status == "verdict recorded")):
                    if ag:
                        st.session_state["view_experiment"] = e["id"]
                        st.switch_page(PAGES["experiment"])
                    else:
                        resume_wizard(e)
                        st.switch_page(PAGES["wizard"])

    # ---------------------------------------------------- flywheel memory
    try:
        from bionexus.flywheel import Flywheel
        _fw = Flywheel()
        _negs = _fw.negative_summary(limit=8)
        if _negs:
            with st.expander(f"🚫 Ruled out ({len(_negs)} recent negatives — "
                             f"steers future portfolios)"):
                for n in _negs:
                    st.caption(f"- **{n['candidate']}** ({n['family']}, "
                               f"{n['assay']}): {n['outcome']}"
                               + (f" — observed {n['observed']:.1f} µM"
                                  if n.get("observed") else "")
                               + f" · {ago(n['ts'])}")
    except Exception:
        pass

# --------------------------------------------------------------------------
# VIEW: wizard (DMTA steps 1–6)
# --------------------------------------------------------------------------
_STEPS = ["Define Problem", "Design Experiment", "Readiness", "Execute",
          "Upload Results", "Analyze & Verdict"]


def _nav(current: int) -> None:
    cols = st.columns(len(_STEPS))
    for i, (col, name) in enumerate(zip(cols, _STEPS), 1):
        marker = "🟢" if i < current else "🔵" if i == current else "⚪"
        col.markdown(f"**{marker} {name}**" if i == current
                     else f"{marker} {name}")


def _goto(n: int) -> None:
    st.session_state.step = n
    st.rerun()


def wizard_view() -> None:
    _consume_goto("wizard")
    inject_css()
    step = st.session_state.get("step", 1)
    if step == 0 or step not in range(1, 7):
        st.switch_page(PAGES["overview"])
    st.title("🧬 BioNexus")
    _nav(step)
    st.button("← Overview", on_click=_go("overview"))

    # ---- STEP 1 — define problem
    if step == 1:
        st.header("1 · Define the problem")
        pdoc = program_cfg.load()
        st.caption(f"🎯 {program_cfg.gate_summary(pdoc)} — your hypothesis "
                   f"thresholds start from this program gate.")
        st.caption("What are you trying to show? A good claim is specific: "
                   "what intervention, in what system, measured how.")
        q = st.text_area("Scientific question", key="q",
                         placeholder="Does S62 phosphorylation cause "
                                     "c-Myc degradation?")
        col1, col2 = st.columns(2)
        target = col1.text_input("Target (protein/pathway)", "c-Myc")
        claim = col2.selectbox("Claim type", [c.value for c in ClaimType])
        if st.button("Continue →", type="primary", disabled=not q.strip()):
            st.session_state["problem"] = {
                "question": q.strip(), "target": target,
                "claim": ClaimType(claim)}
            st.session_state["exp_id"] = store.create(q.strip(), claim, target)
            _save("designing", problem=st.session_state["problem"])
            _goto(2)

    # ---- STEP 2 — design
    elif step == 2:
        st.header("2 · Design the experiment")
        p = st.session_state.get("problem") or {}
        st.info(f"**Question:** {p.get('question', '—')}")
        col1, col2 = st.columns(2)
        site = col1.text_input("Site / variant (if relevant)", "S62")
        half_life = col2.number_input("Target half-life (min)", 1, 9999, 120)
        edited_frac = st.checkbox("Readout measures edited fraction")
        mimetic = st.checkbox("Distinguishes real from mimetic phenotype")
        with st.expander("Make it falsifiable (optional — mechanistic, "
                         "refutable, cited hypotheses are preferred)",
                         expanded=False):
            mech = st.text_input("Mechanism — the causal story",
                                 key="w_mech",
                                 placeholder="Phosphorylation blocks the "
                                             "degron, stabilizing the protein")
            refute = st.text_input("Refuted if...", key="w_refute",
                                   placeholder="Non-phospho mimic also "
                                               "stabilizes")
            cite = st.text_input("Citation grounding it (PMID/DOI)",
                                 key="w_cite")
        controls = [c.strip() for c in
                    st.text_area("Controls (one per line)").split("\n")
                    if c.strip()]
        if st.button("← Back"):
            _goto(1)
        exp = ExperimentDefinition(
            scientific_question=p.get("question", "user experiment"),
            claim_type=p.get("claim", ClaimType.CAUSAL),
            intervention=Intervention(kind="user_defined",
                                      target=p.get("target", "user-target"),
                                      site=site or None),
            system=BiologicalSystem(cell_line="user",
                                    target_half_life_min=half_life),
            delivery=DeliveryConditions(method="user",
                                        per_cell_loading_measured=True),
            readout=ReadoutSpec(assay="user",
                                measures_edited_fraction=edited_frac,
                                distinguishes_modified_from_mimetic=mimetic),
            controls=controls)
        st.session_state["exp_def"] = exp
        if st.button("Check readiness →", type="primary"):
            review = review_experiment(exp)
            st.session_state["readiness"] = review
            extras = {"mechanism": st.session_state.get("w_mech", ""),
                      "refutation_condition": st.session_state.get("w_refute", ""),
                      "citation": st.session_state.get("w_cite", "")}
            if extras["citation"]:
                from bionexus import citations
                res = citations.verify(extras["citation"])
                extras["citation_status"] = res["status"]
                extras["citation_detail"] = res["detail"]
                if res["status"] == "verified":
                    st.toast(f"Citation verified: {res['detail']}", icon="📚")
                elif res["status"] == "invalid":
                    st.toast("Citation does not resolve — hypothesis penalized",
                             icon="⚠️")
            _save("designing", design_extras=extras,
                  exp_def=exp.model_dump(mode="json"),
                  readiness={"verdict": review.verdict.value,
                             "findings": [f.model_dump(mode="json")
                                          for f in review.findings]})
            _wprove(EventType.experiment_defined, {
                "statement": exp.scientific_question,
                "claim_type": exp.claim_type.value,
                "target": exp.intervention.target,
                "controls": exp.controls,
                "success_bar": program_cfg.gate_summary(), **extras})
            _goto(3)

    # ---- STEP 3 — readiness gate
    elif step == 3:
        st.header("3 · Readiness check")
        exp = st.session_state.get("exp_def")
        review = st.session_state.get("readiness")
        if not exp or not review:
            st.warning("Design the experiment first (step 2)")
            if st.button("← Back"):
                _goto(2)
        else:
            icon = {"ready": "✅", "ready_with_warnings": "⚠️",
                    "blocked": "❌"}
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
                             disabled=blocked):
                    _save("readiness_ok" if not blocked else "ready_blocked")
                    _wprove(EventType.experiment_readiness_reviewed, {
                        "verdict": review.verdict.value,
                        "blockers": [f.check for f in review.findings
                                     if f.severity == "blocker"],
                        "warnings": [f.check for f in review.findings
                                     if f.severity == "warning"]})
                    _goto(4)

    # ---- STEP 4 — execute
    elif step == 4:
        st.header("4 · Execute")
        exp = st.session_state.get("exp_def")
        st.info(f"**Question:** {exp.scientific_question}\n\n"
                f"**Claim:** {exp.claim_type.value} · "
                f"**Controls:** {len(exp.controls)}")
        route = st.radio("Execution route",
                         ["🧑 I run it at the bench — bring back the export",
                          "🤖 Agent executes — compounds go through the lab loop"],
                         horizontal=True)
        col1, col2 = st.columns(2)
        with col1:
            if st.button("← Back"):
                _goto(3)
        with col2:
            if route.startswith("🧑"):
                if st.button("I have results →", type="primary"):
                    _save("executing")
                    _wprove(EventType.stage_transition,
                            {"stage": "executing", "detail": "at the bench"})
                    _goto(5)
            else:
                comps = st.text_input("Compounds for the agent to test",
                                      placeholder="compound-a,compound-b")
                thr = st.number_input("Potency threshold (µM)", 0.001, 1000.0,
                                      program_cfg.gate_threshold_um())
                if st.button("🤖 Launch agent execution", type="primary",
                             disabled=not comps.strip()):
                    thr_s = f"{thr:g}"
                    cfg = {
                        "problem": {
                            "objective": exp.scientific_question,
                            "constraints": [{"name": "potency",
                                             "description": f"IC50 <= {thr_s} uM",
                                             "kind": "hard",
                                             "limit": float(thr),
                                             "unit": "uM"}],
                            "success_metric": "IC50 ranking consistent "
                                              "across replicates"},
                        "hypotheses": [
                            {"statement": f"{c.strip()[:24] if _looks_like_smiles(c) else c.strip()} tested — "
                                          f"{exp.scientific_question}",
                             "candidate": (c.strip()[:24]
                                           if _looks_like_smiles(c)
                                           else c.strip()),
                             **({"smiles": c.strip()}
                                if _looks_like_smiles(c) else {}),
                             "assay_type": exp.readout.assay
                             if exp.readout.assay != "user" else "binding",
                             "predicted": f"IC50 <= {thr_s}",
                             "predicted_value": float(thr),
                             "rationale": "",
                             "mechanism": (st.session_state.get(
                                 "w_mech") or ""),
                             "refutation_condition": (st.session_state.get(
                                 "w_refute") or ""),
                             "citation": (st.session_state.get(
                                 "w_cite") or "")}
                            for c in comps.split(",") if c.strip()],
                        "k": min(4, len([c for c in comps.split(",")
                                         if c.strip()])),
                        "autonomy": "gate",
                        "concentrations": ["0.5uM", "2uM", "10uM", "40uM"]}
                    cid = _spawn_agent_experiment(cfg, exp.scientific_question)
                    _save("executing", agent_link=cid)
                    _wprove(EventType.stage_transition,
                            {"stage": "handed-off",
                             "detail": f"agent experiment {cid}"})
                    st.session_state["view_experiment"] = cid
                    st.switch_page(PAGES["experiment"])

    # ---- STEP 5 — upload
    elif step == 5:
        st.header("5 · Upload instrument export")
        st.caption("Plate-reader export (CSV/TSV/XLSX) produced by the "
                   "experiment you defined.")
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
            _wprove(EventType.evaluation, {
                "artifact": "uploaded instrument export",
                "format": r.format, "n_wells": len(r.records),
                "z_prime": r.z_prime,
                "fits": {c: dd.get("ic50_um") for c, dd in
                         r.analysis["compounds"].items()}})
            _goto(6)
        r = st.session_state.get("plate_data")
        if r:
            st.success(f"Loaded: {r.format} · {len(r.records)} wells · "
                       f"Z' = {r.z_prime}")
        if st.button("← Back"):
            _goto(4)

    # ---- STEP 6 — analyze & verdict
    elif step == 6:
        st.header("6 · Analyze hits & verdict")
        r = st.session_state.get("plate_data")
        exp = st.session_state.get("exp_def")
        if not r:
            st.warning("Upload the instrument export (step 5)")
            if st.button("← Back"):
                _goto(5)
        else:
            import pandas as pd
            rows = [{"sample": s, "ic50_uM": dd.get("ic50_um"),
                     "ci_low": (dd.get("ic50_ci") or [None, None])[0],
                     "ci_high": (dd.get("ic50_ci") or [None, None])[1],
                     "points": dd.get("n_points"),
                     "fit": dd.get("fit_quality", "")}
                    for s, dd in r.analysis["compounds"].items()]
            st.dataframe(pd.DataFrame(rows), hide_index=True,
                         column_config={"ic50_uM": st.column_config.NumberColumn(
                             "IC50 (µM)", format="%.2f")})
            selected = st.session_state["selected"]
            for sample, data in r.analysis["compounds"].items():
                ic50 = data.get("ic50_um")
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**{sample}** — IC50 = "
                                f"{f'{ic50:.1f} µM' if ic50 else '> range'}")
                with col2:
                    if ic50 and st.checkbox("Hit", key=f"sel_{sample}",
                                            value=sample in selected):
                        if sample not in selected:
                            selected.append(sample)
                    elif sample in selected:
                        selected.remove(sample)
                pts = [(rr["conc_um"], rr["value"]) for rr in r.records
                       if rr.get("sample") == sample and not rr.get("control")]
                if pts:
                    st.markdown(dose_response_svg(pts, ic50=ic50,
                                ci=data.get("ic50_ci"),
                                title=sample), unsafe_allow_html=True)
            st.session_state["selected"] = selected

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
                                f"- MW: {s['mw_da']} Da · LogP: "
                                f"{s.get('logp', '?')} · TPSA: "
                                f"{s.get('tpsa', '?')}\n"
                                f"- Lipinski violations: "
                                f"{s['lipinski_violations']}\n"
                                f"- PAINS: {s['pains_alerts'] or 'none'}")
                        except Exception as e:
                            st.caption(f"ADMET unavailable: {e}")
                    with col2:
                        st.markdown("**Retrosynthesis**")
                        try:
                            rt = SimulatedRetrosynthesis().plan(smi)
                            st.markdown(f"- Feasible: "
                                        f"{'✅' if rt.feasible else '❌'} · "
                                        f"Steps: {rt.num_steps}")
                        except Exception as e:
                            st.caption(f"Retrosynthesis unavailable: {e}")

            st.subheader("Verdict")
            st.markdown(f"> **{exp.scientific_question}**")
            obs = st.radio("Observed outcome vs prediction",
                           ["supports hypothesis", "refutes hypothesis",
                            "inconclusive"], horizontal=True)
            if st.button("Record verdict", type="primary"):
                _save("verdict_recorded", verdict=obs,
                      selected_hits=st.session_state["selected"])
                ev = (EventType.hypothesis_validated if "supports" in obs
                      else EventType.hypothesis_invalidated
                      if "refutes" in obs else EventType.stage_transition)
                _wprove(ev, {"statement": exp.scientific_question,
                             "verdict": obs,
                             "hits": st.session_state["selected"],
                             "evidence": "uploaded instrument export"})
                st.toast(f"Verdict recorded — {obs}", icon="📓")
                st.success(f"Recorded: **{obs}** — hash-chained. Audit: "
                           f"`bn prove wizard/{st.session_state.get('exp_id')}`")
                if st.button("← Back to overview", on_click=_go("overview")):
                    st.session_state["step"] = 0
            if st.button("← Back"):
                _goto(5)


# --------------------------------------------------------------------------
# VIEW: experiment detail
# --------------------------------------------------------------------------
def experiment_view() -> None:
    _consume_goto("experiment")
    inject_css()
    st.button("← All experiments", on_click=_go("overview"))
    eid = st.session_state.get("view_experiment")
    row = store.get(eid) if eid else None
    if not row:
        st.info("No experiment selected — pick one from the list.")
        st.switch_page(PAGES["overview"])

    ag = row["payload"].get("agent")
    if ag:
        status, logf = agent_row_status(row)
        problem_id = _resolve_problem(ag, logf)
        if problem_id and problem_id != ag.get("problem_id"):
            store.link_problem(row["id"], problem_id)
        st.title(f"🤖 {row['question'][:70]}")
        st.markdown(chip_html(status), unsafe_allow_html=True)
        st.caption(f"agent-driven · autonomy: {ag.get('autonomy', 'act')} · "
                   f"updated {ago(row['updated_at'])}")
        if status == "running":
            st.info("In progress — this view refreshes as the agent works.")

        # metric tiles
        from bionexus.adapters.store.sqlite import SqliteProvenanceStore
        branch = f"problem/{problem_id}" if problem_id else None
        recs = (SqliteProvenanceStore("bionexus.db").branch_records(branch)
                if branch and Path("bionexus.db").exists() else [])
        n_hyp = sum(1 for r in recs
                    if r.event_type.value == "hypothesis_proposed")
        n_dec = sum(1 for r in recs if r.event_type.value in
                    ("hypothesis_validated", "hypothesis_invalidated"))
        n_runs = sum(1 for r in recs if r.event_type.value == "lab_run")
        m1, m2, m3 = st.columns(3)
        m1.metric("Hypotheses", n_hyp)
        m2.metric("Decided", n_dec)
        m3.metric("Lab runs", n_runs)
        st.caption(f"🎯 {program_cfg.gate_summary()} ▸ problem ▸ "
                   f"{n_hyp} hypotheses ▸ experiment `{row['id']}`")

        with st.expander("Lab narrative (hash-chained)", expanded=False):
            if branch and recs:
                import streamlit.components.v1 as components
                from bionexus.diary import build_diary_html
                components.html(build_diary_html(recs, branch),
                                height=640, scrolling=True)

        render_experiment_pipeline(logf, problem_id,
                                   running=(status == "running"),
                                   store=store, eid=row["id"])
    else:
        p = row["payload"]
        st.title(f"🧑 {row['question'][:70]}")
        chip(row["status"].replace("_", " "))
        st.caption(f"🎯 {program_cfg.gate_summary()} ▸ problem ▸ "
                   f"experiment `{row['id']}` · wizard-defined · updated "
                   f"{ago(row['updated_at'])}")
        exp_d = p.get("exp_def")
        if exp_d:
            exp = (exp_d if isinstance(exp_d, ExperimentDefinition)
                   else ExperimentDefinition.model_validate(exp_d))
            st.markdown(f"**Claim:** {exp.claim_type.value} · **target:** "
                        f"{exp.intervention.target} · **controls:** "
                        f"{len(exp.controls)}")
        rd = p.get("readiness")
        if rd:
            icon = {"ready": "✅", "ready_with_warnings": "⚠️",
                    "blocked": "❌"}.get(rd.get("verdict"), "")
            st.caption(f"readiness: {icon} {rd.get('verdict', '—')}")
        if p.get("verdict"):
            st.success(f"verdict: {p['verdict']}")
        if p.get("plate"):
            st.caption(f"plate: {p['plate'].get('n_wells')} wells · "
                       f"Z' {p['plate'].get('z_prime')}")
        if row["status"] != "verdict_recorded" and st.button("Resume →"):
            resume_wizard(row)
            st.switch_page(PAGES["wizard"])
        from bionexus.adapters.store.sqlite import SqliteProvenanceStore
        from bionexus.wizard_chain import wizard_branch
        if Path("bionexus.db").exists():
            srecs = SqliteProvenanceStore("bionexus.db").branch_records(
                wizard_branch(row["id"]))
            if srecs:
                st.subheader("📓 Lab narrative")
                st.caption(f"{len(srecs)} provenance records · hash-chained")
                for r in srecs:
                    d = r.decision or {}
                    st.markdown(f"- **{r.event_type.value.replace('_', ' ')}** "
                                f"· {json.dumps(d)[:140]}")


# --------------------------------------------------------------------------
# router
# --------------------------------------------------------------------------
PAGES = {
    "overview": st.Page(overview_view, title="Overview", icon="🧬",
                        default=True, url_path="overview"),
    "wizard": st.Page(wizard_view, title="Wizard", icon="🧪",
                      url_path="wizard"),
    "experiment": st.Page(experiment_view, title="Experiment", icon="🔬",
                          url_path="experiment"),
}


def _key_new() -> None:
    st.session_state["open_new"] = True


if hasattr(st, "keymap"):        # Streamlit >= 1.44 builds only
    st.keymap("n", _key_new)
    st.keymap("o", lambda: st.session_state.update({"goto": "overview"}))

with st.sidebar:
    st.caption(f"store: `{Path('.data/wizard.db')}` · provenance: "
               f"`bionexus.db` · press **n** for new experiment")

nav = st.navigation(list(PAGES.values()))
nav.run()
