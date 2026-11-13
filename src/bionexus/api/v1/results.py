"""POST /api/v1/campaigns/{id}/results — a person submits a measured plate to a campaign.

The honest way to close the loop for a hand-run experiment: the file is judged
by the SAME verdict code a live campaign uses (pre-registered criteria, CI veto,
abstention), only for hypotheses that are still open. The submission, the file's
digest and who made it are sealed before anything is judged.
"""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from bionexus.api.v1 import schemas as S
from bionexus.api.v1.campaigns import _load
from bionexus.api.v1.deps import who
from bionexus.core.contracts import Actor, ActorKind, Envelope, EventType
from bionexus.core.interfaces import record_for

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

MEASURED = ("measured", "historical")


def _problem(status: int, type_: str, title: str, detail: str = "") -> HTTPException:
    return HTTPException(status, S.Problem(type=type_, title=title, detail=detail).model_dump())


def _gate(h) -> str:
    c = h.criteria
    return f"{c.metric} {'≤' if c.direction == 'min' else '≥'} {c.threshold:g}"


def _inspect(eid: str, data: bytes, filename: str, max_response: float | None):
    from bionexus.adapters.store.sqlite import get_store
    from bionexus.core.hypothesis import HypothesisTracker
    from bionexus.labread import QC_ZPRIME_FLOOR, read_plate
    from bionexus.physfail import classify
    from bionexus.views import ids as _ids
    from bionexus.watch import AutoAnalysisAgent

    _, _, _, branch, recs = _load(eid)
    if not branch:
        raise _problem(409, "no-ledger", "Campaign has no ledger branch yet", eid)
    if not filename.lower().endswith(".csv"):
        raise _problem(422, "rejected-upload", "CSV only for now",
                       "Export the plate as CSV (long table or a supported reader format).")
    sha = hashlib.sha256(data).hexdigest()
    run_id = f"upload-{sha[:8]}"
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / f"{run_id}.csv"
        path.write_bytes(data)
        try:
            res = read_plate(path, max_response=max_response)
        except Exception as exc:  # noqa: BLE001
            raise _problem(422, "unreadable-file", "Could not read this file", str(exc)[:200]) from None
    store = get_store(str(_ids.PROVENANCE_DB))
    tracker = HypothesisTracker.resume(store, Actor(kind=ActorKind.human, id="preview"), branch)
    open_h = [h for h in tracker.hypotheses.values() if h.status in AutoAnalysisAgent._OPEN]
    judged = sorted({h.candidate for h in tracker.hypotheses.values() if h.status not in AutoAnalysisAgent._OPEN})
    samples = {str(r.get("sample")) for r in (m if isinstance(m, dict) else m.model_dump() for m in res.records)
               if r.get("sample") and not r.get("control")}
    matches = [h for h in open_h if h.candidate in samples]
    phys = classify([r["value"] for r in (m if isinstance(m, dict) else m.model_dump() for m in res.records)])
    seen = any((r.decision or {}).get("kind") == "results_submitted" and (r.decision or {}).get("sha256") == sha
               for r in recs)
    return dict(branch=branch, store=store, sha=sha, run_id=run_id, res=res, open_h=open_h, judged=judged,
                samples=samples, matches=matches, phys=phys, seen=seen, floor=QC_ZPRIME_FLOOR)


def _preview(info, filename: str) -> S.ResultsPreview:
    res, phys = info["res"], info["phys"]
    matched = {h.candidate for h in info["matches"]}
    z = res.z_prime
    return S.ResultsPreview(
        run_id=info["run_id"], filename=filename, sha256=info["sha"], n_wells=len(res.records),
        z_prime=z, z_kind=(res.analysis or {}).get("z_prime_kind"),
        qc_ok=z is not None and z >= info["floor"],
        failure=phys["evidence"] if phys["kind"] == "physical" else None,
        matches=[S.ResultMatch(hypothesis_id=h.hypothesis_id, candidate=h.candidate,
                               statement=h.statement, gate=_gate(h)) for h in info["matches"]],
        in_file_only=sorted(info["samples"] - matched - set(info["judged"])),
        waiting_for_data=sorted(h.candidate for h in info["open_h"] if h.candidate not in matched),
        already_judged=sorted(set(info["judged"]) & info["samples"]),
        already_submitted=info["seen"])


@router.post("/{eid}/results", response_model=S.ResultsPreview | S.ResultsOutcome)
async def submit_results(eid: str, request: Request, file: UploadFile = File(...),
                         origin: str = Form("measured"), dry_run: bool = Form(True),
                         max_response: float | None = Form(None)):
    """dry_run=true (default): show which open hypotheses this plate would be judged against.
    dry_run=false: seal the submission, then judge. Idempotent per file digest."""
    if origin not in MEASURED:
        raise _problem(422, "proxy-evidence", "Only measured or historical data can judge a hypothesis",
                       f"'{origin}' data stays in Analyze; it cannot produce a campaign verdict.")
    data = await file.read()
    name = file.filename or "upload.csv"
    info = _inspect(eid, data, name, max_response)
    prev = _preview(info, name)
    if dry_run:
        return prev
    if prev.already_submitted:
        raise _problem(409, "already-submitted", "This exact file was already submitted", info["sha"][:12])
    if prev.failure:
        raise _problem(409, "physical-failure", "This plate shows a physical failure",
                       f"{prev.failure} — no verdicts are derived from it. Re-run the plate.")
    if not info["matches"]:
        raise _problem(409, "nothing-to-judge", "No open hypothesis matches this file",
                       "None of the samples in the file belong to an open hypothesis of this campaign.")
    from bionexus.core.hypothesis import HypothesisTracker
    from bionexus.flywheel import Flywheel
    from bionexus.paths import DATA_DIR
    from bionexus.watch import AutoAnalysisAgent, LabEvent
    user, store, branch = who(request), info["store"], info["branch"]
    pid = branch.split("/", 1)[-1]
    inbox = Path(DATA_DIR) / "inbox" / pid
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / f"{info['run_id']}.csv"
    path.write_bytes(data)
    actor = Actor(kind=ActorKind.human, id=user)
    # seal FIRST: a gap between "submitted" and "judged" is visible, never silent
    store.append(record_for(Envelope(experiment_branch_id=branch), EventType.gate_decision, actor, decision={
        "kind": "results_submitted", "sha256": info["sha"], "original_name": name, "run_id": info["run_id"],
        "evidence_origin": origin, "candidates": [h.candidate for h in info["matches"]],
        "z_prime": prev.z_prime, "note": "judged by the campaign's pre-registered criteria; "
                                         "hypotheses that already have a verdict are left alone"}))
    flywheel = Flywheel()

    def _on_verdict(h) -> None:
        flywheel.submit(h.candidate, h.family, h.assay_type, h.status, h.observed_value, h.observed_ci,
                        problem_id=pid, threshold=(h.criteria.threshold if h.criteria else None),
                        evidence_run=h.evidence_run_id)

    tracker = HypothesisTracker.resume(store, actor, branch, on_verdict=_on_verdict)
    msgs: list[str] = []
    agent = AutoAnalysisAgent(store=store, tracker=tracker, notify=msgs.append, branch_id=branch,
                              max_response=max_response)
    out = agent.handle(LabEvent(kind="plate_ready", source="upload", path=path)) or {}
    verdicts = [S.ResultVerdict(hypothesis_id=v[0], candidate=v[1], status=v[2], observed=v[3])
                for v in out.get("verdicts") or []]
    return S.ResultsOutcome(run_id=info["run_id"], verdicts=verdicts, messages=msgs,
                            failure=(out.get("error") or None))
