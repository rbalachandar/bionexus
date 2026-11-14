"""Generic experiment-analysis contracts (modality-neutral).

The analysis lifecycle — artifacts, revisions, evidence origin, uncertainty,
human disposition — is shared across bio/chemical/material work. Domain
INTERPRETATION (plates, wells, IC50, Z′, controls) lives in analysis
profiles behind a profile discriminator; these types never require any of
those concepts.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class AnalysisProfile(str, Enum):
    """Which domain interpretation owns this analysis. New profiles are
    added ONLY when a real second use case validates the shared seam."""
    plate_assay = "plate_assay"


class EvidenceOrigin(str, Enum):
    """Where the measured values came from. Stored, propagated to every
    report, never inferred from a filename or UI route."""
    measured = "measured"            # instrument export from an identified/declared device
    historical = "historical"        # frozen external dataset or paper deposit
    simulated = "simulated"          # Proef-generated measurement data
    predicted = "predicted"          # model output / proxy metric
    unknown = "unknown"              # declared unknown — never guessed


class AnalysisState(str, Enum):
    """Explicit persisted lifecycle states. Generic states first;
    profile-specific holds are diagnostics that may hold the session."""
    # generic forward path
    uploaded = "uploaded"
    preview_ready = "preview_ready"
    configured = "configured"
    analyzed = "analyzed"
    reviewed = "reviewed"
    # generic failures
    unreadable = "unreadable"                    # bytes could not be parsed at all
    needs_input = "needs_input"                  # a required companion artifact is missing
    analysis_failed = "analysis_failed"          # analysis raised on parseable input
    # profile-specific holds (plate assay today)
    needs_mapping = "needs_mapping"              # layout required but absent/incomplete
    unsupported_regime = "unsupported_regime"    # interpretation refused by regime gate
    qc_hold = "qc_hold"                          # QC below the profile's floor


GENERIC_STATES = {AnalysisState.uploaded, AnalysisState.preview_ready,
                  AnalysisState.configured, AnalysisState.analyzed,
                  AnalysisState.reviewed, AnalysisState.unreadable,
                  AnalysisState.needs_input, AnalysisState.analysis_failed}


class DispositionAction(str, Enum):
    """What a human did with a computed call. Acknowledgement is NOT
    orthogonal experimental confirmation — 'confirmed' stays reserved for
    the campaign confirmation-agreement semantics."""
    acknowledge = "acknowledge"
    comment = "comment"
    override = "override"


class HumanDisposition(BaseModel):
    action: DispositionAction
    reason: str = ""
    target: str = ""                     # sample/call the disposition names, when specific
    actor: str = "scientist"
    at: float = Field(default_factory=lambda: __import__("time").time())


class AnalysisArtifact(BaseModel):
    """A stored file bound by digest. Raw bytes live OUTSIDE the provenance
    chain; the chain holds the sha256."""
    kind: Literal["source", "layout", "result", "report"]
    storage_path: str                    # generated id path — never the user filename
    original_name: str = ""              # sanitized display metadata only
    sha256: str = ""
    size: int = 0


class AnalysisDiagnostic(BaseModel):
    severity: Literal["info", "warning", "blocker"]
    code: str                            # stable machine code, e.g. "no_layout"
    message: str


class PreliminaryCall(BaseModel):
    """A threshold-conditional preliminary verdict on ONE entity of the
    profile's result (compound, specimen, …). Emitted ONLY when the
    scientist registered a threshold; otherwise estimate-only."""
    entity: str
    call: Literal["validated", "invalidated", "inconclusive", "no_call"]
    reason: str = ""
    value: float | None = None
    ci: tuple[float | None, float | None] | None = None
