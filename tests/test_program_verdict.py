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
    # root: achieved iff all achieved; failed if any failed; else partial
    vals = set(leaf_statuses)
    if vals == {"achieved"}:
        rollup["root"] = "achieved"
    elif "failed" in vals:
        rollup["root"] = "failed" if "achieved" not in vals else "partial"
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
