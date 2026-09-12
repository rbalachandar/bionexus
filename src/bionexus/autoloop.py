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
    dose_design: str = "fixed"          # "fixed" | "adaptive" (Bayesian
                                        # sequential dosing, 3 wells)
    noise_variant: int = 0              # measurement-noise offset: varies
                                        # noise, never the ground truth
    rounds: int = 1                     # sequential rounds; each round's
                                        # results feed the next selection
    policy: Any = None                  # assaybench-style ranker (e.g.
                                        # AssayLoopRanker): from round 2 it
                                        # picks the batch, gates still decide
    inbox: str | Path = ".data/inbox"
    flywheel: Any = None                # shared Flywheel (default: local db)
    autonomy: Autonomy = "gate"
    poll_secs: float = 0.5
    actor_name: str = "campaign"


@dataclass
class CampaignReport:
    problem_id: str
    selected: list[str]
    verdicts: dict[str, str] = field(default_factory=dict)   # candidate -> status
    recommendations: list[str] = field(default_factory=list)
    rounds_run: int = 1
    history: list[dict] = field(default_factory=list)


def run_campaign(cfg: CampaignConfig, lab: Any,
                 store: ProvenanceStore,
                 approver: Callable[[str], bool] | None = None,
                 notify: Callable[[str], None] | None = None) -> CampaignReport:
    """Start-to-finish: problem -> portfolio -> filter -> test -> verdict -> confirm."""
    actor = system_actor(cfg.actor_name)
    from bionexus.flywheel import Flywheel
    flywheel = cfg.flywheel if cfg.flywheel is not None else Flywheel()

    def _on_verdict(h) -> None:
        flywheel.submit(h.candidate, h.family, h.assay_type, h.status,
                        h.observed_value, h.observed_ci,
                        problem_id=(cfg.problem.problem_id or None),
                        threshold=(h.criteria.threshold if h.criteria else None),
                        evidence_run=h.evidence_run_id)

    tracker = HypothesisTracker(store, actor, on_verdict=_on_verdict)
    safety = SafetyEngine()
    say = notify or (lambda m: print(f"[campaign] {m}"))

    if cfg.autonomy == "gate":
        if approver is None:
            raise ValueError("autonomy='gate' requires an approver callback")
        branch_hint = f"[problem/{cfg.problem.problem_id or 'pending'}]"
        gateway = _GatedGateway(
            lab, safety, store, actor,
            lambda t: approver(f"{t} {branch_hint}"), say)
    else:
        from bionexus.advisory import AdvisoryReviewer
        gateway = LabGateway(lab, safety, store, actor,
                             advisory=AdvisoryReviewer())

    # 0. problem + portfolio + filter
    from bionexus.adapters.bio.tox_alerts import durc_screen
    durc_hits = durc_screen(" ".join([cfg.problem.objective,
                                      cfg.problem.context or ""]))
    if durc_hits:
        store.append(record_for(
            Envelope(experiment_branch_id=f"problem/{cfg.problem.problem_id or 'unnamed'}"),
            EventType.gate_decision, actor,
            decision={"kind": "durc_refusal", "agents": durc_hits,
                      "action": "campaign refused before hypothesis work"}))
        raise ValueError(
            f"DURC: campaign names a select agent / regulated toxin family "
            f"({', '.join(durc_hits)}) — refused and recorded; requires "
            f"institutional review before BioNexus will run it")
    # every run gets its own branch: an explicit problem_id reused from a
    # previous campaign is auto-suffixed rather than merging records
    _base_pid = cfg.problem.problem_id
    _n = 1
    while store.branch_records(f"problem/{cfg.problem.problem_id}"):
        _n += 1
        cfg.problem.problem_id = f"{_base_pid}-{_n}"
    if cfg.problem.problem_id != _base_pid:
        say(f"branch '{_base_pid}' already holds a previous run — this "
            f"campaign recorded separately as '{cfg.problem.problem_id}'")
    problem = tracker.define_problem(cfg.problem, environment={
        "lab": getattr(lab, "name", "unknown"),
        "lab_version": getattr(lab, "version", None),
        "lab_seed": getattr(lab, "seed", None),
        "concentrations": list(cfg.concentrations),
        "autonomy": cfg.autonomy,
        "dose_design": cfg.dose_design,
        "k": cfg.k,
        "model": getattr(cfg.model, "model", None),
    })
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
            flywheel=flywheel,
            notify=say)
        say(f"resource budget: {remaining_runs}/{budget.max_total_runs} lab runs remaining")
        say(f"agent proposed {len(portfolio)} variant hypotheses")
        _base = cfg.score_fn or (
            lambda h: family_scores.get(h.family or "", 0.5))
        score_fn = lambda h: _base(h) + flywheel.prior_bonus(h.family)
    else:
        portfolio = tracker.propose_portfolio(problem, cfg.hypotheses or [])
        base_fn = cfg.score_fn or (lambda h: 0.5)
        score_fn = lambda h: base_fn(h) + flywheel.prior_bonus(h.family)
    # 1. rounds: select -> design+submit -> analyze; each round feeds the next
    _submit = gateway.submit

    def gateway_submit(protocol):  # budget-enforced submission
        if cfg.budget is not None:
            used = cfg.budget.lab_runs_used(store, cfg.problem.problem_id or "")
            if used >= cfg.budget.max_total_runs:
                say(f"BUDGET EXHAUSTED: {used}/{cfg.budget.max_total_runs} lab "
                    "runs used — submission refused (recorded)")
                store.append(record_for(
                    Envelope(experiment_branch_id=f"problem/{cfg.problem.problem_id}"),
                    EventType.tool_invocation, actor,
                    decision={"kind": "budget_exhausted",
                              "lab_runs": used,
                              "cap": cfg.budget.max_total_runs}))
                return None, f"budget exhausted ({used} runs >= cap)"
        return _submit(protocol)

    gateway.submit = gateway_submit  # confirmations flow through the same gate

    # per-experiment outbox: two campaigns on one inbox would collide on
    # run ids (sim-N-001) and the monitor's seen-set would swallow the second
    inbox = Path(cfg.inbox) / problem.problem_id
    inbox.mkdir(parents=True, exist_ok=True)
    adaptive = cfg.dose_design == "adaptive"
    screen_conc = cfg.concentrations[len(cfg.concentrations) // 2] \
        if adaptive else None

    def _export(run_id: str, candidate: str,
                concs: list[str] | None = None) -> None:
        _export_instrument_file(inbox, run_id, candidate,
                                concs or list(cfg.concentrations), lab=lab,
                                noise_variant=cfg.noise_variant)

    messages: list[str] = []
    agent = AutoAnalysisAgent(notify=(lambda m: (messages.append(m), say(f"[agent] {m}"))),
                              tracker=tracker, gateway=gateway,
                              branch_id=f"problem/{problem.problem_id}",
                              auto_confirm=cfg.autonomy == "act" and not adaptive,
                              export_fn=_export,
                              adaptive=adaptive,
                              dose_ladder=tuple(
                                  float(str(c).rstrip("uM"))
                                  for c in cfg.concentrations) + (80.0,))
    monitor = DeviceMonitor(inbox, poll_secs=cfg.poll_secs)
    # "validated" is PRELIMINARY in fixed mode (confirmation pending), so it
    # must NOT count as terminal or the loop exits before confirmations run.
    terminal = {"confirmed", "refuted", "invalidated", "inconclusive"}

    remaining = list(portfolio)
    history: list[dict] = []
    tested: list = []
    for round_no in range(1, max(1, cfg.rounds) + 1):
        if not remaining:
            say(f"round {round_no}: no untested candidates remain — stopping")
            break
        if cfg.policy is not None and round_no > 1:
            selected = _policy_select(cfg, remaining, tracker, say)
        else:
            selected = tracker.select_portfolio(problem, remaining, score_fn,
                                                k=cfg.k, max_per_family=1)
        remaining = [h for h in remaining if h not in selected]
        if not selected:
            say(f"round {round_no}: nothing selected — stopping")
            break
        say(f"round {round_no}: testing "
            f"{[h.candidate for h in selected]} "
            f"({len(remaining)} candidates remain)")
        if cfg.autonomy == "observe":
            say("observe-only: nothing submitted")
            return CampaignReport(problem_id=problem.problem_id,
                                  selected=[h.candidate for h in selected])

        # design + submit this round
        for h in selected:
            protocol = ProtocolSubmission(
                envelope=Envelope(experiment_branch_id=f"problem/{problem.problem_id}"),
                title=f"screen-{h.candidate}" if adaptive else f"test-{h.candidate}",
                assay_type=h.assay_type,
                steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense,
                                    params={"volume_ul": 50})],
                samples=[SampleSpec(
                    sample_id=h.candidate, kind=SampleKind.compound,
                    concentration=c,
                    metadata={"smiles": (h.metadata or {}).get("smiles", ""),
                              "intent": ("covalent" if "covalent" in
                                         (h.mechanism or "").lower() else "")})
                         for c in ([screen_conc] if adaptive
                                   else cfg.concentrations)]
                + [SampleSpec(sample_id=f"ctrl-neg{i}", kind=SampleKind.buffer,
                              concentration="10uM") for i in (1, 2)],
                reagents=[ReagentSpec(name="assay-buffer", amount="5 mL",
                                      bsl_level=1)],
            )
            h.design = ExperimentDesign(
                assay_type=h.assay_type, concentrations=list(cfg.concentrations),
                replicates=3, controls=["negative"],
                protocol_id=protocol.protocol_id)
            run_id, rejection = gateway.submit(protocol)
            if rejection:
                say(f"submission for {h.candidate} rejected: {rejection}")
                continue
            tracker.attach_test(h, protocol, run_id)
            h.design.run_id = run_id
            say(f"started lab run {run_id} for {h.candidate} on "
                f"{getattr(lab, 'name', 'instrument')} "
                f"({len(cfg.concentrations) if not adaptive else 1} dose"
                f"{'s' if (len(cfg.concentrations) if not adaptive else 1) > 1 else ''}"
                f" × 3 replicates)")
            _export(run_id, h.candidate,
                    [screen_conc] if adaptive else None)

        # analyze this round's outputs
        n_expected = sum(1 for h in selected if h.design and h.design.run_id)
        time.sleep(0.2)
        cap = n_expected * (4 if adaptive else 2) + 1
        for i, ev in enumerate(monitor.events(
                stop_after=cap,
                idle_timeout=max(5.0, cfg.poll_secs * 30))):
            agent.handle(ev)
            if all(h.status in terminal for h in selected) and i + 1 >= n_expected:
                break
        verdicts_r = {h.candidate: h.status for h in selected}
        store.append(record_for(
            Envelope(experiment_branch_id=f"problem/{problem.problem_id}"),
            EventType.stage_transition, actor,
            decision={"stage": f"round-{round_no}-complete",
                      "picked": sorted(verdicts_r), "verdicts": verdicts_r}))
        history.append({"round": round_no,
                        "picked": sorted(verdicts_r),
                        "verdicts": verdicts_r})
        tested.extend(selected)

    verdicts = {h.candidate: h.status for h in tested}
    say(f"CAMPAIGN COMPLETE {problem.problem_id}: "
        + (", ".join(f"{c}={s}" for c, s in verdicts.items()) or "nothing tested"))
    return CampaignReport(problem_id=problem.problem_id,
                          selected=[h.candidate for h in tested],
                          verdicts=verdicts,
                          recommendations=[m for m in messages
                                           if "recommendation" in m],
                          rounds_run=len(history), history=history)


def _policy_select(cfg, remaining, tracker, say):
    """Round r>1 batch choice by an assaybench-style policy. The policy ranks
    candidates from prior observations; BioNexus keeps every veto: diversity
    cap here, safety + budget + approval at the gate."""
    obs = [{"candidate": h.candidate,
            "hit": h.status in ("validated", "confirmed"),
            "relevance_score": (-(h.observed_value or 0.0))
            if h.observed_value is not None else 0.0}
           for h in tracker.hypotheses.values()
           if h.status not in ("proposed", "designed")]
    cands = [h.candidate for h in remaining]
    if hasattr(cfg.policy, "pick_batch"):
        picks = list(cfg.policy.pick_batch(cands, obs, cfg.k))
    elif hasattr(cfg.policy, "rank"):
        picks = [c for c, _ in cfg.policy.rank(cands, obs)[:cfg.k]]
    else:
        say("policy has neither pick_batch nor rank — falling back to scores")
        return tracker.select_portfolio(cfg.problem, remaining,
                                        cfg.score_fn or (lambda h: 0.5),
                                        k=cfg.k, max_per_family=1)
    by_cand = {h.candidate: h for h in remaining}
    out, fam = [], set()
    for c in picks:
        h = by_cand.get(c)
        if h is None or (h.family or "") in fam and h.family:
            continue
        if h.family:
            fam.add(h.family)
        out.append(h)
    say(f"policy picked {[h.candidate for h in out]} from "
        f"{len(obs)} observations")
    return out

def _export_instrument_file(inbox: Path, run_id: str, candidate: str,
                            concentrations: tuple[str, ...], lab: Any = None,
                            noise_variant: int = 0) -> None:
    """Stand-in for the instrument finishing: it drops its export in the
    outbox. Uses the lab's per-compound ground truth when available so the
    fitted IC50 reflects simulated pharmacology, not a fixed pattern."""
    import random

    time.sleep(0.1)
    rng = random.Random(f"{run_id}:{candidate}:v{noise_variant}")
    n_rep = getattr(lab, "replicates", 3) if lab is not None else 3
    lines = ["Well ID,Compound,Conc (uM),RFU", "A1,ctrl,10,100", "A2,ctrl,10,104"]
    true_ic50 = None
    if lab is not None and hasattr(lab, "true_ic50_um"):
        true_ic50 = lab.true_ic50_um(run_id, candidate)
    well = 3
    for c in concentrations:
        conc = float(str(c).rstrip("uM"))
        base = (500.0 / (1.0 + true_ic50 / max(conc, 1e-6))) if true_ic50 \
            else 110 + concentrations.index(c) * 90
        for _ in range(n_rep):          # real plates have replicate wells
            noise = rng.gauss(0.0, max(4.0, base * 0.05))
            lines.append(f"A{well},{candidate},{c},{max(0.0, base + noise):.1f}")
            well += 1
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
