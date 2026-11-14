"""/api/v1/programs and /api/v1/today — programs as containers of campaigns.

A PROGRAM is the scientific goal: a pre-registered gate (metric, direction,
value) and a modality. A CAMPAIGN is one run that tries to meet it. A program
has many campaigns; every candidate in all of them is judged against the same
gate, so program progress is "has anything claimed met the gate, and what is
the best result so far".
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from proef import program as program_cfg
from proef.api.v1 import schemas as S
from proef.api.v1.deps import who
from proef.api.launch import spawn_campaign
from proef.api.v1.campaigns import (_funnel, _load, _reviews, _status,
                                       _summary_of, _ws)
from proef.views.ids import row_status

router = APIRouter(tags=["programs"])

_CLAIMED = ("confirmed", "validated")
_RUNNING = ("running", "executing")


def _gate(doc: dict) -> S.Gate:
    direction = program_cfg.gate_direction(doc)
    value = doc.get("gate_value")
    if value is None:
        try:
            value = program_cfg.gate_threshold_um(doc)
        except Exception:
            value = None
    metric = program_cfg.gate_metric(doc)
    unit = program_cfg.gate_unit(doc)
    from proef.derivation import criteria_label, metric_label
    label = metric_label(metric)
    if value is not None:
        label = criteria_label(metric, direction, value)
    if unit and "(" not in label:
        label += f" {unit}"
    return S.Gate(metric=metric, direction=direction,
                  threshold=float(value) if value is not None else None,
                  unit=unit, label=label)


def _digest(eid: str):
    """(CampaignDigest, [hypotheses]) for one campaign — no chain verify."""
    ws, row, detail, branch, recs = _load(eid)
    reviews = _reviews(recs)
    hyps = [_summary_of(c, None, reviews) for c in detail.get("cards") or []]
    status = _status(detail.get("status") or row_status(row), recs)
    return S.CampaignDigest(
        id=eid, title=detail.get("objective") or row.get("question") or eid,
        status=status, updated_at=row.get("updated_at"),
        funnel=_funnel(hyps)), hyps


def _best(hyps, direction: str, cid: str, title: str) -> S.BestResult | None:
    claimed = [h for h in hyps if h.state in _CLAIMED
               and h.verdict and h.verdict.observed is not None]
    pool = claimed or [h for h in hyps if h.verdict
                       and h.verdict.observed is not None]
    if not pool:
        return None
    pick = (min if direction == "min" else max)(
        pool, key=lambda h: h.verdict.observed)
    return S.BestResult(campaign_id=cid, campaign_title=title,
                        candidate=pick.head, state=pick.state,
                        observed=pick.verdict.observed, ci=pick.verdict.ci)


def _next_steps(p, digests, goal: S.Goal, gate: S.Gate,
                unresolved: list[str]) -> list[S.NextStep]:
    """What a sensible scientist would do next — from the evidence alone."""
    from proef.api.v1.campaigns import pending_approvals
    steps: list[S.NextStep] = []
    waiting = 0
    for link in program_cfg.links_for(p["slug"]):
        try:
            _, _, detail, _, _ = _load(link["eid"])
        except HTTPException:
            continue
        waiting += len(pending_approvals(
            (detail.get("agent") or {}).get("problem_id")))
    if waiting:
        steps.append(S.NextStep(
            kind="inbox", action="inbox",
            title=f"{waiting} lab submission{'s are' if waiting > 1 else ' is'} waiting for you",
            detail="A campaign is paused at the gate until you approve or decline."))
    if unresolved:
        steps.append(S.NextStep(
            kind="follow_up", action="launch", candidates=unresolved,
            title=f"Resolve {len(unresolved)} inconclusive candidate{'s' if len(unresolved) > 1 else ''}",
            detail=f"{', '.join(unresolved)}: the interval straddles the gate. "
                   "A follow-up with more replicates near the gate would settle it."))
    for d in digests:
        if d.status == "awaiting_results":
            steps.append(S.NextStep(
                kind="submit_results", action="open_campaign", campaign_id=d.id,
                title=f"Submit plate results for “{d.title}”",
                detail="Its gate is registered. Run the plate, export a CSV, and submit it: "
                       "it is judged against that gate."))
    running = sum(d.status in _RUNNING for d in digests)
    if not digests:
        steps.append(S.NextStep(kind="start", action="launch",
                                title="Start the first campaign",
                                detail=f"Test candidates against {gate.label or 'the gate'}."))
    elif goal.met and goal.best:
        steps.append(S.NextStep(
            kind="milestone", action="new_program",
            title=f"Goal met by {goal.best.candidate}",
            detail="Next: confirm it in an orthogonal assay, or open a follow-on program "
                   "with a tighter gate (for example a lead-stage potency bar)."))
    elif not running and goal.judged:
        steps.append(S.NextStep(
            kind="expand", action="launch",
            title="No candidate meets the gate yet",
            detail=f"{goal.refuted} of {goal.judged} judged candidates were refuted. "
                   "Propose new candidates or a different scaffold."))
    return steps


def _program(p: dict, with_detail: bool):
    doc = p.get("program") or {}
    gate = _gate(doc)
    direction = gate.direction or "min"
    digests, results, all_best, unresolved = [], [], [], []
    for link in program_cfg.links_for(p["slug"]):
        if link["role"] != "leaf":
            continue                      # campaign roots are containers
        try:
            dg, hyps = _digest(link["eid"])
        except HTTPException:
            continue                      # registry row gone (purged)
        dg.best = _best(hyps, direction, dg.id, dg.title)
        digests.append(dg)
        if dg.best:
            all_best.append(dg.best)
        for h in hyps:
            if h.state == "abstained" and (h.review is None
                                           or h.review.decision == "follow_up"):
                unresolved.append(h.head)
            if h.verdict and h.verdict.observed is not None:
                results.append(S.ProgramResult(
                    hypothesis_id=h.id, campaign_id=dg.id, campaign_title=dg.title,
                    candidate=h.head, state=h.state,
                    observed=h.verdict.observed, ci=h.verdict.ci))
    claimed = [b for b in all_best if b.state in _CLAIMED]
    pool = claimed or all_best
    best = (min if direction == "min" else max)(
        pool, key=lambda b: b.observed) if pool else None
    f = [d.funnel for d in digests]
    goal = S.Goal(met=bool(claimed), best=best,
                  claimed=sum(x.claimed for x in f),
                  refuted=sum(x.refuted for x in f),
                  abstained=sum(x.abstained for x in f),
                  judged=sum(x.judged for x in f))
    base = dict(
        slug=p["slug"], name=p["name"], objective=doc.get("objective") or None,
        modality=doc.get("modality") or None, mode=p.get("mode"), gate=gate,
        goal=goal, campaigns=len(digests),
        running=sum(d.status in _RUNNING for d in digests),
        updated_at=max((d.updated_at or 0 for d in digests), default=None))
    if not with_detail:
        return S.ProgramSummary(**base)
    digests.sort(key=lambda d: -(d.updated_at or 0))
    return S.ProgramDetail(
        **base, campaign_list=digests, results=results,
        next_steps=_next_steps(p, digests, goal, gate, unresolved))


@router.get("/programs", response_model=list[S.ProgramSummary])
def list_programs() -> list[S.ProgramSummary]:
    return [_program(p, False) for p in program_cfg.list_programs()]


@router.get("/programs/{slug}", response_model=S.ProgramDetail)
def get_program(slug: str) -> S.ProgramDetail:
    p = next((x for x in program_cfg.list_programs() if x["slug"] == slug), None)
    if p is None:
        raise HTTPException(404, S.Problem(
            type="program-not-found", title="Program not found",
            detail=slug).model_dump())
    return _program(p, True)


def collect():
    """[(CampaignDigest, [HypothesisSummary])] for every live campaign."""
    out = []
    for row in _ws().ongoing() + _ws().finished(500):
        if (row.get("payload") or {}).get("archived"):
            continue
        try:
            out.append(_digest(row["id"]))
        except HTTPException:
            continue
    return out


@router.post("/programs", response_model=S.ProgramSummary, status_code=201)
def create_program(body: S.ProgramCreate) -> S.ProgramSummary:
    slug = program_cfg._slug(body.name)
    if any(p["slug"] == slug for p in program_cfg.list_programs()):
        raise HTTPException(409, S.Problem(
            type="program-exists", title="A program with this name exists",
            detail=slug).model_dump())
    program_cfg.save_program_record(
        {"program": body.name, "custom": True, "objective": body.objective,
         "modality": body.modality, "metric": body.metric,
         "direction": body.direction, "gate_value": body.gate_value,
         "unit": body.unit, "mode": "autonomous"}, slug)
    p = next(x for x in program_cfg.list_programs() if x["slug"] == slug)
    return _program(p, False)


def _hand_run(p: dict, doc: dict, body: S.CampaignCreate, user: str) -> S.CampaignSummary:
    """A campaign the scientist runs at the bench: the program's gate is
    pre-registered on every candidate NOW; plates are submitted later and judged
    by that gate (see results.py). Nothing is spawned."""
    import time
    import uuid

    from proef.adapters.store.sqlite import get_store
    from proef.core.contracts import Actor, ActorKind, Envelope, EventType
    from proef.core.hypothesis import (Constraint, HypothesisTracker, ProblemStatement,
                                          SuccessCriteria)
    from proef.core.interfaces import record_for
    from proef.views import ids as _ids
    cands = list(dict.fromkeys(c.strip() for c in body.candidates if c.strip()))
    if not cands:
        raise HTTPException(422, S.Problem(
            type="candidates-required", title="Name the candidates you will test",
            detail="A hand-run campaign needs at least one candidate.").model_dump())
    gate = _gate(doc)
    if gate.threshold is None:
        raise HTTPException(409, S.Problem(
            type="no-gate", title="This program has no numeric gate",
            detail="Set the program's success criterion first.").model_dump())
    objective = body.objective or doc.get("objective") or p["name"]
    pid = f"prob-{uuid.uuid4().hex[:8]}"
    branch = f"problem/{pid}"
    store = get_store(str(_ids.PROVENANCE_DB))
    actor = Actor(kind=ActorKind.human, id=user)
    t = HypothesisTracker(store, actor)
    t.define_problem(ProblemStatement(problem_id=pid, objective=objective, constraints=[Constraint(
        name=gate.metric or "ic50_um", description=gate.label or "gate", kind="hard",
        limit=gate.threshold, unit=gate.unit or "uM")]), environment={"mode": "hand-run"})
    crit = SuccessCriteria(metric=gate.metric or "ic50_um", direction=gate.direction or "min",
                           threshold=gate.threshold)
    for c in cands:
        t.propose(f"{c} meets the gate: {gate.label}", c, "binding", "not predicted — measured by hand",
                  None, criteria=crit, branch_id=branch)
    store.append(record_for(Envelope(experiment_branch_id=branch), EventType.gate_decision, actor, decision={
        "kind": "hand_run", "candidates": cands, "gate": gate.label,
        "note": "criteria registered before any data; plates are submitted by a person and judged against them"}))
    cid = f"hand-{int(time.time())}-{uuid.uuid4().hex[:4]}"
    ws = _ws()
    ws.register_agent(cid, objective, "", autonomy="observe")
    ws.link_problem(cid, pid)
    program_cfg.link_leaf(p["name"], cid, campaign_root=None, question=objective, status="executing")
    return S.CampaignSummary(id=cid, title=objective, status="awaiting_results", autonomy="observe",
                             program=S.ProgramRef(slug=p["slug"], name=p["name"]))


@router.post("/programs/{slug}/campaigns", response_model=S.CampaignSummary,
             status_code=201)
def launch_campaign(slug: str, body: S.CampaignCreate, request: Request) -> S.CampaignSummary:
    """Start a campaign against the program's gate. Default autonomy is
    `gate`: every lab submission waits for a human approval."""
    p = next((x for x in program_cfg.list_programs() if x["slug"] == slug), None)
    if p is None:
        raise HTTPException(404, S.Problem(
            type="program-not-found", title="Program not found",
            detail=slug).model_dump())
    if body.mode == "hand":
        return _hand_run(p, p.get("program") or {}, body, who(request))
    doc = {**(p.get("program") or {}), "autonomy": body.autonomy,
           "k": body.k, "rounds": body.rounds,
           "candidates": ",".join(c.strip() for c in body.candidates if c.strip())}
    if body.objective:
        doc["objective"] = body.objective
    cid = spawn_campaign(doc, p["name"])
    if cid is None:
        raise HTTPException(500, S.Problem(
            type="launch-failed", title="Campaign did not start").model_dump())
    return S.CampaignSummary(
        id=cid, title=doc.get("objective") or p["name"], status="running",
        autonomy=body.autonomy,
        program=S.ProgramRef(slug=slug, name=p["name"]))


@router.get("/today", response_model=S.Today)
def today() -> S.Today:
    """The home screen: what needs me, how each program is doing, and the
    campaigns that belong to no program."""
    from proef.approvals import ApprovalInbox
    from proef.governance import HaltSwitch
    from proef.paths import APPROVALS_FILE
    programs = [_program(p, False) for p in program_cfg.list_programs()]
    linked = {l["eid"] for p in program_cfg.list_programs()
              for l in program_cfg.links_for(p["slug"])}
    standalone, abstentions, running = [], [], 0
    for dg, hyps in collect():
        running += dg.status in _RUNNING
        abst = [h.head for h in hyps if h.state == "abstained" and h.review is None]
        if abst:
            abstentions.append(S.AbstentionNote(
                campaign_id=dg.id, campaign_title=dg.title, candidates=abst))
        if dg.id not in linked:
            standalone.append(dg)
    standalone.sort(key=lambda d: -(d.updated_at or 0))
    return S.Today(
        attention=S.Attention(
            pending_approvals=len(ApprovalInbox(str(APPROVALS_FILE)).pending()),
            abstentions=abstentions, running=running,
            halted=HaltSwitch().engaged() is not None),
        programs=programs, standalone=standalone)
