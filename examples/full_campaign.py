"""Full campaign simulation — the entire platform flow on the virtual lab (P8).

Runs the complete Stage Pipeline (docs/flows.md, diagram 06) with zero hardware
and zero network:

    Target ID → Hit Generation (tournament) → Lead Optimization (active-learning
    rounds with forked assay branches) → Preclinical → Trial Design → IND summary

Every hop writes provenance; wet-lab goes through the SafetyEngine (LabGateway);
parallel assay hypotheses run in forked sandboxes; confirmed results feed the
flywheel; review gates are recorded (auto-approved by a scripted scientist).

    python examples/full_campaign.py
"""
from __future__ import annotations

import json
from pathlib import Path

from bionexus.adapters.lab.recording import RecordingLab
from bionexus.adapters.lab.simulator import SimulatorLab
from bionexus.adapters.models.openai_compat import OpenAICompatProvider
from bionexus.adapters.sandbox.local import LocalSandbox
from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.core.contracts import (
    Actor,
    Artifact,
    ArtifactKind,
    Envelope,
    EventType,
    GateType,
    ProtocolOp,
    ProtocolStep,
    ProtocolSubmission,
    ReagentSpec,
    SampleKind,
    SampleSpec,
    ToolInvocation,
)
from bionexus.core.flywheel import FlywheelLog
from bionexus.core.hypothesis import HypothesisTracker
from bionexus.core.interfaces import record_for, system_actor
from bionexus.core.registry import Registry
from bionexus.core.safety import LabGateway, SafetyEngine
from bionexus.core.workflow import HypothesisTournament, TournamentConfig

BRANCH = "campaign-root"
SEED = 42
ASSAYS = ["binding", "enzymatic", "cytotoxicity"]


def artifact(envelope: Envelope, kind: ArtifactKind, name: str, payload: dict) -> Artifact:
    """Store an artifact inline and write an artifact_created record."""
    art = Artifact(artifact_id=f"{kind.value}-{abs(hash(name)) % 10**8}",
                   kind=kind, uri=f"mem://{envelope.experiment_branch_id}/{name}",
                   metadata=payload)
    return art


def main() -> None:
    store = SqliteProvenanceStore("campaign.db")
    actor: Actor = system_actor("campaign-sim")
    model = OpenAICompatProvider()  # offline stub
    registry = Registry()
    registry.register_model(model, default=True)

    # record the session: playback in CI forever after (T3.3)
    rec = RecordingLab(SimulatorLab(seed=SEED), "examples/_campaign_recording.json")
    safety = SafetyEngine(rules=[])  # demo: allow BSL defaults via rule defaults
    from bionexus.core.safety import MaxBslRule, MaxStepsRule
    safety = SafetyEngine(rules=[MaxBslRule(2), MaxStepsRule(50)])
    gateway = LabGateway(rec, safety, store, actor)
    flywheel = FlywheelLog("examples/_campaign_training.jsonl")
    tracker = HypothesisTracker(store, actor)
    sandbox = LocalSandbox(BRANCH, store=store, actor=actor)
    log = lambda msg: print(msg)  # noqa: E731

    def env(branch: str = BRANCH) -> Envelope:
        return Envelope(experiment_branch_id=branch)

    def gate(name: str, approved: bool) -> None:
        store.append(record_for(env(), EventType.gate_decision, actor,
                                decision={"gate": name, "approved": approved,
                                          "approved_by": "scripted-scientist"}))
        log(f"  [gate] {name}: {'APPROVED' if approved else 'REJECTED'}")

    def stage(name: str, detail: str) -> None:
        store.append(record_for(env(), EventType.stage_transition, actor,
                                decision={"stage": name, "detail": detail}))
        log(f"\n=== {name.upper()} === {detail}")

    # ---------------------------------------------------------------- 1. Target ID
    stage("target_id", "literature + omics triage")
    inv = ToolInvocation(envelope=env(), tool="c.kb.search_literature",
                         args={"query": "KRAS G12C covalent inhibitors resistance"})
    dossier = registry.model.generate(inv, "triage targets for KRAS_G12C").output["text"]
    target = {"gene": "KRAS_G12C", "rationale": dossier[:80], "priority": 1}
    store.append(record_for(env(), EventType.artifact_created, actor,
                            artifact=artifact(env(), ArtifactKind.target_dossier, "kras", target)))
    log(f"  target dossier: {target['gene']}")
    gate(GateType.approve_candidate_batch.value, True)

    # ---------------------------------------------------- 2. Hit Generation (tournament)
    stage("hit_generation", "hypothesis tournament (Generate→Reflect→Rank→Evolve)")
    gen_inv = ToolInvocation(envelope=env(), tool="c.fm.generate_molecules", args=target)
    gen = registry.model.generate(gen_inv, f"generate 8 candidates for {target['gene']}", n=8)
    candidates = json.loads(gen.output["text"])
    tournament = HypothesisTournament(model, TournamentConfig(population=8, survivors=3, waves=2))
    hits = tournament.run(BRANCH, target, generate_fn=lambda ctx: candidates,
                          score_fn=lambda p: p["smiles"].count("C"))
    log(f"  survivors: {[h['smiles'] for h in hits]}")

    # --------------------------------------- 3. Lead Optimization (active-learning loop)
    stage("lead_optimization", "propose hypotheses → forked wet-lab tests → validate/record → flywheel")
    best, best_score = None, -1.0
    for rnd in range(1, 3):
        log(f" round {rnd}:")
        # in-silico analysis proposes one falsifiable hypothesis per assay
        predictions = {a: 55.0 + 5.0 * rnd for a in ASSAYS}
        # fork one sandbox branch per assay hypothesis, test, and record verdicts
        scores: dict[str, list[float]] = {}
        for i, assay in enumerate(ASSAYS):
            branch = sandbox.fork().branch_id
            benv = env(branch)
            top = hits[0]["smiles"]
            hyp = tracker.propose(
                statement=f"{top} achieves >= {predictions[assay]:.0f} {assay} response",
                candidate=top, assay_type=assay,
                predicted=f">= {predictions[assay]:.0f}",
                predicted_value=predictions[assay], round_no=rnd,
            )
            protocol = ProtocolSubmission(
                envelope=benv,
                title=f"r{rnd}-{assay}",
                assay_type=assay,
                steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense, params={"volume_ul": 50})],
                samples=[SampleSpec(sample_id=h["smiles"], kind=SampleKind.compound) for h in hits]
                + [SampleSpec(sample_id="ctrl-1", kind=SampleKind.buffer)],
                reagents=[ReagentSpec(name="assay-buffer", amount="5 mL", bsl_level=1)],
            )
            run_id, rejection = gateway.submit(protocol)
            if rejection:
                log(f"  [{branch}] {assay}: safety rejected — {rejection}")
                continue
            tracker.attach_test(hyp, protocol, run_id)
            result = gateway.results(benv, run_id)
            h = tracker.verdict(hyp, result, threshold=predictions[assay])
            vals = {m.sample_id: m.value for m in result.measurements}
            scores[assay] = [vals.get(h2["smiles"], 0.0) for h2 in hits]
            flywheel.pair_from_round(protocol, result)  # T4.4: ground truth for next models
            measured = vals.get(top, 0.0)
            log(f"  [{branch.split('/')[-1]}] {assay}: {hyp.status.upper()} "
                f"(predicted >= {predictions[assay]:.0f}, measured {measured:.1f}, run {run_id})")
        # combine assay panel into a composite score (stand-in for the Analysis Agent)
        combined = [sum(scores.get(a, [0] * len(hits))[i] for a in ASSAYS) / len(ASSAYS)
                    for i in range(len(hits))]
        rnd_best = int(max(range(len(hits)), key=lambda i: combined[i]))
        if combined[rnd_best] > best_score:
            best, best_score = hits[rnd_best]["smiles"], combined[rnd_best]
        log(f"  round {rnd} leader: {best} (composite {best_score:.1f})")
        # evolve: tournament next wave from proposals (stub: re-rank survivors)
        hits = tournament.run(BRANCH, {"prev": best}, generate_fn=lambda ctx: hits,
                              score_fn=lambda p: p["smiles"].count("C"))
    gate(GateType.approve_wetlab_protocol.value, True)

    # ------------------------------------------------------------- 4. Preclinical
    stage("preclinical", "ADMET panel + tox on the lead series")
    adm_inv = ToolInvocation(envelope=env(), tool="c.fm.predict_admet", args={"smiles": best})
    admet = registry.model.predict(adm_inv, "c.fm.predict_admet", {"smiles": best})
    tox_ok = best.count("C") <= 6  # stub tox rule: molecules beyond 6 heavy atoms fail
    log(f"  lead: {best}  admet: {admet.status}  tox_screen: {'pass' if tox_ok else 'fail'}")
    gate("preclinical_signoff", tox_ok)
    if not tox_ok:
        log("\n=== CAMPAIGN HALTED === tox screen failed — no IND package (recorded)")
        log(f"  hypotheses: {tracker.summary()}")
        log(f"  provenance: bn prove {BRANCH} --db campaign.db")
        return

    # ------------------------------------------------------------- 5. Trial Design
    stage("trial_design", "population simulation → IND package")
    trial_inv = ToolInvocation(envelope=env(), tool="e.sim.trial_simulation",
                               args={"candidate": best, "phase": 1})
    trial = registry.model.generate(trial_inv, "simulate phase-1 for lead").output
    ind = {"candidate": best, "composite_score": round(best_score, 2),
           "phase": 1, "est_enrollment": 60, "flywheel_examples": len(flywheel.load())}
    store.append(record_for(env(), EventType.artifact_created, actor,
                            artifact=artifact(env(), ArtifactKind.trial_protocol, "ind", ind)))

    # ----------------------------------------------------------------- Summary
    records = store.branch_records(BRANCH)
    hyp_summary = tracker.summary()
    log("\n=== CAMPAIGN SUMMARY ===")
    log(f"  IND package:         {ind}")
    log(f"  hypotheses:          {hyp_summary['proposed']} proposed, "
        f"{hyp_summary['validated']} validated, {hyp_summary['invalidated']} invalidated")
    log(f"  provenance records:  {len(records)} in {BRANCH} (hash-chained)")
    log(f"  flywheel examples:   {ind['flywheel_examples']} -> examples/_campaign_training.jsonl")
    log(f"  lab session:         examples/_campaign_recording.json (playback in CI)")
    log("  replay audit:        bn prove campaign-root --db campaign.db")


if __name__ == "__main__":
    main()
