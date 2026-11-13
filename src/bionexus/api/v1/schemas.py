"""API v1 response models — the single source of truth for the workbench
contract. The TypeScript client is GENERATED from the OpenAPI these produce."""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

State = Literal["confirmed", "validated", "abstained", "refuted", "refused",
                "in_lab", "selected", "not_selected", "proposed"]
VerdictStatus = Literal["confirmed", "validated", "abstained", "refuted"]


# a 2-element [low, high] pair; a plain list keeps the generated TS type simple
Interval = Annotated[list[float], Field(min_length=2, max_length=2)]


class Problem(BaseModel):
    """RFC 7807-style error body."""
    type: str = "about:blank"
    title: str
    detail: str | None = None


class ProgramRef(BaseModel):
    slug: str
    name: str


class Gate(BaseModel):
    """The pre-registered success criterion the campaign is judged against."""
    metric: str | None = None
    direction: Literal["min", "max"] | None = None
    threshold: float | None = None
    unit: str | None = None
    label: str | None = Field(None, description="e.g. 'IC50 (µM) ≤ 2'")


class Budget(BaseModel):
    runs_used: int
    runs_max: int | None = None


class Funnel(BaseModel):
    proposed: int
    selected: int = Field(description="chosen for testing (incl. refused/in lab)")
    tested: int = Field(description="reached the lab")
    judged: int = Field(description="has a verdict")
    claimed: int = Field(description="validated or confirmed")
    refuted: int
    abstained: int = Field(description="interval straddles the gate")


class Verdict(BaseModel):
    status: VerdictStatus
    observed: float | None = None
    ci: Interval | None = None
    unit_label: str | None = None
    margin: str | None = None
    extrapolation: bool = False


class HypothesisSummary(BaseModel):
    id: str
    candidate: str | None = None
    head: str
    statement: str
    state: State
    stage: str = Field(description="one-line, human-readable status")
    round: int | None = None
    verdict: Verdict | None = None
    gate_label: str | None = None
    selected: bool = False


class Pick(BaseModel):
    candidate: str
    reason: str
    score: float | None = Field(None, description="EI value or portfolio score")
    mean: float | None = None
    sd: float | None = None


class Refusal(BaseModel):
    candidate: str
    reason: str


class Why(BaseModel):
    """'Why this plate': how a round's batch was chosen."""
    policy: str | None = None
    policy_version: str | None = None
    k: int | None = None
    target: float | None = None
    direction: str | None = None
    picks: list[Pick] = []
    refusals: list[Refusal] = []
    note: str = ""


class Round(BaseModel):
    n: int
    candidates: list[str]
    verdicts: dict[str, str] = {}
    why: Why | None = None


class ReviewFinding(BaseModel):
    severity: str
    kind: str
    candidate: str | None = None
    detail: str


class Reviewer(BaseModel):
    critical: int = 0
    warnings: int = 0
    findings: list[ReviewFinding] = []


class ChainStatus(BaseModel):
    verified: bool
    records: int
    problems: list[dict[str, Any]] = []


class ActivityItem(BaseModel):
    ts: float | None = None
    kind: str
    text: str
    candidate: str | None = None


class CampaignSummary(BaseModel):
    id: str
    title: str
    status: str
    autonomy: str | None = None
    program: ProgramRef | None = None
    updated_at: float | None = None
    problem_id: str | None = None


class CampaignDetail(CampaignSummary):
    objective: str | None = None
    branch: str | None = None
    gate: Gate = Gate()
    budget: Budget
    funnel: Funnel
    rounds: list[Round] = []
    hypotheses: list[HypothesisSummary] = []
    eliminated: list[Refusal] = []
    reviewer: Reviewer | None = None
    chain: ChainStatus


class HypothesisDetail(HypothesisSummary):
    rationale: str | None = None
    predicted: str | None = None
    predicted_by: dict[str, Any] | None = None
    mechanism: str | None = None
    refutation_condition: str | None = None
    citation: str | None = None
    citation_status: str | None = None
    evidence: dict[str, Any] | None = None
    derivation: str | None = Field(None, description="how the verdict was derived")
    evidence_runs: list[str] = []
    events: list[ActivityItem] = []


class ProvenanceRecord(BaseModel):
    ts: float | None = None
    event: str
    summary: str


class ProvenanceView(BaseModel):
    chain: ChainStatus
    records: list[ProvenanceRecord]


class EvalSummary(BaseModel):
    mean: float
    tasks: int
    all_pass: bool


class AnchorStatus(BaseModel):
    records: int
    age_s: float | None = Field(None, description="seconds since the last anchor")
    published: bool | None = None


class SystemStatus(BaseModel):
    """What the top bar and trust strip show on every page."""
    halted: bool
    halt_reason: str | None = None
    pending_approvals: int
    chain: ChainStatus
    anchor: AnchorStatus | None = None
    eval: EvalSummary | None = None


class CurvePoint(BaseModel):
    conc_um: float
    value: float


class CurveFit(BaseModel):
    ic50_um: float | None = None
    ci: Interval | None = None
    top: float | None = Field(None, description="known or fitted plateau")
    method: str | None = None
    model: str | None = Field(None, description="what the curve model is (slope/bottom fixed)")
    right_censored: bool = False
    left_censored: bool = False
    line: list[CurvePoint] = Field([], description="the fitted curve, sampled for plotting")


class Curve(BaseModel):
    run_id: str
    label: str
    points: list[CurvePoint]
    fit: CurveFit | None = None
    z_prime: float | None = None
    z_kind: str | None = None
    unit: str | None = None


class CurveSet(BaseModel):
    candidate: str | None = None
    curves: list[Curve] = []
    note: str | None = None


class BestResult(BaseModel):
    campaign_id: str
    campaign_title: str
    candidate: str
    state: str
    observed: float | None = None
    ci: Interval | None = None


class Goal(BaseModel):
    """Progress against the program's pre-registered gate, across ALL its campaigns."""
    met: bool = Field(description="at least one candidate is claimed (validated/confirmed)")
    best: BestResult | None = Field(None, description="best claimed result, else the closest judged one")
    claimed: int = 0
    refuted: int = 0
    abstained: int = 0
    judged: int = 0


class CampaignDigest(BaseModel):
    id: str
    title: str
    status: str
    updated_at: float | None = None
    funnel: Funnel
    best: BestResult | None = None


class ProgramSummary(BaseModel):
    slug: str
    name: str
    objective: str | None = None
    modality: str | None = None
    mode: str | None = None
    gate: Gate
    goal: Goal
    campaigns: int
    running: int
    updated_at: float | None = None


class ProgramResult(BaseModel):
    hypothesis_id: str
    campaign_id: str
    campaign_title: str
    candidate: str
    state: str
    observed: float | None = None
    ci: Interval | None = None


class ProgramDetail(ProgramSummary):
    campaign_list: list[CampaignDigest] = []
    results: list[ProgramResult] = []


class AbstentionNote(BaseModel):
    campaign_id: str
    campaign_title: str
    candidates: list[str]


class Attention(BaseModel):
    """What needs the scientist right now."""
    pending_approvals: int
    abstentions: list[AbstentionNote]
    running: int
    halted: bool


class Today(BaseModel):
    attention: Attention
    programs: list[ProgramSummary]
    standalone: list[CampaignDigest]
