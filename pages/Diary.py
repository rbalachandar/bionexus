"""Diary page — full lab-notebook view for a provenance branch."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="BioNexus — Diary", page_icon="📓", layout="wide")

from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.diary import build_diary_html

st.title("📓 Lab Diary")
st.caption("Hash-chained narrative record — verify any entry with `bn prove`.")

if not Path("bionexus.db").exists():
    st.info("No provenance database yet — run an experiment first.")
    st.stop()

store = SqliteProvenanceStore("bionexus.db")
branches = [b for b in store.branches() if b.startswith(
    ("problem/", "campaign-root", "branch-root", "case-study", "blind-paper",
     "autonomous"))]

if not branches:
    st.info("No diary branches yet.")
    st.stop()

default = st.session_state.get("diary_branch")
idx = branches.index(default) if default in branches else 0
branch = st.selectbox("Branch", branches, index=idx,
                      format_func=lambda b: b)
recs = store.branch_records(branch)
components.html(build_diary_html(recs, branch), height=760, scrolling=True)
