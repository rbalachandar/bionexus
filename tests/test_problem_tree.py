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


def test_hierarchical_allocation_protects_branch_shares():
    """A deep subtree cannot soak a flat sibling's budget: potency's slice
    is split among ITS children only, out of the root's sight."""
    t = _tree(run_budget=12)
    pot = t.add(t.root.id, objective="potency", priority=1.0)
    t.add(pot.id, objective="PKA binding", priority=1.0)
    t.add(pot.id, objective="off-target", priority=1.0)
    sel = t.add(t.root.id, objective="selectivity", priority=1.0)
    alloc = t.allocation()
    assert sum(alloc.values()) <= 12
    leaves = t.leaves()
    assert all(alloc[l.id] >= 2 for l in leaves)
    # potency's two children together get ~half the budget, same as
    # selectivity — the root split is by priority among ITS children
    pot_total = sum(alloc[l.id] for l in t.subtree_leaves(pot.id))
    sel_total = alloc[sel.id]
    assert abs(pot_total - sel_total) <= 2      # equal priorities, ~equal split
    # intermediate nodes never appear in the allocation
    assert pot.id not in alloc and t.root.id not in alloc


def test_subtree_leaves_nesting():
    t = _tree()
    pot = t.add(t.root.id, objective="potency")
    a = t.add(pot.id, objective="PKA")
    b = t.add(pot.id, objective="off-target")
    c = t.add(t.root.id, objective="solubility")
    assert {n.id for n in t.subtree_leaves(pot.id)} == {a.id, b.id}
    assert {n.id for n in t.subtree_leaves(t.root.id)} == {a.id, b.id, c.id}


def test_synthesis_deterministic_and_gated():
    """Make is first-class: same structure -> same batch; failed batches
    are deterministic and gateable."""
    from bionexus.adapters.lab.synthesis import VirtualSynthesizer
    s = VirtualSynthesizer()
    a = s.synthesize("X-1", "c1ccccc1")
    b = s.synthesize("X-1", "c1ccccc1")
    assert a == b and a["ok"] is True            # clean structures pass
    fails = [i for i in range(50)
             if not s.synthesize(f"F-{i}", "CC(=O)Oc1ccccc1C")["ok"]]
    assert 0 < len(fails) < 50                   # real, but not universal
    again = s.synthesize(f"F-{fails[0]}", "CC(=O)Oc1ccccc1C")
    assert again["ok"] is False                  # failures are deterministic
