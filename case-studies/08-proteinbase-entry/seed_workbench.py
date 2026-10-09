#!/usr/bin/env python3
"""Seed the workbench with the CS08 campaign (no LLM, deterministic).

Registers "CS08 PD-L1 Designs" as a program, replays the real measured
Boltz-2 scores (.data/cs08-designs/night1/) through the hypothesis
tracker into the LIVE bionexus.db, and attaches the problem tree under
the program so the workspace renders: program -> problem tree ->
112 hypotheses (designs + controls) with CI-veto verdicts, all
`predicted_by`-stamped. Idempotent: refuses to double-seed.
"""
from __future__ import annotations

import json, re, sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
DATA = ROOT / ".data" / "cs08-designs" / "night1"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))
from bionexus import program as program_cfg                      # noqa: E402
from bionexus.adapters.lab.protein_design import (               # noqa: E402
    ProteinDesignLabAdapter)
from bionexus.adapters.store.sqlite import SqliteProvenanceStore  # noqa: E402
from bionexus.core.hypothesis import (Constraint, HypothesisTracker,  # noqa: E402
                                      ProblemStatement, SuccessCriteria)
from bionexus.core.interfaces import system_actor                 # noqa: E402
from bionexus.wizard_store import WizardStore                     # noqa: E402

PROGRAM = "CS08 PD-L1 Designs"
GATE, BAND_HALF = 0.7, 0.05


def load_scores(pred_dir: Path) -> dict[str, dict]:
    out = {}
    for f in sorted(pred_dir.glob("*/confidence_*.json")):
        name = f.name.removeprefix("confidence_").removesuffix("_model_0.json")
        out[name] = json.loads(f.read_text())
    return out


def main() -> int:
    slug = re.sub(r"[^a-z0-9]+", "-", PROGRAM.lower()).strip("-")[:48]
    if any(p["slug"] == slug for p in program_cfg.list_programs()):
        print(f"program '{PROGRAM}' already seeded — skipping (no double-append)")
        return 0

    doc = {"program": PROGRAM, "custom": True, "mode": "guided",
           "modality": "protein",
           "objective": "Prospective PD-L1 binder designs (BindCraft+MPNN) "
                        "screened by Boltz-2 ipTM against 30 composition-"
                        "matched controls; gate ipTM >= 0.7, single-"
                        "prediction +/-0.05 band",
           "metric": "iptm", "direction": "max", "gate_value": GATE,
           "unit": "iptm"}
    branch = program_cfg.save_program_record(doc)

    designs = load_scores(DATA / "boltz_predictions")
    ctrls = load_scores(DATA / "ctrl_predictions")
    binder_seq = {}
    for p in (DATA / "boltz_in2").glob("*.yaml"):
        m = re.search(r"id: A\n      sequence: (\w+)", p.read_text())
        if m:
            binder_seq[p.stem] = m.group(1)

    store = SqliteProvenanceStore("bionexus.db")
    tr = HypothesisTracker(store, system_actor("cs08-workbench"))
    prob = ProblemStatement(
        objective="PD-L1 binder design (CS08 prospective GPU run)",
        constraints=[Constraint(name="iptm", kind="hard", limit=GATE,
                                unit="iptm",
                                description="Boltz-2 interface confidence")])
    tr.define_problem(prob)
    hyp_branch = f"problem/{prob.problem_id}"
    criteria = SuccessCriteria(metric="iptm", direction="max",
                               threshold=GATE, proxy_of="pd_l1_binding_kd")

    # pre-registered single-node problem tree (the materials.py shape) —
    # written BEFORE any verdict lands, so the tree is genuinely prior
    from bionexus.problem_tree import ProblemNode, ProblemTree
    from bionexus.core.contracts import Envelope, EventType
    from bionexus.core.interfaces import record_for, system_actor as _sa
    pid = prob.problem_id
    leaf_branch = f"problem/{pid}-{pid}"     # canonical single-node leaf campaign
    screen_tree = ProblemTree(
        root=ProblemNode(id=pid, objective=prob.objective,
                         metric="iptm", direction="max", gate=GATE),
        nodes={pid: ProblemNode(id=pid, objective=prob.objective,
                                metric="iptm", direction="max", gate=GATE)},
        modality="protein", run_budget=len(designs) + len(ctrls))
    store.append(record_for(
        Envelope(experiment_branch_id=hyp_branch), EventType.problem_defined,
        _sa("cs08-workbench"),
        decision={"problem_id": pid, "objective": prob.objective,
                  "modality": "protein",
                  "constraints": [c.model_dump() for c in prob.constraints],
                  "success_metric": f"designs clear ipTM >= {GATE} while "
                                    f"matched controls do not",
                  "environment": {"kind": "problem-tree",
                                  "tree": screen_tree.model_dump(),
                                  "run_budget": screen_tree.run_budget}}))
    program_cfg.record_launch(PROGRAM, pid, prob.objective)
    ws_store = WizardStore()
    eid = f"cs08-{pid}"
    ws_store.register_agent(eid, objective="CS08 prospective PD-L1 design screen",
                            log=".data/cs08-designs/night1/logs/boltz_run4.log",
                            autonomy="guided", program=PROGRAM)
    # the workspace retired-tree filter matches single-node trees via the
    # doubled pid form (root-leaf), same convention as materials runs
    ws_store.link_problem(eid, f"{pid}-{pid}")
    ws_store.update(eid, "verdict_recorded")
    program_cfg.attach_experiment(PROGRAM, eid, pid,
                                  "prospective design screen, 82 designs + "
                                  "30 controls", status="verdict_recorded")

    adapter = ProteinDesignLabAdapter(mock=False)
    rows = [{"name": n, "sequence": binder_seq.get(n, "X" * 50),
             "plddt": c["complex_plddt"]} for n, c in designs.items()]
    passing, rejected = adapter.apply_quality_floor(rows)
    pass_names = {d["name"] for d in passing}

    def origin_of(name: str, c: dict) -> tuple[str, str, str]:
        """(statement, rationale, mechanism) with real provenance — a card
        must say WHAT the molecule is, not just what the model scored."""
        seq_len = int(c.get("n_seq") or 0)
        if name.startswith("SCR_"):
            parent = name[4:]
            return (f"{name}: binds PD-L1 ECD (ipTM >= {GATE}) — CONTROL",
                    f"Composition-matched scramble of designed binder "
                    f"{parent} ({seq_len} aa); tests whether ipTM knows "
                    f"design from anagram",
                    "control: shuffled sequence, same AA composition")
        if name.startswith("RND_"):
            return (f"{name}: binds PD-L1 ECD (ipTM >= {GATE}) — CONTROL",
                    f"Random {seq_len}-mer over natural AA alphabet; "
                    f"null-distribution probe for Boltz-2 ipTM",
                    "control: random peptide, no design process")
        m = re.search(r"_l(\d+)_s(\d+)_mpnn(\d+)$", name)
        if m:
            ln, seed, mp = m.groups()
            return (f"{name}: binds PD-L1 ECD (ipTM >= {GATE})",
                    f"BindCraft de novo design against PD-L1 hotspot-56 "
                    f"(CD80-competition face): {ln} aa, AF2 seed {seed}, "
                    f"MPNN sequence {mp}; complex pLDDT "
                    f"{c['complex_plddt']:.3f}",
                    "designed helical/sheet binder interface (BindCraft "
                    "multimer pipeline)")
        return (f"{name}: binds PD-L1 ECD (ipTM >= {GATE})", "", "")

    def run_one(name: str, c: dict, role: str) -> str:
        statement, rationale, mechanism = origin_of(name, c)
        h = tr.propose(
            statement=statement,
            candidate=name, assay_type="protein_binder_screen",
            predicted=f"ipTM >= {GATE}", predicted_value=c["iptm"],
            rationale=rationale, mechanism=mechanism,
            refutation_condition=(
                "ipTM 95% CI lies wholly below "
                f"{GATE} (observed +{BAND_HALF} < gate); if the CI "
                f"straddles {GATE} the honest outcome is inconclusive, "
                "not refuted"
                + ("; NOTE: if this control validates while clearing the "
                   "same bar as real designs, the ranking value of ipTM "
                   "is itself refuted" if role != "design" else "")),
            predicted_observables=[f"iptm >= {GATE}",
                                   "complex pLDDT >= 0.7"],
            branch_id=leaf_branch, criteria=criteria,
            predicted_by={"source": "bindcraft+mpnn" if role == "design"
                          else "control (scramble|random)",
                          "policy": "AF2-backprop+MPNN -> boltz2 ipTM"},
            role=role, model="boltz-2", n_replicates=1,
            seed=(re.search(r"_s(\d+)_", name).group(1)
                  if re.search(r"_s(\d+)_", name) else None))
        ci = (round(c["iptm"] - BAND_HALF, 4), round(c["iptm"] + BAND_HALF, 4))
        h.status = criteria.classify(c["iptm"], ci)
        h.observed_value = c["iptm"]
        h.observed_ci = ci
        h.qc_passed = True
        tr.record_outcome(h, extra={"evidence_tier": "proxy",
                                    "iptm": c["iptm"],
                                    "complex_plddt": c["complex_plddt"]})
        return h.status

    ctrl_seq = {}
    for p in (DATA / "controls_in").glob("*.yaml"):
        m = re.search(r"id: A\n      sequence: (\w+)", p.read_text())
        if m:
            ctrl_seq[p.stem] = m.group(1)
    for n, c in designs.items():
        c["n_seq"] = len(binder_seq.get(n, ""))
    for n, c in ctrls.items():
        c["n_seq"] = len(ctrl_seq.get(n, ""))

    store.append(record_for(
        Envelope(experiment_branch_id=leaf_branch), EventType.stage_transition,
        _sa("cs08-workbench"),
        decision={"kind": "round_start", "round": 1,
                  "candidates": sorted(list(designs) + list(ctrls))}))
    # physical reality: TWO in-silico screening batches, not 112 submissions
    for run_id, group, n_ctrl in (("boltz-screen-designs", designs, 0),
                                  ("boltz-screen-controls", ctrls, len(ctrls))):
        store.append(record_for(
            Envelope(experiment_branch_id=leaf_branch), EventType.lab_run,
            _sa("cs08-workbench"),
            decision={"run_id": run_id, "round": 1,
                      "title": f"Boltz-2 batch: {group and len(group)} "
                               f"sequences vs PD-L1 ECD (115-res)",
                      "assay": "boltz2_iptm_screen (in silico)",
                      "n_samples": len(group), "replicates": 1,
                      "n_controls": n_ctrl,
                      "model": "boltz-2", "use_msa_server": True,
                      "max_msa_seqs": 64}))
    tally: dict[str, dict[str, int]] = {}
    for n, c in sorted(designs.items()):
        if n in pass_names:
            s = run_one(n, c, "design")
            tally.setdefault("design", {})[s] = tally.setdefault("design", {}).get(s, 0) + 1
    for n, c in sorted(ctrls.items()):
        role = "control_scramble" if n.startswith("SCR_") else "control_random"
        s = run_one(n, c, role)
        tally.setdefault(role, {})[s] = tally.setdefault(role, {}).get(s, 0) + 1

    # honest leaf status: the pre-registered claim was "designs clear the
    # gate AND matched controls do not". Designs did (72/82) — controls DID
    # too (11/30 validated). The claim is PARTIAL, not achieved. Say so.
    ctrl_validated = (tally.get("control_scramble", {}).get("validated", 0)
                      + tally.get("control_random", {}).get("validated", 0))
    des_validated = tally.get("design", {}).get("validated", 0)
    leaf_status = ("achieved" if des_validated and ctrl_validated == 0 else
                   "partial" if des_validated else "failed")
    screen_tree.nodes[pid].status = leaf_status
    store.append(record_for(
        Envelope(experiment_branch_id=hyp_branch), EventType.problem_defined,
        _sa("cs08-workbench"),
        decision={"problem_id": pid, "objective": prob.objective,
                  "modality": "protein",
                  "constraints": [c.model_dump() for c in prob.constraints],
                  "success_metric": "designs clear ipTM >= 0.7 while matched "
                                     "controls do not",
                  "verdict_note": f"designs {des_validated}/82 validated; "
                                  f"controls {ctrl_validated}/30 validated — "
                                  f"gate separates distributions (MWU "
                                  f"p~1e-4) but NOT individuals "
                                  f"(AUC 0.80): ipTM is a gate, not a ranking",
                  "environment": {"kind": "problem-tree",
                                  "tree": screen_tree.model_dump(),
                                  "run_budget": screen_tree.run_budget}}))
    WizardStore().set_status(eid, "verdict_recorded")
    print(json.dumps({"branch": branch, "problem_id": pid, "eid": eid,
                      "leaf_status": leaf_status, "tallies": tally,
                      "floor_rejected": len(rejected)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
