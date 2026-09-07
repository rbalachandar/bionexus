"""One-call campaign loop: problem in, verdicts out.

`run_campaign()` assembles the full flow — problem, portfolio, filter,
design/test, lab awareness, verdicts, confirmation — so it can be started
manually by a scientist (one function call / `bn auto`) or kicked off by an
agent (the same function, called programmatically or via MCP).

autonomy levels:
  "act"      — agent runs everything, incl. auto-submitted confirmation assays
  "gate"     — agent runs everything, but every lab submission needs the
               operator's approver callback to return True first
  "observe"  — agent only reads, fits and recommends; submits nothing
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from bionexus.core.contracts import (
    Envelope, EventType, ProtocolOp, ProtocolStep, ProtocolSubmission,
    ReagentSpec, SampleKind, SampleSpec,
)
from bionexus.core.hypothesis import (
    Constraint, ExperimentDesign, HypothesisTracker, PortfolioDecision,
    ProblemStatement, SuccessCriteria,
)
from bionexus.core.interfaces import ProvenanceStore, record_for, system_actor
from bionexus.core.safety import LabGateway, SafetyEngine
from bionexus.watch import AutoAnalysisAgent, DeviceMonitor

Autonomy = str  # "act" | "gate" | "observe"


@dataclass
class ResourceBudget:
    """Hard caps on what a campaign may consume. Enforced at submission time
    (no new lab runs past the limit) and at generation time (no hypothesis
    explosion). Exhaustion is provenance-recorded, never silent."""
    max_total_runs: int = 50             # lab runs (incl. confirmations)
    max_hypotheses_total: int = 30       # across all rounds
    max_confirmations: int = 10
    wall_clock_secs: float | None = None

    def lab_runs_used(self, store: ProvenanceStore, problem_id: str) -> int:
        try:
            recs = store.branch_records(f"problem/{problem_id}")
        except Exception:
            return 0
        return sum(1 for r in recs if r.event_type.value == "lab_run")


@dataclass
class CampaignConfig:
    problem: ProblemStatement
    hypotheses: list[dict[str, Any]] | None = None   # config-defined portfolio...
    hypothesis_source: str = "config"         # ...or "agent": the model decides
    model: Any = None                         # required when hypothesis_source == "agent"
    candidates: list[dict[str, Any]] | None = None   # library shown to the agent
    skill_guidance: str | None = None         # Agent Skills text injected into
                                              # the hypothesis prompt (P: skills)
    max_families: int = 3
    max_variants_per_family: int = 3
    score_fn: Callable[[Any], float] | None = None   # portfolio filter scoring
    k: int = 2                                # hypotheses taken to wet-lab
    budget: ResourceBudget | None = None      # None = uncapped ( discouraged)
    concentrations: tuple[str, ...] = ("0.5uM", "2uM", "10uM", "40uM")
    inbox: str | Path = ".data/inbox"
    autonomy: Autonomy = "gate"
    poll_secs: float = 0.5
    actor_name: str = "campaign"


@dataclass
class CampaignReport:
    problem_id: str
    selected: list[str]
    verdicts: dict[str, str] = field(default_factory=dict)   # candidate -> status
    recommendations: list[str] = field(default_factory=list)


def run_campaign(cfg: CampaignConfig, lab: Any,
                 store: ProvenanceStore,
                 approver: Callable[[str], bool] | None = None,
                 notify: Callable[[str], None] | None = None) -> CampaignReport:
    """Start-to-finish: problem -> portfolio -> filter -> test -> verdict -> confirm."""
    actor = system_actor(cfg.actor_name)
    tracker = HypothesisTracker(store, actor)
    safety = SafetyEngine()
    say = notify or (lambda m: print(f"[campaign] {m}"))

    if cfg.autonomy == "gate":
        if approver is None:
            raise ValueError("autonomy='gate' requires an approver callback")
        gateway = _GatedGateway(lab, safety, store, actor, approver, say)
    else:
        gateway = LabGateway(lab, safety, store, actor)

    # 0. problem + portfolio + filter
    problem = tracker.define_problem(cfg.problem)
    family_scores: dict[str, float] = {}
    if cfg.hypothesis_source == "agent":
        from bionexus.hypothesis_agent import propose_families_with_agent
        budget = cfg.budget or ResourceBudget()
        used = budget.lab_runs_used(store, cfg.problem.problem_id or "")
        remaining_runs = max(0, budget.max_total_runs - used)
        portfolio, family_scores = propose_families_with_agent(
            tracker, cfg.problem, cfg.model, candidates=cfg.candidates,
            max_families=cfg.max_families,
            max_variants_per_family=cfg.max_variants_per_family,
            max_total_hypotheses=max(0, budget.max_hypotheses_total
                                     - len(tracker.hypotheses)),
            existing_keys={(h.candidate, h.statement) for h in tracker.hypotheses.values()},
            skill_guidance=cfg.skill_guidance,
            notify=say)
        say(f"resource budget: {remaining_runs}/{budget.max_total_runs} lab runs remaining")
        say(f"agent proposed {len(portfolio)} variant hypotheses")
        score_fn = cfg.score_fn or (lambda h: family_scores.get(h.family or "", 0.5))
    else:
        portfolio = tracker.propose_portfolio(problem, cfg.hypotheses or [])
        score_fn = cfg.score_fn or (lambda h: 0.5)
    selected = tracker.select_portfolio(problem, portfolio, score_fn, k=cfg.k,
                                        max_per_family=1)
    say(f"problem {problem.problem_id}: {len(portfolio)} hypotheses -> {len(selected)} selected")
    say("PHASE design+submit")

    # 1. design + submit for each selected hypothesis
    _submit = gateway.submit

    def gateway_submit(protocol):  # budget-enforced submission
        if cfg.budget is not None:
            used = cfg.budget.lab_runs_used(store, cfg.problem.problem_id or "")
            if used >= cfg.budget.max_total_runs:
                say(f"BUDGET EXHAUSTED: {used}/{cfg.budget.max_total_runs} lab runs "
                    "used — submission refused (recorded)")
                store.append(record_for(
                    Envelope(experiment_branch_id=f"problem/{cfg.problem.problem_id}"),
                    EventType.tool_invocation, actor,
                    decision={"kind": "budget_exhausted",
                              "lab_runs": used,
                              "cap": cfg.budget.max_total_runs}))
                return None, f"budget exhausted ({used} runs >= cap)"
        return _submit(protocol)

    gateway.submit = gateway_submit  # confirmations flow through the same gate

    inbox = Path(cfg.inbox)
    inbox.mkdir(parents=True, exist_ok=True)
    for h in selected:
        protocol = ProtocolSubmission(
            envelope=Envelope(experiment_branch_id=f"problem/{problem.problem_id}"),
            title=f"test-{h.candidate}", assay_type=h.assay_type,
            steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense, params={"volume_ul": 50})],
            samples=[SampleSpec(sample_id=h.candidate, kind=SampleKind.compound,
                                concentration=c) for c in cfg.concentrations]
            + [SampleSpec(sample_id=f"ctrl-neg{i}", kind=SampleKind.buffer,
                          concentration="10uM") for i in (1, 2)],
            reagents=[ReagentSpec(name="assay-buffer", amount="5 mL", bsl_level=1)],
        )
        h.design = ExperimentDesign(
            assay_type=h.assay_type, concentrations=list(cfg.concentrations),
            replicates=3, controls=["negative"], protocol_id=protocol.protocol_id)
        if cfg.autonomy == "observe":
            say(f"observe-only: would test {h.candidate} — stopping")
            continue
        run_id, rejection = gateway.submit(protocol)
        if rejection:
            say(f"submission for {h.candidate} rejected: {rejection}")
            continue
        tracker.attach_test(h, protocol, run_id)
        h.design.run_id = run_id
        _export_instrument_file(inbox, run_id, h.candidate, cfg.concentrations,
                                lab=lab)

    if cfg.autonomy == "observe":
        return CampaignReport(problem_id=problem.problem_id,
                              selected=[h.candidate for h in selected])

    # 2. agent notices the outputs, verdicts, confirms
    say("PHASE analyze")
    messages: list[str] = []
    def _export(run_id: str, candidate: str) -> None:
        _export_instrument_file(inbox, run_id, candidate,
                                cfg.concentrations, lab=lab)

    agent = AutoAnalysisAgent(notify=(lambda m: (messages.append(m), say(f"[agent] {m}"))),
                              tracker=tracker, gateway=gateway,
                              branch_id=f"problem/{problem.problem_id}",
                              auto_confirm=cfg.autonomy == "act",
                              export_fn=_export)
    monitor = DeviceMonitor(inbox, poll_secs=cfg.poll_secs)
    time.sleep(0.2)
    n_expected = sum(1 for h in selected if h.design and h.design.run_id)
    # primary runs + their orthogonal confirmations (guarded, <= 1 per candidate)
    terminal = {"confirmed", "refuted", "invalidated", "inconclusive"}
    for i, ev in enumerate(monitor.events(stop_after=n_expected * 2 + 1,
                                          idle_timeout=max(5.0, cfg.poll_secs * 20))):
        agent.handle(ev)
        if all(h.status in terminal for h in selected) and i + 1 >= n_expected:
            break

    verdicts = {h.candidate: h.status for h in selected}
    say(f"CAMPAIGN COMPLETE {problem.problem_id}: "
        + ", ".join(f"{c}={s}" for c, s in verdicts.items()))
    return CampaignReport(problem_id=problem.problem_id,
                          selected=[h.candidate for h in selected],
                          verdicts=verdicts,
                          recommendations=[m for m in messages if "recommendation" in m])


def _export_instrument_file(inbox: Path, run_id: str, candidate: str,
                            concentrations: tuple[str, ...], lab: Any = None) -> None:
    """Stand-in for the instrument finishing: it drops its export in the
    outbox. Uses the lab's per-compound ground truth when available so the
    fitted IC50 reflects simulated pharmacology, not a fixed pattern."""
    time.sleep(0.1)
    lines = ["Well ID,Compound,Conc (uM),RFU", "A1,ctrl,10,100", "A2,ctrl,10,104"]
    true_ic50 = None
    if lab is not None and hasattr(lab, "true_ic50_um"):
        true_ic50 = lab.true_ic50_um(run_id, candidate)
    for i, c in enumerate(concentrations):
        conc = float(c.rstrip("uM"))
        if true_ic50 is not None:
            rfu = 500.0 / (1.0 + true_ic50 / max(conc, 1e-6))
            rfu += ((hash(f"{run_id}:{candidate}:{conc}") % 100) / 100.0 - 0.5) * 8
        else:
            rfu = 110 + i * 90
        lines.append(f"A{i + 3},{candidate},{c},{rfu:.1f}")
    (inbox / f"{run_id}.csv").write_text("\n".join(lines) + "\n")


class _GatedGateway:
    """LabGateway wrapper where every submission needs operator approval first
    (autonomy='gate'). Rejection by the human is final; SafetyEngine still runs."""

    def __init__(self, lab: Any, safety: SafetyEngine, store: ProvenanceStore,
                 actor: Any, approver: Callable[[str], bool], say: Callable[[str], None]):
        self._gw = LabGateway(lab, safety, store, actor)
        self._approver = approver
        self._say = say

    def submit(self, protocol: ProtocolSubmission):
        title = getattr(protocol, "title", str(protocol))
        if not self._approver(title):
            self._say(f"operator declined: '{title}' — submission cancelled")
            return None, "declined by operator"
        return self._gw.submit(protocol)

    def results(self, *a, **kw):
        return self._gw.results(*a, **kw)

    def capabilities(self, *a, **kw):
        return self._gw.capabilities(*a, **kw)
