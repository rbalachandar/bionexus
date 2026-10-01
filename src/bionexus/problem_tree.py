"""Problem trees — recursive decomposition with guardrails at every level.

A compound objective ("potent AND selective AND soluble") is not one
question; it is a tree of sub-problems, each with its own metric, gate,
hypothesis space, and slice of the experiment budget. Recursion is allowed
(any node may decompose further) but bounded: max_depth, max_children,
max_nodes, and a run budget that allocates DOWN the tree — a leaf can never
spend more than it was given, so decomposition cannot silently multiply
experiments.

Verdicts roll UP: a node is achieved only when its required children are;
the roll-up itself is a provenance event, so "how did we conclude the
program is working?" is answerable from the chain.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from pydantic import BaseModel, Field


class TreeLimits(BaseModel):
    """The anti-runaway guardrails. Every knob is configurable per plan."""
    max_depth: int = 2          # root = 0
    max_children: int = 4       # per node
    max_nodes: int = 12         # whole tree
    max_hypotheses_per_leaf: int = 4
    k_per_leaf: int = 2         # lab slots per leaf campaign


class ProblemNode(BaseModel):
    id: str = Field(default_factory=lambda: f"sp-{uuid.uuid4().hex[:6]}")
    parent: str | None = None
    objective: str
    metric: str | None = None          # e.g. ic50_um, fold_change
    direction: str = "min"
    gate: float | None = None
    priority: float = 1.0              # budget weight among siblings
    required: bool = True
    rationale: str = ""
    status: str = "open"               # open|achieved|partial|failed
    verdicts: dict[str, str] = Field(default_factory=dict)

    def branch(self, root_id: str) -> str:
        return f"problem/{root_id}/{self.id}"


class ProblemTree(BaseModel):
    root: ProblemNode
    nodes: dict[str, ProblemNode]      # includes root, keyed by id
    limits: TreeLimits = Field(default_factory=TreeLimits)
    run_budget: int = 20               # total lab runs across all leaves
    modality: str = ""                 # small molecule | biologic | ... free text

    # ------------------------------------------------------------ building

    @classmethod
    def create(cls, objective: str, *, limits: TreeLimits | None = None,
               run_budget: int = 20, metric: str | None = None,
               gate: float | None = None,
               modality: str = "") -> "ProblemTree":
        root = ProblemNode(objective=objective, metric=metric, gate=gate)
        return cls(root=root, nodes={root.id: root},
                   limits=limits or TreeLimits(), run_budget=run_budget,
                   modality=modality)

    def depth_of(self, node_id: str) -> int:
        d, cur = 0, self.nodes[node_id]
        while cur.parent:
            d += 1
            cur = self.nodes[cur.parent]
        return d

    def children(self, node_id: str) -> list[ProblemNode]:
        return [n for n in self.nodes.values() if n.parent == node_id]

    def add(self, parent_id: str, **spec: Any) -> ProblemNode:
        """Guardrailed growth: depth, breadth and total-node caps, each
        refusal explicit (mirrors the hypothesis-budget pattern)."""
        parent = self.nodes[parent_id]
        if self.depth_of(parent_id) + 1 > self.limits.max_depth:
            raise ValueError(
                f"max_depth={self.limits.max_depth}: '{parent.objective[:40]}'"
                " cannot decompose further (recorded, not silently dropped)")
        if len(self.children(parent_id)) >= self.limits.max_children:
            raise ValueError(
                f"max_children={self.limits.max_children} reached under "
                f"'{parent.objective[:40]}'")
        if len(self.nodes) >= self.limits.max_nodes:
            raise ValueError(
                f"max_nodes={self.limits.max_nodes} — tree is full")
        node = ProblemNode(parent=parent_id, **spec)
        self.nodes[node.id] = node
        return node

    def leaves(self) -> list[ProblemNode]:
        return [n for n in self.nodes.values() if not self.children(n.id)]

    # ------------------------------------------------------------ budgets

    def allocation(self) -> dict[str, int]:
        """Hierarchical run budget: the root's budget flows down the tree —
        each intermediate node splits its OWN slice among its children by
        priority weight, so a branch's share is protected from siblings
        regardless of depth (a deep subtree cannot soak another branch's
        budget). Leaves end up with concrete budgets; a floor of 2 keeps
        any leaf meaningful; totals never exceed run_budget unless the
        floors alone demand more."""
        out: dict[str, int] = {}
        if self.run_budget <= 0 or not self.leaves():
            return out

        def share(budget: int, nid: str) -> None:
            kids = self.children(nid)
            if not kids:
                out[nid] = budget
                return
            weights = [max(0.1, k.priority) for k in kids]
            total_w = sum(weights)
            alloc = []
            for k, w in zip(kids, weights):
                floor = 0 if self.children(k.id) else 2
                alloc.append(max(floor, int(budget * w / total_w)))
            # trim to the parent's slice, largest first, honoring floors
            while sum(alloc) > budget:
                idx = max(range(len(kids)),
                          key=lambda i: alloc[i]
                          - (0 if self.children(kids[i].id) else 2))
                floor = 0 if self.children(kids[idx].id) else 2
                if alloc[idx] <= floor:
                    break
                alloc[idx] -= 1
            for k, a in zip(kids, alloc):
                share(a, k.id)

        share(self.run_budget, self.root.id)
        return out

    def subtree_leaves(self, nid: str) -> list[ProblemNode]:
        """Leaves beneath a node (the node itself if it is a leaf)."""
        kids = self.children(nid)
        if not kids:
            return [self.nodes[nid]]
        out: list[ProblemNode] = []
        for k in kids:
            out.extend(self.subtree_leaves(k.id))
        return out

    # ------------------------------------------------------------ roll-up

    def set_leaf_status(self, leaf_id: str, statuses: dict[str, str]) -> None:
        node = self.nodes[leaf_id]
        node.verdicts = dict(statuses)
        vals = set(statuses.values())
        if not vals:
            node.status = "failed"
        elif vals <= {"validated", "confirmed"}:
            node.status = "achieved"
        elif vals & {"confirmed", "validated"}:
            node.status = "partial"
        else:
            node.status = "failed"

    def rollup(self) -> dict[str, str]:
        """Bottom-up: a node is achieved iff all required children are."""
        out: dict[str, str] = {}

        def resolve(nid: str) -> str:
            n = self.nodes[nid]
            kids = self.children(nid)
            if not kids:
                out[nid] = n.status
                return n.status
            kid_states = [resolve(k.id) for k in kids]
            req = [s for k, s in zip(kids, kid_states) if k.required]
            if req and all(s == "achieved" for s in req):
                n.status = "achieved"
            elif any(s == "failed" for s in req):
                n.status = "partial" if any(
                    s == "achieved" for s in req) else "failed"
            else:
                n.status = "partial"
            out[nid] = n.status
            return n.status

        resolve(self.root.id)
        return out

    # ------------------------------------------------------------ display

    def render(self) -> str:
        lines = []

        def walk(nid: str, indent: int) -> None:
            n = self.nodes[nid]
            alloc = self.allocation().get(nid)
            gtxt = ""
            if n.gate is not None and n.metric:
                op = "≤" if n.direction == "min" else "≥"
                gtxt = f" [{n.metric} {op} {n.gate:g}]"
            mark = {"open": "○", "achieved": "✅", "partial": "◐",
                    "failed": "❌", "in lab": "🔬"}.get(n.status, "○")
            budget = f" · {alloc} runs" if alloc is not None else ""
            lines.append("  " * indent + f"{mark} {n.objective[:60]}{gtxt}"
                         + (f" (p={n.priority:g}){budget}"))
            for k in self.children(nid):
                walk(k.id, indent + 1)

        walk(self.root.id, 0)
        return "\n".join(lines)


# ------------------------------------------------------------------ agent

DECOMPOSE_PROMPT = """You are the study director of a drug-discovery program.
Decompose this objective into independent, separately-testable SUB-PROBLEMS.

Objective: {objective}
Program context: {context}

Rules:
- At most {max_children} sub-problems. Fewer is better; only split what is
  genuinely a distinct question with its own measurement.
- Each sub-problem: a one-line objective, the metric it is judged on
  (e.g. ic50_um, selectivity_ratio, fold_change, solubility_uM), direction
  ('min' lower-is-better / 'max'), a numeric gate, and a priority weight
  (relative importance, any positive number).
- Do NOT propose experiments or hypotheses — only the decomposition.

Reply ONLY with JSON:
{{"sub_problems": [
  {{"objective": "...", "metric": "...", "direction": "min|max",
    "gate": 0.0, "priority": 1.0, "rationale": "why this is its own question"}}
]}}"""


def decompose_with_agent(model: Any, objective: str, context: str = "",
                         limits: TreeLimits | None = None,
                         say: Any = None) -> ProblemTree:
    """Agent-assisted decomposition, guardrailed: over-proposals are
    truncated (and announced), never silently accepted."""
    limits = limits or TreeLimits()
    say = say or (lambda m: None)
    from bionexus.core.contracts import Envelope, ToolInvocation
    prompt = DECOMPOSE_PROMPT.format(objective=objective,
                                     context=context or "-",
                                     max_children=limits.max_children)
    inv = ToolInvocation(envelope=Envelope(experiment_branch_id="plan"),
                         tool="c.fm.generate_molecules")
    raw = model.generate(inv, prompt).output["text"]
    import re
    doc = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
    subs = doc.get("sub_problems", [])
    if len(subs) > limits.max_children:
        say(f"model proposed {len(subs)} sub-problems; truncated to "
            f"max_children={limits.max_children} (recorded)")
    tree = ProblemTree.create(objective, limits=limits)
    for s in subs[:limits.max_children]:
        tree.add(tree.root.id, objective=str(s.get("objective", ""))[:160],
                 metric=s.get("metric"),
                 direction="max" if s.get("direction") == "max" else "min",
                 gate=_num(s.get("gate")),
                 priority=_num(s.get("priority"), 1.0) or 1.0,
                 rationale=str(s.get("rationale", ""))[:200])
    return tree


def _num(v: Any, default: float | None = None) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ------------------------------------------------------------------ execution

def default_hypotheses(tree: "ProblemTree", candidates: list[str]) -> dict[str, list]:
    """Config-path hypothesis space: one claim per candidate per leaf,
    phrased against that leaf's own gate."""
    out: dict[str, list] = {}
    for leaf in tree.leaves():
        # per-leaf prefix: SOL-1 / PKA-1 ... so each sub-problem's
        # hypotheses are distinct records, not clones of each other
        tag = "".join(w[0] for w in leaf.objective.split()[:3]).upper()
        specs = []
        for i, c in enumerate(candidates, 1):
            cid = f"{tag}-{i}"
            pred = (f"{leaf.metric} "
                    f"{'<=' if leaf.direction == 'min' else '>='} "
                    f"{leaf.gate:g}" if leaf.gate is not None else "meets bar")
            specs.append({
                "statement": f"{cid} ({c}) — {leaf.objective} ({pred})",
                "candidate": cid, "assay_type": "binding",
                "metadata": {"source_candidate": c},
                "predicted": pred,
                "predicted_value": leaf.gate,
                "family": leaf.id,
                "rationale": leaf.rationale or ""})
        for sp in specs:
            sp.setdefault("metadata", {})
            if tree.modality:
                sp["metadata"].setdefault("modality", tree.modality)
        out[leaf.id] = specs
    return out


def run_tree(tree: "ProblemTree", lab_factory, store, *,
             hypotheses: dict[str, list] | None = None,
             model: Any = None, candidates: list[dict] | None = None,
             inbox: str = ".data/inbox-tree", autonomy: str = "act",
             rounds: int | None = None,
             notify: Any = None) -> dict[str, str]:
    """Each leaf runs as its own budgeted campaign; the roll-up is recorded
    on the root branch. Resumable: achieved leaves are skipped."""
    from pathlib import Path

    from bionexus.autoloop import (CampaignConfig, ResourceBudget,
                                   announce_branch, run_campaign)
    from bionexus.core.contracts import Envelope, EventType
    from bionexus.core.hypothesis import Constraint, ProblemStatement
    from bionexus.core.interfaces import record_for, system_actor

    say = notify or (lambda m: print(f"[plan] {m}"))
    alloc = tree.allocation()
    hyps = hypotheses or default_hypotheses(
        tree, [c["sample_id"] if isinstance(c, dict) else str(c)
               for c in (candidates or [])])
    root_branch = f"problem/{tree.root.id}"
    # launched from a program (workbench dialog): link the tree root to
    # it once, in provenance — the workspace nests on this record
    import os as _os
    _bn_prog = _os.environ.get("BN_PROGRAM")
    if _bn_prog:
        try:
            from bionexus import program as _program
            _program.record_launch(_bn_prog, tree.root.id,
                                   tree.root.objective)
        except Exception:
            pass
    store.append(record_for(
        Envelope(experiment_branch_id=root_branch), EventType.problem_defined,
        system_actor("planner"),
        decision={"problem_id": tree.root.id, "objective": tree.root.objective,
                  "constraints": [], "success_metric": "all required sub-problems",
                  "environment": {"kind": "problem-tree",
                                  "tree": tree.model_dump(),
                                  "run_budget": tree.run_budget}}))
    for leaf in tree.leaves():
        if leaf.status == "achieved":
            say(f"leaf {leaf.id} already achieved — skipping (resumable)")
            continue
        specs = hyps.get(leaf.id) or []
        if not specs:
            leaf.status = "failed"
            say(f"leaf {leaf.id}: no hypotheses available — recorded failed")
            continue
        cons = []
        if leaf.gate is not None and leaf.metric:
            cons = [Constraint(
                name=leaf.metric,
                description=f"{leaf.metric} "
                            f"{'<=' if leaf.direction == 'min' else '>='} "
                            f"{leaf.gate:g}",
                kind="hard", limit=leaf.gate)]
        # the leaf's registered objective must say more than its own
        # name: state the purpose within the tree (parent context, gate,
        # metric) so the experiment page's Objective line carries
        # information instead of echoing the title
        gate_txt = (f"{leaf.metric} "
                    f"{'<=' if leaf.direction == 'min' else '>='} "
                    f"{leaf.gate:g}" if leaf.metric and
                    leaf.gate is not None else "its registered gate")
        if leaf.parent and leaf.parent != tree.root.id:
            parent = (f"a {tree.nodes[leaf.parent].objective} sub-problem")
        else:
            parent = "a direct sub-problem"
        problem = ProblemStatement(
            objective=(f"{leaf.objective} — {parent} of "
                       f"'{tree.root.objective}': show {gate_txt}"),
            problem_id=f"{tree.root.id}-{leaf.id}",
            constraints=cons,
            success_metric=f"{leaf.metric or 'objective'} gate met")
        budget = ResourceBudget(
            max_total_runs=alloc.get(leaf.id, 2),
            max_hypotheses_total=tree.limits.max_hypotheses_per_leaf,
            max_confirmations=max(0, alloc.get(leaf.id, 2) - 1))
        k_eff = min(tree.limits.k_per_leaf, alloc.get(leaf.id, 2))
        cfg = CampaignConfig(
            problem=problem,
            hypotheses=specs[: tree.limits.max_hypotheses_per_leaf],
            hypothesis_source="config", model=model, candidates=candidates,
            k=k_eff,
            rounds=(max(2, len(specs) // max(1, k_eff))
                    if not rounds else rounds),
            autonomy=autonomy,
            inbox=str(Path(inbox) / leaf.id), poll_secs=0.05,
            budget=budget)
        say(f"leaf {leaf.id}: '{leaf.objective[:50]}' — "
            f"{budget.max_total_runs} runs allocated")
        # the leaf's workbench id, announced BEFORE the campaign runs so
        # the API watcher streams its records while it is still in flight
        leaf_eid = f"tree-{tree.root.id}-{leaf.id}"
        announce_branch(leaf_eid, problem.problem_id)
        # per-leaf log: the leaf's Trace log is its own campaign diary
        from bionexus.paths import CAMPAIGN_DIR, ensure_dirs
        ensure_dirs()
        leaf_log = CAMPAIGN_DIR / f"{tree.root.id}-{leaf.id}.log"
        leaf_log.write_text("")
        def _tee(msg, _f=leaf_log):
            with open(_f, "a") as fh:
                fh.write(str(msg) + "\n")
            say(msg)
        report = run_campaign(cfg, lab_factory(), store, notify=_tee)
        tree.set_leaf_status(leaf.id, report.verdicts)
        # the leaf surfaces in the workbench Experiments list like any
        # other agent run (one registry, tagged by origin)
        try:
            from bionexus.wizard_store import WizardStore
            _ws = WizardStore()
            _eid = leaf_eid
            _root_name = tree.root.objective.split(":")[0].strip()[:40]
            import os as _os
            _status = ("completed" if leaf.status == "achieved"
                       else ("failed" if leaf.status == "failed"
                             else "verdict_recorded"))
            _ws.register_agent(
                _eid, f"{leaf.objective} · sub-problem of {_root_name}",
                log=str(leaf_log), autonomy=autonomy, status=_status)
            _bn_prog = _os.environ.get("BN_PROGRAM")
            if _bn_prog:
                try:
                    from bionexus import program as _program
                    _program.link_leaf(_bn_prog, _eid, tree.root.id,
                                       leaf.objective, _status)
                except Exception:
                    pass
            _ws.link_problem(_eid, problem.problem_id)
        except Exception:
            pass
        store.append(record_for(
            Envelope(experiment_branch_id=leaf.branch(tree.root.id),
                     parent_branch_id=root_branch),
            EventType.stage_transition, system_actor("planner"),
            decision={"stage": "leaf-complete", "leaf": leaf.id,
                      "objective": leaf.objective,
                      "status": leaf.status, "verdicts": report.verdicts}))
    summary = tree.rollup()
    store.append(record_for(
        Envelope(experiment_branch_id=root_branch), EventType.gate_decision,
        system_actor("planner"),
        decision={"kind": "tree-rollup", "root_status": summary[tree.root.id],
                  "statuses": {n: summary[n] for n in summary},
                  "tree": tree.model_dump()}))
    say("TREE ROLL-UP: " + summary[tree.root.id])
    return summary
