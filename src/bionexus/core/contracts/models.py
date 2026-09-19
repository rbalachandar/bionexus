"""BioNexus core contracts — pydantic models for the five integration contracts.

Mirrors contracts/v1/*.yaml (OpenAPI drafts). These types cross every block
boundary; adapters and user code should only exchange these + the interfaces.
"""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def new_id() -> str:
    return str(uuid.uuid4())


def now() -> float:
    return time.time()


class Envelope(BaseModel):
    """Common wrapper on every contract message (P5: provenance ref required path)."""
    contract_id: str = Field(default_factory=new_id)
    schema_version: Literal["v1"] = "v1"
    experiment_branch_id: str
    parent_branch_id: str | None = None
    provenance_ref: str | None = None
    created_at: float = Field(default_factory=now)
    trace_id: str | None = None


class StageName(str, Enum):
    target_id = "target_id"
    hit_generation = "hit_generation"
    lead_optimization = "lead_optimization"
    preclinical = "preclinical"
    trial_design = "trial_design"


class GateType(str, Enum):
    approve_candidate_batch = "approve_candidate_batch"
    approve_wetlab_protocol = "approve_wetlab_protocol"
    approve_trial_protocol = "approve_trial_protocol"
    arbitrary_redirect = "arbitrary_redirect"


class ArtifactKind(str, Enum):
    target_dossier = "target_dossier"
    molecule = "molecule"
    biologic = "biologic"
    hypothesis = "hypothesis"
    protocol = "protocol"
    assay_result = "assay_result"
    trial_protocol = "trial_protocol"
    report = "report"
    model_output = "model_output"
    raw_telemetry = "raw_telemetry"
    other = "other"


class ArtifactRef(BaseModel):
    artifact_id: str = Field(default_factory=new_id)
    kind: ArtifactKind
    uri: str
    sha256: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------- StageTask

class StageStatus(str, Enum):
    succeeded = "succeeded"
    failed_retryable = "failed_retryable"
    failed_terminal = "failed_terminal"
    needs_human = "needs_human"


class StageError(BaseModel):
    code: str
    message: str
    retryable: bool = False


class StageTask(BaseModel):
    """Orchestration -> Agents. Idempotent via task_id; redelivery is deduped."""
    envelope: Envelope
    task_id: str = Field(default_factory=new_id)
    stage: StageName
    attempt: int = 1
    gate_after: GateType | None = None
    input_artifacts: list[ArtifactRef] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)


class Proposal(BaseModel):
    """A next-round proposal emitted by the analysis stage (active-learning loop)."""
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)


class StageResult(BaseModel):
    """Agents -> Orchestration."""
    envelope: Envelope
    task_id: str
    status: StageStatus
    output_artifacts: list[ArtifactRef] = Field(default_factory=list)
    next_round_proposals: list[Proposal] = Field(default_factory=list)
    error: StageError | None = None


# ------------------------------------------------------------ ToolInvocation

class ToolName(str, Enum):
    # Block C — models & knowledge
    fm_predict_structure = "c.fm.predict_structure"
    fm_generate_molecules = "c.fm.generate_molecules"
    fm_predict_property = "c.fm.predict_property"
    fm_predict_admet = "c.fm.predict_admet"
    kb_search_literature = "c.kb.search_literature"
    registry_get_put_candidate = "c.registry.get_put_candidate"
    evals_benchmark_batch = "c.evals.benchmark_batch"
    evals_rank_batch = "c.evals.rank_batch"
    flywheel_submit_example = "c.flywheel.submit_example"
    flywheel_list_model_variants = "c.flywheel.list_model_variants"
    # Block D — lab
    lab_list_capabilities = "d.lab.list_capabilities"
    lab_submit_protocol = "d.lab.submit_protocol"
    lab_get_status = "d.lab.get_status"
    lab_fetch_results = "d.lab.fetch_results"
    lab_cancel = "d.lab.cancel"
    # Block E — simulation & data
    sim_docking = "e.sim.docking"
    sim_md_job = "e.sim.md_job"
    sim_assay_prediction = "e.sim.assay_prediction"
    sim_trial_simulation = "e.sim.trial_simulation"
    data_query_feature_store = "e.data.query_feature_store"


class ToolInvocation(BaseModel):
    envelope: Envelope
    invocation_id: str = Field(default_factory=new_id)
    tool: ToolName
    args: dict[str, Any] = Field(default_factory=dict)
    timeout_secs: int = 300


class ToolResult(BaseModel):
    envelope: Envelope
    invocation_id: str
    status: Literal["succeeded", "failed", "rejected"]
    output: dict[str, Any] = Field(default_factory=dict)
    model_version: str | None = None
    rejection_reason: str | None = None


# --------------------------------------------------------- ProtocolSubmission

class AssayType(str, Enum):
    binding = "binding"
    enzymatic = "enzymatic"
    cytotoxicity = "cytotoxicity"
    counterscreen = "counterscreen"
    adme = "adme"
    pcr = "pcr"
    sequencing = "sequencing"
    plate_reader = "plate_reader"
    # materials characterization
    tensile = "tensile"
    dsc = "dsc"
    dls = "dls"
    ftir = "ftir"
    xrd = "xrd"
    density = "density"
    # biologics
    elisa = "elisa"
    dsf = "dsf"
    immunogenicity = "immunogenicity"
    aggregation = "aggregation"
    thermal_stability = "thermal_stability"
    # cell therapy
    potency = "potency"
    sterility = "sterility"
    phenotype_stability = "phenotype_stability"
    # mRNA
    expression = "expression"
    stability = "stability"
    # agrochemical
    organism_dose_response = "organism_dose_response"
    phytotoxicity = "phytotoxicity"
    custom = "custom"


class Priority(str, Enum):
    low = "low"
    normal = "normal"
    high = "high"


class ProtocolOp(str, Enum):
    dispense = "dispense"
    mix = "mix"
    incubate = "incubate"
    transfer = "transfer"
    measure = "measure"
    centrifuge = "centrifuge"
    heat = "heat"
    plate = "plate"
    sequence = "sequence"
    wait = "wait"


class ProtocolStep(BaseModel):
    seq: int = Field(ge=1)
    op: ProtocolOp
    params: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[int] = Field(default_factory=list)


class SampleKind(str, Enum):
    compound = "compound"
    protein = "protein"
    cell_line = "cell_line"
    nucleic_acid = "nucleic_acid"
    buffer = "buffer"
    other = "other"


class SampleSpec(BaseModel):
    sample_id: str
    kind: SampleKind
    candidate_artifact_id: str | None = None
    concentration: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReagentSpec(BaseModel):
    name: str
    amount: str
    lot: str | None = None
    bsl_level: int = Field(default=1, ge=1, le=4)


class ProtocolSubmission(BaseModel):
    """Assay Planning Agent -> Protocol Compiler (Block D). Abstract wet-lab protocol."""
    envelope: Envelope
    protocol_id: str = Field(default_factory=new_id)
    title: str
    assay_type: AssayType
    priority: Priority = Priority.normal
    steps: list[ProtocolStep] = Field(min_length=1)
    samples: list[SampleSpec] = Field(default_factory=list)
    reagents: list[ReagentSpec] = Field(default_factory=list)
    controls: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------- AssayResult

class RunStatus(str, Enum):
    completed = "completed"
    partial = "partial"
    failed = "failed"
    cancelled = "cancelled"


class MeasurementFlag(str, Enum):
    out_of_range = "out_of_range"
    below_lod = "below_lod"
    suspect = "suspect"
    control = "control"


class Measurement(BaseModel):
    sample_id: str
    well: str | None = None
    assay_type: str
    value: float
    unit: str
    uncertainty: float | None = None
    replicate: int = Field(default=1, ge=1)
    derived_metrics: dict[str, float] = Field(default_factory=dict)
    flags: list[MeasurementFlag] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)  # adapter-specific evidence


class InstrumentInfo(BaseModel):
    adapter: str  # e.g. "simulator", "opentrons"
    instrument_id: str
    raw_output_uri: str | None = None


class QCInfo(BaseModel):
    controls_passed: bool = True
    z_prime: float | None = None  # assay window quality (imaging/plate readouts)
    failed_wells: list[str] = Field(default_factory=list)
    notes: str | None = None


class AssayResult(BaseModel):
    """Telemetry -> Orchestration/Analysis. Normalized results + lineage."""
    envelope: Envelope
    run_id: str = Field(default_factory=new_id)
    protocol_id: str
    instrument: InstrumentInfo
    status: RunStatus
    measurements: list[Measurement] = Field(default_factory=list)
    qc: QCInfo = Field(default_factory=QCInfo)


# ----------------------------------------------------------- ProvenanceRecord

class EventType(str, Enum):
    artifact_created = "artifact_created"
    model_invocation = "model_invocation"
    tool_invocation = "tool_invocation"
    lab_run = "lab_run"
    simulation_job = "simulation_job"
    evaluation = "evaluation"
    gate_decision = "gate_decision"
    stage_transition = "stage_transition"
    problem_defined = "problem_defined"
    hypothesis_proposed = "hypothesis_proposed"
    hypotheses_filtered = "hypotheses_filtered"
    experiment_defined = "experiment_defined"
    experiment_readiness_reviewed = "experiment_readiness_reviewed"
    hypothesis_tested = "hypothesis_tested"
    hypothesis_validated = "hypothesis_validated"
    hypothesis_invalidated = "hypothesis_invalidated"
    synthesis_complete = "synthesis_complete"
    sandbox_fork = "sandbox_fork"
    sandbox_snapshot = "sandbox_snapshot"


class ActorKind(str, Enum):
    agent = "agent"
    human = "human"
    service = "service"
    instrument = "instrument"


class Actor(BaseModel):
    kind: ActorKind
    id: str
    sandbox_id: str | None = None
    model_version: str | None = None
    prompt_ref: str | None = None


class Artifact(BaseModel):
    artifact_id: str
    kind: ArtifactKind
    uri: str
    sha256: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProvenanceRecord(BaseModel):
    """Everything -> Provenance Store. Append-only, WORM, hash-chained."""
    envelope: Envelope
    record_id: str = Field(default_factory=new_id)
    event_type: EventType
    actor: Actor
    artifact: Artifact | None = None
    inputs: list[Artifact] = Field(default_factory=list)
    decision: dict[str, Any] | None = None
    prev_record_hash: str | None = None
    record_hash: str | None = None
