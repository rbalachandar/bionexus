"""Pure read-models for the web API (P0.1).

Extracted from webview.py so the FastAPI layer can serve the same
information the Streamlit UI renders — without importing streamlit.
Every function here is JSON-able-in, JSON-able-out and unit-tested
against real campaign branches (tests/test_views.py).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from bionexus.paths import DATA_DIR

PROVENANCE_DB = "bionexus.db"


# --------------------------------------------------------------- row status
def row_status(e: dict) -> str:
    """Registry status for log-less runs (tree leaves), log/pid-derived
    status for launched campaigns. Port of webview._row_status."""
    ag = e["payload"].get("agent") or {}
    if not ag:
        return e["status"].replace("_", " ")
    log = ag.get("log") or ""
    logf = Path(log)
    if log and logf.is_file() and "CAMPAIGN COMPLETE" in logf.read_text(
            errors="replace"):
        return "completed"
    pid = ag.get("pid")
    if pid:
        try:
            os.kill(pid, 0)
            return "running"
        except OSError:
            return "interrupted"
    return e["status"]


# ------------------------------------------------------- problem id helpers
def has_doubled_branch(root_id: str,
                       db_path: str | Path = PROVENANCE_DB) -> bool:
    """run_tree convention (problem/<root>-<root>) is the default when
    no provenance exists yet."""
    if not Path(db_path).exists():
        return True
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    return bool(SqliteProvenanceStore(str(db_path)).branch_records(
        f"problem/{root_id}-{root_id}"))


def leaf_pid(root_id: str, leaf_id: str,
             db_path: str | Path = PROVENANCE_DB) -> str:
    """Preferred campaign branch id for a leaf. Single-node trees (root
    is its own leaf) may run on problem/<root> OR problem/<root>-<root>."""
    if leaf_id == root_id:
        return f"{root_id}-{root_id}" if has_doubled_branch(
            root_id, db_path) else root_id
    return f"{root_id}-{leaf_id}"


def pid_aliases(root_id: str, leaf_id: str) -> set[str]:
    """All pid forms a leaf's campaign may be registered under."""
    doubled = f"{root_id}-{leaf_id}"
    if leaf_id == root_id:
        return {root_id, doubled}
    return {doubled}


def resolve_problem(meta: dict, logf: Path) -> str | None:
    """Latest prob-* id for a campaign: explicit metadata wins; else the
    log is searched (problem-registration lines first, then any
    CAMPAIGN COMPLETE-style token). Port of Overview._resolve_problem."""
    problem_id = meta.get("problem_id")
    if logf and str(logf) != "." and Path(logf).is_file():
        txt = Path(logf).read_text(errors="replace")
        m = re.findall(r"problem (prob-\w+):", txt) \
            or re.findall(r"\b(prob-[0-9a-f]+)\b", txt)
        latest = m[-1] if m else None
        if latest and latest != problem_id:
            problem_id = latest
    return problem_id


# ------------------------------------------------------------- dmta counts
def dmta_counts(recs) -> dict:
    """DMTA phase counts for a slice of provenance records. Test counts
    unique lab_run submissions (one submission = one run = one analyzed
    export); Analyze counts verdict-bearing decisions, deduplicated —
    a hypothesis earns ONE verdict: its latest. Port of
    webview._dmta_counts."""
    c = {"proposed": 0, "selected": 0, "submitted": 0, "refused": 0,
         "runs": 0, "verdicts": 0,
         "validated": 0, "confirmed": 0, "inconclusive": 0,
         "refuted": 0}
    final: dict[str, str] = {}
    orphan = 0
    for r in recs:
        d = r.decision or {}
        et = r.event_type.value
        if et == "hypothesis_proposed":
            c["proposed"] += 1
        elif et == "hypotheses_filtered":
            c["selected"] += sum(1 for x in d.get("decisions", [])
                                 if x.get("selected"))
        elif et == "lab_run" and d.get("run_id"):
            c["submitted"] += 1
            c["runs"] += 1
        elif et == "gate_decision":
            k = d.get("kind")
            if k in ("halt_refusal", "safety_refusal", "authorization",
                     "synthesis_failed") \
                    and d.get("column") != "autonomous":
                c["refused"] += 1
        elif et in ("hypothesis_validated", "hypothesis_invalidated",
                    "hypothesis_tested") and d.get("verdict"):
            hid = d.get("hypothesis_id") \
                or (r.artifact.artifact_id if r.artifact else None)
            if not hid:
                orphan += 1
                continue
            final[hid] = str(d.get("verdict"))
    for v in final.values():
        c["verdicts"] += 1
        if v in ("validated", "confirmed"):
            c[v] += 1
        elif v in ("inconclusive", "refuted"):
            c[v] += 1
    return c


def round_markers(recs) -> list[tuple[int, list[str]]]:
    """[(round_no, [candidates])] sorted by round, from round_start
    markers."""
    markers = [(int((r.decision or {}).get("round", 0)),
                [str(c) for c in (r.decision or {}).get("candidates") or []])
               for r in recs
               if r.event_type.value == "stage_transition"
               and (r.decision or {}).get("kind") == "round_start"]
    return sorted(markers)


# ------------------------------------------------------------- problem trees
def problem_trees(db_path: str | Path = PROVENANCE_DB) -> tuple[list, set]:
    """All serialized problem trees with live status, as JSON-able
    dicts. Returns (trees, leaf_problem_ids); each tree is
    {root, nodes, alloc, leaf_stats, rollup, has_rollup, objective}
    where nodes carry id/parent/objective/status and leaves carry their
    campaign pids. Port of webview.collect_problem_trees."""
    if not Path(db_path).exists():
        return [], set()
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.problem_tree import ProblemTree
    full = SqliteProvenanceStore(str(db_path))
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
            aliases = pid_aliases(tree.root.id, leaf.id)
            lrecs = []
            for a in aliases:
                lrecs = full.branch_records(f"problem/{a}")
                if lrecs:
                    break
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
                                   "pids": sorted(aliases)}
            leaf_pids.update(aliases)
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


def wizard_db_path() -> Path:
    """The registry DB path, honoring BIONEXUS_DATA_DIR."""
    return DATA_DIR / "wizard.db"
