"""Problem-tree tests: guardrails, allocation, roll-up, execution budget."""
import json

import pytest

from bionexus.problem_tree import (ProblemTree, TreeLimits,
                                   decompose_with_agent, run_tree)


def _tree(**kw):
    lim = TreeLimits(max_children=kw.get("max_children", 3),
                     max_depth=kw.get("max_depth", 2),
                     max_nodes=kw.get("max_nodes", 12))
    return ProblemTree.create("root objective", limits=lim,
                              run_budget=kw.get("run_budget", 8))


def test_depth_and_breadth_guards_raise():
    t = _tree(max_children=2, max_depth=1)
    a = t.add(t.root.id, objective="a")
    with pytest.raises(ValueError, match="max_depth"):
        t.add(a.id, objective="grandchild")
    t.add(t.root.id, objective="b")
    with pytest.raises(ValueError, match="max_children"):
        t.add(t.root.id, objective="c")


def test_allocation_weights_and_caps():
    t = _tree(run_budget=10)
    t.add(t.root.id, objective="hi", priority=3)
    t.add(t.root.id, objective="lo", priority=1)
    alloc = t.allocation()
    assert sum(alloc.values()) <= 10
    assert max(alloc.values()) >= 2 * min(alloc.values())


def test_rollup_conjunction():
    t = _tree()
    a = t.add(t.root.id, objective="a")
    b = t.add(t.root.id, objective="b")
    t.set_leaf_status(a.id, {"x": "confirmed"})
    t.set_leaf_status(b.id, {"y": "refuted"})
    assert t.rollup()[t.root.id] == "partial"
    t.set_leaf_status(b.id, {"y": "confirmed"})
    assert t.rollup()[t.root.id] == "achieved"


def test_decompose_truncates_overeager_model():
    class Model:
        def generate(self, inv, prompt):
            class R:
                output = {"text": json.dumps({"sub_problems": [
                    {"objective": f"s{i}", "metric": "ic50_um",
                     "direction": "min", "gate": 20.0}
                    for i in range(9)]})}
            return R()
    t = decompose_with_agent(Model(), "obj",
                             limits=TreeLimits(max_children=3),
                             say=lambda m: None)
    assert len(t.children(t.root.id)) == 3


def test_run_tree_respects_budget(tmp_path):
    from bionexus.adapters.lab.simulator import SimulatorLab
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    t = _tree(run_budget=6)
    t.add(t.root.id, objective="potency", metric="ic50_um", gate=20.0)
    t.add(t.root.id, objective="clarity", metric="solubility_uM",
          direction="max", gate=10.0)
    store = SqliteProvenanceStore()
    run_tree(t, lambda: SimulatorLab(seed=1), store,
             candidates=[{"sample_id": f"C-{i}"} for i in range(1, 4)],
             inbox=str(tmp_path / "in"), notify=lambda m: None)
    runs = 0
    for leaf in t.leaves():
        runs += sum(1 for r in store.branch_records(leaf.branch(t.root.id))
                    if r.event_type.value == "lab_run")
    assert runs <= t.run_budget
    assert t.rollup()[t.root.id] in ("achieved", "partial", "failed")
    assert any((r.decision or {}).get("kind") == "tree-rollup"
               for r in store.branch_records(f"problem/{t.root.id}"))
