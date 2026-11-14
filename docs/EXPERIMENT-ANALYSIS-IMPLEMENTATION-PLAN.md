# Experiment Data Analysis — Implementation Plan

**Status:** Phases 1–4 SHIPPED (Oct 2026): generic lifecycle contracts,
plate-assay profile, artifact store + `/api/analyses` lifecycle (preview →
configure → run → review), workbench `Analyze data` flow with plate map,
history list, control/normalization configuration, report + CSV export with
chain verification, and campaign handoff with an explicit recorded
proxy-evidence transition.
OPEN: browser-level tests + accessibility verification (no browser-test
infra in repo yet — needs a Playwright decision), Phase 0 named-scientist
walkthrough and Phase 5 design-partner validation — the utility claim is
unproven until those run.
**Scope:** modality-neutral analysis workflow and evidence lifecycle, with plate-reader assay analysis as the first validated profile  
**Product goal:** make Proef useful to a scientist who already has experimental data, without narrowing the framework's bio/chemical/material domain.

## 1. Decision

Make **analyze existing experiment data and produce a reviewable, uncertainty-aware report** the first-class scientist workflow. Validate the workflow first with plate-reader assay data because the repo already has real exports, parsers, QC, dose-response analysis, and case-study evidence. A plate assay is the initial profile—not the shared domain model. Treat agent-guided campaign execution as a later, optional continuation from an analysis.

This plan builds on the existing `proef.labread.read_plate` parser and plate-assay analysis code, the four real instrument exports under `tests/data/instruments/`, and the existing provenance store. It does not propose another parser or a replacement for the campaign engine. The generic lifecycle should handle measurement artifacts, provenance, uncertainty, review, and reporting; plate-specific parsing, controls, normalization, Z′, dose-response fits, and IC50 interpretation remain in the plate-assay profile.

The current wizard is not yet this workflow: it creates an experiment definition first, calls `read_plate(path)` with no user-configurable layout or normalization, moves directly from upload to results, and records a user-selected hit list rather than a decision against an explicit analysis gate. Preserve its guided-campaign purpose; add a separate analysis path and connect the two only after that path is useful. Do not let plate-specific assumptions leak into the shared contracts, workspace summaries, or campaign lifecycle.

## 2. Target user and job

**Initial design partner:** a scientist or assay operator who has a CSV, TSV, or XLSX plate-reader export, may have a separate plate map, and currently uses scripts or spreadsheets to get to a hit list. The workflow should be described generically as experiment-data analysis; this first profile is an intentional narrow wedge, not a claim that all Proef users work with plates.

**Job:** “Help me understand what my experimental data supports, what it does not support, and why—without changing my source file or hiding uncertain calls.”

### Success measures

For the first design-partner workflow:

- A new user can get from export to a reviewed report without editing the source file or writing code.
- The report exposes every material parsing/analysis assumption and links every call to the source wells and analysis configuration.
- The scientist can identify and correct a wrong mapping before interpreting fitted results.
- Uncertain and unsupported results remain abstentions/refusals; they are not converted to binary hits by the UI.
- On a repeat plate from the same workflow, the scientist can reuse the saved assay setup and recognizes the report as useful enough to use again.
- Record time-to-first-report, manual corrections, analysis disagreements, and whether the scientist reuses the workflow. Do not treat parser success or CI-green status as user-value evidence.

## 3. Product workflow

### Main path

1. **Start:** choose “Analyze experiment data” from the workspace, then select an available analysis profile. Initially, only the plate-reader assay profile is shipped. Campaign launch remains available but is visually secondary.
2. **Upload:** add the profile's source artifact and any required companion files (for the initial profile, an instrument export and optional plate-layout file). Store original bytes unchanged and calculate SHA-256 digests.
3. **Preview:** show generic artifact status plus profile-specific interpretation. For the plate profile: detected format, device metadata, dimensions/well count, channels, detected columns, units, candidate control classes, and rows/wells that could not be interpreted. Do not fit or publish verdicts yet.
4. **Configure:** confirm or correct the selected profile's interpretation. For the plate profile: response channel, layout mapping, concentration units, control wells/classes, response direction, normalization, and analysis metric. Show which settings were inferred and which the user supplied.
5. **QC:** report profile-specific QC. For the plate profile: control availability, real Z′ or clearly labeled heuristic, curve coverage/censoring, missingness, replicate counts, and spatial QC. A QC warning is not silently transformed into a correction or a pass.
6. **Analyze:** show the profile's estimates, intervals, tested range, fit status, evidence class, and—only if the user registered a threshold—a preliminary validated / invalidated / inconclusive call under that threshold. Reserve **confirmed** for the existing confirmation-agreement semantics; a user's review acknowledgement is not orthogonal experimental confirmation.
7. **Review:** let the scientist acknowledge, annotate, or override a call with a reason. Preserve the machine-derived call alongside the human disposition.
8. **Report:** export a shareable HTML report and a profile-appropriate standardized data export; retain a link to the analysis record and original input digest.
9. **Continue (optional):** start a guided campaign from the saved assay setup or selected unresolved question. The campaign inherits the setup as context, not as an implicit approval to act.

### Required state vocabulary

Use explicit persisted states rather than inferring progress from whichever fields happen to exist:

`uploaded → preview_ready → configured → analyzed → reviewed`

Failures and holds are distinct states/reasons. Keep generic states such as `unreadable`, `needs_input`, and `analysis_failed`; profile-specific diagnostics may include `needs_mapping`, `unsupported_regime`, or `qc_hold`. Re-uploading or changing configuration creates a new immutable analysis revision; it does not rewrite the old result.

### Evidence classes

Every result/report labels its origin as one of:

- **Measured:** an instrument export from an identified or user-declared device.
- **Historical deposit:** a frozen external dataset or paper deposit.
- **Simulated:** Proef-generated measurement data.
- **Predicted:** a model output or proxy metric, not a physical measurement.

The UI must not aggregate these classes into a single unlabeled hit rate. Unknown origin stays `unknown`; it is not guessed from a filename.

## 4. Architecture and interfaces

### 4.1 Keep the analysis lifecycle generic and interpretation profile-specific

Introduce a `proef.experiment_analysis` module for the application-facing lifecycle around source artifacts, revisions, results, and dispositions. It should handle concepts common to bio, chemical, and materials work: evidence artifacts, typed measurement records, units, uncertainty, profile identity/version, review state, and provenance references. A selected analysis profile owns domain interpretation. The first implementation wraps existing `labread` behavior for plate-reader assays; do not rename IC50, positive/negative controls, percent inhibition, or Z′ into fake universal concepts.

The module's interface should capture the facts a caller must know:

- generic lifecycle operations are deterministic for identical artifacts, configuration, profile, and pinned implementation versions;
- profile-detected values are provisional until confirmed when they affect scientific meaning;
- unsupported formats/regimes return typed profile diagnostics, not partial confident results;
- an analysis run never modifies the original artifact;
- analysis configuration and implementation versions are included in the returned result.

Use a small typed generic request/result contract with a profile discriminator and a profile-specific configuration/result payload. The shared contract must not require plates, compounds, IC50s, or a biological assay. Keep vendor-specific parsing internals private to `labread` and its adapters. Do not expose parser stages or dozens of helper methods as a new public interface. Retain `read_plate` as a supported Python/CLI facade and add parity tests so existing users are not forced to migrate. Do not build a speculative plugin registry for every modality; establish the profile seam with the first profile, and validate its shared shape when a second real profile is selected.

Suggested data carried by the contract:

- **Generic request:** source artifact reference/digest, analysis profile and version, optional success threshold/direction, and evidence origin.
- **Plate-assay config/preview/result:** optional layout artifact, selected channel, cycle reduction, response unit/direction, normalization, explicit positive/negative control mapping, detected dialect, mapped/unmapped wells, control counts, candidate regime, IC50/curve estimates, confidence intervals, censoring/fit quality, and plate QC.
- **Generic result:** typed measurement/result artifact references, profile-specific diagnostics, optional admissible preliminary verdict (or reason for abstention/refusal), exact profile configuration, implementation versions, source digests, and evidence origin.

Place types in `core/contracts` only when they cross a package/API seam; keep internal result helpers local to the analysis module. Avoid expanding the general `Envelope`/workflow contract for plate-specific concerns.

### 4.2 Separate computation from persistence and orchestration

- `labread.py`: remain the plate-reader parser/analysis implementation. Do not combine parser refactoring with UI work unless a failing real fixture requires it.
- `experiment_analysis.py` (new): coordinate the generic lifecycle and one explicitly selected analysis profile; keep HTTP, browser state, file persistence, and provenance writes out of scientific calculations.
- `analysis_profiles/plate_assay.py` (new): adapt existing `labread` functions into the initial profile's preview, configuration, QC, and result payload.
- `api/analyses.py` (new): own lifecycle transitions, artifact storage, session persistence, and provenance integration. Keep FastAPI route functions thin in `api/app.py`.
- `views.py`: build a generic analysis list/detail/report read-model, with profile-specific details nested rather than hard-coded into every workspace summary.
- `web/src/routes/Analysis*.tsx` (new): profile selection, upload/preview/configure/report screens; reusable controls and evidence displays live in components.
- Existing `wizard_sessions.py`: remain the guided-campaign path. Reuse the analysis module and shared report components later, rather than merging the two state machines now.

### 4.3 Persistence and provenance

Store source files and derived exports as artifacts beneath the configured Proef data directory using generated IDs, never the user filename as a storage path. Persist metadata needed to retrieve the analysis; do not put large well tables into provenance event payloads.

For each immutable analysis revision, record at minimum:

- analysis ID and revision;
- source and optional layout SHA-256 digests, original filename as sanitized display metadata, size, and evidence origin;
- parser/version and analysis/config schema versions;
- explicit configuration and confirmation/override decisions;
- QC outcomes, result artifact references, and derived metric summary;
- human review/disposition and actor/time when supplied.

Append events to a dedicated analysis branch using the existing provenance store. Verify the chain before issuing the “intact” report claim. A changed file or changed scientific configuration produces a new revision and new records; it never mutates a prior analysis. Keep raw file bytes outside the chain and bind them by digest.

### 4.4 HTTP interface

Add a narrow analysis resource, separate from campaign creation:

- `POST /api/analyses` — upload source and optional layout; create an analysis and return its preview.
- `GET /api/analyses` — list recent analyses and states.
- `GET /api/analyses/{id}` — return state, preview/config, results, QC, evidence class, and provenance summary.
- `POST /api/analyses/{id}/configure` — validate and save a configuration revision; return an updated preview.
- `POST /api/analyses/{id}/run` — execute deterministic analysis against the selected revision.
- `POST /api/analyses/{id}/review` — record acknowledgement, comment, or human disposition without overwriting the computed call.
- `GET /api/analyses/{id}/report` and `/export.csv` — return report/standardized records.

Return structured error codes and field diagnostics for unreadable files, unknown formats, incomplete layouts, unsupported regimes, invalid controls, and resource limits. Enforce upload size limits and allow-listed formats. These routes are for local scientist workflow; they do not create a general multi-tenant upload service.

## 5. Implementation phases

### Phase 0 — Lock the smallest useful workflow

**Tasks**

- Walk one scientist through CS05/real-export examples and the current `proef read` output; capture their actual input files, plate map, required outputs, and decision terminology.
- Select one initial assay family and one supported device family for the first polished path. Keep the already-supported CSV/TSV/XLSX formats, but do not promise every vendor dialect is equally validated.
- Agree on how this first assay defines positive/negative controls, normalization, threshold, and what constitutes an unusable plate.
- Produce a one-page workflow and two annotated screens (preview and report) before building the route.

**Exit criteria**

- A named user and a recurring assay job are identified.
- Every required input and expected report field has an owner/source.
- The distinction between a parser result, a QC finding, a scientific estimate, and a human decision is agreed.

### Phase 1 — Generic lifecycle contract and first analysis profile

**Tasks**

- Define typed generic analysis lifecycle/result contracts with a profile discriminator, artifact refs/digests, version, evidence-origin, and disposition fields. Put profile-specific options and outputs in the plate-assay payload rather than universal fields.
- Add the `proef.experiment_analysis` lifecycle module and the initial plate-assay profile around `labread`; preserve `read_plate` behavior as the compatibility facade.
- Make the plate profile preview identify missing/unmapped wells and which inferred fields need confirmation. Ensure it refuses a required-but-missing mapping or unresolved response polarity rather than guessing.
- Keep human disposition separate from computed verdict. A threshold-less analysis returns estimates/QC, not a fabricated hit label.
- Include exact analysis config, parser version, and source digest in the structured result.

**Target files**

- `src/proef/labread.py`
- `src/proef/experiment_analysis.py` (new)
- `src/proef/analysis_profiles/plate_assay.py` (new)
- `src/proef/core/contracts/analysis.py` (new, if the generic typed contract crosses the API seam)
- `src/proef/core/contracts/__init__.py`
- `tests/test_experiment_analysis.py` and `tests/test_plate_assay_analysis.py` (new)
- Existing `tests/test_vendor_ingest.py`, `tests/test_labread_pubchem.py`, and `tests/test_censoring.py`

**Exit criteria**

- Same bytes + same config + same pinned versions produce equivalent structured results.
- All existing `read_plate`/CLI behavior stays covered by compatibility tests.
- Generic tests cover lifecycle transitions, artifact/version/evidence-origin handling, and human disposition. Plate-profile tests cover no-layout, partial-layout, ambiguous response scale, absent controls, failed normalization, unsupported regime, censored curves, low replicate counts, and threshold-straddling intervals.
- No decisive preliminary `validated`/`invalidated` call is emitted without an explicit registered threshold and a supported analysis regime; `confirmed` remains reserved for the existing confirmation-agreement semantics.

### Phase 2 — Analysis persistence, artifacts, and API

**Tasks**

- Add an `analysis_sessions` (or equivalent) persistence table with generic state/profile/revision fields and profile-scoped config/result artifacts; use migrations or safe `CREATE TABLE IF NOT EXISTS` consistent with the existing store approach.
- Add artifact storage helpers that generate IDs, calculate digests, preserve source bytes, sanitize display metadata, and enforce upload limits.
- Implement state-transition validation and idempotent `configure`, `run`, and `review` operations. Invalid transitions return clear errors.
- Append provenance events for upload, configuration confirmation, analysis completion/refusal, and human disposition. Keep well-level results in a separate result artifact.
- Add the HTTP endpoints above in `api/analyses.py`; wire them into `api/app.py` and return view-ready JSON without embedding plate-specific result assumptions in generic endpoints.
- Make report generation reproducible from the stored source artifact and explicit config. Do not silently re-run under changed parser code and label it the original result.

**Target files**

- `src/proef/api/analyses.py` (new)
- `src/proef/api/app.py`
- `src/proef/adapters/store/` or the existing wizard/artifact store, depending on the chosen persistence seam
- `src/proef/views.py`
- `tests/test_experiment_analysis_api.py` (new)
- `tests/test_provenance_security.py` and `tests/test_api.py`

**Exit criteria**

- Upload, preview, configuration revision, run, review, and export survive an app restart.
- Original bytes verify against the stored SHA-256; changing bytes/config produces a new revision.
- Provenance verification catches payload alteration and report generation refuses a tampered chain.
- API errors are structured, never return partial results as successful verdicts, and do not leak local storage paths.

### Phase 3 — Standalone workbench workflow

**Tasks**

- Add **Analyze experiment data** as the primary workspace action; keep campaign launch visible but secondary. The first profile is explicitly labeled “Plate-reader assay”; do not imply other profiles are already implemented.
- Add `/analyses/new` for profile and artifact selection and `/analyses/:id` for the analysis lifecycle. Link analysis history from Workspace.
- Implement a generic upload state with file/size expectations, progress, and recoverable errors; show optional companion-file upload required by the selected profile.
- Implement generic analysis state plus a plate-assay preview/configuration screen with detected metadata, channel selection, mapping coverage, control classification, units, normalization, and explicit confirmation of inferred scientific fields.
- Provide a compact plate map visualization with controls, unmapped wells, missing values, and selected compound wells distinguished by icon plus label, not color alone.
- Implement a result screen with a top-line state (ready, QC hold, abstained, unsupported, or reviewed), followed by per-sample estimate/CI/range/call, curve evidence, and QC details.
- Add “why this call?” expansion that shows the registered threshold, CI relation, model/fit/censoring status, and source wells; avoid JSON in the default view.
- Show measured/historical/simulated/predicted evidence labels everywhere results are summarized.
- Make human acknowledgement and override reason explicit and visually distinct from computed calls.
- Add report download and link to the provenance record.

**Target files**

- `web/src/main.tsx`
- `web/src/routes/Workspace.tsx`
- `web/src/routes/Analysis*.tsx` (new)
- `web/src/components/PlateMap.tsx`, `AnalysisCall.tsx`, `EvidenceOrigin.tsx`, and profile-specific views (new as needed)
- `web/src/api/client.ts`
- `web/src/styles/`

**Exit criteria**

- A scientist can complete the chosen workflow without using CLI, reading JSON, or editing the export.
- The result page makes uncertainty, unsupported regimes, simulation, and human overrides visually unambiguous.
- Keyboard navigation, labels, focus handling, contrast, and responsive layout are verified.
- Browser tests exercise successful upload, correction of a bad mapping, QC hold, abstention, and report download.

### Phase 4 — Honest report and campaign handoff

**Tasks**

- Produce a profile-labeled HTML report with generic source identity/digest, evidence class, profile/version, user-confirmed config, review annotations, and provenance verification status; the initial plate profile adds instrument metadata, QC, curves/CIs, calls, abstentions, and refusals.
- Produce a profile-labeled export. The initial plate profile's CSV keeps raw and normalized values separate and includes well mapping, units, fit estimates, intervals, call, fit status, and evidence origin. Do not prescribe a universal flat CSV schema for all future modalities.
- Add a handoff from a reviewed analysis to a guided campaign: copy assay settings, plate mapping conventions, and unresolved decisions; require the user to register the campaign's objective and gate separately.
- Do not let a result marked simulated or predicted flow into a “measured” campaign result without an explicit source transition that is recorded.

**Target files**

- `src/proef/analysis_report.py` (new generic report shell) and the plate profile's report renderer, or an equivalent composition with `src/proef/report.py`
- `src/proef/api/analyses.py`
- `web/src/routes/Analysis*.tsx`
- `tests/test_analysis_report.py` and `tests/test_plate_assay_report.py` (new)
- `tests/test_api.py`

**Exit criteria**

- Downloaded HTML and CSV agree with the browser result and can be regenerated from the stored revision.
- A third party can identify the input, assumptions, decision rule, and whether a human changed the call.
- Campaign handoff creates a new campaign record and never mutates or upgrades the original analysis evidence.

### Phase 5 — Design-partner validation and scope decision

**Tasks**

- Run the workflow with one named scientist on their own plate exports, including at least one file that needs correction or is refused.
- Observe first-use without coaching; log where they pause, correct mappings, mistrust assumptions, or leave the workflow.
- Compare Proef outputs to the user's current process and have them adjudicate disagreements blind to the tool call where feasible.
- Track time to report, setup reuse, correction frequency, unresolved disagreements, abstention usefulness, and repeat usage.
- Maintain a fixed corpus of permissioned, de-identified regression exports from that pilot, with source and license notes in `tests/data/instruments/README.md`.
- After the pilot, decide whether to deepen assay analysis, add another instrument family, or connect campaigns more tightly. Do not pre-commit to broad modality expansion.

**Exit criteria**

- The scientist uses the workflow more than once without maintainer intervention.
- Disagreements are explained and either fixed or retained as a documented limitation; no “agreement percentage” is reported without naming the reference and its limits.
- A next investment is chosen from observed user friction and decision impact, not feature availability.

## 6. Cross-cutting quality and safety requirements

- **Scientific honesty:** CI-straddling calls abstain; missing/unstable CI cannot become a decisive call; each profile declares its uncertainty and admissibility rules. A non-validated plate normalization regime cannot produce absolute potency verdicts.
- **No silent inference:** inferred unit, channel, polarity, controls, or layout are visible and confirmable when they affect a call.
- **Modality integrity:** the generic analysis lifecycle does not assume compounds, wells, IC50s, controls, or inhibition. Each profile owns its domain-specific interpretation and diagnostics.
- **Origin integrity:** evidence origin is stored, propagated into every report, and never inferred from a UI route or filename.
- **Provenance integrity:** immutable revisions, content digests, parser/config versions, and chain verification are part of the report contract.
- **Input robustness:** malformed, oversized, encoding-hostile, injection-shaped, and partially corrupt exports fail into explicit diagnostics without crashing or changing verdicts.
- **Privacy:** store data locally by default; do not send plate contents to an LLM. Any future model-based explanation must be opt-in and must not alter scientific results.
- **Compatibility:** existing CLI and Python `read_plate` users continue to work through the existing facade.
- **Accessibility:** no color-only statuses; controls have labels; tables and plate maps are keyboard accessible; state changes are announced.

## 7. Test and evaluation strategy

1. **Unit/contract tests:** analysis contract state, diagnostics, transitions, deterministic results, call/abstention semantics, input digest behavior.
2. **Fixture tests:** all committed Tecan/BioTek/Gen5 exports and layout fixtures, CS05/CS06 frozen deposits, corrupt/ambiguous variants. Preserve original fixture files unchanged. Other modalities add profile fixtures only when those profiles are selected for implementation.
3. **API integration tests:** upload → preview → configure → analyze → review → export, persistence after reopening the store, provenance verification, permissions/resource limits.
4. **Browser-level tests:** the same main path plus mapping correction, refusal/hold, no threshold, and human override.
5. **Regression reports:** compare parser diagnostics, QC, fits, and statuses against approved fixture expectations. Never use hand-copied display strings as the only oracle.
6. **Pilot evidence:** maintain a separate user-validation log. Software tests prove behavior; they do not prove scientist utility.

Run focused checks during development (`pytest -q tests/test_experiment_analysis.py tests/test_plate_assay_analysis.py tests/test_experiment_analysis_api.py`, relevant existing ingestion/API tests, and the web typecheck/build), then the full project checks required by `AGENTS.md` before declaring the slice complete.

## 8. Explicit non-goals for this slice

- Replacing the agent campaign engine or removing the existing wizard.
- Claiming autonomous drug discovery or scientific breakthrough capability.
- Implementing additional analysis profiles (materials stress/strain, chemistry, or other assay types) before the pilot and a real second use case select the next one.
- Introducing a queue, distributed workers, multi-tenant auth, hosted storage, or cloud deployment.
- Automatically correcting edge effects, changing normalization, or overriding a scientist's call.
- Using an LLM to produce or decide assay verdicts.

## 9. Principal risks and mitigations

| Risk | Mitigation |
|---|---|
| The parser auto-detects a plausible but wrong layout/channel | Preview first; expose inference and mapping coverage; require confirmation when scientific meaning changes. |
| UI turns a heuristic into an apparent validated metric | Carry `z_prime_kind`, regime, fit status, and evidence origin as typed data; use explicit labels and refusal states. |
| Analysis result cannot be reproduced after code changes | Store exact input/config/version and immutable revision; make “re-analyze with current version” a new revision. |
| Wizard, CLI, and web paths compute slightly different results | Keep one analysis seam; make each surface an adapter; add cross-surface parity tests. |
| A plate-specific first workflow narrows the agnostic framework | Keep generic lifecycle, artifact, measurement, evidence-origin, and provenance concepts modality-neutral; label plate analysis as the first profile and defer other profiles until selected by real users. |
| Plan expands into a broad ELN/LIMS | Limit scope to file-in, reviewable report, export, provenance, and one optional campaign handoff. |
| A technically correct report is not useful to the scientist | Make design-partner observation and repeat use a release gate, not post-launch polish. |

## 10. Recommended delivery order

Deliver in this order: **Phase 0 → Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5**. Do not start a broad refactor of `labread.py` before the analysis lifecycle and first profile reveal what must be isolated. Do not expand campaign autonomy or claim broad cross-modality analysis before the first workflow has been exercised by a scientist and a second profile has validated the shared seam.
