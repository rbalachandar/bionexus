# Workbench redesign — spec

Status: approved scope (Nov 12, 2026) · first flow: **Campaign cockpit**.
Decisions: new `/api/v1` layer over the unchanged engine; React + Vite + TS
with Tailwind + Radix primitives + visx charts; a real end-to-end tool, not a
demo build; no static demo mode.

## 1. Who and what for

A bench or computational scientist running real campaigns. Five jobs:

| Job | Question | Surface |
|---|---|---|
| Trust the data | "Is this plate any good, and what does it say?" | **Analyze** |
| Decide what's next | "What do we test next, and why?" | **Campaign** (why-this-plate) |
| Respond | "What needs me right now?" | **Inbox** |
| Defend | "Can I stand behind this result?" | **Evidence** |
| Steer | "Are we winning against the gate?" | **Today** |

Principles: uncertainty is the main visual idea (every estimate is drawn with
its interval against the gate); abstention is a first-class, dignified state,
never an error; the system explains itself (every pick, refusal and verdict has
a "why" one click away); nothing happens without a record.

## 2. Information architecture

```
Today ─ program cards (progress vs gate, needs-you count, changes since last visit)
Inbox ─ approvals · abstentions to review · QC failures · refusals   (decide inline)
Campaigns ─ list ─ Campaign cockpit (see §3)
Analyze ─ drop file → detect → confirm → results → "make it a verdict" → export
Evidence ─ provenance chain · Verify · anchor status · report export
Lab ─ instruments & fence · simulated/real badges · halt switch
```

Global chrome: left rail (the six sections), top bar with the **Halt** button,
a trust strip ("chain verified ✓ · anchored 2 d ago · eval 0.947"), ⌘K command
palette, light/dark theme.

## 3. Campaign cockpit (first flow)

```
┌ objective · status chip · autonomy · gate "IC50 ≤ 2 µM" · budget 7/20 runs · chain ✓ ┐
│ FUNNEL  proposed 5 → selected 3 → tested 3 → judged 3  (validated 1 · refuted 2 · abstained 0)
├───────────────────────────────┬────────────────────────────────────────────────────┤
│ ROUNDS (timeline)             │ HYPOTHESES (table, sortable)                       │
│  ● Round 1  H1 H2 AD1         │  cand │ verdict │ estimate ±CI vs gate (interval   │
│    why this plate ▸           │       │         │ plot, gate as a vertical line)   │
│  ● Round 2  H3 M1             │  ...                                               │
│    why this plate ▸           │  row click → side drawer: statement, mechanism,    │
│  ○ Round 3  (planned)         │  refuted-if clause, curve, evidence run, derivation│
├───────────────────────────────┴────────────────────────────────────────────────────┤
│ ACTIVITY  live stream: "run sim-42-003 submitted" · "H1 VALIDATED (preliminary)" …  │
└────────────────────────────────────────────────────────────────────────────────────┘
```

**Why-this-plate drawer** (per round): the policy and seed; each pick with its
reason (EI arithmetic when acquisition is on, portfolio score otherwise); each
refusal with the gate that refused it (AD veto, diversity, budget, safety).

**States are never colour-only:** validated ✓, refuted ✕, abstained ◐
(interval straddles the gate), refused ⊘, in lab ◷, proposed ·.

Actions: Approve/Decline pending submissions (inline), Halt, re-run review,
export report, open Evidence, archive.

## 4. Design system

Tailwind tokens + Radix primitives (Dialog, Popover, Tooltip, Tabs, Select,
Dropdown, Command) styled as a small in-repo component set. Type: Inter for
text, JetBrains Mono (tabular figures) for numbers and ids. Neutral ink with
one accent; semantic verdict palette validated for colour-blind safety.
visx for the interval-vs-gate plot, funnel, dose–response curves and plate map.
Light and dark themes; keyboard-first; WCAG AA contrast.

## 5. API v1 (resource model)

Generated OpenAPI → generated TypeScript client (no hand-written types).

```
GET  /api/v1/campaigns                       list (filter: program, status)
GET  /api/v1/campaigns/{id}                  cockpit model (header, funnel, rounds+why, hypotheses, reviewer)
GET  /api/v1/campaigns/{id}/hypotheses/{h}   one hypothesis: card + evidence + derivation
GET  /api/v1/campaigns/{id}/activity         recent human-readable events
GET  /api/v1/campaigns/{id}/events           SSE stream
GET  /api/v1/campaigns/{id}/provenance       chain + verification result
POST /api/v1/campaigns/{id}/archive
GET  /api/v1/inbox                           unified action queue
POST /api/v1/inbox/{item}/decision           approve / decline (identity from the token)
GET  /api/v1/programs, /programs/{slug}      program + gate progress
GET  /api/v1/instruments, /halt, POST /halt
POST /api/v1/analyses, GET/POST /analyses/{id}/…   (Analyze flow)
```

Write endpoints keep the existing guard (local Host/Origin, optional per-person
tokens). One event stream. Errors are RFC 7807-style `{type, title, detail}`.

## 6. What gets removed

- the Wizard flow (`/api/wizard/*`, `Wizard.tsx`): a hand-run experiment becomes a
  campaign with `autonomy: observe` and manual result upload (same cockpit);
- every `/api/*` route replaced by `/api/v1/*`, and the hand-written
  `client.ts` + duplicated types;
- the per-screen ad-hoc CSS in `web/src/styles` (replaced by tokens);
- duplicated read-model code paths once the v1 models read from `views/` only.

## 7. Phases (each ends green and committed)

Status: **1 done** (API v1 campaigns) · **2 done** (foundation: Tailwind tokens +
Radix primitives, shell with Halt / trust strip / ⌘K, generated client,
`/api/v1/system/status`, campaigns list, dark + light) · **3 done** (campaign
cockpit: outcome bar, interval-vs-gate forest plot on a log axis, rounds timeline
with why-this-plate, evidence drawer with the recorded dose–response curve + QC,
plain-language verdict explanation and next step, live activity) · **4 done** (decisions: Inbox, approvals on the campaign, sealed human review of
abstentions, follow-up / new-campaign / new-program dialogs with `gate` autonomy by
default, agents + full trace per actor, deterministic "what next"; legacy Workspace /
Program / Experiment / Wizard / Approvals screens and ~800 lines of old API removed) ·
**5 done** (Evidence: verify / anchor / exports; Lab: honest instrument badges, authority policy, SOP sign-off; Analyze: drop a plate file → curves with IC50 ± CI, QC, abstentions → your decision → attach as evidence; legacy Analysis screen, `/api/analyses` and the legacy CSS layer removed) · 6 next: polish (Playwright e2e, accessibility, README screenshots), Lab instrument Test-connection / configure.

1. **API v1 for campaigns**: pydantic response models, `/campaigns`, hypothesis,
   activity, events, provenance; OpenAPI export; tests on the golden campaign.
2. **Frontend foundation**: Tailwind + Radix primitives, tokens, app shell
   (rail, top bar, Halt, trust strip, ⌘K), generated client, routing.
3. **Campaign cockpit**: header/funnel, rounds timeline + why-this-plate,
   hypothesis table with interval plot, drawer, activity stream.
4. **Inbox + Halt** (approve/decline inline), then **Evidence** (verify, export).
5. **Today** (program board) and **Lab**.
6. **Analyze** rebuilt on the same system; Wizard removal.
7. Polish: accessibility pass, Playwright end-to-end tests, performance, README
   screenshots, delete the old routes and client.


## 8. Removed in phase 4 (and where it went)

- The LLM-drafted **program brief** and the problem-tree **program verdict / termination
  policy** were API+UI features of the old workspace. The engine modules remain
  (`problem_tree`, `proef campaign plan`), but they are no longer surfaced; the new
  program page shows deterministic **What next** recommendations instead. Restore the
  model-drafted brief on top of v1 if/when a model is configured for the workbench.
- `/api/wizard/*`, `/api/programs*`, `/api/experiments*`, `/api/approvals*`,
  `/api/instruments`, `/api/taste`, `/api/events` (SSE): replaced by `/api/v1/*` (the UI
  polls). `/api/analyses/*` → `/api/v1/analyses/*` (Analyze rebuilt).

## 9. Realigned to the original flow (Nov 14, 2026)

Phase 4 made the *campaign* (which needs candidates) the centre of the launch flow and dropped the problem-tree and the
LLM program brief from the workbench. That moved away from the original idea: **define a problem with limits, press
Start, an agent proposes hypotheses and designs the experiments, runs them under the person's approval, and loops.**
Restored, in order:

1. **Program limits** — rounds, lab runs, hypotheses, families, variants per family, breadth. Hard caps every campaign
   inherits; a campaign may use less, never more; the engine receives a real `ResourceBudget`.
2. **Start research + plan review** — the primary action on a program. A model proposes families of hypotheses; in
   *Ask me first* the campaign pauses and shows the plan (mechanism, refuted-if, confidence, citation status, every
   variant). The person removes hypotheses, declines, or approves; removals are recorded with a reason and never tested.
3. **Wording** — "autonomy" means only how much runs without approval. The ways to run are *Start research*, *I have
   candidates* and *I'll run the plate myself*.

Still open: decomposition of an objective into sub-problems in the workbench (`proef campaign plan` exists in the
engine/CLI); re-planning after each round from the results; one approval that covers a whole approved plan's lab
submissions (today each submission is still approved separately in *Ask me first*).
