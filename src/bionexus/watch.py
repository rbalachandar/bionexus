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
        from bionexus.labread import read_plate

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
                    f"Z'={result.z_prime}")

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
                        prop_value = max(cand_vals)[1]
                    elif any_val is not None:
                        prop_value = any_val
                if prop_value is not None and hyp.status in (
                        "proposed", "designed", "tested"):
                    hyp.observed_value = prop_value
                    hyp.observed_ci = None
                    hyp.evidence_run_id = event.path.stem
                    hyp.qc_passed = (result.z_prime or 0) >= 0.5
                    if crit:
                        hyp.status = crit.classify(prop_value, None)
                    if hasattr(self.tracker, "record_outcome"):
                        from bionexus.derivation import build
                        inst, ver = self._instrument()
                        self.tracker.record_outcome(hyp, extra={
                            "derivation": build(
                                instrument=inst, version=ver,
                                quantity=crit.metric,
                                counts={"wells": len(result.records)},
                                metric=crit.metric,
                                method="property readout at highest dose",
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
                    hyp.qc_passed = (result.z_prime or 0) >= 0.5
                    if hyp.criteria:
                        hyp.status = hyp.criteria.classify(
                            match["ic50_um"], match.get("ic50_ci"))
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

        result = read_plate(event.path, max_response=self.max_response)
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
        """Orthogonal confirmation means AGREEMENT between methods, not just a
        second curve: |primary/secondary| within 3x -> confirmed; otherwise
        refuted; bad QC -> inconclusive. Provenance carries the comparison."""
        from bionexus.labread import read_plate
        cand, primary = conf["candidate"], conf["primary_ic50"]
        result = read_plate(event.path, max_response=self.max_response)
        hyp_tmp0 = next((h for h in (self.tracker.hypotheses.values()
                                     if self.tracker else [])
                         if h.candidate == cand), None)
        crit0 = hyp_tmp0.criteria if hyp_tmp0 else None
        if crit0 is not None and crit0.metric not in ("ic50_um", "value"):
            # property metric: the confirmation readout is the recorded
            # value at the highest dose of the orthogonal run, compared
            # like-for-like; the gate decides, not a ratio
            vals = []
            for m in result.records:
                d_ = m if isinstance(m, dict) else m.model_dump()
                if d_.get("sample") == cand and not d_.get("control"):
                    vals.append(d_.get("value"))
            secondary = max((v for v in vals
                             if isinstance(v, (int, float))), default=None)
            secondary_ci = None
            primary_ci = None
            ratio = 1.0 if secondary is not None else None
            agreed = ratio is not None
            qc_ok = (result.z_prime or 0) >= 0.5
            hyp_tmp = hyp_tmp0
            pri_status = hyp_tmp.status if hyp_tmp else "tested"
            cls = (crit0.classify(secondary, None)
                   if secondary is not None else "inconclusive")
            if not qc_ok or secondary is None:
                status = "inconclusive"
            elif pri_status in ("validated", "confirmed"):
                status = "confirmed" if cls == "validated" else "refuted"
            else:
                status = "refuted" if cls == "invalidated" else "confirmed"
            unit = next((d_.get("unit", "") for d_ in
                         (m if isinstance(m, dict) else m.model_dump()
                          for m in result.records)
                         if d_.get("sample") == cand), "")
            self.notify(f"orthogonal confirmation for {cand}: "
                        f"{crit0.metric} {secondary} {unit} vs threshold "
                        f"{crit0.threshold} -> {status.upper()}")
            if self.tracker:
                for hyp in self.tracker.hypotheses.values():
                    if hyp.candidate == cand:
                        hyp.observed_value = secondary
                        hyp.evidence_run_id = event.path.stem
                        hyp.qc_passed = qc_ok
                        hyp.status = status
                        hyp.observed_ci = None
                return {"candidate": cand, "status": status}
        match = result.analysis["compounds"].get(cand) or {}
        secondary = match.get("ic50_um")
        secondary_ci = match.get("ic50_ci")
        primary_ci = conf.get("primary_ci")
        qc_ok = (result.z_prime or 0) >= 0.5
        ratio = (max(primary, secondary) / min(primary, secondary)
                 if primary and secondary else None)
        if primary_ci and secondary_ci:
            # interval overlap is a stronger agreement test than a point
            # ratio: two methods whose CIs overlap cannot distinguish each other
            agreed = min(primary_ci[1], secondary_ci[1]) >= max(
                primary_ci[0], secondary_ci[0])
        else:
            agreed = ratio is not None and ratio <= 3.0
        hyp_tmp = next((h for h in (self.tracker.hypotheses.values()
                                    if self.tracker else [])
                        if h.candidate == cand), None)
        pri_status = hyp_tmp.status if hyp_tmp else "tested"
        if not qc_ok or ratio is None:
            status = "inconclusive"
        elif not agreed:
            # methods disagree: a claimed HIT that doesn't reproduce is
            # refuted; a claimed NON-HIT that disagrees is simply unclear
            status = "refuted" if pri_status in ("validated", "confirmed") \
                else "inconclusive"
        else:
            # agreement VERIFIES the preliminary verdict's direction —
            # confirmed only for hits, refuted for non-hits, and borderline
            # CIs stay inconclusive no matter how well the methods agree
            cls = (hyp_tmp.criteria.classify(secondary, secondary_ci)
                   if (hyp_tmp and hyp_tmp.criteria and secondary is not None)
                   else "inconclusive")
            pri_cls = (hyp_tmp.criteria.classify(primary, primary_ci)
                       if (hyp_tmp and hyp_tmp.criteria) else cls)
            if cls == "inconclusive" or pri_cls == "inconclusive":
                status = "inconclusive"
                self.notify(f"gate honesty: {cand} methods agree but a "
                            f"borderline CI straddles threshold "
                            f"{hyp_tmp.criteria.threshold if hyp_tmp and hyp_tmp.criteria else '?'} "
                            f"-> inconclusive")
            elif pri_status in ("validated", "confirmed"):
                status = "confirmed" if cls == "validated" else "refuted"
            else:
                status = "refuted" if cls == "invalidated" else "confirmed"
        self.notify(f"orthogonal confirmation for {cand}: primary {primary:.2f} vs "
                    f"secondary {secondary:.2f} µM (ratio {ratio:.1f}x) -> {status.upper()}"
                    if ratio else f"orthogonal confirmation for {cand}: no usable "
                    f"secondary fit -> {status.upper()}")
        if self.tracker:
            for hyp in self.tracker.hypotheses.values():
                if hyp.candidate == cand:
                    hyp.observed_value = secondary or primary
                    hyp.evidence_run_id = event.path.stem
                    hyp.qc_passed = qc_ok
                    hyp.status = status
                    hyp.observed_ci = secondary_ci
                    if hasattr(self.tracker, "record_outcome"):
                        from bionexus.derivation import build
                        inst, ver = self._instrument()
                        _der = build(
                            instrument=inst, version=ver,
                            quantity=getattr(result, "response_unit", None),
                            counts={"wells": len(result.records)},
                            metric=hyp_tmp.criteria.metric if hyp_tmp and hyp_tmp.criteria else None,
                            method="orthogonal re-measurement + fit",
                            ci="residual bootstrap 95%" if secondary_ci else None,
                            criteria_metric=hyp_tmp.criteria.metric
                            if hyp_tmp and hyp_tmp.criteria else None,
                            criteria_direction=hyp_tmp.criteria.direction
                            if hyp_tmp and hyp_tmp.criteria else None,
                            criteria_threshold=hyp_tmp.criteria.threshold
                            if hyp_tmp and hyp_tmp.criteria else None)
                        self.tracker.record_outcome(hyp, extra={
                            "derivation": _der,
                            "confirmation": {
                                "run_id": event.path.stem,
                                "primary_ic50": primary,
                                "primary_ci": list(primary_ci) if primary_ci else None,
                                "secondary_ic50": secondary,
                                "secondary_ci": list(secondary_ci) if secondary_ci else None,
                                "ratio": round(ratio, 2) if ratio else None,
                                "agreed": agreed,
                                "rule": ("ci-overlap" if (primary_ci and secondary_ci)
                                         else "3x-ratio")}})
                    break
        return {"confirmation": status, "candidate": cand,
                "primary": primary, "secondary": secondary, "ratio": ratio}

    def _submit_confirmation(self, candidate: str, ic50: float) -> str | None:
        """Close the loop: design + safety-submit the orthogonal confirmation."""
        from bionexus.core.contracts import (
            Envelope, ProtocolOp, ProtocolStep, ProtocolSubmission,
            ReagentSpec, SampleKind, SampleSpec,
        )

        assay = self.ORTHOGONAL_ASSAY.get("binding", "enzymatic")
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
