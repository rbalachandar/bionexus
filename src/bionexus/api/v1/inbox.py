"""/api/v1/inbox — everything waiting on a human, in one queue.

Two kinds of item: APPROVALS (a lab submission paused at the gate) and REVIEWS
(a candidate whose interval straddles the gate and that nobody has decided on
yet). Approvals are decided here; reviews are decided on the hypothesis.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from bionexus.api.v1 import schemas as S
from bionexus.api.v1.campaigns import _PID, campaign_for_problem
from bionexus.api.v1.deps import who
from bionexus.api.v1.programs import collect

router = APIRouter(prefix="/inbox", tags=["inbox"])


def _approval_items() -> list[S.InboxItem]:
    from bionexus.approvals import ApprovalInbox
    from bionexus.paths import APPROVALS_FILE
    out = []
    for k, v in ApprovalInbox(str(APPROVALS_FILE)).state().items():
        m = _PID.search(v.get("title", ""))
        camp = campaign_for_problem(m.group(1)) if m else None
        out.append(S.InboxItem(
            id=k, kind="approval", title=v["title"], detail=v.get("detail", ""),
            ts=v.get("ts"), status=v.get("status", "pending"),
            decided_by=v.get("decided_by"),
            campaign_id=camp[0] if camp else None,
            campaign_title=camp[1] if camp else None))
    return out


_VERB = {"follow_up": "followed up", "accept": "accepted as inconclusive",
         "drop": "dropped"}


def _review_items() -> list[S.InboxItem]:
    out = []
    for dg, hyps in collect():
        for h in hyps:
            if h.state != "abstained":
                continue
            v = h.verdict
            rng = f" [{v.ci[0]:.3g} – {v.ci[1]:.3g}]" if v and v.ci else ""
            base = dict(id=f"rev:{dg.id}:{h.id}", kind="review",
                        campaign_id=dg.id, campaign_title=dg.title,
                        hypothesis_id=h.id, candidate=h.head)
            if h.review is None:
                out.append(S.InboxItem(
                    **base, title=f"{h.head} abstained", ts=dg.updated_at,
                    detail=(f"{v.unit_label or 'value'} {v.observed:.3g}{rng}: "
                            "the interval straddles the gate. Follow up, accept "
                            "the abstention, or drop it." if v and v.observed
                            is not None else "No claim either way.")))
            else:
                r = h.review
                out.append(S.InboxItem(
                    **base, status="reviewed", ts=r.ts, decided_by=r.by,
                    decision=r.decision,
                    follow_up_campaign_id=r.follow_up_campaign_id,
                    title=f"{h.head}: {_VERB[r.decision]}",
                    detail=(f"“{r.note}”" if r.note else "")))
    return out


@router.get("", response_model=list[S.InboxItem])
def list_inbox(status: str = Query("pending", pattern="^(pending|all)$")
               ) -> list[S.InboxItem]:
    items = _approval_items() + _review_items()
    if status == "pending":
        items = [i for i in items if i.status == "pending"]
    return sorted(items, key=lambda i: -(i.ts or 0))


@router.post("/{item_id}/decision", response_model=S.InboxItem)
def decide(item_id: str, body: S.DecisionIn, request: Request) -> S.InboxItem:
    """Approve or decline a paused lab submission. The decider is the
    authenticated person, never a field in the body."""
    from bionexus.approvals import ApprovalInbox
    from bionexus.paths import APPROVALS_FILE
    inbox = ApprovalInbox(str(APPROVALS_FILE))
    if item_id not in inbox.state():
        raise HTTPException(404, S.Problem(
            type="approval-not-found", title="Approval not found",
            detail=item_id).model_dump())
    user = who(request)
    inbox.decide(item_id, body.approve, by=user)
    _seal(item_id, inbox.state()[item_id]["title"], body, user)
    return next(i for i in _approval_items() if i.id == item_id)


def _seal(item_id: str, title: str, body: S.DecisionIn, user: str) -> None:
    """A human approval is a governance event: seal it in the campaign's
    hash-chained branch under the approver's name (the approvals log alone is
    not tamper-evident)."""
    m = _PID.search(title)
    if not m:
        return
    from bionexus.adapters.store.sqlite import get_store
    from bionexus.core.contracts import Actor, ActorKind, Envelope, EventType
    from bionexus.core.interfaces import record_for
    from bionexus.views import ids as _ids
    get_store(str(_ids.PROVENANCE_DB)).append(record_for(
        Envelope(experiment_branch_id=f"problem/{m.group(1)}"),
        EventType.gate_decision, Actor(kind=ActorKind.human, id=user),
        decision={"kind": "human_approval", "approval_id": item_id,
                  "title": _PID.sub("", title).strip(), "approve": body.approve,
                  "note": body.note[:500]}))
