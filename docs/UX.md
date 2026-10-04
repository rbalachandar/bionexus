# BioNexus Workbench — UX Flow & Story

Design authority for the workbench UI — today the React app in `web/` (the
Streamlit-era modules `Overview.py`/`story.py`/`webview.py`/`narrative.py`
were retired; the React routes are the living surface). Visual tokens live
in `docs/BRAND.md`; this
document defines the flows, voices, and vocabulary that sit above them.
Rule: this document is written before pixels change, and the workbench is
reviewed against it.

---

## 1. The story (one sentence)

*A scientist gives the agent a goal; the harness holds the gate; the record
shows exactly what happened and who decided what.*

Every surface is a chapter of that sentence. If a screen doesn't advance
it, it doesn't ship.

## 2. Personas

| Persona | Their job | Primary surfaces |
|---|---|---|
| **Program lead** | sets the TPP/program gates, approves HUMAN-column submissions, reads verdicts | Overview, Wizard, Experiment |
| **Lab operator** | owns devices and the physical world: SOP sign-off, halt/clear, fault response | Overview (halt), Experiment (faults), device cards |
| **Auditor / reviewer** | answers "can I trust this result?" months later | Experiment (provenance, reproduce), Documentation |

One person often wears all three hats (that is today's reality); the
design still keeps the three concerns separable, because their questions
are different.

## 3. The core loop (what the product does)

```
Program (TPP, gates, budget)
   └─> Agent proposes hypotheses          [agent voice]
         └─> Harness gates each proposal   [harness voice]
               ├─ run                      [world: lab/instrument]
               │    └─ analyze ── evidence
               └─ refuse / escalate        [back to human]
                     └─ human adjudicates  [human voice]
                          └─ verdicts recorded ──> flywheel memory
```

Two loops close here: the **experimental** loop (hypothesis → gate →
evidence → verdict) and the **governance** loop (proposal → column →
human → standing policy). The UI must let a reader follow *either* loop
without losing the other.

## 4. Page architecture — one question per page

| Page | The one question it answers | Success test |
|---|---|---|
| **Overview** | "Where do things stand across my program?" | In 5 seconds: is anything blocked, running, or waiting on me? |
| **Wizard** | "What am I being asked to approve, and what will it cost?" | An approval can be understood without leaving the page |
| **Experiment** | "What happened in this run, in order, and who decided what?" | A stranger can reconstruct the run from the page alone |
| **Documentation** | "Why should I trust this tool?" | Claims link to evals and fixtures, never to adjectives |

Navigation is linear and shallow: Overview → Experiment → (within it)
everything about that run. No page requires context from another page.

## 5. The three voices (the central design idea)

Every line on the Experiment page is spoken by one of three actors, and
the reader must never be confused about who is talking:

| Voice | Who | Visual signature (token) | Tone |
|---|---|---|---|
| **Agent** | the AI's proposals, reasoning, plans | teal accent `#1f7a86`, "proposes / recommends" | claims a hypothesis |
| **Harness** | deterministic code: gates, matrix, physical-fault detection | ink rules + status color, "allowed / refused / escalated" | states a decision |
| **Human** | approvals, SOP sign-off, halt, adjudication | amber `#b07d2b`, named actor | owns an action |

Governance surfacing failed before because harness lines looked like agent
chatter. The fix is attribution (see §6) plus the voice distinction.

## 6. Experiment page — narrative arc

Top to bottom, it replays the run chronologically, coarse → fine:

1. **Pipeline cards** — live state right now (creating → running →
   analyzing …). Answers "is it working *at this moment*".
2. **The record of this run** — the completed story:
   - Hypotheses as proposed (agent voice)
   - Hypothesis scores (why the agent picked what it picked)
   - Hypotheses at the gates (harness voice: what passed, what was
     refused, what needed a human — each line attributed, see below)
   - Verdicts (with derivation, CI, margin)
   - Evidence (runs, plates, files behind each verdict)
3. **Trace log** — the raw transcript, last, for deep audit only.

**Attribution rule for harness decisions**: every gate line is prefixed
with what it decided *about* — `sample / hypothesis · protocol title —
decision — reason`. A decision that cannot name its subject is a bug.
Where the decision concerns a halt (a global condition, not one
hypothesis), it says so and links to the halt episode.

**Halted runs**: proposals stay visible (they were really proposed) but
the gate section states plainly that submissions were refused while the
halt was engaged and nothing was measured. Hiding rows would erase the
evidence that governance worked.

## 7. System-state surfaces (halt, faults)

- The **halt banner** is global system state: shown once, at the top of
  every page, at caption scale (it must not shout over the record).
  It carries: reason, when engaged, and a Clear action. Clearing is a
  human action and is *recorded as an episode* (engaged → cleared, by
  whom, how long) that stays visible in the Harness decisions section
  after the fact.
- **Physical faults** are harness findings about the world, not policy
  decisions: they get their own visual token and never say "retry".

## 8. Status vocabulary (event → token → icon)

| Event kind | Token | Icon (name) | Color | Voice |
|---|---|---|---|---|
| halt engaged / NEVER column | `refused` | `halt`, `gate-closed` | rust `#a3402f` | harness |
| safety refusal, operator declined | `refused` | `gate-closed` | rust | harness |
| HUMAN column, SOP pending, advisory escalation | `human-action` | `human`, `clock` | amber `#b07d2b` | harness → human |
| SOP signed off, autonomous under standing policy | `autonomous` | `gate-open` | teal `#1f7a86` | harness |
| physical failure mode | `fault` | `fault` | slate `#5b5850` | harness (world) |
| past episode, trace, history | `provenance` | `history` | stone `#8a867c` | record |
| running / in progress | `progress` | `ring` (the mark's ring) | teal | world |
| verdict validated / confirmed | `confirmed` | `nexus-dot` | teal | record |
| verdict invalidated / inconclusive | `resolved` | `nexus-dot` hollow | ink | record |

## 9. Iconography

- Monoline SVG, 24px grid, **1.5px stroke**, square caps, no fills
  except the nexus dot.
- Geometry derived from the mark: the **ring** = in-progress; the
  **gate bar** = closed/refused (bar removed = open); the **nexus dot**
  = evidence/verdict. Icons must read at 14px.
- Set (initial 12): `program`, `hypothesis`, `gate-open`, `gate-closed`,
  `halt`, `human`, `clock`, `fault`, `history`, `instrument`,
  `verdict`, `evidence`. Stored in `assets/icons/*.svg`; rendered via a
  single `ui.icon(name, size, color)` helper.
- **No emoji anywhere in the workbench**, including page icons in the
  router. Emoji is acceptable only in CLI console output, where icons
  cannot render.

## 10. Honesty rules (carried over from the product principles)

- Empty beats fake: no decorative strings, no placeholder metrics.
- No instrument-specific captions or columns anywhere in generic views.
- Every number on screen traceable to a provenance record.
- An honest empty state beats a busy fake one — but a *quiet* empty
  state (one caption line) beats silence for sections a reader expects
  ("no gate decisions — every submission ran under standing policy").

## 12. Multi-round representation rule

ONE branch per sub-problem; rounds live INSIDE the experiment page as
per-round DMTA chip rows (attributed by candidate via round_start
markers). Rounds never become separate branches — a round is another
loop of the same hypothesis, not a new one. If a round's Analyze
suggests a genuinely new hypothesis, that becomes a new LEAF in the
problem tree (flywheel/problem-tree already model this).

## 11. Anti-goals

- No dual banners or repeated global state per section.
- No walls of JSON in primary sections (JSON belongs to the trace log
  and `bn prove` reports).
- No color-only meaning: color always pairs with an icon and a word
  (accessibility + print).
- No redesign-by-PR: changes to flow or vocabulary update this document
  first.
