"""Make-as-gate: rule-corpus retrosynthesis blocks unmakeable molecules at Make.

The gate answers the med-chemist's first question — CAN we make this, how
long, at what cost, via how many routes — from named-reaction disconnection
rules. Every number is modeled per candidate (seeded) and stamped
SIMULATED; the block is earned by the yield/lead-time floors, not hard-coded.
"""
import pytest

from bionexus.adapters.retrosynthesis import (SIM_LABEL, RoutePlan,
                                              RuleBasedRetrosynthesis,
                                              _complexity,
                                              get_retrosynthesis_adapter)

AMIDE = "CC(=O)Nc1ccc(-c2ccccc2)c(F)c1"
SIMPLE = "CC(=O)NCC"
NIGHTMARE = ("[C@H]1([C@H]2[C@@H]1[C@@H]3[C@H]2[C@@H]4[C@@H]3[C@@H](C4)O)"
             "Cc5ccccc5")


def test_rule_corpus_plans_multiple_routes_with_cost_and_lead_time():
    routes = RuleBasedRetrosynthesis().plan_routes(AMIDE)
    assert len(routes) >= 2  # amide + biaryl/halogen/aryl-N motifs
    assert any("amide" in r.route for r in routes)
    for r in routes:
        assert 0.5 <= r.yield_pct <= 95
        assert 0 < r.lead_time_days < 120
        assert 40 <= r.cost_usd <= 10000
        assert r.data_origin == SIM_LABEL  # EVERY plan is stamped simulated


def test_plans_are_deterministic_per_candidate():
    rb = RuleBasedRetrosynthesis()
    a = [r.summary() for r in rb.plan_routes(AMIDE)]
    b = [r.summary() for r in rb.plan_routes(AMIDE)]
    assert a == b


def test_the_block_is_earned_not_hardcoded():
    rb = RuleBasedRetrosynthesis()
    assert not any(r.feasible for r in rb.plan_routes(NIGHTMARE))  # modeled
    assert rb.plan(NIGHTMARE).feasible is False
    assert any(r.feasible for r in rb.plan_routes(SIMPLE))
    assert rb.plan(SIMPLE).feasible is True


def test_complexity_grows_with_rings_and_stereo():
    assert _complexity("CCO") == 1
    assert _complexity(NIGHTMARE) > _complexity("c1ccccc1") + 3


def test_virtual_synthesizer_draws_yield_from_the_route():
    from bionexus.adapters.lab.synthesis import VirtualSynthesizer
    vs = VirtualSynthesizer()
    route = RoutePlan(route="amide coupling", steps=1, yield_pct=85.0,
                      lead_time_days=3.0, cost_usd=240.0).summary()
    batch = vs.synthesize("M-1", AMIDE, route=route)
    assert 25 <= batch["yield_pct"] <= 95  # ~N(85, 21), not flat U[5,95]
    assert batch["route"] == "amide coupling"
    assert batch["route_yield_model_pct"] == 85.0
    assert batch["route_lead_time_days"] == 3.0
    assert batch["data_origin"] == SIM_LABEL
    plain = vs.synthesize("M-1", AMIDE)  # legacy flat prior, no route keys
    assert "route" not in plain
    assert vs.synthesize("M-virtual")["ok"]  # structureless stays synthesizable


def _campaign(hyps, **kw):
    from bionexus.adapters.lab.simulator import SimulatorLab
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.autoloop import CampaignConfig, run_campaign
    from bionexus.core.hypothesis import Constraint, ProblemStatement

    problem = ProblemStatement(objective="makeability gate", constraints=[
        Constraint(name="potency", description="d", kind="hard", limit=60.0,
                   unit="uM")])
    cfg = CampaignConfig(problem=problem, hypotheses=hyps, k=2, rounds=1,
                         autonomy="act", inbox=".data/inbox-makegate",
                         poll_secs=0.05, **kw)
    store = SqliteProvenanceStore(":memory:")
    rep = run_campaign(cfg, SimulatorLab(seed=5), store)
    return store.branch_records(f"problem/{rep.problem_id}")


def _h(cand, smiles):
    return {"statement": f"{cand} binds", "candidate": cand,
            "assay_type": "binding", "predicted": "<= 60",
            "predicted_value": 60.0, "rationale": "t", "smiles": smiles}


def test_campaign_blocks_unmakeable_before_any_batch():
    records = _campaign([_h("NO-ROUTE", NIGHTMARE), _h("ROUTE", SIMPLE)])
    gates = [r for r in records if r.event_type.value == "gate_decision"
             and (r.decision or {}).get("kind") == "no_viable_route"]
    assert [g.decision["candidate"] for g in gates] == ["NO-ROUTE"]
    assert "simulated" in gates[0].decision["data_origin"]
    assert gates[0].decision["routes_planned"] >= 1
    assert gates[0].decision["best_modeled_yield_pct"] is not None
    # the blocked candidate NEVER reaches Make attempts or Test
    assert not [r for r in records
                if (r.decision or {}).get("candidate") == "NO-ROUTE"
                and r.event_type.value == "synthesis_complete"]
    # the viable one carries its route into the batch provenance
    syns = [r for r in records if r.event_type.value == "synthesis_complete"
            and (r.decision or {}).get("candidate") == "ROUTE"]
    assert syns and "route" in syns[0].decision
    assert syns[0].decision["route"]  # named route chosen by the model
    assert syns[0].decision["route_lead_time_days"] > 0


def test_campaign_gate_can_be_turned_off():
    records = _campaign([_h("NO-ROUTE", NIGHTMARE), _h("ROUTE", SIMPLE)],
                        synthesis_backend="none")
    assert not [r for r in records
                if (r.decision or {}).get("kind") == "no_viable_route"]


def test_toolkit_check_synthesis_answers_the_four_questions():
    from bionexus.core.interfaces import system_actor
    from bionexus.toolkit import AgentToolkit

    tk = AgentToolkit(None, None, system_actor("tk"),
                      branch_id="makeability")
    ans = tk.executors()["check_synthesis"](AMIDE)
    assert ans["makeable"] is True
    assert ans["num_routes"] >= 2 and ans["viable_routes"] >= 1
    assert 0 < ans["best_route"]["lead_time_days"] < 120
    assert ans["best_route"]["cost_usd"] > 0
    assert "simulated" in ans["data_origin"]
    blocked = tk.executors()["check_synthesis"](NIGHTMARE)
    assert blocked["makeable"] is False
    assert "CANNOT MAKE" in blocked["answer"]
