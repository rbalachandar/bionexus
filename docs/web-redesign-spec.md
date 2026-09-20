# Web Redesign Spec — React/TS Frontend + FastAPI Backend

Status: **approved plan** (this document is the alignment record).
Decisions locked with the product owner:

1. API lives in `src/bionexus/api/` (ships in the package).
2. Guided wizard: all 6 steps ported to React before hard-cut.
3. Evidence curves: client-side rendering is the target; SVG endpoint
   ships first as fallback/export.
4. Dev: uvicorn :8000 + Vite :5173 (proxy). Prod: uvicorn serves the
   built SPA on :8000.
5. SSE (REST + SSE), multi-user-ready service; auth deferred.
6. Hard-cut to React once workspace + experiment pages are ready
   (wizard ported within P2 before cut).

## Goals

- Replace Streamlit with React/TS SPA + FastAPI. Kill the framework-
  ceiling problems (no buttons in tree nodes, fragment dim-flash,
  dialog lifecycle, stale closures, session loss on refresh).
- Python engine untouched: wizard store, program, autoloop, provenance,
  reviewer, governance, assays. The API imports it directly.

## Non-goals (this phase)

Auth, Postgres, multi-node, changes to campaign/provenance semantics.

## Feature inventory (parity targets)

- Program form: name, objective, modality dropdown (6 packs + Other),
  metric/unit/direction/gate, execution mode (locked when linked
  experiments exist), launch settings (autonomy, top-k, DMTA rounds,
  optional candidates). Launch spawns the campaign directly.
- Workspace: per-program trees (program -> Autonomous campaign ->
  problem root -> sub-problems -> leaves), campaigns/guided groups for
  unlinked rows, status tallies, retired-tree filtering, Archived.
- Experiment page: title/status, program strip, campaign-spec strip
  (objective/constraints/k/rounds/autonomy/candidate policy, provenance
  precedence), Hypothesis Pipeline cards (candidate/statement,
  mechanism, citation badge, refutation, gate, verdict+CI+margin, round
  attribution, state), DMTA chips + rounds table + verdict tally,
  "The record of this run" (portfolio, gates/refusals, make, evidence,
  verdicts, reviewer v1 + LLM advisory, trust), Trace log (live, last).
- Wizard guided steps 1-6 (problem, design, readiness, execute,
  upload, analyze/verdict).
- Approvals inbox; governance halt banner; safety-rule badges.
- Program delete: deferred (soft-delete design later).

## Architecture

```
web/                      React 18 + TS strict + Vite + TanStack Query v5
                          + Tailwind (docs/BRAND.md tokens) + lucide icons
src/bionexus/api/         FastAPI: routers (programs, experiments,
                          wizard, approvals, system), sse.py broker,
                          events.py store-append hook
src/bionexus/views.py     pure read-models extracted from webview.py /
                          narrative.py (no streamlit imports)
engine modules            unchanged; API imports them in-process
```

One uvicorn process, SQLite WAL, single writer via existing
WizardStore lock. Campaign subprocesses unchanged (`bn auto`,
`BN_PROGRAM` env).

## Data model delta

```sql
CREATE TABLE api_events (          -- SSE fan-out + reconnect replay
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  topic TEXT, kind TEXT, payload TEXT, created_at REAL
);
CREATE TABLE wizard_sessions (     -- guided wizard state (P2.3)
  id TEXT PRIMARY KEY, doc TEXT NOT NULL, step INTEGER,
  created_at REAL, updated_at REAL
);
```

Read models (response shapes): ProgramOut (with links + tree),
ExperimentOut (row + program strip + spec + merged objective/
constraints + DMTA counts + rounds), PipelineCardOut (state machine:
proposed/selected/in_lab/confirmed/validated/refuted/inconclusive/
not_selected/refused), TraceOut, NarrativeOut. Precedence rule:
provenance `problem_defined` overrides campaign_specs for
objective/constraints; spec always supplies k/rounds/autonomy/
candidate policy.

## API v1

```
GET  /api/programs                          ProgramOut[]
POST /api/programs                          create/update (mode-lock)
POST /api/programs/{slug}/launch            -> {eid} (spawn + link)
GET  /api/experiments                       ExperimentOut[]
GET  /api/experiments/{eid}                 detail (merged)
GET  /api/experiments/{eid}/pipeline        PipelineCardOut[]
GET  /api/experiments/{eid}/trace           TraceOut
GET  /api/experiments/{eid}/record          NarrativeOut
GET  /api/experiments/{eid}/evidence.svg    dose-response SVG (P1)
POST /api/experiments/{eid}/archive
GET  /api/approvals | POST /api/approvals/{id}/approve|deny
GET  /api/halt | POST /api/halt
GET  /api/system/health | /api/system/modalities
POST /api/wizard/sessions                   -> {sid}
GET/PUT /api/wizard/sessions/{sid}/step/{1..6}
GET  /api/events?topics=...                 SSE (Last-Event-ID replay)
```

SSE events: `status {eid,status}`, `records {eid,branch,new_count}`,
`log {eid,appended}`, `workspace {kind}`. Sources: wizard-store append
hook (in-process), pid poll (2s), log tail. FE: TanStack Query +
EventSource; `records` -> invalidate that experiment's queries. No
client timers.

## Launch flow (P2.2)

Load program -> mode-lock check (409) -> build cfg (problem from
objective/constraints via coerce_assay_type; hypotheses from
candidates or hypothesis_source=agent) -> spawn `bn auto` with
BN_PROGRAM -> register_agent + set_campaign_spec + link_leaf -> SSE
fire -> return {eid}.

## Phases & tasks (27)

### P0 — read-models + API skeleton (risk carrier)
- P0.1 views.py foundation: row_status, resolve_problem, leaf_pid/
  pid_aliases/has_doubled_branch, round_markers, dmta_counts,
  problem_trees — pure, JSON-able, unit-tested. [done in this commit]
- P0.2 pipeline_cards(recs, problem_id) port of
  render_experiment_pipeline computation; Streamlit renders from it
  temporarily (parity proof).
- P0.3 narrative_data(recs, log_lines) port of narrative renderers.
- P0.4 experiment_detail(eid) + workspace() assemblers (precedence,
  grouping, retired filtering).
- P0.5 FastAPI skeleton + read-only routers (WAL, CORS :5173,
  TestClient tests on tmp data seeded by simulator campaign).
- P0.6 SSE broker + api_events + append hook + Last-Event-ID replay;
  test: stream during a real spawned campaign.

### P1 — React workspace + experiment page
- P1.1 scaffold (Vite/TS/Tailwind tokens, typed client from
  /openapi.json, useEventSource hook).
- P1.2 Workspace route + WorkspaceTree (inline action slots, chips,
  tallies, collapse persistence).
- P1.3 Experiment page shell (strips, captions).
- P1.4 Pipeline cards (golden tests per card state).
- P1.5 SSE live updates + completion swap + TraceLog component.
- P1.6 Evidence: SVG <img> first; recharts client-side behind flag.

### P2 — launch + wizard + governance
- P2.1 Program form (modality dropdown from /system/modalities,
  mode-lock 409).
- P2.2 Launch endpoint + FE flow.
- P2.3 Wizard sessions API (6 steps, wizard_sessions table).
- P2.4 Wizard UI (6 steps, session resume).
- P2.5 Approvals + halt endpoints + UI.

### P3 — hard-cut
- P3.1 delete Overview.py + streamlit deps + AppTest usage.
- P3.2 uvicorn static SPA mount; make api / web-dev / web-build.
- P3.3 CI: web job (typecheck/vitest/build) + api job; Playwright e2e.
- P3.4 README, screenshots, version bump.

Exit criteria per phase: P0 curl+SSE on real branches; P1 React parity
on same data; P2 full flow React-only; P3 CI green with zero
Streamlit.

## Status

- P0 ✅ complete (ed89713..7fbfd7b): views.py read-models (parity-
  verified), pipeline_cards (incl. terminal-verdict precedence fix),
  narrative_data, experiment_detail/workspace assemblers, FastAPI read
  API, poll-based SSE watcher + replay (subprocess-safe by design).
- P1 ✅ complete: web/ Vite+React+TS scaffold (design tokens from
  BRAND.md), workspace route (programs/trees/groups/archived),
  experiment route (strips, DMTA chips + rounds, pipeline cards, record
  of this run, live trace), SSE-driven query invalidation. Playwright-
  verified against the real completed CAR-T campaign; typecheck+build
  green. Note: evidence renders as verdicts table + files list;
  interactive curves (recharts) deferred to P1.6 follow-up in P2.
