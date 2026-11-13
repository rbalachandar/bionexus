"""/api/v1/campaigns — the campaign cockpit's data.

Everything here is a pure adaptation of the existing read-models in
`bionexus.views` into the typed v1 contract (see schemas.py); no engine logic
lives in this file.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query, Request

from bionexus import views
from bionexus.api.v1 import schemas as S
from bionexus.api.v1.deps import who
from bionexus.views import ids as _ids
from bionexus.views.experiment import _branch_records, _problem_id
from bionexus.views.ids import row_status
from bionexus.wizard_store import WizardStore

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

_STATE = {"inconclusive": "abstained", "invalidated": "refuted"}
_JUDGED = {"confirmed", "validated", "abstained", "refuted"}
_TESTED = _JUDGED | {"in_lab"}


def _norm(x: str | None) -> str | None:
    return _STATE.get(x, x) if x else x


# ------------------------------------------------------------------ helpers
def _ws() -> WizardStore:
    return WizardStore()


def _program_index() -> dict[str, S.ProgramRef]:
    """eid -> the program that links it."""
    from bionexus import program as program_cfg
    out: dict[str, S.ProgramRef] = {}
    for p in program_cfg.list_programs():
        for link in program_cfg.links_for(p["slug"]):
            out.setdefault(link["eid"],
                           S.ProgramRef(slug=p["slug"], name=p["name"]))
    return out


def _cand(rec) -> str | None:
    d = rec.decision or {}
    if d.get("candidate"):
        return str(d["candidate"])
    if rec.artifact:
        c = (rec.artifact.metadata or {}).get("candidate")
        return str(c) if c else None
    return None


def summarize(rec) -> tuple[str, str, str | None]:
    """(kind, human text, candidate) for one provenance record."""
    et = rec.event_type.value
    d = rec.decision or {}
    cand = _cand(rec)
    if et == "problem_defined":
        return "problem", f"Problem defined: {d.get('objective', '')}", None
    if et == "hypothesis_proposed":
        label = cand or str(d.get("statement", ""))[:60]
        return "proposed", f"Proposed {label}", cand
    if et == "hypotheses_filtered":
        if d.get("kind") == "acquisition_selection":
            return ("batch", f"Batch chosen by {d.get('policy')}: "
                    f"{len(d.get('picks') or [])} picked, "
                    f"{len(d.get('refusals') or [])} refused", None)
        decs = d.get("decisions") or []
        return ("batch", f"Portfolio filtered: "
                f"{sum(1 for x in decs if x.get('selected'))} of "
                f"{len(decs)} selected", None)
    if et == "lab_run":
        return ("run", f"Run {d.get('run_id', '?')} submitted"
                + (f" — {d['title']}" if d.get("title") else ""), cand)
    if et == "synthesis_complete":
        return ("make", f"Synthesised {d.get('candidate', '?')}: yield "
                f"{d.get('yield_pct', '?')}%, purity {d.get('purity', '?')}%",
                cand)
    if et in ("hypothesis_validated", "hypothesis_invalidated",
              "hypothesis_inconclusive"):
        word = {"hypothesis_validated": "VALIDATED",
                "hypothesis_invalidated": "REFUTED",
                "hypothesis_inconclusive": "ABSTAINED"}[et]
        obs = d.get("observed")
        return ("verdict", f"{cand or '?'}: {word}"
                + (f" — observed {obs}" if obs is not None else ""), cand)
    if et == "gate_decision" and d.get("kind") == "human_approval":
        verb = "approved" if d.get("approve") else "declined"
        return ("review", f"{rec.actor.id} {verb} the lab submission “{d.get('title', '')}”", cand)
    if et == "gate_decision" and d.get("kind") == "human_review":
        verb = {"follow_up": "follow up", "accept": "accept as inconclusive",
                "drop": "drop"}.get(d.get("decision"), d.get("decision"))
        return ("review", f"{rec.actor.id} decided to {verb} {cand or '?'}"
                + (f" — “{d['note']}”" if d.get("note") else ""), cand)
    if et == "gate_decision" and d.get("kind") == "hand_run":
        return ("run", f"{rec.actor.id} registered a hand-run campaign for "
                f"{', '.join(d.get('candidates') or [])} against {d.get('gate', 'the gate')}", None)
    if et == "gate_decision" and d.get("kind") == "results_submitted":
        return ("run", f"{rec.actor.id} submitted a plate ({d.get('original_name', '?')}) — judging "
                f"{', '.join(d.get('candidates') or []) or 'nothing'}", None)
    if et == "gate_decision" and d.get("kind") == "analysis_attached":
        return ("review", f"{rec.actor.id} attached analysis {d.get('analysis_id', '?')} as evidence"
                + (f" for {d['candidate']}" if d.get("candidate") else ""), d.get("candidate"))
    if et == "gate_decision":
        kind = d.get("kind", "gate")
        reason = d.get("reason") or d.get("action") or ""
        return ("gate", f"{kind.replace('_', ' ').capitalize()}"
                + (f": {reason}" if reason else ""), cand)
    if et == "stage_transition":
        stage = str(d.get("stage", d.get("kind", "")))
        if d.get("kind") == "round_start":
            return ("round", f"Round {d.get('round')} started: "
                    f"{', '.join(d.get('candidates') or [])}", None)
        if stage.endswith("-complete") and stage.startswith("round-"):
            return "round", f"Round {stage.split('-')[1]} complete", None
        if d.get("kind") == "review_report":
            n = len(d.get("findings") or [])
            return ("review", "Reviewer: no findings" if not n
                    else f"Reviewer: {n} finding(s)", None)
    return "event", et.replace("_", " ").capitalize(), cand


def _ts(rec) -> float | None:
    return getattr(getattr(rec, "envelope", None), "created_at", None)


ROLE = {
    "campaign": "Campaign orchestrator — proposes, selects, tests and judges",
    "synthesis": "Make — synthesis and batch QC",
    "bioprocess": "Make — bioprocess stability QC",
    "reviewer": "Independent reviewer — audits every verdict",
    "llm-reviewer": "Advisory LLM reviewer — can only add flags",
    "safety": "Safety gate — refuses unsafe submissions",
    "planner": "Planner — decomposes the objective into sub-problems",
    "program": "Program registry",
}


def _actor(rec) -> tuple[str, str, str | None]:
    a = rec.actor
    return a.id, a.kind.value, a.model_version


def _role(aid: str, kind: str) -> str:
    if kind == "human":
        return "Scientist — your decisions"
    return ROLE.get(aid, aid)


_QUIET = {"proposed", "event"}      # kept in provenance, hidden in the feed


def activity_items(recs, limit: int = 50) -> list[S.ActivityItem]:
    out = []
    for r in recs:
        kind, text, cand = summarize(r)
        if kind in _QUIET:
            continue
        out.append(S.ActivityItem(ts=_ts(r), kind=kind, text=text,
                                  candidate=cand, actor=_actor(r)[0]))
    return list(reversed(out))[:limit]


def _id2cand(recs) -> dict[str, str]:
    m: dict[str, str] = {}
    for r in recs:
        if r.event_type.value == "hypothesis_proposed":
            c = _cand(r)
            hid = (r.decision or {}).get("hypothesis_id")
            for k in (hid, r.artifact.artifact_id if r.artifact else None):
                if k and c:
                    m[k] = c
    return m


def _why_rounds(recs, detail_rounds) -> list[S.Round]:
    id2c = _id2cand(recs)
    portfolio = [r.decision for r in recs
                 if r.event_type.value == "hypotheses_filtered"
                 and (r.decision or {}).get("decisions") is not None]
    out = []
    for rd in detail_rounds:
        n = rd["round"]
        sel, why = rd.get("selection"), None
        if sel:
            why = S.Why(
                policy=sel.get("policy"),
                policy_version=(str(sel["policy_version"])
                                if sel.get("policy_version") is not None else None),
                k=sel.get("k"),
                target=sel.get("target"), direction=sel.get("direction"),
                note=sel.get("note", ""),
                picks=[S.Pick(candidate=p["candidate"],
                              reason=p.get("reason", ""),
                              score=p.get("acquisition"), mean=p.get("mean"),
                              sd=p.get("sd")) for p in sel.get("picks", [])],
                refusals=[S.Refusal(candidate=x["candidate"],
                                    reason=x.get("reason", ""))
                          for x in sel.get("refusals", [])])
        elif 0 <= n - 1 < len(portfolio):
            decs = portfolio[n - 1].get("decisions", [])

            def name(d):
                return id2c.get(d.get("hypothesis_id"),
                                d.get("hypothesis_id", "?"))
            why = S.Why(
                policy="portfolio score", k=sum(1 for d in decs
                                                if d.get("selected")),
                picks=[S.Pick(candidate=name(d), reason=d.get("reason", ""),
                              score=d.get("score"))
                       for d in decs if d.get("selected")],
                refusals=[S.Refusal(candidate=name(d),
                                    reason=d.get("reason") or "not selected")
                          for d in decs if not d.get("selected")])
        out.append(S.Round(n=n, candidates=rd["candidates"],
                           verdicts={k: _norm(v) or v
                                     for k, v in rd.get("verdicts", {}).items()},
                           why=why))
    return out


def _reviews(recs) -> dict[str, S.Review]:
    """Latest human decision per hypothesis id (and candidate)."""
    out: dict[str, S.Review] = {}
    for r in recs:
        d = r.decision or {}
        if d.get("kind") != "human_review" or not d.get("decision"):
            continue
        rv = S.Review(decision=d["decision"], note=d.get("note", ""),
                      by=r.actor.id, ts=_ts(r),
                      follow_up_campaign_id=d.get("follow_up_campaign_id"))
        for k in (d.get("hypothesis_id"), d.get("candidate")):
            if k:
                out[str(k)] = rv
    return out


def _summary_of(card, gate_label: str | None = None,
                reviews: dict | None = None) -> S.HypothesisSummary:
    v = card.get("verdict")
    verdict = None
    if v and v.get("status"):
        status = _norm(str(v["status"]).lower())
        if status in ("confirmed", "validated", "abstained", "refuted"):
            ci = v.get("ci")
            verdict = S.Verdict(
                status=status, observed=v.get("observed"),
                ci=list(ci) if ci else None, unit_label=v.get("unit_label"),
                margin=v.get("margin") or None,
                extrapolation=bool(v.get("extrapolation")))
    return S.HypothesisSummary(
        id=card["key"], candidate=card.get("candidate"),
        head=card.get("head") or card["key"],
        statement=card.get("statement") or "",
        state=_norm(card["state"]), stage=card.get("stage") or "",
        round=card.get("round"), verdict=verdict,
        gate_label=gate_label or card.get("gate_label"),
        selected=bool(card.get("selected")),
        review=(reviews or {}).get(card["key"])
        or (reviews or {}).get(str(card.get("candidate"))))


def _funnel(hyps: list[S.HypothesisSummary]) -> S.Funnel:
    st = [h.state for h in hyps]
    tested = sum(s in _TESTED for s in st)
    return S.Funnel(
        proposed=len(st),
        selected=tested + sum(s in ("selected", "refused") for s in st),
        tested=tested, judged=sum(s in _JUDGED for s in st),
        claimed=sum(s in ("confirmed", "validated") for s in st),
        refuted=sum(s == "refuted" for s in st),
        abstained=sum(s == "abstained" for s in st))


def _gate(recs, cards, detail) -> S.Gate:
    """The campaign's gate, from what the VERDICTS were judged against (the
    recorded decision), then the problem's hard constraint, then the program.
    Per-card proposal-time thresholds are not authoritative (a hypothesis
    can be proposed against a prediction, then judged against the gate)."""
    from bionexus.derivation import criteria_label
    for r in reversed(recs):
        d = r.decision or {}
        if d.get("threshold") is not None and d.get("metric") \
                and d.get("verdict"):
            direction = d.get("direction") or "min"
            return S.Gate(
                metric=d["metric"], direction=direction,
                threshold=float(d["threshold"]),
                label=criteria_label(d["metric"], direction,
                                     d["threshold"]))
    for c in detail.get("constraints") or []:
        if c.get("limit") is not None:
            direction = "max" if ">=" in (c.get("description") or "") else "min"
            label = criteria_label(c.get("name"), direction, c["limit"])
            if c.get("unit") and "(" not in label:
                label += f" {c['unit']}"
            return S.Gate(metric=c.get("name"), direction=direction,
                          threshold=float(c["limit"]), unit=c.get("unit"),
                          label=label)
    g = ((detail.get("program") or {}).get("gate")) or {}
    if g.get("value") is not None:
        return S.Gate(metric=g.get("metric"), direction=g.get("direction"),
                      threshold=g["value"], unit=g.get("unit"),
                      label=f"{g.get('metric')} {g.get('symbol', '')} "
                            f"{g['value']}")
    for c in cards:
        if c.get("threshold") is not None:
            return S.Gate(threshold=float(c["threshold"]),
                          label=c.get("gate_label"))
    return S.Gate()


def _reviewer(recs) -> S.Reviewer | None:
    last = None
    for r in recs:
        d = r.decision or {}
        if d.get("kind") == "review_report":
            last = d
    if last is None:
        return None
    return S.Reviewer(
        critical=last.get("critical", 0), warnings=last.get("warnings", 0),
        findings=[S.ReviewFinding(severity=f.get("severity", "?"),
                                  kind=f.get("kind", "?"),
                                  candidate=f.get("candidate"),
                                  detail=f.get("detail", ""))
                  for f in last.get("findings") or []])


def _chain(branch: str | None, recs) -> S.ChainStatus:
    if not branch:
        return S.ChainStatus(verified=True, records=0)
    from bionexus.adapters.store.sqlite import get_store
    problems = get_store(str(_ids.PROVENANCE_DB)).verify_chain(branch)
    return S.ChainStatus(verified=not problems, records=len(recs),
                         problems=problems[:10])


def _status(raw: str, recs) -> str:
    """The registry status lags (a launched campaign stays 'executing' for
    ever when no log marker exists); the ledger knows: the autonomous loop
    writes its reviewer report last, so its presence means the campaign is
    complete."""
    if any((r.decision or {}).get("kind") == "hand_run" for r in recs):
        # nothing is running: the person runs the plate, so the campaign is
        # either waiting for their data or done
        judged = {r.artifact.artifact_id for r in recs if r.artifact and r.event_type.value in (
            "hypothesis_validated", "hypothesis_invalidated", "hypothesis_inconclusive")}
        proposed = {r.artifact.artifact_id for r in recs
                    if r.artifact and r.event_type.value == "hypothesis_proposed"}
        return "awaiting_results" if proposed - judged else "completed"
    if raw in ("executing", "running", "interrupted", "verdict recorded") \
            and any((r.decision or {}).get("kind") == "review_report"
                    for r in recs):
        return "completed"
    return raw


_PID = re.compile(r"\[problem/([^\]]+)\]")


def campaign_for_problem(pid: str) -> tuple[str, str] | None:
    """(campaign id, title) whose agent runs the problem branch `pid`."""
    ws = _ws()
    try:                      # a running campaign announces its branch itself
        from bionexus.autoloop import announced_branches
        announced = {v: k for k, v in announced_branches().items()}
    except Exception:
        announced = {}
    for e in ws.ongoing() + ws.finished(500):
        ag = (e.get("payload") or {}).get("agent") or {}
        if ag.get("problem_id") == pid or announced.get(pid) == e["id"]:
            return e["id"], e.get("question") or e["id"]
    return None


def pending_approvals(problem_id: str | None) -> list[S.ApprovalRef]:
    """Lab submissions of THIS campaign waiting for a human (gate autonomy)."""
    if not problem_id:
        return []
    from bionexus.approvals import ApprovalInbox
    from bionexus.paths import APPROVALS_FILE
    out = []
    for k, v in ApprovalInbox(str(APPROVALS_FILE)).state().items():
        m = _PID.search(v.get("title", ""))
        if v.get("status") == "pending" and m and m.group(1) == problem_id:
            out.append(S.ApprovalRef(id=k, title=v["title"],
                                     detail=v.get("detail", ""), ts=v.get("ts")))
    return out


def _load(eid: str):
    ws = _ws()
    row = ws.get(eid)
    if not row:
        raise HTTPException(404, S.Problem(
            type="campaign-not-found", title="Campaign not found",
            detail=eid).model_dump())
    detail = views.experiment_detail(eid, ws) or {}
    branch = detail.get("branch")
    recs = _branch_records(branch, _ids.PROVENANCE_DB)
    return ws, row, detail, branch, recs


# ------------------------------------------------------------------ routes
@router.get("", response_model=list[S.CampaignSummary])
def list_campaigns(program: str | None = Query(None),
                   status: str | None = Query(None),
                   include_archived: bool = False) -> list[S.CampaignSummary]:
    ws = _ws()
    rows = ws.ongoing() + ws.finished(500)
    progs = _program_index()
    out = []
    for e in rows:
        payload = e.get("payload") or {}
        if payload.get("archived") and not include_archived:
            continue
        ag = payload.get("agent") or {}
        pref = progs.get(e["id"])
        st = row_status(e)
        if st in ("executing", "running", "interrupted") and ag.get("problem_id"):
            st = _status(st, _branch_records(f"problem/{ag['problem_id']}",
                                             _ids.PROVENANCE_DB))
        if program and (not pref or pref.slug != program):
            continue
        if status and st != status:
            continue
        out.append(S.CampaignSummary(
            id=e["id"], title=e.get("question") or e["id"], status=st,
            autonomy=ag.get("autonomy"), program=pref,
            updated_at=e.get("updated_at"),
            problem_id=ag.get("problem_id")))
    out.sort(key=lambda c: -(c.updated_at or 0))
    return out


@router.get("/{eid}", response_model=S.CampaignDetail)
def get_campaign(eid: str) -> S.CampaignDetail:
    ws, row, detail, branch, recs = _load(eid)
    cards = detail.get("cards") or []
    gate = _gate(recs, cards, detail)
    rounds = _why_rounds(recs, detail.get("rounds") or [])
    tested_cands = {c for r in rounds for c in r.candidates}
    reviews = _reviews(recs)
    hyps = [_summary_of(c, gate.label, reviews) for c in cards]
    runs = sum(1 for r in recs if r.event_type.value == "lab_run"
               and (r.decision or {}).get("run_id"))
    progs = _program_index()
    pid = (detail.get("agent") or {}).get("problem_id")
    return S.CampaignDetail(
        awaiting_approvals=pending_approvals(pid),
        id=eid, title=row.get("question") or eid,
        status=_status(detail.get("status") or row_status(row), recs),
        autonomy=(detail.get("agent") or {}).get("autonomy"),
        program=progs.get(eid), updated_at=row.get("updated_at"),
        problem_id=(detail.get("agent") or {}).get("problem_id"),
        objective=detail.get("objective"), branch=branch,
        gate=gate,
        budget=S.Budget(runs_used=runs,
                        runs_max=(detail.get("spec") or {}).get("run_budget")),
        funnel=_funnel(hyps), rounds=rounds,
        hypotheses=hyps,
        eliminated=[S.Refusal(candidate=str(x.get("candidate")),
                              reason=x.get("reason") or "not selected")
                    for x in detail.get("eliminated") or []
                    if str(x.get("candidate")) not in tested_cands],
        reviewer=_reviewer(recs), chain=_chain(branch, recs))


@router.get("/{eid}/hypotheses/{hid}", response_model=S.HypothesisDetail)
def get_hypothesis(eid: str, hid: str) -> S.HypothesisDetail:
    _, _, detail, branch, recs = _load(eid)
    card = next((c for c in detail.get("cards") or [] if c["key"] == hid), None)
    if card is None:
        raise HTTPException(404, S.Problem(
            type="hypothesis-not-found", title="Hypothesis not found",
            detail=hid).model_dump())
    base = _summary_of(card, _gate(recs, detail.get("cards") or [], detail).label,
                       _reviews(recs))
    cand = card.get("candidate")
    mine = [r for r in recs
            if (r.decision or {}).get("hypothesis_id") == hid
            or (r.artifact and r.artifact.artifact_id == hid)
            or (cand and _cand(r) == cand)]
    from bionexus.derivation import describe
    deriv, runs = None, []
    for r in mine:
        d = r.decision or {}
        if d.get("derivation"):
            deriv = describe(d["derivation"])
        for k in ("evidence_run_id", "run_id"):
            if d.get(k) and d[k] not in runs:
                runs.append(d[k])
    events = []
    for r in mine:
        kind, text, c = summarize(r)
        events.append(S.ActivityItem(ts=_ts(r), kind=kind, text=text,
                                     candidate=c, actor=_actor(r)[0]))
    return S.HypothesisDetail(
        **base.model_dump(), rationale=card.get("rationale"),
        predicted=card.get("predicted"), predicted_by=card.get("predicted_by"),
        mechanism=card.get("mechanism"),
        refutation_condition=card.get("refutation_condition"),
        citation=card.get("citation"),
        citation_status=card.get("citation_status"),
        evidence=card.get("evidence"), derivation=deriv, evidence_runs=runs,
        events=events)


@router.get("/{eid}/hypotheses/{hid}/curves", response_model=S.CurveSet)
def get_curves(eid: str, hid: str) -> S.CurveSet:
    """The recorded dose–response data behind a verdict: every plate point,
    the fit with its interval, and the plate's QC — so a scientist can LOOK at
    the evidence, not only read the number."""
    import math

    from bionexus.fitting import hill_fit, hill_response
    from bionexus.labread import read_plate
    from bionexus.paths import DATA_DIR
    _, _, detail, branch, recs = _load(eid)
    card = next((c for c in detail.get("cards") or [] if c["key"] == hid), None)
    if card is None:
        raise HTTPException(404, S.Problem(
            type="hypothesis-not-found", title="Hypothesis not found",
            detail=hid).model_dump())
    cand = card.get("candidate")
    items = views.narrative_data(recs, [], str(DATA_DIR)).get(
        "evidence", {}).get("curves", [])
    mine = sorted((i for i in items if i.get("candidate") == cand),
                  key=lambda i: i["run_id"])
    out = S.CurveSet(candidate=cand)
    for n, it in enumerate(mine):
        try:
            res = read_plate(it["path"])
        except Exception as exc:        # unreadable evidence file: say so
            out.note = f"could not read {it['run_id']}: {str(exc)[:80]}"
            continue
        pts = [(float(r["conc_um"]), float(r["value"]))
               for r in (m if isinstance(m, dict) else m.model_dump()
                         for m in res.records)
               if r.get("sample") == cand and not r.get("control")
               and isinstance(r.get("conc_um"), (int, float))
               and isinstance(r.get("value"), (int, float))]
        if not pts:
            continue
        comp = (res.analysis.get("compounds") or {}).get(cand) or {}
        fit = None
        if comp:
            line: list[S.CurvePoint] = []
            hf = hill_fit(pts, None)
            if comp.get("ic50_um") and hf:
                lo, hi = min(c for c, _ in pts) / 1.6, max(c for c, _ in pts) * 1.6
                for i in range(60):
                    c = lo * (hi / lo) ** (i / 59)
                    line.append(S.CurvePoint(
                        conc_um=c, value=hill_response(c, comp["ic50_um"],
                                                       hf["top"])))
            ci = comp.get("ic50_ci")
            fit = S.CurveFit(
                ic50_um=comp.get("ic50_um"),
                ci=list(ci) if ci else None, top=hf["top"] if hf else None,
                method=comp.get("fit_method"), model=comp.get("fit_model"),
                right_censored=bool(comp.get("right_censored")),
                left_censored=bool(comp.get("left_censored")), line=line)
        out.curves.append(S.Curve(
            run_id=it["run_id"],
            label="Primary screen" if n == 0 else f"Confirmation {n}",
            points=[S.CurvePoint(conc_um=c, value=v) for c, v in sorted(pts)],
            fit=fit, z_prime=res.z_prime,
            z_kind=(res.analysis or {}).get("z_prime_kind"),
            unit=getattr(res, "response_unit", None)))
    if not out.curves and not out.note:
        out.note = "no recorded plate file found for this candidate"
    return out


@router.get("/{eid}/activity", response_model=list[S.ActivityItem])
def get_activity(eid: str, limit: int = Query(50, ge=1, le=500)
                 ) -> list[S.ActivityItem]:
    _, _, _, _, recs = _load(eid)
    return activity_items(recs, limit)


@router.get("/{eid}/provenance", response_model=S.ProvenanceView)
def get_provenance(eid: str, limit: int = Query(500, ge=1, le=5000),
                   actor: str | None = Query(None, description="only this agent / person")
                   ) -> S.ProvenanceView:
    _, _, _, branch, recs = _load(eid)
    items = []
    for r in recs:
        aid, kind, model = _actor(r)
        if actor and aid != actor:
            continue
        _, text, _ = summarize(r)
        items.append(S.ProvenanceRecord(
            ts=_ts(r), event=r.event_type.value, summary=text, actor=aid,
            actor_kind=kind, model_version=model, detail=r.decision))
    return S.ProvenanceView(chain=_chain(branch, recs), records=items[-limit:])


@router.get("/{eid}/agents", response_model=list[S.AgentSummary])
def get_agents(eid: str) -> list[S.AgentSummary]:
    """Who acted in this campaign — each agent/service/person with what it did."""
    _, _, _, _, recs = _load(eid)
    by: dict[str, dict] = {}
    for r in recs:
        aid, kind, model = _actor(r)
        e = by.setdefault(aid, {"kind": kind, "model": model, "n": 0,
                                "ts": None, "text": ""})
        e["n"] += 1
        e["model"] = e["model"] or model
        _, text, _ = summarize(r)
        e["ts"], e["text"] = _ts(r), text
    out = [S.AgentSummary(id=k, kind=v["kind"], role=_role(k, v["kind"]),
                          model_version=v["model"], events=v["n"],
                          last_ts=v["ts"], last_text=v["text"])
           for k, v in by.items()]
    return sorted(out, key=lambda a: -a.events)


@router.post("/{eid}/hypotheses/{hid}/review", response_model=S.Review)
def review_hypothesis(eid: str, hid: str, body: S.ReviewIn,
                      request: Request) -> S.Review:
    """Record the scientist's decision on a hypothesis. Append-only and sealed
    in the same hash chain as everything the agents did."""
    from bionexus.adapters.store.sqlite import get_store
    from bionexus.core.contracts import Actor, ActorKind, Envelope, EventType
    from bionexus.core.interfaces import record_for
    _, _, detail, branch, recs = _load(eid)
    card = next((c for c in detail.get("cards") or [] if c["key"] == hid), None)
    if card is None or not branch:
        raise HTTPException(404, S.Problem(
            type="hypothesis-not-found", title="Hypothesis not found",
            detail=hid).model_dump())
    user = who(request)
    rec = record_for(
        Envelope(experiment_branch_id=branch), EventType.gate_decision,
        Actor(kind=ActorKind.human, id=user),
        decision={"kind": "human_review", "hypothesis_id": hid,
                  "candidate": card.get("candidate"),
                  "decision": body.decision, "note": body.note[:500],
                  "follow_up_campaign_id": body.follow_up_campaign_id})
    get_store(str(_ids.PROVENANCE_DB)).append(rec)
    return S.Review(decision=body.decision, note=body.note[:500], by=user,
                    ts=_ts(rec),
                    follow_up_campaign_id=body.follow_up_campaign_id)


@router.post("/{eid}/archive", response_model=S.CampaignSummary)
def archive_campaign(eid: str) -> S.CampaignSummary:
    ws = _ws()
    if not ws.get(eid):
        raise HTTPException(404, S.Problem(
            type="campaign-not-found", title="Campaign not found",
            detail=eid).model_dump())
    ws.set_archived(eid, True)
    row = ws.get(eid)
    return S.CampaignSummary(id=eid, title=row.get("question") or eid,
                             status=row_status(row))
