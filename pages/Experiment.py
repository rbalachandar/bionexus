"""Experiment page — full detail for one experiment (state + provenance)."""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import streamlit as st

st.set_page_config(page_title="BioNexus — Experiment", page_icon="🧬",
                   layout="wide")

from bionexus.wizard_store import WizardStore
from bionexus.webview import render_experiment_pipeline

store = WizardStore()

if st.button("← All experiments"):
    st.switch_page("app.py")

eid = st.session_state.get("view_experiment")
row = store.get(eid) if eid else None
if not row:
    st.info("No experiment selected — pick one from the list.")
    st.stop()

agent = row["payload"].get("agent")


def agent_status(row: dict) -> tuple[str, Path]:
    ag = row["payload"].get("agent") or {}
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
    if row["status"] == "executing":
        if logf.exists() and time.time() - logf.stat().st_mtime < 300:
            return "running", logf
        return "interrupted", logf
    return row["status"].replace("_", " "), logf


if agent:
    status, logf = agent_status(row)
    problem_id = agent.get("problem_id")
    if not problem_id and logf.exists():
        m = re.findall(r"problem (prob-\w+):", logf.read_text(errors="replace"))
        if m:
            problem_id = m[-1]
            store.link_problem(row["id"], problem_id)
    st.title(f"🤖 {row['question'][:70]}")
    st.caption(f"experiment `{row['id']}` · agent-driven · "
               f"autonomy: {agent.get('autonomy', 'act')} · {status}" +
               (f" · branch `problem/{problem_id}`" if problem_id else ""))
    if status == "running":
        st.info("This experiment is in progress — the view refreshes as the "
                "agent works.")
    render_experiment_pipeline(logf, problem_id, running=(status == "running"),
                               store=store, eid=row["id"])
else:
    from bionexus.readiness import ExperimentReadinessReview, ReviewVerdict
    p = row["payload"]
    st.title(f"🧑 {row['question'][:70]}")
    st.caption(f"experiment `{row['id']}` · wizard-defined · "
               f"{row['status'].replace('_', ' ')} · updated "
               f"{time.strftime('%m-%d %H:%M', time.localtime(row['updated_at']))}")
    exp_d = p.get("exp_def")
    if exp_d:
        from bionexus.experiment import ExperimentDefinition
        exp = (exp_d if isinstance(exp_d, ExperimentDefinition)
               else ExperimentDefinition.model_validate(exp_d))
        st.markdown(f"**Claim:** {exp.claim_type.value} · "
                    f"**target:** {exp.intervention.target} · "
                    f"**controls:** {len(exp.controls)}")
    rd = p.get("readiness")
    if rd:
        icon = {"ready": "✅", "ready_with_warnings": "⚠️", "blocked": "❌"}.get(
            rd.get("verdict"), "")
        st.caption(f"readiness: {icon} {rd.get('verdict', '—')}")
    if p.get("verdict"):
        st.success(f"verdict: {p['verdict']}")
    if row["status"] != "verdict_recorded":
        if st.button("Resume this experiment →"):
            from bionexus.webview import resume_wizard
            resume_wizard(row)
    if p.get("plate"):
        st.caption(f"plate: {p['plate'].get('n_wells')} wells · "
                   f"Z' {p['plate'].get('z_prime')}")
