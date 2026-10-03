"""Program-level consolidated verdicts (deterministic tree roll-up)."""
from bionexus.views import program_verdict


def _tree(leaf_statuses: list[str], metric: str = "ic50") -> dict:
    """A one-level tree: root + N leaves, each leaf status given."""
    nodes = [{"id": "root", "parent": None, "objective": "obj",
              "status": "", "metric": metric, "direction": "min",
              "gate": 20.0}]
    rollup = {}
    for i, st in enumerate(leaf_statuses):
        lid = f"l{i}"
        nodes.append({"id": lid, "parent": "root", "objective": f"leaf {i}",
                      "status": st, "metric": None, "direction": None,
                      "gate": None})
        rollup[lid] = st
    # root: achieved iff all achieved; failed if any failed; abstention
    # with nothing earned is inconclusive — never a false refutation
    vals = set(leaf_statuses)
    if vals == {"achieved"}:
        rollup["root"] = "achieved"
    elif "failed" in vals:
        rollup["root"] = "failed" if "achieved" not in vals else "partial"
    elif "partial" in vals:
        rollup["root"] = "partial"
    elif "inconclusive" in vals:
        rollup["root"] = "partial" if "achieved" in vals else "inconclusive"
    else:
        rollup["root"] = "partial"
    return {"root_id": "root", "objective": "obj", "nodes": nodes,
            "rollup": rollup, "leaf_stats": {}}


def test_no_tree():
    v = program_verdict([])
    assert v["status"] == "no-tree"


def test_unresolved_is_inconclusive():
    v = program_verdict([_tree(["", ""])])
    assert v["status"] == "inconclusive"
    assert v["resolved"] == 0 and v["leaves"] == 2


def test_all_supported():
    v = program_verdict([_tree(["achieved", "achieved"])])
    assert v["status"] == "supported"
    assert v["resolved"] == v["leaves"] == 2


def test_refuted():
    v = program_verdict([_tree(["failed", "failed"])])
    assert v["status"] == "refuted"


def test_partial_with_unresolved():
    v = program_verdict([_tree(["achieved", ""])])
    assert v["status"] == "partial"
    assert "1 unresolved" in v["reason"]


def test_gate_met_and_missed():
    t = _tree(["achieved"])
    # the gate leaf measures the root metric
    t["nodes"][1]["metric"] = "ic50"
    v = program_verdict([t])
    assert v["gate"] == {"status": "met", "leaf": "leaf 0",
                         "metric": "ic50"}
    t2 = _tree(["failed"])
    t2["nodes"][1]["metric"] = "ic50"
    assert program_verdict([t2])["gate"]["status"] == "missed"


def test_gate_unexercised_when_no_leaf_measures_it():
    v = program_verdict([_tree(["achieved"])])
    assert v["gate"] is None


def test_parse_actions():
    from bionexus.api.app import _parse_actions
    prose, actions, concl = _parse_actions(
        "Learned: x\nBlocks: y\nNext: try z\nNEXT:\n"
        "- Diagnose the potency discrepancy with an orthogonal assay\n"
        "1. Run a hERG counter-screen on the lead chemotype\n"
        "- too short\n")
    assert prose.startswith("Learned:")
    assert concl is None
    assert actions == [
        {"objective": "Diagnose the potency discrepancy with an "
                      "orthogonal assay", "tree": False},
        {"objective": "Run a hERG counter-screen on the lead chemotype",
         "tree": False}]
    # no NEXT block -> everything stays prose
    p2, a2, c2 = _parse_actions("Learned: x\nNext: y")
    assert a2 == [] and p2.endswith("y") and c2 is None
    # CONCLUSION wins over actions and ends the loop
    p3, a3, c3 = _parse_actions(
        "Learned: x\nNEXT:\n- more work\nCONCLUSION: "
        "objective met within assay limits")
    assert a3 == [] and c3.startswith("objective met") and p3 == "Learned: x"


def test_policy_active_and_escalated():
    from bionexus.views import program_policy
    t = _tree(["achieved", ""])
    p = {"verdict": program_verdict([t]),
         "links": [{"eid": "e1", "runs": 3, "verdicts": {"confirmed": 1}},
                   {"eid": "root", "campaign_root": "x", "runs": 99}],
         "trees": [{**t, "leaf_stats": {}}]}
    doc = {}
    pol = program_policy(p, doc)
    assert pol["status"] == "active"
    assert pol["runs"] == 3  # tree-root container runs don't count

    # evidence budget
    pol = program_policy(p, {"policy": {"max_runs": 2}})
    assert pol["status"] == "escalated" and "budget" in pol["reason"]

    # cycle budget
    pol = program_policy(p, {"brief": {"cycle": 5}})
    assert pol["status"] == "escalated" and "cycle" in pol["reason"]

    # decisive objective
    t2 = _tree(["achieved", "achieved"])
    p2 = {"verdict": program_verdict([t2]), "links": [], "trees": [t2]}
    pol = program_policy(p2, {})
    assert pol["status"] == "escalated" and "supported" in pol["reason"]


def test_all_abstain_is_inconclusive_not_refuted():
    """THE inversion: a program whose decisive leaves all abstained must
    never print 'Objective refuted' — borderline evidence is unresolved."""
    v = program_verdict([_tree(["inconclusive", "inconclusive"])])
    assert v["status"] == "inconclusive"
    assert "abstained" in v["reason"]


def test_achieved_plus_abstention_is_partial():
    v = program_verdict([_tree(["achieved", "inconclusive"])])
    assert v["status"] == "partial"
