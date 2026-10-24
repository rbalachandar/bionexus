"""Plate-reader assay analysis profile.

The FIRST analysis profile: wraps `bionexus.labread` (auto-detect, parse,
normalize, Hill fit with bootstrap CI, Z′, regime gate) behind the generic
analysis lifecycle. Everything plate-specific — wells, control classes,
%inhibition, dose-response, censoring — stays HERE; the shared contract
never learns these words.

Honesty rules carried over unchanged:
- a CI straddling the registered threshold ABSTAINS (inconclusive);
- a fit without a usable CI (unstable bootstrap / linear-interp fallback)
  can NOT earn a decisive call;
- right-censored / single-dose entities get `no_call` with the reason, not
  a fabricated number;
- the regime gate (CS06) refuses absolute claims on unvalidated
  normalization frames — `assert_regimes` is NOT configurable here;
  research bypasses belong to declared reproduction studies in case-study
  scripts, never to the scientist workflow.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from bionexus.core.contracts.analysis import (AnalysisDiagnostic,
                                              AnalysisState, EvidenceOrigin,
                                              PreliminaryCall)
from bionexus.core.hypothesis import SuccessCriteria

PROFILE_NAME = "plate_assay"
PROFILE_VERSION = 1


class PlateAssayConfig(BaseModel):
    """Scientist-confirmed interpretation of ONE plate. Every field the
    engine would otherwise infer silently is explicit here."""
    metric: str = "ic50_um"
    direction: str = "min"               # min = lower IC50 is better
    threshold: float | None = None       # registered gate; None => estimates only
    cycles: str = "last"                 # kinetic reduction: last | first | mean
    normalize: str | None = None         # None | "pct_inhibition"
    max_response: float | None = None    # None => 3-param observed-max fit
    positive_controls: list[str] = []    # sample ids FORCED into the pos class
    negative_controls: list[str] = []    # sample ids FORCED into the neg class
    evidence_origin: EvidenceOrigin = EvidenceOrigin.measured

    model_config = ConfigDict(extra="forbid")


# profile seam: the generic lifecycle reads this (see experiment_analysis)
CONFIG_TYPE = PlateAssayConfig


def _engine_version() -> str:
    try:
        from importlib.metadata import version
        return version("bionexuslab")
    except Exception:  # noqa: BLE001 — editable installs may lack metadata
        return "unknown"


def _override_map(cfg: PlateAssayConfig) -> dict[str, str] | None:
    """Scientist-confirmed sample->class map (None when unset)."""
    if not (cfg.positive_controls or cfg.negative_controls):
        return None
    m = {s.strip(): "pos" for s in cfg.positive_controls}
    m.update({s.strip(): "neg" for s in cfg.negative_controls})
    return m


def _read(path: Path, cfg: PlateAssayConfig,
          layout_path: Path | None = None):
    """read_plate + scientist-confirmed control classes + optional layout
    join, folded in. The override map re-classes wells; normalization
    refusal is RECORDED as a refusal (no silent fall-back to raw values
    dressed as normalized); refused regimes keep their refusal."""
    from bionexus import labread
    r = labread.read_plate(
        path, max_response=cfg.max_response, cycles=cfg.cycles,
        normalize=None if _override_map(cfg) else cfg.normalize,
        layout=layout_path, assert_regimes=True)
    overrides = _override_map(cfg)
    if not overrides:
        return r
    for rec in r.records:
        if str(rec.get("sample", "")).strip() in overrides:
            rec["control"] = True
    if r.regime and not r.regime.get("validated"):
        return r
    if cfg.normalize == "pct_inhibition":
        if not labread.to_pct_inhibition(r.records,
                                         control_classes=overrides):
            r.analysis = dict(labread.analyze_records(
                [], cfg.max_response, control_classes=overrides))
            r.analysis["normalization_refused"] = True
            r.analysis["normalization_note"] = (
                "requested %inhibition normalization is impossible on this "
                "plate (needs >=2 wells of BOTH control classes with blank "
                "signal > positive) — fits refused rather than run on "
                "mislabeled raw values")
            return r
    r.analysis = labread.analyze_records(r.records, cfg.max_response,
                                         control_classes=overrides)
    return r


def records_for(path: Path, cfg: PlateAssayConfig,
                layout_path: Path | None = None) -> list[dict[str, Any]]:
    """The exact well records behind a stored analysis (same fold-ins as
    _read), for CSV export. Never mutates the source."""
    return _read(path, cfg, layout_path).records


def _wells(r, cfg: PlateAssayConfig) -> list[dict[str, Any]]:
    """Compact well view for the plate map: identity, mapping coverage,
    control CLASS (not just is-control), channel. Wells without geometry
    (deposits) simply have no row."""
    from bionexus import labread
    overrides = _override_map(cfg)
    out = []
    for rec in r.records:
        well = str(rec.get("well") or "")
        if not well:
            continue
        sample = str(rec.get("sample", ""))
        out.append({"well": well, "sample": sample,
                    "conc_um": rec.get("conc_um"), "value": rec["value"],
                    "control": labread.control_class(sample, overrides),
                    "channel": rec.get("channel")})
    return out


def preview(source: Path, cfg: PlateAssayConfig,
            layout_path: Path | None = None) -> dict[str, Any]:
    """Parse-level interpretation ONLY: no fits published, no verdicts.

    Returns the preview payload + the profile's opinion of the session
    state (a regime refusal or missing controls holds the session, it
    does not fabricate a pass)."""
    r = _read(source, cfg, layout_path)
    diags: list[AnalysisDiagnostic] = []
    if r.format in ("unknown", "xlsx-unknown"):
        diags.append(AnalysisDiagnostic(
            severity="blocker", code="unknown_format",
            message="export format not recognized — no rows parsed"))
    if not r.records:
        diags.append(AnalysisDiagnostic(
            severity="blocker", code="no_wells",
            message="no interpretable wells in the export"))
    if r.z_prime is None:
        diags.append(AnalysisDiagnostic(
            severity="warning", code="no_controls",
            message="no control wells detected — QC unavailable; confirm "
                    "control classes or supply positive/negative controls"))
    elif r.z_prime_kind != "real":
        diags.append(AnalysisDiagnostic(
            severity="warning", code="heuristic_zprime",
            message="control-spread heuristic Z'~ (real Z' needs BOTH "
                    "control classes, >=2 wells each)"))
    has_doses = any(rec.get("conc_um") is not None for rec in r.records)
    if not has_doses and r.format not in ("pubchem",):
        diags.append(AnalysisDiagnostic(
            severity="warning", code="no_layout",
            message="no concentrations bound — pass a plate-layout file "
                    "for dose-response fits"))
    needs: list[str] = []
    if cfg.positive_controls or cfg.negative_controls:
        known = {str(rec.get("sample", "")).strip() for rec in r.records}
        for name in cfg.positive_controls + cfg.negative_controls:
            if name.strip() not in known:
                needs.append(name)
    if needs:
        diags.append(AnalysisDiagnostic(
            severity="blocker", code="unknown_control_ids",
            message=f"configured control ids not present on the plate: "
                    f"{sorted(set(needs))}"))
    if r.regime and not r.regime.get("validated"):
        state = AnalysisState.unsupported_regime
    elif any(d.severity == "blocker" for d in diags):
        state = AnalysisState.needs_mapping
    else:
        state = AnalysisState.preview_ready
    return {
        "profile": PROFILE_NAME,
        "profile_version": PROFILE_VERSION,
        "state": (state.value if hasattr(state, "value") else state),
        "format": r.format,
        "n_wells": len(r.records),
        "channels": list(r.channels),
        "response_unit": r.response_unit,
        "instrument": dict(r.instrument or {}),
        "z_prime": r.z_prime,
        "z_prime_kind": r.z_prime_kind,
        "controls_detected": r.analysis.get("controls_detected", 0),
        "regime": dict(r.regime) if r.regime else None,
        "samples": sorted({str(rec.get("sample")) for rec in r.records
                           if not rec.get("control")}),
        "wells": _wells(r, cfg),
        "has_doses": has_doses,
        "diagnostics": [d.model_dump() for d in diags],
        "needs_confirmation": ["control_classes"] if r.z_prime is None else [],
        "evidence_origin": cfg.evidence_origin.value,
    }


def analyze(source: Path, cfg: PlateAssayConfig,
            source_sha256: str | None = None,
            layout_path: Path | None = None) -> dict[str, Any]:
    """Deterministic analysis + threshold-conditional preliminary calls.

    Same bytes + same config => same payload. Verdicts exist ONLY where a
    threshold was registered and the regime/CI physics support a call."""
    r = _read(source, cfg, layout_path)
    from bionexus import labread

    compounds = r.analysis.get("compounds", {})
    regime_refused = bool(r.analysis.get("regime_refusal"))
    norm_refused = bool(r.analysis.get("normalization_refused"))
    criteria = None
    if cfg.threshold is not None:
        criteria = SuccessCriteria(metric=cfg.metric, direction=cfg.direction,
                                   threshold=cfg.threshold)

    calls: list[PreliminaryCall] = []
    results: dict[str, dict[str, Any]] = {}
    top_dose: dict[str, float] = {}
    for rec in r.records:
        c = rec.get("conc_um")
        s = str(rec.get("sample"))
        if c is not None and (s not in top_dose or c > top_dose[s]):
            top_dose[s] = float(c)
    for sample, comp in compounds.items():
        results[sample] = comp
        if criteria is None or regime_refused or norm_refused:
            continue
        ic50, ci = comp.get("ic50_um"), comp.get("ic50_ci")
        usable_ci = ci is not None and ci[0] is not None and ci[1] is not None
        if comp.get("flagged_single_dose"):
            calls.append(PreliminaryCall(
                entity=sample, call="no_call",
                reason="single-dose — no concentration series"))
        elif comp.get("right_censored") or ic50 is None:
            calls.append(PreliminaryCall(
                entity=sample, call="no_call",
                reason="right-censored: no 50% crossing inside the tested "
                       "window — a range statement, not a number"))
        elif top_dose.get(sample) and ic50 > 2.0 * top_dose[sample]:
            calls.append(PreliminaryCall(
                entity=sample, call="no_call", value=ic50,
                reason="no 50% crossing inside the tested window — the fit "
                       "extrapolates past the top dose; a range statement, "
                       "not a number"))
        elif not usable_ci:
            calls.append(PreliminaryCall(
                entity=sample, call="inconclusive",
                value=ic50,
                reason="fit without a usable CI (unstable bootstrap or "
                       "interpolation fallback) — cannot earn a decisive "
                       "call"))
        else:
            call = criteria.classify(ic50, (ci[0], ci[1]))
            calls.append(PreliminaryCall(
                entity=sample, call=call, value=ic50, ci=(ci[0], ci[1]),
                reason=("CI fully clears the gate" if call != "inconclusive"
                        else "95% CI straddles the registered gate — "
                             "honest abstention")))

    zp = r.z_prime
    # `zp == zp` is the NaN guard: a NaN Z' cannot gate (NaN < x is False,
    # but the explicit check keeps the intent auditable)
    qc_hold = (zp is not None and zp == zp
               and zp < labread.QC_ZPRIME_FLOOR
               and not regime_refused and not norm_refused)
    state = AnalysisState.analyzed
    if regime_refused:
        state = AnalysisState.unsupported_regime
    elif qc_hold:
        state = AnalysisState.qc_hold

    payload: dict[str, Any] = {
        "profile": PROFILE_NAME,
        "profile_version": PROFILE_VERSION,
        "state": (state.value if hasattr(state, "value") else state),
        "format": r.format,
        "n_wells": len(r.records),
        "response_unit": r.response_unit,
        "instrument": dict(r.instrument or {}),
        "batch": r.batch,
        "z_prime": r.z_prime,
        "z_prime_kind": r.z_prime_kind,
        "z_prime_note": r.analysis.get("z_prime_note"),
        "layout_qc": r.analysis.get("layout_qc"),
        "controls_detected": r.analysis.get("controls_detected", 0),
        "regime": dict(r.regime) if r.regime else None,
        "regime_refused": regime_refused,
        "normalization_refused": norm_refused,
        "normalization_note": r.analysis.get("normalization_note"),
        "shape_only": r.analysis.get("shape_only"),
        "engine_version": _engine_version(),
        "compounds": results,
        "wells": _wells(r, cfg),
        "calls": [c.model_dump() for c in calls],
        "threshold_registered": cfg.threshold is not None,
        "metric": cfg.metric,
        "direction": cfg.direction,
        "evidence_origin": cfg.evidence_origin.value,
        "source_sha256": source_sha256,
        "qc_hold": qc_hold,
    }
    if not compounds and not regime_refused:
        payload["diagnostics"] = [AnalysisDiagnostic(
            severity="blocker", code="analysis_empty",
            message="analysis produced no compound results").model_dump()]
    return payload
