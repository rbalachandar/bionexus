"""The Story page — the framework's own narrative, computed not copywritten.

Rendering lives here (not in the router script) so it is importable and
testable in isolation; Overview.py wraps it with navigation plumbing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

from bionexus.ui_kit import inject_css


def render() -> None:
    inject_css()
    st.title("📖 The BioNexus story")
    st.caption("Every number here is computed from the shipped code or read "
               "from the eval suite — not hand-typed marketing.")
    tab_thesis, tab_framework, tab_works, tab_trust, tab_start = st.tabs(
        ["The thesis", "The framework", "Does it work?", "Can you trust it?",
         "Get started"])

    with tab_thesis:
        st.markdown(
            "<p style='font-size:19px;max-width:720px'>Most agent demos stop "
            "at talking. BioNexus is built so you can let it act in a lab: "
            "<b>hypotheses, safety-gated experiments, honest verdicts against "
            "pre-registered criteria, tamper-evident provenance.</b> Drug "
            "discovery first, domain-agnostic core.</p>",
            unsafe_allow_html=True)
        st.markdown("#### Three principles")
        c1, c2, c3 = st.columns(3)
        c1.markdown("**Safety first, and it checks molecules.**\n\n"
                    "The only path from an agent to a lab is the gateway: a "
                    "policy engine the agent cannot modify or approve itself, "
                    "budgets that cap consumption, toxicophore screening of "
                    "declared structures, dual-use refusal. All recorded.")
        c2.markdown("**Tiered trust.**\n\n"
                    "Deterministic rules hold the floor. AI may add a flag or "
                    "demand human review, never clear a refusal. Citations "
                    "are verified: a fabricated reference ranks below "
                    "silence.")
        c3.markdown("**Everything auditable.**\n\n"
                    "Hash-chained records, Merkle anchoring, replay with "
                    "`bn reproduce`, export to your ELN. The record is the "
                    "product.")
        from bionexus import figures
        st.markdown("### How fast does the loop reach a defensible decision?")
        st.markdown(figures.get("recovery"), unsafe_allow_html=True)
        st.caption("Adaptive 3-well Bayesian dosing vs the fixed 4-point "
                   "series vs random doses — 60 simulated compounds, "
                   "computed by bionexus.figures (same math as the eval "
                   "tasks).")

    with tab_framework:
        st.markdown("The core depends on **pydantic only**. Everything else "
                    "is an adapter behind one of five interfaces:")
        st.dataframe([
            {"interface": "ModelProvider",
             "contract": "generate / predict over tool invocations",
             "adapters": "Anthropic, OpenAI-compatible (vLLM, ollama), stub"},
            {"interface": "LabAdapter",
             "contract": "protocols in, evidence out — behind the gateway",
             "adapters": "SimulatorLab, imaging simulator, Opentrons, "
                         "PlateReaderShare, SiLA 2, HCS microscope, LC-MS, "
                         "arm scheduler, MHS driver"},
            {"interface": "BioTool",
             "contract": "local computation, never physical action",
             "adapters": "RDKit ADMET, Morgan+RF, AlphaGenome Atlas (AVI), "
                         "retrosynthesis"},
            {"interface": "Sandbox",
             "contract": "snapshot / fork / resume state",
             "adapters": "local, docker, OpenSandbox, AgentENV"},
            {"interface": "ProvenanceStore",
             "contract": "append-only hash-chained records",
             "adapters": "SQLite (default), postgres, s3-worm (roadmap)"},
        ], hide_index=True)
        st.markdown("#### One campaign, step by step")
        st.dataframe([
            {"#": 1, "who": "problem definition",
             "enforced": "problem, constraints and the execution "
                         "environment (lab+version+seed) recorded as the "
                         "provenance root"},
            {"#": 2, "who": "hypothesis agent + skills",
             "enforced": "schema validated, deduped; mechanism, refutation "
                         "condition and a verified citation earn portfolio "
                         "edge"},
            {"#": 3, "who": "portfolio selector / policy",
             "enforced": "diversity cap, flywheel priors; every accept/reject "
                         "recorded with its reason"},
            {"#": 4, "who": "readiness review",
             "enforced": "BLOCKS experiments whose result would be "
                         "uninterpretable"},
            {"#": 5, "who": "safety engine + advisory tier",
             "enforced": "BSL, reagents, steps, toxicophores in declared "
                         "structures, DURC; advisory may escalate, never "
                         "clears"},
            {"#": 6, "who": "LabAdapter via gateway",
             "enforced": "run, instrument+version, parameters recorded; "
                         "approval queue in gate mode"},
            {"#": 7, "who": "device monitor",
             "enforced": "exports noticed automatically; unreadable files "
                         "flagged, never crash the loop"},
            {"#": 8, "who": "labread + fitter",
             "enforced": "3-param Hill with bootstrap CIs, Z′ QC, CI bands"},
            {"#": 9, "who": "criteria + confirmation",
             "enforced": "CI straddling the gate ⇒ inconclusive; orthogonal "
                         "confirmation verifies the verdict's DIRECTION"},
            {"#": 10, "who": "provenance store",
             "enforced": "hash chain, Merkle anchor, bn reproduce, ELN "
                         "export"},
        ], hide_index=True,
            column_config={"#": st.column_config.NumberColumn(width="small")})
        for label, svg in (("problem → portfolio → autonomous loop",
                            "diagrams/svg/07-problem-loop.svg"),
                           ("the wet-lab round trip",
                            "diagrams/svg/04-wetlab-roundtrip.svg")):
            with st.expander(f"Diagram · {label}"):
                try:
                    st.markdown(Path(svg).read_text(), unsafe_allow_html=True)
                except Exception:
                    st.caption("(diagram file missing)")

    with tab_works:
        import subprocess
        rp = Path("evals/results.json")
        c1, c2 = st.columns([4, 1])
        c1.caption("Deterministic, offline, runs in CI on every commit.")
        if c2.button("▶ Run eval suite", disabled=not rp.exists()):
            with st.spinner("Scoring the claims (≈40s)…"):
                subprocess.run([sys.executable, "-m", "bionexus.cli", "eval"],
                               capture_output=True, timeout=300)
            st.rerun()
        if rp.exists():
            import datetime
            rows = json.loads(rp.read_text())
            st.dataframe([{"task": r["task"], "score": r["score"],
                           "pass": "✅" if r["passed"] else "❌",
                           "evidence": r["notes"][:110]} for r in rows],
                         hide_index=True)
            st.caption(f"Last run "
                       f"{datetime.datetime.fromtimestamp(rp.stat().st_mtime):%Y-%m-%d %H:%M}"
                       f" · mean {sum(r['score'] for r in rows) / len(rows):.3f}")
        st.markdown("#### Case studies on real papers")
        k1, k2, k3 = st.columns(3)
        k1.markdown("**AZ3246 / HPK1 · JMC 2025**\n\nPost-cutoff blind "
                    "reproduction. Clean by self-report *and* never-published "
                    "variant probes. Agent derived the pyrazine-carboxamide "
                    "hypothesis from structures alone; blinded ranking "
                    "ρ = **+0.42** vs a trained RF's +0.08.")
        k2.markdown("**Multi-paper sweep · ChEMBL 2025**\n\nBlind chemotype ID "
                    "on 4/4 papers. The honest counterweight: **no enrichment "
                    "claim survives** bootstrap CIs + BH at n=31–67 (best "
                    "EF's CI spans 0.0–6.98). Reported as such.")
        k3.markdown("**EGFR tyrphostins · 1989**\n\nThe original blind "
                    "reproduction, kept with its contamination qualification: "
                    "when a probe says the model has prior exposure, the "
                    "result ships flagged, not dropped.")
        st.caption("Case-study inputs are frozen: gzip checksummed fixtures, "
                   "verified in CI (`bn fixtures verify`).")

    with tab_trust:
        st.markdown(
            "**Trust is tiered, and the tiers are asymmetric:** deterministic "
            "rules hold the floor; AI may only tighten a gate, never loosen "
            "one; humans adjudicate, and their decisions — not the model's "
            "confidence — promote new rules.")
        st.markdown("#### The deterministic floor: versioned structural alerts")
        try:
            rules = json.loads(Path(
                "src/bionexus/adapters/bio/safety_rules.json").read_text())
            st.caption(f"{rules['version']} · {len(rules['alerts'])} alerts · "
                       f"the rule version rides in every refusal and every "
                       f"provenance record")
            st.dataframe([{"alert": a["name"], "severity": a["severity"],
                           "why": a["note"]} for a in rules["alerts"]],
                         hide_index=True,
                         column_config={"severity":
                                        st.column_config.TextColumn(
                                            width="small")})
        except Exception:
            st.caption("(rule file missing)")
        st.markdown("#### Enforcement examples, all in CI")
        st.markdown(
            "- **Citations** resolved against PubMed; fabricated ⇒ ranked "
            "below a bare hypothesis\n"
            "- **DURC**: campaigns naming select agents are refused before "
            "any work, and the refusal is recorded\n"
            "- **Faults**: junk/adversarial instrument files degrade to "
            "'unreadable, no verdicts changed'\n"
            "- **Inputs**: instrument labels are sanitized data — an "
            "injection-shaped sample name provably cannot reach the gate\n"
            "- **Replay**: `bn reproduce` replays the recorded environment and "
            "diffs verdicts; `bn anchor` seals the store with a Merkle root "
            "publishable somewhere you do not control")
        with st.expander("Evidence panels: what a verdict is made of"):
            from bionexus import figures
            st.markdown(figures.get("evidence"), unsafe_allow_html=True)
            st.markdown(figures.get("stability"), unsafe_allow_html=True)
            st.caption("Clear hit, narrow margin (labeled as such), clear "
                       "miss — CI bands from the bootstrap fitter. Below: "
                       "abstention rises naturally near the gate; the system "
                       "abstains where the evidence is thin.")

    with tab_start:
        st.markdown(
            "```sh\n"
            "pip install bionexuslab\n"
            "bn eval                       # watch the claims get scored\n"
            "bn auto --template dose-response-screen \\\n"
            "    --field compounds=gefitinib,erlotinib --field threshold=20\n"
            "streamlit run Overview.py     # this workbench\n"
            "```")
        st.dataframe([
            {"autonomy": "observe",
             "behavior": "reads, fits, recommends — submits nothing"},
            {"autonomy": "gate",
             "behavior": "every lab submission waits for your Approve "
                         "('Awaiting your decision')"},
            {"autonomy": "act",
             "behavior": "autonomous within the safety engine, budgets and "
                         "confirmations"},
        ], hide_index=True)
        st.caption("Instruments: Opentrons, plate-reader shares, SiLA 2, "
                   "LC-MS, HCS microscopes — plus device cards "
                   "(`bn connect describe`) for what manuals don't say. "
                   "Agent Skills + MCP expose the toolset to Claude, Cursor "
                   "or your own loop.")
