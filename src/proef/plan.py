"""The research plan: what a model proposed, shown to a person BEFORE any lab submission.

In `gate` autonomy a campaign whose hypotheses came from a model pauses after proposing, shows the plan
(families, their mechanisms and refuted-if clauses, and every variant), and waits. The person can approve
it, decline it, or remove individual hypotheses. Whatever they remove is recorded with a reason and never
tested; the rounds then run on what remains.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PlanDecision:
    approved: bool
    excluded: set[str] = field(default_factory=set)      # hypothesis ids the person removed
    by: str = "operator"
    note: str = ""


def build_plan(portfolio, family_info: dict | None, family_scores: dict | None) -> dict:
    """A JSON-safe plan from the proposed variants. Pure: no I/O."""
    family_info, family_scores = family_info or {}, family_scores or {}
    fams: dict[str, dict] = {}
    for h in portfolio:
        fid = h.family or "ungrouped"
        info = family_info.get(fid, {})
        f = fams.setdefault(fid, {
            "id": fid, "claim": info.get("parent_statement", ""),
            "mechanism": info.get("mechanism") or h.mechanism or "",
            "refuted_if": info.get("refutation_condition") or h.refutation_condition or "",
            "confidence": family_scores.get(fid),
            "citation": h.citation or info.get("citation") or "",
            "citation_status": h.citation_status if (h.citation or info.get("citation")) else "",
            "variants": []})
        f["variants"].append({
            "hypothesis_id": h.hypothesis_id, "candidate": h.candidate, "statement": h.statement,
            "predicted": h.predicted, "rationale": h.rationale, "assay": h.assay_type})
    return {"families": list(fams.values()), "n_hypotheses": len(portfolio)}


def web_plan_approver(inbox, poll_secs: float = 2.0, timeout_secs: float = 24 * 3600,
                      notify: Callable[[str], None] | None = None) -> Callable[[dict, str], PlanDecision]:
    """Request the plan into the approval inbox and wait for the person's decision. Denies on timeout."""
    from proef.approvals import ApprovalInbox
    box = inbox if isinstance(inbox, ApprovalInbox) else ApprovalInbox(str(Path(inbox)))
    say = notify or (lambda m: None)

    def approve(plan: dict, problem_id: str) -> PlanDecision:
        n, m = plan["n_hypotheses"], len(plan["families"])
        title = f"[problem/{problem_id}] Approve the research plan: {n} hypotheses in {m} famil{'y' if m == 1 else 'ies'}"
        aid = box.request(title, detail="Review what the model proposed. Remove any hypothesis you do not want tested.",
                          payload=plan)
        say(f"plan approval requested ({aid}): {n} hypotheses in {m} families — waiting in the workbench")
        deadline = time.time() + timeout_secs
        while time.time() < deadline:
            rec = box.state().get(aid) or {}
            if rec.get("status") in ("approved", "denied"):
                data = rec.get("data") or {}
                return PlanDecision(approved=rec["status"] == "approved", excluded=set(data.get("exclude") or []),
                                    by=rec.get("decided_by", "operator"), note=str(data.get("note") or ""))
            time.sleep(poll_secs)
        say("plan approval timed out")
        return PlanDecision(approved=False, note="timed out waiting for a decision")

    return approve
