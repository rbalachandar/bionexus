"""experiment_analysis — the generic analysis lifecycle (modality-neutral).

The application-facing seam: source artifact + selected profile + explicit
configuration -> deterministic preview / analysis result. This module owns
 NOTHING domain-specific (no plates, no IC50, no controls) and nothing
infrastructural (no HTTP, no browser state, no file persistence, no
provenance writes — those belong to the API layer).

Profile contract (the seam): a profile module exposes
  CONFIG_TYPE  — its pydantic config class (extra=forbid)
  preview(source: Path, cfg) -> dict
  analyze(source: Path, cfg, source_sha256=None) -> dict

Guarantees the interface makes to every caller:
- deterministic for identical bytes + config + profile + pinned versions;
- profile-detected values are provisional until confirmed when they affect
  scientific meaning;
- unsupported regimes / unreadable input surface as typed errors, never as
  partial confident results;
- the source artifact is never modified.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from proef.analysis_profiles import plate_assay
from proef.core.contracts.analysis import AnalysisProfile, AnalysisState

PROFILES = {
    AnalysisProfile.plate_assay: plate_assay,
}


class AnalysisError(Exception):
    """Typed failure: `code` is a stable machine code, message is human."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _profile(name: str):
    try:
        key = AnalysisProfile(name)
    except ValueError:
        raise AnalysisError("unknown_profile",
                            f"no such analysis profile: {name}") from None
    mod = PROFILES.get(key)
    if mod is None:  # pragma: no cover — registry is complete today
        raise AnalysisError("profile_unavailable",
                            f"profile {name} is registered but not wired")
    return mod


def _call(profile_name: str, op: str, source: Path, config: dict,
          fail_code: str, fn: Callable[[Any, Any], dict],
          **kwargs: Any) -> dict:
    """One dispatch + one typed-error ladder for every lifecycle op. A typo
    or unsupported knob in the config is a typed error, never a silent
    default (the profile's pydantic config is extra=forbid)."""
    mod = _profile(profile_name)
    if not Path(source).exists():
        raise AnalysisError("missing_source", f"source not found: {source}")
    try:
        cfg = mod.CONFIG_TYPE(**config)
    except Exception as exc:
        raise AnalysisError("invalid_config", str(exc)[:300]) from None
    try:
        return fn(mod, cfg)
    except AnalysisError:
        raise
    except FileNotFoundError as exc:
        raise AnalysisError("missing_source", str(exc)) from None
    except ImportError as exc:
        raise AnalysisError("missing_dependency", str(exc)) from None
    except ValueError as exc:
        raise AnalysisError("unreadable_source", str(exc)[:300]) from None
    except Exception as exc:  # noqa: BLE001 — fail loud, typed, no partial result
        raise AnalysisError(fail_code, str(exc)[:300]) from None


def preview(profile_name: str, source: Path, config: dict,
            layout_path: str | Path | None = None) -> dict:
    """Parse-level preview: diagnostics + inferred interpretation, no fits,
    no verdicts. Never modifies the source."""
    return _call(
        profile_name, "preview", source, config, "preview_failed",
        lambda mod, cfg: mod.preview(Path(source), cfg,
                                     layout_path=(Path(layout_path)
                                                  if layout_path else None)))


def analyze(profile_name: str, source: Path, config: dict,
            source_sha256: str | None = None,
            layout_path: str | Path | None = None) -> dict:
    """Deterministic analysis; threshold-conditional preliminary calls.
    Regime refusals and QC holds are RETURNED states, not errors."""
    return _call(
        profile_name, "analyze", source, config, "analysis_failed",
        lambda mod, cfg: mod.analyze(Path(source), cfg,
                                     source_sha256=source_sha256,
                                     layout_path=(Path(layout_path)
                                                  if layout_path else None)))


def is_terminal_hold(payload: dict) -> bool:
    """True when the analysis completed honestly but must not be read as a
    pass (regime refusal, QC hold, unreadable)."""
    return payload.get("state") in (
        AnalysisState.unsupported_regime, AnalysisState.qc_hold,
        AnalysisState.unreadable, AnalysisState.needs_mapping)
