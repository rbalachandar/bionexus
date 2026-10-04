# BioNexus

Agentic drug-discovery framework: pluggable models/labs/sandboxes behind five
core interfaces (ModelProvider, BioTool, LabAdapter, Sandbox, ProvenanceStore),
with a FastAPI + React workbench as the scientist surface.

## Continue work here
- **`docs/ROADMAP.md` — the live TODO plan**. Epistemic P0s (uncertainty-aware
  verdicts, small-n stats, provenance physics, governance-on-agent-surfaces)
  are CLOSED (Oct 2026 review — `docs/REVIEW-2026-10.md`). The frontier is now
  **Scientist Utility** (S-T0: prospective real-data case study, real-plate
  ingestion, Make-as-gate). Start there in any new session; update status
  boxes as you complete items.
- `docs/PLAN.md` — original design (principles P1–P8)
- `docs/QUICKSTART.md` — scientist path · `README.md` — product overview

## Commands
```sh
.venv/bin/python -m pytest -q          # all tests (256 green as of this writing)
make test                              # same suite via the Makefile
make api                               # backend + built SPA on :8000
make api-dev                           # backend only, auto-reload
make web-dev                           # Vite SPA on :5173 (proxies /api)
python -m bionexus.cli auto --template dose-response-screen \
  --field compounds=a,b --field threshold=20 --autonomy act --yes   # e2e sim
.venv/bin/python -m bionexus.cli eval  # offline eval suite -> evals/leaderboard.md
```

## Layout (hot files)
- `src/bionexus/api/app.py` — FastAPI routes · `web/src/` — React SPA routes
  (Workspace / Program / Experiment / Wizard) · `src/bionexus/views.py` —
  the read-model the API serves (pipeline cards, verdict tally, rollups)
- `src/bionexus/core/hypothesis.py` — Hypothesis lifecycle + **verdict logic**
- `src/bionexus/watch.py` — auto-analysis agent (+ orthogonal confirmation
  agreement check) · `autoloop.py` — campaign flow
- `src/bionexus/diary.py` — swimlane lab narrative · `program.py` — TPP state
- `src/bionexus/adapters/store/sqlite.py` — hash-chained provenance (engine
  triggers + `verify_chain()` recompute on read)
- `src/bionexus/wizard_store.py` / `wizard_chain.py` — experiment registry +
  wizard provenance (`.data/wizard.db`, `bionexus.db`)
- `src/bionexus/adapters/` — everything pluggable; tests are the contract

## Conventions
- pydantic contracts in `core/contracts` are the source of truth (no YAML)
- Simulated data must be labeled simulated; verdicts must be honest about
  uncertainty — a CI straddling the gate abstains, and READING a verdict is
  as sacred as computing it (payload-driven, recency-wins; see the review)
- Conventional commits; keep `pytest -q` green before pushing
