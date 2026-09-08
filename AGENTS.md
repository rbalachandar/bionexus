# BioNexus

Agentic drug-discovery framework: pluggable models/labs/sandboxes behind five
core interfaces (ModelProvider, BioTool, LabAdapter, Sandbox, ProvenanceStore),
with a Streamlit workbench as the scientist surface.

## Continue work here
- **`docs/ROADMAP.md` — the live TODO plan** (frontier-review priorities:
  P0 uncertainty-aware verdicts, P0 small-n stats, P1 eval harness, ...).
  Start there in any new session; update status boxes as you complete items.
- `docs/PLAN.md` — original design (principles P1–P8)
- `docs/QUICKSTART.md` — scientist path · `README.md` — product overview

## Commands
```sh
.venv/bin/python -m pytest -q          # all tests (31+ green)
.venv/bin/streamlit run Overview.py    # workbench on :8501
python -m bionexus.cli auto --template dose-response-screen \
  --field compounds=a,b --field threshold=20 --autonomy act --yes   # e2e sim
```

## Layout (hot files)
- `Overview.py` — Streamlit router: Overview / Wizard / Experiment views
- `src/bionexus/webview.py` — shared experiment rendering (pipeline cards)
- `src/bionexus/core/hypothesis.py` — Hypothesis lifecycle + **verdict logic**
- `src/bionexus/watch.py` — auto-analysis agent (+ orthogonal confirmation
  agreement check) · `autoloop.py` — campaign flow
- `src/bionexus/diary.py` — swimlane lab narrative · `program.py` — TPP state
- `src/bionexus/wizard_store.py` / `wizard_chain.py` — experiment registry +
  wizard provenance (`.data/wizard.db`, `bionexus.db`)
- `src/bionexus/adapters/` — everything pluggable; tests are the contract

## Conventions
- pydantic contracts in `core/contracts` are the source of truth (no YAML)
- Simulated data must be labeled simulated; verdicts must be honest about
  uncertainty (the current gap — see ROADMAP P0)
- Conventional commits; keep `pytest -q` green before pushing
