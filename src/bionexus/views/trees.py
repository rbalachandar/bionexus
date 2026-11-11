"""Problem-tree read-model (leaf campaigns, allocation, rollups)."""
from __future__ import annotations

from pathlib import Path

from bionexus.views.ids import leaf_pid
from bionexus.views import ids as _ids


# ------------------------------------------------------------- problem trees
def problem_trees(db_path: str | Path = _ids.PROVENANCE_DB) -> tuple[list, set]:
    """All serialized problem trees with live status, as JSON-able
    dicts. Returns (trees, leaf_problem_ids); each tree is
    {root, nodes, alloc, leaf_stats, rollup, has_rollup, objective}
    where nodes carry id/parent/objective/status and leaves carry their
    campaign pids. Port of webview.collect_problem_trees."""
    if not Path(db_path).exists():
        return [], set()
    from bionexus.adapters.store.sqlite import get_store
    from bionexus.problem_tree import ProblemTree
    full = get_store(str(db_path))
    roots = []
    for br in full.branches():
        if not br.startswith("problem/") or br.count("/") != 1:
            continue
        recs = full.branch_records(br)
        for r in recs:
            env = (r.decision or {}).get("environment") or {}
            if env.get("kind") == "problem-tree":
                roots.append((br, recs))
                break
    trees: list[dict] = []
    leaf_pids: set[str] = set()
    for br, recs in roots:
        tree = None
        rollup_rec = None
        for r in recs:
            d = r.decision or {}
            env = d.get("environment") or {}
            if env.get("kind") == "problem-tree":
                try:
                    tree = ProblemTree.model_validate(env["tree"])
                except Exception:
                    continue
            if d.get("kind") == "tree-rollup" and d.get("tree"):
                rollup_rec = d
        if tree is None:
            continue
        alloc = tree.allocation()
        leaf_stats: dict[str, dict] = {}
        for leaf in tree.leaves():
            pid = leaf_pid(tree.root.id, leaf.id)
            lrecs = full.branch_records(f"problem/{pid}")
            lrecs = lrecs or full.branch_records(
                leaf.branch(tree.root.id)) or []
            runs = sum(1 for r in lrecs if r.event_type.value == "lab_run")
            verdicts: dict[str, str] = {}
            blocked = None
            for r in lrecs:
                d = r.decision or {}
                v = d.get("verdict")
                hid = (d.get("hypothesis_id")
                       or (r.artifact.artifact_id if r.artifact else None))
                if v and hid:
                    verdicts[hid] = v
                if d.get("kind") == "halt_refusal" or (
                        d.get("kind") == "authorization"
                        and d.get("column") != "autonomous"):
                    blocked = d.get("kind")
            statement = ""
            for r in lrecs:
                if r.event_type.value == "problem_defined" and r.decision:
                    statement = (r.decision.get("success_metric")
                                 or r.decision.get("objective") or "")
                    break
            if verdicts:
                tree.set_leaf_status(leaf.id, verdicts)
            leaf_stats[leaf.id] = {"runs": runs, "hyp": len(verdicts),
                                   "statement": statement,
                                   "ok": sum(1 for v in verdicts.values()
                                             if v in ("validated",
                                                      "confirmed")),
                                   "blocked": blocked,
                                   "pids": [pid]}
            leaf_pids.add(pid)
        nodes = [{"id": n.id, "parent": n.parent,
                  "objective": n.objective, "status": n.status,
                  "metric": n.metric, "direction": n.direction,
                  "gate": n.gate}
                 for n in tree.nodes.values()]
        trees.append({
            "root_id": tree.root.id,
            "objective": tree.root.objective,
            "nodes": nodes,
            "alloc": dict(alloc),
            "leaf_stats": leaf_stats,
            "rollup": tree.rollup(),
            "has_rollup": bool(rollup_rec),
            "branch": br,
        })
    return trees, leaf_pids
