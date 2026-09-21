"""Agent-driven hypothesis generation — the agent decides the structure.

Given a ProblemStatement (and optionally a candidate library), a ModelProvider
proposes the hypothesis structure itself:

  - how many mechanistic FAMILIES (distinct bets) and what they claim
  - how many VARIANTS per family (parameter sweeps) and WHICH variables to
    tune (warhead type, concentration range, assay modality...)
  - a self-assessed score per family (used by the portfolio filter unless the
    operator overrides it)

Everything the agent produces is JSON-validated, provenance-recorded (prompt +
response + structure), and constrained by operator limits (max_families,
max_variants_per_family) — autonomy inside guardrails, as everywhere else.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from bionexus.core.contracts import ToolInvocation
from bionexus.core.hypothesis import (
    Constraint, Hypothesis, HypothesisTracker, ProblemStatement, SuccessCriteria,
)
from bionexus.core.interfaces import record_for

PROMPT = """You are the hypothesis lead of a drug-discovery program.

PROBLEM
objective: {objective}
context: {context}
constraints: {constraints}
success metric: {success_metric}

CANDIDATE LIBRARY (measured/predicted so far)
{candidates}

Decide the hypothesis structure yourself:
- How many DISTINCT mechanistic families to pursue (each family = one
  falsifiable mechanistic claim; variants = the same claim with different
  parameterizations, e.g. analogs or tuned assay variables).
- For each variant: which variables you tune and why (declare them in
  "variables"), what it predicts, and its rationale.
- Your own confidence score per family (0-1) — be honest.

Limits: at most {max_families} families, at most {max_variants_per_family}
variants per family. Prefer few distinct ideas over many similar ones.

Reply ONLY with JSON:
{{"families": [
  {{"family": "short-family-id",
    "parent_statement": "falsifiable mechanistic claim",
    "kind": "mechanistic",
    "mechanism": "the CAUSAL story — molecules, binding, pathway; not 'it fits'",
    "refutation_condition": "the ONE observation that kills this family",
    "predicted_observables": ["what else must be true if this holds"],
    "citation": "PMID or DOI grounding the rationale ('' if none — never invent)",
    "rationale": "why this bet",
    "confidence": 0.0-1.0,
    "variables": ["what you tune across variants"],
    "variants": [
      {{"statement": "falsifiable variant prediction",
        "candidate": "sample id",
        "assay_type": "binding",
        "predicted": "human-readable prediction",
        "predicted_value": 20.0,
        "rationale": "why this variant",
        "variables": {{"tuned_param": "value"}}}}
    ]}}
]}}"""


from bionexus.core.contracts.models import coerce_assay_type


def propose_families_with_agent(
    tracker: HypothesisTracker,
    problem: ProblemStatement,
    model: Any,
    candidates: list[dict[str, Any]] | None = None,
    max_families: int = 3,
    max_variants_per_family: int = 3,
    max_total_hypotheses: int | None = None,
    existing_keys: set[tuple[str, str]] | None = None,
    skill_guidance: str | None = None,
    flywheel: Any = None,
    branch_id: str | None = None,
    score_fn: Callable[[dict[str, Any]], float] | None = None,
    notify: Callable[[str], None] | None = None,
) -> tuple[list[Hypothesis], dict[str, float]]:
    """max_total_hypotheses: hard cap on hypotheses this generation may add.
    existing_keys: (candidate, statement) pairs already tried — duplicates the
    agent re-proposes are dropped (no re-running the same experiment).
    skill_guidance: Agent Skills text (e.g. the bionexus/opentrons skill)
    injected into the prompt so domain procedure shapes the generation."""

    """The agent designs the hypothesis portfolio; returns (variants, scores).

    Enforces operator limits post-hoc (truncates), records the raw generation
    into provenance, and derives family scores from the agent's confidence
    unless `score_fn` is given.
    """
    from bionexus.core.contracts import Envelope, EventType

    branch = branch_id or f"problem/{problem.problem_id}"
    env = Envelope(experiment_branch_id=branch)
    actor = tracker.actor
    say = notify or (lambda m: None)

    if skill_guidance:
        guidance_block = ("PROCEDURAL GUIDANCE (Agent Skills — follow while "
                          "designing):\n" + skill_guidance[:3000])
    else:
        guidance_block = ""
    prompt = PROMPT.format(
        objective=problem.objective,
        context=problem.context or "-",
        constraints=json.dumps([c.model_dump() for c in problem.constraints]),
        success_metric=problem.success_metric or "-",
        candidates=json.dumps(candidates or [], indent=1)[:4000],
        max_families=max_families,
        max_variants_per_family=max_variants_per_family,
    ) + ("\n\n" + guidance_block if guidance_block else "")
    negatives_injected: list[str] = []
    if flywheel is not None:
        negs = flywheel.prompt_context()
        if negs:
            prompt = prompt + "\n\n" + negs
            negatives_injected = [line.split(" ")[1] for line
                                  in negs.splitlines()[1:] if line.startswith("- ")]
            say("prompt includes previously ruled-out candidates (flywheel)")
    inv = ToolInvocation(envelope=env.model_copy(), tool="c.fm.generate_molecules")
    raw = model.generate(inv, prompt).output["text"]
    # record the raw generation (agent reasoning is provenance too)
    store_append = tracker.store.append
    import hashlib as _hl
    store_append(record_for(env, EventType.tool_invocation, actor,
                            decision={"kind": "hypothesis_generation",
                                      "prompt_chars": len(prompt),
                                      "response_chars": len(raw),
                                      # retrieval trace: what shaped this gen
                                      "trace": {
                                          "prompt_sha256":
                                              _hl.sha256(
                                                  prompt.encode()).hexdigest()[:16],
                                          "model": getattr(model, "model",
                                                           "unknown"),
                                          "skill_guidance_chars":
                                              len(skill_guidance or ""),
                                          "flywheel_negatives":
                                              len(negatives_injected)
                                              if "negatives_injected" in dir()
                                              else 0,
                                          "candidates_count":
                                              len(candidates or []),
                                      }}))

    doc = _extract_json(raw)
    families_in = doc.get("families", [])[:max_families]
    family_scores: dict[str, float] = {}
    specs: list[dict[str, Any]] = []
    # the program's primary hard constraint is the gate: variant criteria
    # inherit its metric/direction (threshold stays the variant's own
    # predicted value when the agent declared one)
    _con = next((c for c in problem.constraints if c.kind == "hard"
                 and c.limit is not None), None)
    _gate = None
    if _con is not None:
        _gate = {"metric": _con.name,
                 "direction": "max" if ">=" in (_con.description or "")
                 else "min",
                 "threshold": float(_con.limit)}
    for fam in families_in:
        fid = str(fam.get("family", f"fam-{len(family_scores)}"))[:40]
        family_scores[fid] = float(fam.get("confidence", 0.5))
        say(f"family '{fid}' (confidence {family_scores[fid]:.2f}): "
            f"{fam.get('parent_statement', '')[:80]}")
        for v in fam.get("variants", [])[:max_variants_per_family]:
            _assay = str(coerce_assay_type(
                v.get("assay_type", "binding")).value)
            if _gate is None:
                _spec_criteria = None
            elif _assay == "ic50_um" or _assay in (
                    "binding", "enzymatic", "cytotoxicity", "counterscreen"):
                # dose-response assay: the fit produces ic50_um, lower is
                # better — keep the classic convention
                _spec_criteria = {"metric": "ic50_um", "direction": "min",
                                  "threshold": float(
                                      v.get("predicted_value")
                                      or _gate["threshold"])}
            else:
                # property assay: read in the program's metric/direction
                _spec_criteria = {"metric": _gate["metric"],
                                  "direction": _gate["direction"],
                                  "threshold": float(
                                      v.get("predicted_value")
                                      or _gate["threshold"])}
            spec = {
                "statement": v.get("statement", ""),
                "candidate": v.get("candidate", ""),
                "assay_type": _assay,
                "criteria": _spec_criteria,
                "predicted": v.get("predicted", v.get("statement", "")),
                "predicted_value": v.get("predicted_value"),
                "rationale": v.get("rationale", ""),
                "variables": v.get("variables", {}),
            }
            for k in ("mechanism", "refutation_condition", "citation",
                      "predicted_observables"):
                if fam.get(k) is not None:
                    spec[k] = fam[k]
                elif v.get(k) is not None:
                    spec[k] = v[k]
            specs.append({"family": fid, "parent_statement":
                          fam.get("parent_statement", ""), **spec})

    # dedup against already-tried hypotheses + global total cap
    existing = existing_keys or set()
    seen: set[tuple[str, str]] = set()
    kept_specs: list[dict[str, Any]] = []
    for s_ in specs:
        key = (s_["candidate"], s_["statement"])
        if key in existing or key in seen:
            say(f"dropped duplicate hypothesis: {s_['candidate']} — "
                "already proposed/tried")
            continue
        if max_total_hypotheses is not None and len(kept_specs) >= max_total_hypotheses:
            say(f"hypothesis budget reached ({max_total_hypotheses}) — "
                "truncating portfolio (recorded)")
            break
        seen.add(key)
        kept_specs.append(s_)
    specs = kept_specs

    # verify every cited reference — the "never invent" clause, enforced
    cited = sorted({s.get("citation") for s in specs if s.get("citation")})
    if cited:
        from bionexus import citations
        results = {c: citations.verify(c) for c in cited}
        for s in specs:
            c = s.get("citation")
            if c and c in results:
                s["citation_status"] = results[c]["status"]
                s["citation_detail"] = results[c]["detail"]
        summary = ", ".join(f"{c}={results[c]['status']}" for c in cited)
        say(f"citation check: {summary}")
        bad = [c for c in cited if results[c]["status"] == "invalid"]
        if bad:
            say(f"WARNING: {len(bad)} fabricated/unresolvable citation(s) "
                "penalized in portfolio scoring")

    variants = tracker.propose_families(problem, [
        {**{k: f[k] for k in ("family", "parent_statement", "kind", "rationale")
            if k in f}, "variants": [s for s in specs if s["family"] == f.get("family")]}
        for f in families_in
    ])
    # carry per-variant tuned variables into hypothesis metadata
    for h in variants:
        for s in specs:
            if s["candidate"] == h.candidate and s["statement"] == h.statement:
                h.metadata["variables"] = s.get("variables", {})
    return variants, family_scores


def _extract_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    doc = None
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        import re
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            doc = json.loads(m.group(0))
    if not isinstance(doc, dict) or "families" not in doc:
        raise ValueError(
            "agent response must be a JSON object with a 'families' key — "
            "use a model that follows the schema (see PROMPT): " + text[:120])
    return doc


