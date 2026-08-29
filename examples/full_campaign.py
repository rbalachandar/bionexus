"""Full campaign simulation — the real drug-discovery cycle on the virtual lab.

Mirrors docs/domain-review.md phase by phase:

    0. Target ID + validation (evidence score, druggability)      [gate]
    1. Hit discovery           (hypothesis tournament)            [gate]
    2. Hit validation          (counterscreen, dose–response IC50, replicates)
    3. Hit-to-lead / Lead opt  (DMTA rounds: MPO + kill criteria) [gate]
    4. Preclinical             (tox panel: hERG/Ames/microsomal)  [gate]
    5. Clinical plan           (Ph I/II/III go-no-go structure)   → IND

Hypotheses are first-class: proposed → tested → validated/invalidated with
evidence, all provenance-recorded and hash-chained. Confirmed results feed the
flywheel. Zero hardware, zero network.

    python examples/full_campaign.py
"""
from __future__ import annotations

import json
import statistics

from bionexus.adapters.lab.recording import RecordingLab
from bionexus.adapters.lab.simulator import SimulatorLab, parse_concentration_um
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
from bionexus.core.hypothesis import Hypothesis, HypothesisTracker
from bionexus.core.interfaces import record_for, system_actor
from bionexus.core.registry import Registry
from bionexus.core.safety import LabGateway, MaxBslRule, MaxStepsRule, SafetyEngine
from bionexus.core.workflow import HypothesisTournament, TournamentConfig

BRANCH = "campaign-root"
SEED = 42
CONCS = ["0.5uM", "2uM", "10uM", "40uM"]  # dose–response series


def fit_ic50(points: list[tuple[float, float]]) -> float:
    """Coarse IC50 (uM): concentration nearest 50% of max observed response."""
    if not points:
        return float("inf")
    top = max(v for _, v in points)
    if top <= 1.0:
        return float("inf")
    target = top / 2.0
    pts = sorted(points)
    for i in range(1, len(pts)):
        (c0, v0), (c1, v1) = pts[i - 1], pts[i]
        if v0 <= target <= v1:
            frac = 0.0 if v1 == v0 else (target - v0) / (v1 - v0)
            return c0 + frac * (c1 - c0)
    return float("inf") if pts[-1][1] < target else pts[-1][0]


def main() -> None:
    store = SqliteProvenanceStore("campaign.db")
    actor: Actor = system_actor("campaign-sim")
    model = OpenAICompatProvider()  # offline stub
    registry = Registry()
    registry.register_model(model, default=True)

    rec = RecordingLab(SimulatorLab(seed=SEED), "examples/_campaign_recording.json")
    safety = SafetyEngine(rules=[MaxBslRule(2), MaxStepsRule(50)])
    gateway = LabGateway(rec, safety, store, actor)
    flywheel = FlywheelLog("examples/_campaign_training.jsonl")
    tracker = HypothesisTracker(store, actor)
    sandbox = LocalSandbox(BRANCH, store=store, actor=actor)

    def env(branch: str = BRANCH) -> Envelope:
        return Envelope(experiment_branch_id=branch)

    def log(msg: str) -> None:
        print(msg)

    def gate(name: str, approved: bool, reason: str = "") -> bool:
        store.append(record_for(env(), EventType.gate_decision, actor,
                                decision={"gate": name, "approved": approved,
                                          "approved_by": "scripted-scientist", "reason": reason}))
        log(f"  [gate] {name}: {'APPROVED' if approved else 'REJECTED'}"
            + (f" — {reason}" if reason else ""))
        return approved

    def stage(name: str, detail: str) -> None:
        store.append(record_for(env(), EventType.stage_transition, actor,
                                decision={"stage": name, "detail": detail}))
        log(f"\n=== {name.upper()} === {detail}")

    def run_assay(branch: str, title: str, assay: str, compounds: list[str]) -> dict:
        """Submit one assay protocol (dose–response series + replicates + controls)."""
        samples = [SampleSpec(sample_id=c, kind=SampleKind.compound, concentration=cc)
                   for c in compounds for cc in CONCS]
        samples.append(SampleSpec(sample_id="ctrl-neg", kind=SampleKind.buffer, concentration="10uM"))
        protocol = ProtocolSubmission(
            envelope=env(branch), title=title, assay_type=assay,
            steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense, params={"volume_ul": 50})],
            samples=samples,
            reagents=[ReagentSpec(name="assay-buffer", amount="5 mL", bsl_level=1)],
        )
        run_id, rejection = gateway.submit(protocol)
        if rejection:
            return {"rejected": rejection}
        result = gateway.results(env(branch), run_id)
        flywheel.pair_from_round(protocol, result)
        # collect per-compound responses (median across concentrations not used; we fit below)
        by_compound: dict[str, list[tuple[float, float]]] = {}
        for m in result.measurements:
            if "control" in [f.value for f in m.flags]:
                continue
            by_compound.setdefault(m.sample_id, []).append(
                (parse_concentration_um(m.well.split("-")[-1]), m.value))
        return {"run_id": run_id, "protocol": protocol, "result": result,
                "by_compound": by_compound}

    # ------------------------------------------------- 0. Target ID + validation
    stage("target_id", "disease association, target validation, druggability")
    inv = ToolInvocation(envelope=env(), tool="c.kb.search_literature",
                         args={"query": "KRAS G12C covalent inhibitors resistance"})
    dossier = registry.model.generate(inv, "triage targets for KRAS_G12C").output["text"]
    evidence_score, druggable = 0.87, True  # genetics/omics evidence; pocket tractable
    validated = evidence_score >= 0.7 and druggable
    log(f"  evidence_score={evidence_score}  druggable={druggable}  "
        f"-> {'VALIDATED' if validated else 'REJECTED'}")
    store.append(record_for(env(), EventType.artifact_created, actor,
                            artifact=Artifact(artifact_id="dossier-kras", kind=ArtifactKind.target_dossier,
                                              uri=f"mem://{BRANCH}/kras",
                                              metadata={"gene": "KRAS_G12C", "evidence": evidence_score})))
    if not gate("target_validation", validated, "evidence + druggability"):
        log("\n=== CAMPAIGN HALTED: target not validated ===")
        return

    # ------------------------------------------------------- 1. Hit discovery
    stage("hit_discovery", "hypothesis tournament (Generate→Reflect→Rank→Evolve)")
    gen_inv = ToolInvocation(envelope=env(), tool="c.fm.generate_molecules",
                             args={"gene": "KRAS_G12C"})
    gen = registry.model.generate(gen_inv, "generate 8 candidates for KRAS_G12C", n=8)
    candidates = json.loads(gen.output["text"])
    hits = [c["smiles"] for c in HypothesisTournament(
        model, TournamentConfig(population=8, survivors=4, waves=2)
    ).run(BRANCH, {}, generate_fn=lambda ctx: candidates,
          score_fn=lambda p: p["smiles"].count("C"))]
    log(f"  hits: {hits}")
    gate(GateType.approve_candidate_batch.value, True)

    # ------------------------------------------------------- 2. Hit validation
    stage("hit_validation", "counterscreen → primary dose–response → IC50 (replicates)")
    cs = run_assay(sandbox.fork().branch_id, "counterscreen", "counterscreen", hits)
    interferers = {c for c, pts in cs["by_compound"].items()
                   if statistics.median([v for _, v in pts]) > 20.0}
    log(f"  counterscreen: {len(interferers)} artifact(s) dropped: {sorted(interferers) or 'none'}")
    confirmed: list[dict] = []
    for c in [h for h in hits if h not in interferers]:
        prim = run_assay(sandbox.fork().branch_id, f"confirm-{c}", "binding", [c])
        ic50 = fit_ic50(prim["by_compound"].get(c, []))
        hyp = tracker.propose(
            statement=f"{c} is a confirmed binder (IC50 <= 20 uM)",
            candidate=c, assay_type="binding", predicted="IC50 <= 20 uM",
            predicted_value=20.0, round_no=0,
        )
        tracker.attach_test(hyp, prim["protocol"], prim["run_id"])
        # verdict from the fitted IC50 vs the 20 uM cutoff
        measured_ok = ic50 <= 20.0
        hyp.status = "validated" if measured_ok else "invalidated"
        hyp.measured_value = None if ic50 == float("inf") else ic50
        hyp.evidence_run_id = prim["run_id"]
        store.append(record_for(
            env(hyp.branch_id),
            EventType.hypothesis_validated if measured_ok else EventType.hypothesis_invalidated,
            actor,
                                    artifact=Artifact(artifact_id=hyp.hypothesis_id, kind=ArtifactKind.hypothesis,
                                                      uri=f"mem://{hyp.branch_id}/{hyp.hypothesis_id}"),
            decision={"ic50_um": None if ic50 == float("inf") else round(ic50, 2),
                      "cutoff_um": 20.0, "evidence_run_id": prim["run_id"]},
        ))
        if measured_ok:
            confirmed.append({"compound": c, "ic50_um": round(ic50, 2)})
    confirmed.sort(key=lambda d: d["ic50_um"])
    log(f"  confirmed hits (IC50 <= 20 uM): {confirmed}")
    if not gate("hit_validation", len(confirmed) >= 1,
                "need >=1 confirmed hit"):
        log("\n=== CAMPAIGN HALTED: no confirmed hits ===")
        return

    # -------------------------------------- 3. Lead optimization (DMTA + MPO)
    stage("lead_optimization",
          "DMTA rounds: MPO (potency/selectivity/ADME/physchem) with kill criteria")
    series = [{"compound": c["compound"], "ic50_um": c["ic50_um"]} for c in confirmed[:4]]
    best, backups, best_mpo = None, [], -1.0
    for rnd in range(1, 3):
        log(f" DMTA round {rnd}: design → make(stub) → test → analyze")
        panel = {}
        for i, member in enumerate(series):
            branch = sandbox.fork().branch_id
            assays = ["binding", "enzymatic", "cytotoxicity"]
            selectivity_pts, potency = [], None
            for assay in assays:
                r = run_assay(branch, f"r{rnd}-{member['compound']}-{assay}", assay,
                              [member["compound"]])
                if "rejected" in r:
                    continue
                pts = r["by_compound"].get(member["compound"], [])
                if assay == "binding":
                    potency = fit_ic50(pts)
                else:
                    selectivity_pts.append(fit_ic50(pts))
            adme = 0.6 + 0.3 * ((hash(member["compound"]) % 100) / 100)  # stub ADME score
            physchem_ok = member["compound"].count("C") <= 7             # Lipinski-ish stub
            selectivity = (min(selectivity_pts) / max(potency, 1e-9)
                           if selectivity_pts and potency else 1.0)
            mpo = mpo_score(potency, selectivity, adme, physchem_ok)
            member.update(potency_um=potency, selectivity=round(selectivity, 2),
                          adme=round(adme, 2), physchem=physchem_ok, mpo=mpo)
            panel[member["compound"]] = member
            # hypothesis: predicted potency improvement this round
            hyp = tracker.propose(
                statement=f"{member['compound']} holds MPO >= 0.5 in round {rnd}",
                candidate=member["compound"], assay_type="panel",
                predicted="MPO >= 0.5", predicted_value=0.5, round_no=rnd,
            )
            hyp.status = "validated" if mpo >= 0.5 else "invalidated"
            tracker.hypotheses[hyp.hypothesis_id] = hyp
            store.append(record_for(env(branch),
                                    EventType.hypothesis_validated if mpo >= 0.5
                                    else EventType.hypothesis_invalidated, actor,
                                    artifact=Artifact(artifact_id=hyp.hypothesis_id,
                                                      kind=ArtifactKind.hypothesis,
                                                      uri=f"mem://{branch}/{hyp.hypothesis_id}"),
                                    decision={"mpo": round(mpo, 3)}))
        # kill criteria: drop members failing hard cutoffs
        killed = [c for c, m in panel.items()
                  if m["physchem"] is False or m["selectivity"] < 0.3 or m["potency_um"] > 30]
        for k in killed:
            panel.pop(k)
        log(f"  killed: {killed or 'none'} | survivors: "
            f"{[(m['compound'], round(m['mpo'], 2)) for m in panel.values()]}")
        if panel:
            leader = max(panel.values(), key=lambda m: m["mpo"])
            if leader["mpo"] > best_mpo:
                best, best_mpo = leader["compound"], leader["mpo"]
            backups = [m["compound"] for m in sorted(panel.values(),
                                                     key=lambda m: -m["mpo"])[1:3]]
        # evolve series toward the leader's profile (stub 'design' step)
        series = [dict(m) for m in panel.values()] or series
    log(f"  lead: {best} (MPO {best_mpo:.2f})  backups: {backups}")
    gate(GateType.approve_wetlab_protocol.value, best is not None, "lead selected")

    # ------------------------------------------------------- 4. Preclinical
    stage("preclinical", "tox panel: hERG / Ames / microsomal stability (stub assays)")
    tox = tox_panel(best)
    for k, v in tox.items():
        log(f"  {k}: {'PASS' if v else 'FAIL'}")
    tox_ok = all(tox.values())
    gate("preclinical_signoff", tox_ok,
         "lead failed tox panel — promote backup" if not tox_ok else "")
    if not tox_ok and backups:
        best, best_mpo = backups[0], best_mpo  # reps & backups: promote backup
        tox = tox_panel(best)
        tox_ok = all(tox.values())
        log(f"  promoted backup {best}: {'PASS' if tox_ok else 'FAIL'}")
        gate("preclinical_signoff_backup", tox_ok)
    if not tox_ok:
        log("\n=== CAMPAIGN HALTED: no candidate passed preclinical tox ===")
        log(f"  hypotheses: {tracker.summary()}")
        return

    # ------------------------------------------------------- 5. Clinical plan
    stage("clinical_plan", "Ph I/II/III structure with go/no-go criteria → IND")
    ind = {
        "candidate": best, "mpo": round(best_mpo, 2),
        "phases": [
            {"phase": 1, "n": 60, "objective": "safety/PK", "go": "MTD established, half-life >= 6h"},
            {"phase": 2, "n": 150, "objective": "PoC", "go": ">= 30% ORR, futility boundary at 10%"},
            {"phase": 3, "n": 600, "objective": "confirmatory", "go": "OS/PFS superiority"},
        ],
        "flywheel_examples": len(flywheel.load()),
    }
    store.append(record_for(env(), EventType.artifact_created, actor,
                            artifact=Artifact(artifact_id="ind-1", kind=ArtifactKind.trial_protocol,
                                              uri=f"mem://{BRANCH}/ind", metadata=ind)))

    # ----------------------------------------------------------------- Summary
    log("\n=== CAMPAIGN SUMMARY ===")
    log(f"  IND package:         {ind}")
    log(f"  hypotheses:          {tracker.summary()}")
    log(f"  provenance records:  {len(store.branch_records(BRANCH))} in {BRANCH} (hash-chained)")
    log(f"  flywheel examples:   {ind['flywheel_examples']}")
    log("  replay audit:        bn prove campaign-root --db campaign.db")


# ------------------------------------------------------------------ helpers

def predicted_binding_response(ic50: float, concs: list[str]) -> float:
    """Expected response at the highest test concentration (for hypothesis verdicts)."""
    c = parse_concentration_um(concs[-1])
    return 100.0 / (1.0 + ic50 / c)


def mpo_score(potency_um: float, selectivity: float, adme: float, physchem: bool) -> float:
    """Weighted multiparameter optimization score in [0, 1]."""
    potency = max(0.0, 1.0 - potency_um / 30.0)          # 0 uM -> 1.0, 30+ uM -> 0
    sel = max(0.0, min(1.0, selectivity))                 # >1 means cleaner than target
    phys = 1.0 if physchem else 0.0
    return round(0.4 * potency + 0.25 * sel + 0.2 * adme + 0.15 * phys, 3)


def tox_panel(compound: str) -> dict[str, bool]:
    """Stub tox panel with compound-seeded outcomes (hERG, Ames, microsomal).
    Uses sha256 (stable across processes, unlike hash())."""
    import hashlib

    key = int(hashlib.sha256(("tox:" + compound).encode()).hexdigest()[:8], 16) % 97
    return {"hERG": key % 3 != 0, "Ames": key % 5 != 0, "microsomal_stability": key % 7 != 0}


if __name__ == "__main__":
    main()
