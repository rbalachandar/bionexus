"""/api/v1/programs and /api/v1/today — programs as containers of campaigns.

A PROGRAM is the scientific goal: a pre-registered gate (metric, direction,
value) and a modality. A CAMPAIGN is one run that tries to meet it. A program
has many campaigns; every candidate in all of them is judged against the same
gate, so program progress is "has anything claimed met the gate, and what is
the best result so far".
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from bionexus import program as program_cfg
from bionexus.api.v1 import schemas as S
from bionexus.api.v1.campaigns import (_funnel, _load, _status, _summary_of,
                                       _ws)
from bionexus.views.ids import row_status

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
    from bionexus.derivation import criteria_label, metric_label
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
    hyps = [_summary_of(c) for c in detail.get("cards") or []]
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


def _program(p: dict, with_detail: bool):
    doc = p.get("program") or {}
    gate = _gate(doc)
    direction = gate.direction or "min"
    digests, results, all_best = [], [], []
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
    return S.ProgramDetail(**base, campaign_list=digests, results=results)


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


@router.get("/today", response_model=S.Today)
def today() -> S.Today:
    """The home screen: what needs me, how each program is doing, and the
    campaigns that belong to no program."""
    from bionexus.approvals import ApprovalInbox
    from bionexus.governance import HaltSwitch
    from bionexus.paths import APPROVALS_FILE
    programs = [_program(p, False) for p in program_cfg.list_programs()]
    linked = {l["eid"] for p in program_cfg.list_programs()
              for l in program_cfg.links_for(p["slug"])}
    ws = _ws()
    standalone, abstentions, running = [], [], 0
    rows = ws.ongoing() + ws.finished(500)
    for row in rows:
        if (row.get("payload") or {}).get("archived"):
            continue
        try:
            dg, hyps = _digest(row["id"])
        except HTTPException:
            continue
        running += dg.status in _RUNNING
        abst = [h.head for h in hyps if h.state == "abstained"]
        if abst:
            abstentions.append(S.AbstentionNote(
                campaign_id=dg.id, campaign_title=dg.title, candidates=abst))
        if row["id"] not in linked:
            standalone.append(dg)
    standalone.sort(key=lambda d: -(d.updated_at or 0))
    return S.Today(
        attention=S.Attention(
            pending_approvals=len(ApprovalInbox(str(APPROVALS_FILE)).pending()),
            abstentions=abstentions, running=running,
            halted=HaltSwitch().engaged() is not None),
        programs=programs, standalone=standalone)
