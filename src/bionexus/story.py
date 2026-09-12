"""The Story page — one real campaign, start to finish.

Not a brochure: the narrative is an actual recorded run (assets/story/
demo-run.json — regenerate with scripts/capture_story_run.py), and every
figure is computed by bionexus.figures from the same code the run used.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import streamlit as st

from bionexus.ui_kit import inject_css

RUN_FILE = Path("assets/story/demo-run.json")


def _run() -> dict:
    try:
        return json.loads(RUN_FILE.read_text())
    except Exception:
        return {}


def _diagram(path: str, caption: str) -> None:
    """SVGs with <defs>/<style> get stripped by markdown sanitization;
    embed as data-URI images instead — always renders."""
    try:
        b64 = base64.b64encode(Path(path).read_bytes()).decode()
        st.markdown(
            f"<img src='data:image/svg+xml;base64,{b64}' "
            f"style='width:100%;max-width:1040px;border-radius:12px;"
            f"border:1px solid #30363d'>"
            f"<p style='color:#8a8272;font-size:13px'>{caption}</p>",
            unsafe_allow_html=True)
    except Exception:
        st.caption(f"(diagram missing: {path})")


def render() -> None:
    inject_css()
    run = _run()
    st.title("📖 Documentation")
    tab_framework, tab_works, tab_trust, tab_start = st.tabs(
        ["The framework", "Does it work?", "Can you trust it?",
         "Get started"])

    # ------------------------------------------------ FRAMEWORK
    with tab_framework:
        st.markdown("Five interfaces, pydantic-only core, everything else an "
                    "adapter:")
        st.dataframe([
            {"interface": "ModelProvider",
             "contract": "generate / predict over tool invocations",
             "adapters": "Anthropic, OpenAI-compatible (vLLM, ollama), stub"},
            {"interface": "LabAdapter",
             "contract": "protocols in, evidence out — behind the gateway",
             "adapters": "SimulatorLab, imaging, Opentrons, PlateReaderShare, "
                         "SiLA 2, HCS, LC-MS, arm scheduler, MHS driver"},
            {"interface": "BioTool",
             "contract": "local computation, never physical action",
             "adapters": "RDKit ADMET, Morgan+RF, AlphaGenome Atlas, "
                         "retrosynthesis"},
            {"interface": "Sandbox",
             "contract": "snapshot / fork / resume state",
             "adapters": "local, docker, OpenSandbox, AgentENV"},
            {"interface": "ProvenanceStore",
             "contract": "append-only hash-chained records",
             "adapters": "SQLite (default), postgres, s3-worm (roadmap)"},
        ], hide_index=True)
        st.markdown("#### One campaign, step by step — with this run's output")
        steps = [
            ("problem definition", "problem + constraints + environment "
             "(sim-v1, seed 2) recorded as provenance root"),
            ("hypothesis proposal", "4 hypotheses with mechanism, refutation, "
             "citation — one citation caught fabricated"),
            ("portfolio filter", "k=2 slots; +0.20 explanatory bonus visible "
             "in the recorded reasons"),
            ("readiness review", "gate-honesty checks active (CI vs bar)"),
            ("safety gate", "BX-1 refused: 3 toxicophores [safety-rules-v1]"),
            ("advisory tier", "BB-1's acrylamide flagged despite declared "
             "intent — recorded, not hidden"),
            ("lab execution", "runs sim-2-001…004 on SimulatorLab, Z′ 0.93"),
            ("evidence", "exports noticed automatically; Hill fit + bootstrap "
             "CI + CI band on the curve"),
            ("verdict + confirmation", "2× inconclusive by gate honesty; "
             "0 overclaims"),
            ("record", "21 hash-chained records; replayable with "
             "`bn reproduce`"),
        ]
        st.dataframe([{"#": i + 1, "step": a, "what this run did": b}
                      for i, (a, b) in enumerate(steps)],
                     hide_index=True)
        _diagram("diagrams/svg/07-problem-loop.svg",
                 "Problem → portfolio → autonomous test-and-confirm, with "
                 "the provenance spine.")
        _diagram("diagrams/svg/04-wetlab-roundtrip.svg",
                 "The wet-lab round trip: protocol through the safety "
                 "boundary, instruments, and back as evidence.")

    # ------------------------------------------------ DOES IT WORK
    with tab_works:
        import subprocess
        rp = Path("evals/results.json")
        c1, c2 = st.columns([4, 1])
        c1.caption("Deterministic, offline, in CI on every commit. The run "
                   "you just read about exercises tasks 1–3 live.")
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
                           "what it proves": r["notes"][:110]}
                          for r in rows], hide_index=True)
            st.caption(f"Last run "
                       f"{datetime.datetime.fromtimestamp(rp.stat().st_mtime):%Y-%m-%d %H:%M}"
                       f" · mean {sum(r['score'] for r in rows)/len(rows):.3f}")
        st.markdown("#### Against real published science")
        k1, k2, k3 = st.columns(3)
        k1.markdown("**AZ3246 / HPK1 · JMC 2025**\n\nPost-cutoff blind "
                    "reproduction. Clean by self-report *and* never-published "
                    "variant probes; agent-derived pyrazine-carboxamide "
                    "hypothesis, blinded ranking ρ=+0.42 vs RF's +0.08.")
        k2.markdown("**Multi-paper sweep · 2025**\n\nBlind chemotype ID 4/4. "
                    "The counterweight we also publish: no enrichment claim "
                    "survives bootstrap CIs + BH at n=31–67.")
        k3.markdown("**EGFR tyrphostins · 1989**\n\nKept with its "
                    "contamination qualification — flagged prior exposure "
                    "ships as a limitation, not a footnote.")
        st.caption("Study inputs are frozen: checksummed fixtures, "
                   "`bn fixtures verify` in CI.")
        from bionexus import figures
        st.markdown("#### Why adaptive dosing exists")
        st.markdown(figures.get("recovery"), unsafe_allow_html=True)
        st.caption("A fixed 0.5/2/10/40 series cannot resolve compounds near "
                   "the gate — they stay inconclusive (as they should). "
                   "Bayesian well placement reaches ~4× more confident "
                   "decisions at 3 wells: `bn auto … --dose-design adaptive`.")
        st.markdown(figures.get("stability"), unsafe_allow_html=True)
        st.caption("Abstention rises exactly where evidence is thin — "
                   "near the gate. An agent that never says 'inconclusive' "
                   "is not more useful; it is lying.")

    # ------------------------------------------------ TRUST
    with tab_trust:
        st.markdown("**Deterministic rules hold the floor. AI may only "
                    "tighten a gate, never loosen one. Humans adjudicate — "
                    "and their decisions, not the model's confidence, promote "
                    "new rules.**")
        try:
            rules = json.loads(Path(
                "src/bionexus/adapters/bio/safety_rules.json").read_text())
            st.caption(f"{rules['version']} · {len(rules['alerts'])} alerts · "
                       "the version rides in every refusal and record")
            st.dataframe([{"alert": a["name"], "severity": a["severity"],
                           "why": a["note"]} for a in rules["alerts"]],
                         hide_index=True)
        except Exception:
            st.caption("(rule file missing)")
        st.markdown(
            "- **Citations** verified against PubMed; fabricated ranks below "
            "silence (see the run: AA-2)\n"
            "- **DURC**: select-agent campaigns refused before any work, "
            "recorded\n"
            "- **Faults**: adversarial instrument files degrade to "
            "'unreadable, no verdicts changed'\n"
            "- **Inputs**: sanitized labels — injection-shaped sample names "
            "provably cannot reach the gate\n"
            "- **Replay & seal**: `bn reproduce` diffs verdicts from the "
            "recorded environment; `bn anchor` publishes a Merkle root; "
            "`bn prove --eln` exports to the lab notebook")
        with st.expander("Evidence panels: what a verdict is made of"):
            from bionexus import figures
            st.markdown(figures.get("evidence"), unsafe_allow_html=True)

    # ------------------------------------------------ START
    with tab_start:
        st.markdown(
            "```sh\n"
            "pip install bionexuslab\n"
            "bn eval                       # watch the claims get scored\n"
            "bn auto --template dose-response-screen \\\n"
            "    --field compounds=gefitinib,erlotinib --field threshold=20\n"
            "bn auto campaign.json --dose-design adaptive   # the fix from "
            "this story\n"
            "streamlit run Overview.py     # this workbench\n"
            "```")
        st.dataframe([
            {"autonomy": "observe",
             "behavior": "reads, fits, recommends — submits nothing"},
            {"autonomy": "gate",
             "behavior": "every submission waits for your Approve"},
            {"autonomy": "act",
             "behavior": "autonomous within safety, budgets, confirmations"},
        ], hide_index=True)
        st.caption("Instruments: Opentrons, plate-reader shares, SiLA 2, "
                   "LC-MS, HCS — plus device cards (`bn connect describe`). "
                   "Agent Skills + MCP expose the toolset to Claude, Cursor "
                   "or your own loop.")
