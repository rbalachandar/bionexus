"""Lab awareness — agents notice device outputs instead of being pointed at them.

Three pieces:

1. `DeviceMonitor`  — watches an instrument "outbox"/inbox directory (the
   universal convention: every real instrument exports a file when a run
   completes) and emits `LabEvent`s as files appear.
2. `AutoAnalysisAgent` — consumes those events: reads the result
   (read_plate), updates any hypotheses whose candidate was measured,
   records diary entries into provenance, and queues decisions for the
   scientist. Humans never shuttle files.
3. `bn watch <inbox>` — runs the loop.

The same event interface later maps 1:1 to real push sources (instrument
webhooks, queue depth on the LabGateway, device SDKs) — inbox watching is the
lowest-common-denominator that works with every existing instrument.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator


@dataclass
class LabEvent:
    kind: str                 # "plate_ready" | "file_seen"
    source: str               # device/file path
    path: Path | None = None
    detail: str = ""
    seen_at: float = field(default_factory=time.time)


class DeviceMonitor:
    """Watch a directory instruments write into; yield events for new files."""

    def __init__(self, inbox: str | Path, poll_secs: float = 1.0,
                 patterns: tuple[str, ...] = ("*.csv", "*.tsv", "*.xlsx", "*.npy")):
        self.inbox = Path(inbox)
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.poll_secs = poll_secs
        self.patterns = patterns
        self._seen: set[Path] = set()

    def poll(self) -> list[LabEvent]:
        events = []
        for pattern in self.patterns:
            for f in self.inbox.glob(pattern):
                if f in self._seen:
                    continue
                self._seen.add(f)
                kind = "plate_ready" if f.suffix.lower() in (".csv", ".tsv", ".xlsx") else "file_seen"
                events.append(LabEvent(kind=kind, source=self.inbox.name, path=f,
                                       detail=f"instrument output appeared: {f.name}"))
        return events

    def events(self, stop_after: int | None = None, once: bool = False,
               idle_timeout: float | None = None) -> Iterator[LabEvent]:
        """Blocking generator. `stop_after` bounds total events (for demos/tests);
        `idle_timeout` ends the stream after that many seconds without a new
        event (for open-ended campaigns)."""
        count = 0
        last_event = time.time()
        while True:
            for ev in self.poll():
                yield ev
                count += 1
                last_event = time.time()
                if stop_after is not None and count >= stop_after:
                    return
            if once:
                return
            if idle_timeout is not None and time.time() - last_event > idle_timeout:
                return
            time.sleep(self.poll_secs)


class AutoAnalysisAgent:
    """Reacts to lab events: reads results, updates hypotheses, records decisions.

    `notify` is how the scientist hears about it (console, MCP message, chat...).
    If `gateway` is provided, recommendations with a clear next experiment are
    AUTO-SUBMITTED through the safety gateway — closing the loop: the agent
    designs and runs the orthogonal confirmation assay itself, still inside the
    SafetyEngine's trust boundary.
    """

    ORTHOGONAL_ASSAY = {"binding": "enzymatic", "enzymatic": "binding",
                        "cytotoxicity": "binding"}

    def __init__(self, store: Any = None, tracker: Any = None,
                 notify: Callable[[str], None] | None = None,
                 max_response: float | None = None,
                 gateway: Any = None, branch_id: str = "autonomous-loop",
                 auto_confirm: bool = True,
                 export_fn: Callable[..., None] | None = None,
                 adaptive: bool = False,
                 dose_ladder: tuple[float, ...] = (0.5, 2.0, 10.0, 40.0, 80.0),
                 adaptive_wells: int = 3):
        self.store = store
        self.tracker = tracker
        self.notify = notify or (lambda msg: print(f"[agent] {msg}"))
        self.max_response = max_response
        self.gateway = gateway
        self.branch_id = branch_id
        self.auto_confirm = auto_confirm and gateway is not None
        self.export_fn = export_fn   # drops the instrument export for a run
        self.adaptive = adaptive and gateway is not None
        self.dose_ladder = dose_ladder
        self.adaptive_wells = adaptive_wells
        self._designers: dict[str, Any] = {}
        self._confirmations: dict[str, dict] = {}   # run_id -> confirmation task
        self._confirm_submitted: set[str] = set()   # candidates already confirmed

    def handle(self, event: LabEvent) -> dict[str, Any] | None:
        if event.kind != "plate_ready" or event.path is None:
            return None
        from bionexus.labread import QC_ZPRIME_FLOOR, read_plate, replicate_ci

        try:
            if self.adaptive:
                return self._handle_adaptive(event)
            conf = self._confirmations.get(event.path.stem)
            if conf:
                return self._handle_confirmation(event, conf)
            self.notify(f"reading instrument output {event.path.name} "
                        "(device finished the measurement)")
            result = read_plate(event.path, max_response=self.max_response)
            from bionexus.physfail import classify as _fm
            _phys = _fm([r["value"] for r in result.records])
            if _phys["kind"] == "physical":
                self.notify(f"⚠ PHYSICAL failure mode "
                            f"({event.path.name}): {_phys['evidence']} — "
                            f"{_phys['action']}; no verdicts derived")
                self._record_failure_mode(event, _phys)
                return {"failure_mode": _phys, "file": event.path.name}
        except Exception as exc:
            # classify BEFORE the retry reflex: physical failures must not be
            # treated as software hiccups (the foam/retry trap)
            from bionexus.physfail import classify as _fm
            verdict = _fm([], error=str(exc))
            if verdict["kind"] == "physical":
                self.notify(f"⚠ PHYSICAL failure mode "
                            f"({event.path.name}): {verdict['evidence']} — "
                            f"{verdict['action']}")
                self._record_failure_mode(event, verdict)
                return {"error": str(exc)[:200], "file": event.path.name,
                        "failure_mode": verdict}
            self.notify(f"⚠ instrument output unreadable ({event.path.name}): "
                        f"{str(exc)[:120]} — flagged for review, no verdicts "
                        f"changed")
            return {"error": str(exc)[:200], "file": event.path.name,
                    "failure_mode": verdict}
        self.notify(f"analyzed: {len(result.analysis['compounds'])} compound(s), "
                    f"Z'~{result.z_prime} (heuristic)")

        # auto-update hypotheses whose candidate appears in this plate
        verdicts = []
        if self.tracker:
            for hyp in self.tracker.hypotheses.values():
                match = result.analysis["compounds"].get(hyp.candidate)
                crit = hyp.criteria
                # property metrics (potency_pct, tensile, ...) read the
                # recorded value at the HIGHEST dose directly; only
                # IC50-style metrics use the Hill fit
                prop_value = None
                if crit and crit.metric not in ("ic50_um", "value"):
                    # records may be dicts (labread) or Measurement
                    # models (simulator); read both shapes uniformly
                    def _recs():
                        for m in result.records:
                            if isinstance(m, dict):
                                yield m
                            else:
                                yield m.model_dump()
                    cand_vals = []
                    any_val = None
                    for rec in _recs():
                        if rec.get("sample") != hyp.candidate:
                            continue
                        if rec.get("control"):
                            continue
                        if any_val is None:
                            any_val = rec.get("value")
                        conc = rec.get("conc_um")
                        val = rec.get("value")
                        if isinstance(conc, (int, float)) and \
                                isinstance(val, (int, float)):
                            cand_vals.append((conc, val))
                    if cand_vals:
                        # replicate-mean at the top dose + well-level
                        # bootstrap CI: property metrics get the SAME
                        # abstention machinery as IC50 fits
                        top_conc = max(c for c, _ in cand_vals)
                        top_vals = [v for c, v in cand_vals if c == top_conc]
                        prop_value = sum(top_vals) / len(top_vals)
                        prop_ci = replicate_ci(top_vals)
                    elif any_val is not None:
                        prop_value = any_val
                        prop_ci = None
                    else:
                        prop_value = None
                        prop_ci = None
                if prop_value is not None and hyp.status in (
                        "proposed", "designed", "tested"):
                    hyp.observed_value = prop_value
                    hyp.observed_ci = prop_ci
                    hyp.evidence_run_id = event.path.stem
                    hyp.qc_passed = (result.z_prime or 0) >= QC_ZPRIME_FLOOR
                    if crit:
                        hyp.status = crit.classify(prop_value, prop_ci)
                    if hasattr(self.tracker, "record_outcome"):
                        from bionexus.derivation import build
                        inst, ver = self._instrument()
                        self.tracker.record_outcome(hyp, extra={
                            "derivation": build(
                                instrument=inst, version=ver,
                                quantity=crit.metric,
                                counts={"wells": len(result.records),
                                        "replicates_at_gate_dose":
                                            len(top_vals) if cand_vals else 1},
                                metric=crit.metric,
                                method="property readout: replicate mean "
                                       "at top dose" if prop_ci else
                                       "property readout at highest dose "
                                       "(single reading — no variance "
                                       "estimate)",
                                ci="replicate bootstrap 95%" if prop_ci
                                   else None,
                                criteria_metric=crit.metric,
                                criteria_direction=crit.direction,
                                criteria_threshold=crit.threshold),
                            "direction": crit.direction})
                    verdicts.append((hyp.hypothesis_id, hyp.candidate,
                                     hyp.status, prop_value))
                    unit = ""
                    for rec in result.records:
                        d_ = rec if isinstance(rec, dict) else rec.model_dump()
                        if d_.get("sample") == hyp.candidate:
                            unit = d_.get("unit", "")
                            break
                    self.notify(f"hypothesis {hyp.hypothesis_id} "
                                f"({hyp.candidate}): {hyp.status.upper()} — "
                                f"{crit.metric} {prop_value} {unit} vs "
                                f"threshold {crit.threshold}")
                    continue
                if match and hyp.status in ("proposed", "designed", "tested") and match["ic50_um"]:
                    # attach evidence directly (measurement already fitted)
                    hyp.observed_value = match["ic50_um"]
                    hyp.observed_ci = match.get("ic50_ci")
                    hyp.evidence_run_id = event.path.stem  # run ↔ verdict link
                    hyp.qc_passed = (result.z_prime or 0) >= QC_ZPRIME_FLOOR
                    if hyp.criteria:
                        if not match.get("ic50_ci"):
                            # NO-USABLE-CI RULE: a fit whose residual bootstrap
                            # collapsed (hill-no-ci) or that leans on a
                            # 2-point interpolation carries unknown
                            # uncertainty — exactly when a binary call is
                            # least defensible. Abstain, don't guess.
                            hyp.status = "inconclusive"
                        else:
                            hyp.status = hyp.criteria.classify(
                                match["ic50_um"], match["ic50_ci"])
                    if hasattr(self.tracker, "record_outcome"):
                        from bionexus.derivation import build
                        inst, ver = self._instrument()
                        crit = hyp.criteria
                        self.tracker.record_outcome(hyp, extra={
                            "derivation": build(
                                instrument=inst, version=ver,
                                quantity=getattr(result, "response_unit", None),
                                counts={"wells": len(result.records)},
                                metric=crit.metric if crit else None,
                                method=match.get("fit_method"),
                                ci="residual bootstrap 95%"
                                   if match.get("ic50_ci") else None,
                                criteria_metric=crit.metric if crit else None,
                                criteria_direction=crit.direction if crit else None,
                                criteria_threshold=crit.threshold if crit else None)})
                    verdicts.append((hyp.hypothesis_id, hyp.candidate, hyp.status,
                                     match["ic50_um"]))
                    ci_txt = (f" (95% CI {match['ic50_ci'][0]}–{match['ic50_ci'][1]})"
                              if match.get("ic50_ci") else "")
                    self.notify(f"hypothesis {hyp.hypothesis_id} ({hyp.candidate}): "
                                f"{hyp.status.upper()} (preliminary — pending "
                                f"orthogonal confirmation) — IC50 {match['ic50_um']} uM"
                                f"{ci_txt} vs threshold "
                                f"{hyp.criteria.threshold if hyp.criteria else '?'}")
        # scientist-facing diary line
        best = sorted(((c, r["ic50_um"]) for c, r in result.analysis["compounds"].items()
                       if r["ic50_um"]), key=lambda t: t[1])
        if best:
            candidate, ic50 = best[0]
            self.notify(f"recommendation: best binder so far is {candidate} "
                        f"(IC50 {ic50} uM) — next: confirm with orthogonal assay")
            if self.auto_confirm and candidate not in self._confirm_submitted:
                self._submit_confirmation(candidate, ic50)
        summary = {"compounds": len(result.analysis["compounds"]),
                   "z_prime": result.z_prime, "verdicts": verdicts}
        return summary

    _TERMINAL = ("validated", "confirmed", "invalidated", "refuted",
                 "inconclusive")

    def _record_failure_mode(self, event, verdict: dict) -> None:
        if self.store is None:
            return
        try:
            from bionexus.core.contracts import Envelope, EventType
            from bionexus.core.interfaces import record_for, system_actor
            self.store.append(record_for(
                Envelope(experiment_branch_id=self.branch_id),
                EventType.gate_decision, system_actor("harness"),
                decision={"kind": "failure-mode",
                          "file": getattr(event.path, "name", "?"),
                          **verdict}))
        except Exception:
            pass

    def _instrument(self) -> tuple[str | None, str | None]:
        lab = getattr(self.gateway, "lab", None) or \
            getattr(getattr(self.gateway, "_gw", None), "lab", None)
        if lab is None:
            return None, None
        return getattr(lab, "name", None), getattr(lab, "version", None)

    def _handle_adaptive(self, event) -> None:
        """Bayesian sequential dosing: each well updates the posterior over
        IC50; the next dose is the most informative unused point on the
        ladder; after `adaptive_wells` the posterior median + credible
        interval decide the verdict (CI-aware, same gate as fixed runs)."""
        from bionexus.adaptive import DoseDesigner
        from bionexus.labread import read_plate
        from bionexus.physfail import classify as _fm

        result = read_plate(event.path, max_response=self.max_response)
        # physical-failure check before ANY posterior update (P1-6):
        # a saturated dark well must not contaminate the belief state
        vals = [r["value"] for r in result.records
                if isinstance(r.get("value"), (int, float))]
        phys = _fm(vals) if vals else _fm([], error="no readings")
        if phys["kind"] == "physical":
            self.notify(f"⚠ physical failure mode on adaptive well "
                        f"{event.path.name}: {phys['evidence']} — "
                        f"{phys['action']}; well discarded, posterior "
                        f"unchanged")
            self._record_failure_mode(event, phys)
            return None
        obs = {}
        for r in result.records:
            if not r.get("control") and r.get("conc_um") is not None:
                obs[r["sample"]] = (r["conc_um"], r["value"])
        for cand, (conc, value) in obs.items():
            hyp = next((h for h in (self.tracker.hypotheses.values()
                                    if self.tracker else [])
                        if h.candidate == cand), None)
            if hyp is None or hyp.status in self._TERMINAL:
                continue
            d = self._designers.get(cand)
            if d is None:
                d = self._designers[cand] = DoseDesigner(
                    doses=self.dose_ladder, first_dose=conc)
            if conc not in d.used:
                d.observe(conc, value)
                if len(d.used) == 1:
                    self.notify(f"adaptive screen {cand}: {value:.0f} RFU @ "
                                f"{conc:g} µM")
                else:
                    est0, ci0 = d.estimate()
                    self.notify(f"adaptive: {cand} well @ {conc:g} µM -> "
                                f"IC50 posterior {est0:.2f} µM "
                                f"(CrI {ci0[0]:.2f}–{ci0[1]:.2f})")
            if len(d.used) < self.adaptive_wells:
                nxt = d.next_dose()
                if nxt:
                    run_id = self._submit_adaptive_well(cand, nxt, hyp)
                    if run_id:
                        self.notify(f"adaptive: {cand} next dose {nxt:g} µM "
                                    f"-> run {run_id} "
                                    f"({len(d.used)}/{self.adaptive_wells} wells)")
                        continue
            est, ci = d.estimate()
            hyp.observed_value = est
            hyp.observed_ci = ci
            hyp.evidence_run_id = event.path.stem
            hyp.qc_passed = True
            hyp.status = (hyp.criteria.classify(est, ci) if hyp.criteria
                          else "tested")
            if self.tracker and hasattr(self.tracker, "record_outcome"):
                from bionexus.derivation import build
                inst, ver = self._instrument()
                self.tracker.record_outcome(hyp, extra={
                    "design": {"mode": "adaptive-bayesian",
                               "wells": [round(x, 3) for x in d.used]},
                    "derivation": build(
                        instrument=inst, version=ver,
                        quantity=getattr(result, "response_unit", None),
                        counts={"wells": len(d.used)},
                        metric=hyp.criteria.metric if hyp.criteria else None,
                        method="Bayesian grid posterior (adaptive dose series)",
                        ci="posterior 95% credible interval",
                        criteria_metric=hyp.criteria.metric if hyp.criteria else None,
                        criteria_direction=hyp.criteria.direction if hyp.criteria else None,
                        criteria_threshold=hyp.criteria.threshold if hyp.criteria else None)})
            self.notify(f"adaptive verdict {cand}: IC50 {est:.2f} µM "
                        f"(95% CrI {ci[0]:.2f}–{ci[1]:.2f}) after "
                        f"{len(d.used)} wells -> {hyp.status.upper()}")
            self._designers.pop(cand, None)
        return None

    def _submit_adaptive_well(self, candidate: str, conc: float,
                              hyp) -> str | None:
        from bionexus.core.contracts import (
            Envelope, ProtocolOp, ProtocolStep, ProtocolSubmission,
            ReagentSpec, SampleKind, SampleSpec,
        )
        protocol = ProtocolSubmission(
            envelope=Envelope(experiment_branch_id=self.branch_id),
            title=f"adaptive-{candidate}-{conc:g}uM",
            assay_type=hyp.assay_type or "binding",
            steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense,
                                params={"volume_ul": 50})],
            samples=[SampleSpec(sample_id=candidate, kind=SampleKind.compound,
                                concentration=f"{conc:g}uM"),
                     SampleSpec(sample_id="ctrl-neg", kind=SampleKind.buffer,
                                concentration="10uM")],
            reagents=[ReagentSpec(name="assay-buffer", amount="5 mL",
                                  bsl_level=1)],
        )
        run_id, rejection = self.gateway.submit(protocol)
        if rejection:
            self.notify(f"adaptive well for {candidate} blocked: {rejection}")
            return None
        if self.export_fn:
            self.export_fn(run_id, candidate, [f"{conc:g}uM"])
        if self.tracker:
            self.tracker.attach_test(hyp, protocol, run_id)
        return run_id

    def _handle_confirmation(self, event, conf: dict) -> dict[str, Any]:
        """Orthogonal confirmation means AGREEMENT between methods, not just
        a second curve: overlapping 95% intervals (fallback: within 3x when
        a CI is missing) -> the preliminary call is re-tested against the
        pre-registered gate on the SECOND read. Bad QC or a PHYSICAL plate
        failure yields inconclusive — and every confirmation outcome,
        including the property-metric ones, is provenance-recorded with the
        comparison and the rule used."""
        from bionexus.labread import QC_ZPRIME_FLOOR, read_plate, replicate_ci
        from bionexus.physfail import classify as _fm

        cand, primary = conf["candidate"], conf["primary_ic50"]
        primary_ci = conf.get("primary_ci")
        result = read_plate(event.path, max_response=self.max_response)
        recs = [m if isinstance(m, dict) else m.model_dump()
                for m in result.records]
        hyp = next((h for h in (self.tracker.hypotheses.values()
                                if self.tracker else [])
                    if h.candidate == cand), None)
        crit = hyp.criteria if hyp else None
        property_metric = bool(crit
                               and crit.metric not in ("ic50_um", "value"))

        # a physically failed plate confirms nothing (P1-6): flag for the
        # operator, record the failure mode, abstain — never retry blindly
        vals = [r.get("value") for r in recs
                if isinstance(r.get("value"), (int, float))]
        phys = _fm(vals) if vals else _fm([], error="no readings")
        if phys["kind"] == "physical":
            self.notify(f"\u26a0 physical failure mode on confirmation plate "
                        f"{event.path.name}: {phys['evidence']} — "
                        f"{phys['action']}; no confirmation verdict")
            self._record_failure_mode(event, phys)
            return self._finish_confirmation(
                event, conf, hyp, secondary=None, secondary_ci=None,
                ratio=None, agreed=False, rule="physical-failure",
                qc_ok=False, force_status="inconclusive", result=result)

        qc_ok = (result.z_prime or 0) >= QC_ZPRIME_FLOOR
        if property_metric:
            # property metrics are confirmed as they are judged: the
            # SECOND method's readout at the top dose, with its own
            # replicate CI, is decided against the SAME pre-registered
            # gate. No fake 1.0 ratio; agreement = same gate decision
            # (computed in _finish_confirmation via classify)
            pairs = [(r.get("conc_um"), r.get("value")) for r in recs
                     if r.get("sample") == cand and not r.get("control")
                     and isinstance(r.get("conc_um"), (int, float))
                     and isinstance(r.get("value"), (int, float))]
            if pairs:
                top = max(c for c, _ in pairs)
                top_vals = [v for c, v in pairs if c == top]
                secondary = sum(top_vals) / len(top_vals)
                secondary_ci = replicate_ci(top_vals)
            else:
                singles = [r.get("value") for r in recs
                           if r.get("sample") == cand
                           and not r.get("control")
                           and isinstance(r.get("value"), (int, float))]
                secondary = sum(singles) / len(singles) if singles else None
                secondary_ci = None
            ratio = None
            agreed = None            # gate-direction agreement decided below
            rule = "gate-direction"
        else:
            match = result.analysis["compounds"].get(cand) or {}
            secondary = match.get("ic50_um")
            secondary_ci = match.get("ic50_ci")
            ratio = (max(primary, secondary) / min(primary, secondary)
                     if primary and secondary else None)
            if primary_ci and secondary_ci:
                # interval overlap is a stronger agreement test than a
                # point ratio: two methods whose CIs overlap cannot
                # distinguish each other
                agreed = min(primary_ci[1], secondary_ci[1]) >= max(
                    primary_ci[0], secondary_ci[0])
                rule = "ci-overlap"
            else:
                agreed = ratio is not None and ratio <= 3.0
                rule = "3x-ratio"
        return self._finish_confirmation(
            event, conf, hyp, secondary, secondary_ci, ratio, agreed,
            rule, qc_ok, result=result)

    def _finish_confirmation(self, event, conf: dict, hyp, secondary,
                             secondary_ci, ratio, agreed, rule: str,
                             qc_ok: bool, force_status: str | None = None,
                             result=None) -> dict[str, Any]:
        """One status machine + one provenance tail for ALL confirmation
        shapes (IC50-fit, property readout, physical failure). Nothing
        that decides a hypothesis leaves without a record."""
        cand = conf["candidate"]
        primary = conf["primary_ic50"]
        primary_ci = conf.get("primary_ci")
        crit = hyp.criteria if hyp else None
        pri_status = hyp.status if hyp else "tested"
        property_metric = bool(crit
                               and crit.metric not in ("ic50_um", "value"))
        status = force_status
        if status is None and (not qc_ok or secondary is None):
            status = "inconclusive"
        elif status is None and property_metric:
            # agreement for a property metric = the second method makes the
            # SAME gate decision as the first (direction-aware). A flipped
            # decision is a disagreement, even though both are decisive.
            cls = crit.classify(secondary, secondary_ci)
            pri_hit = pri_status in ("validated", "confirmed")
            if cls == "inconclusive":
                agreed, status = False, "inconclusive"
            elif pri_hit:
                agreed = cls == "validated"
                status = "confirmed" if agreed else "refuted"
            else:
                agreed = cls == "invalidated"
                status = "refuted" if agreed else "confirmed"
        elif status is None and agreed is False:
            # methods disagree: a claimed HIT that doesn't reproduce is
            # refuted; a claimed NON-HIT that disagrees is simply unclear
            status = "refuted" if pri_status in ("validated", "confirmed") \
                else "inconclusive"
        elif status is None:
            # agreement VERIFIES the preliminary verdict's direction —
            # confirmed only for hits, refuted for non-hits, and borderline
            # CIs stay inconclusive no matter how well the methods agree
            cls = (crit.classify(secondary, secondary_ci)
                   if (crit and secondary is not None) else "inconclusive")
            pri_cls = (crit.classify(primary, primary_ci) if crit
                       else cls)
            if cls == "inconclusive" or pri_cls == "inconclusive":
                status = "inconclusive"
                self.notify(f"gate honesty: {cand} methods agree but a "
                            f"borderline CI straddles threshold "
                            f"{crit.threshold if crit else '?'} "
                            f"-> inconclusive")
            elif pri_status in ("validated", "confirmed"):
                status = "confirmed" if cls == "validated" else "refuted"
            else:
                status = "refuted" if cls == "invalidated" else "confirmed"

        if property_metric:
            unit = next((r.get("unit", "") for r in
                         (m if isinstance(m, dict) else m.model_dump()
                          for m in result.records)
                         if r.get("sample") == cand), "") if result else ""
            self.notify(f"orthogonal confirmation for {cand}: "
                        f"{crit.metric if crit else '?'} {secondary} {unit} "
                        f"vs threshold {crit.threshold if crit else '?'} "
                        f"-> {status.upper()}")
        elif ratio:
            self.notify(f"orthogonal confirmation for {cand}: primary "
                        f"{primary:.2f} vs secondary {secondary:.2f} \u00b5M "
                        f"(ratio {ratio:.1f}x, rule {rule}) -> "
                        f"{status.upper()}")
        else:
            self.notify(f"orthogonal confirmation for {cand}: no usable "
                        f"secondary fit -> {status.upper()}")

        if self.tracker:
            for h in self.tracker.hypotheses.values():
                if h.candidate != cand:
                    continue
                if secondary is not None:
                    h.observed_value = secondary
                    h.observed_ci = secondary_ci
                elif not property_metric:
                    h.observed_value = primary
                    h.observed_ci = primary_ci
                # a failed property confirmation keeps the primary's own
                # property readout — the ic50 fit on a property plate is
                # meaningless and must not overwrite evidence
                h.evidence_run_id = event.path.stem
                h.qc_passed = qc_ok
                h.status = status
                if not hasattr(self.tracker, "record_outcome"):
                    break
                from bionexus.derivation import build
                inst, ver = self._instrument()
                _der = build(
                    instrument=inst, version=ver,
                    quantity=(getattr(result, "response_unit", None)
                              if result is not None else None),
                    counts={"wells": len(result.records) if result else 0},
                    metric=crit.metric if crit else None,
                    method=("property orthogonal re-measurement"
                            if property_metric else
                            "orthogonal re-measurement + fit"),
                    ci=("residual bootstrap 95%" if (rule == "ci-overlap")
                        else "replicate bootstrap 95%"
                        if (property_metric and secondary_ci) else None),
                    criteria_metric=crit.metric if crit else None,
                    criteria_direction=crit.direction if crit else None,
                    criteria_threshold=crit.threshold if crit else None)
                self.tracker.record_outcome(h, extra={
                    "derivation": _der,
                    "confirmation": {
                        "run_id": event.path.stem,
                        "primary_ic50": primary,
                        "primary_ci": list(primary_ci) if primary_ci else None,
                        "secondary_ic50": secondary,
                        "secondary_ci": (list(secondary_ci)
                                         if secondary_ci else None),
                        "ratio": round(ratio, 2) if ratio else None,
                        "agreed": bool(agreed) if agreed is not None
                        else status == "confirmed",
                        "rule": rule}})
                break
        return {"confirmation": status, "candidate": cand,
                "primary": primary, "secondary": secondary, "ratio": ratio}

    def _submit_confirmation(self, candidate: str, ic50: float) -> str | None:
        """Close the loop: design + safety-submit the orthogonal confirmation.

        Orthogonal means a DIFFERENT method: the confirmation assay is
        chosen from the hypothesis's own assay type — an enzymatic primary
        is confirmed by binding, not by repeating enzymatic (P1-1)."""
        from bionexus.core.contracts import (
            Envelope, ProtocolOp, ProtocolStep, ProtocolSubmission,
            ReagentSpec, SampleKind, SampleSpec,
        )

        hyp = next((h for h in (self.tracker.hypotheses.values()
                                if self.tracker else [])
                    if h.candidate == candidate), None)
        primary_assay = (hyp.assay_type if hyp else "") or "binding"
        assay = (self.ORTHOGONAL_ASSAY.get(primary_assay)
                 or ("binding" if primary_assay != "binding" else "enzymatic"))
        protocol = ProtocolSubmission(
            envelope=Envelope(experiment_branch_id=self.branch_id),
            title=f"auto-confirmation-{candidate}",
            assay_type=assay,
            steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense, params={"volume_ul": 50})],
            samples=[SampleSpec(sample_id=candidate, kind=SampleKind.compound,
                                concentration="10uM"),
                     SampleSpec(sample_id="ctrl-neg", kind=SampleKind.buffer,
                                concentration="10uM")],
            reagents=[ReagentSpec(name="assay-buffer", amount="5 mL", bsl_level=1)],
        )
        run_id, rejection = self.gateway.submit(protocol)
        if rejection:
            self.notify(f"confirmation assay for {candidate} BLOCKED by safety: {rejection}")
            return None
        self._confirm_submitted.add(candidate)
        primary_ci = None
        if self.tracker:
            for hyp in self.tracker.hypotheses.values():
                if hyp.candidate == candidate:
                    primary_ci = hyp.observed_ci
        self._confirmations[run_id] = {"candidate": candidate,
                                       "primary_ic50": ic50,
                                       "primary_ci": primary_ci}
        if self.export_fn:
            self.export_fn(run_id, candidate)   # confirmation runs get outputs too
        # keep the run↔hypothesis link in provenance, not just in memory
        if self.tracker:
            for hyp in self.tracker.hypotheses.values():
                if hyp.candidate == candidate and self.tracker.hypotheses.get(hyp.hypothesis_id):
                    self.tracker.attach_test(hyp, protocol, run_id)
                    break
        self.notify(f"sending orthogonal confirmation assay for {candidate} "
                    f"(safety-approved) -> run {run_id}")
        return run_id


def watch(inbox: str | Path, store: Any = None, tracker: Any = None,
          stop_after: int | None = None, poll_secs: float = 1.0,
          notify: Callable[[str], None] | None = None,
          gateway: Any = None, branch_id: str = "autonomous-loop") -> None:
    monitor = DeviceMonitor(inbox, poll_secs=poll_secs)
    agent = AutoAnalysisAgent(store=store, tracker=tracker, notify=notify,
                              gateway=gateway, branch_id=branch_id)
    for event in monitor.events(stop_after=stop_after):
        agent.handle(event)
