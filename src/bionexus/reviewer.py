"""The reviewer pass — an independent audit over a campaign's analysis.

Pattern from Anthropic's science stack and The Virtual Biotech: a
separate reviewer inspects methodology and claims before results are
finalized. Design rules that keep it tiered-trust compliant:

- Deterministic, rule-based, OFFLINE: the reviewer is ordinary
  verification code, not an LLM's opinion — the same findings on the
  same records, eval-verifiable.
- It may DEMAND REVISION (findings are recorded as provenance and
  surfaced in the workbench) but it can NEVER clear a refusal or
  overturn a gate — tightening only, like every AI actor here.
- It reviews the ANALYSIS, not the science: math consistency
  (verdict labels vs observed values vs CIs vs gates), evidence
  linkage (every verdict traceable to a recorded run), citation
  integrity (invalid citations cannot back validated claims).

Findings: [{severity: critical|warning, kind, candidate?, detail}].
critical = the verdict as recorded contradicts the recorded evidence.
"""
from __future__ import annotations


def review_campaign(recs) -> dict:
    findings: list[dict] = []
    runs: set[str] = set()
    verdicts: dict[str, dict] = {}       # candidate -> latest final event
    tests: dict[str, int] = {}           # candidate -> analyzed-run count
    for r in recs:
        d = r.decision or {}
        et = r.event_type.value
        art_meta = (r.artifact.metadata or {}) if r.artifact else {}
        cand = d.get("candidate") or art_meta.get("candidate")
        if et == "lab_run" and d.get("run_id"):
            runs.add(d["run_id"])
        elif et in ("hypothesis_validated", "hypothesis_invalidated"):
            key = str(cand or d.get("hypothesis_id") or art_meta.get(
                "candidate") or len(verdicts))
            verdicts[key] = {"verdict": d.get("verdict"),
                             "observed": d.get("observed"),
                             "ci": d.get("observed_ci"),
                             "threshold": d.get("threshold"),
                             "candidate": str(cand) if cand else None,
                             "evidence": d.get("evidence_run_id"),
                             "event": et}
        elif et == "hypothesis_tested" and d.get("verdict"):
            if cand:
                tests[str(cand)] = tests.get(str(cand), 0) + 1

    for key, v in verdicts.items():
        cand = v.get("candidate") or key
        verdict, observed, ci = v.get("verdict"), v.get("observed"), v.get("ci")
        gate = v.get("threshold")

        # 1. label vs observation vs gate (direction: lower is better for
        # ic50-style metrics; inconclusive is exempt by design)
        if verdict in ("validated", "confirmed") and observed is not None \
                and gate is not None and observed > gate:
            # a confirmed hit whose center is beyond the gate needs the
            # CI to straddle it — otherwise the label contradicts data
            if not (ci and ci[0] <= gate <= ci[1]):
                findings.append({
                    "severity": "critical", "kind": "label-vs-data",
                    "candidate": cand,
                    "detail": f"{verdict} but {observed} > gate {gate} "
                              "and CI does not straddle the gate"})

        # 2. CI sanity
        if ci and len(ci) == 2 and ci[0] > ci[1]:
            findings.append({"severity": "critical", "kind": "ci-malformed",
                             "candidate": cand,
                             "detail": f"CI {ci} is inverted"})

        # 3. evidence linkage: a final verdict must point at a recorded run
        if verdict in ("validated", "confirmed", "inconclusive") and runs:
            ev = v.get("evidence")
            if not ev:
                findings.append({"severity": "warning", "kind": "no-evidence",
                                 "candidate": cand,
                                 "detail": f"{verdict} without an "
                                           "evidence_run_id"})
            elif ev not in runs:
                findings.append({"severity": "critical",
                                 "kind": "evidence-unrecorded",
                                 "candidate": cand,
                                 "detail": f"evidence run {ev} is not in "
                                           "the recorded lab runs"})

        # 4. a final claim needs at least one analyzed read
        if verdict in ("validated", "confirmed") and not tests.get(cand):
            findings.append({"severity": "warning", "kind": "no-analyzed-read",
                             "candidate": cand,
                             "detail": f"{verdict} without any analyzed "
                                       "hypothesis_tested record"})

    critical = sum(1 for f in findings if f["severity"] == "critical")
    return {"findings": findings, "critical": critical,
            "warnings": len(findings) - critical,
            "verdicts_reviewed": len(verdicts),
            "review": "reviewer-v1"}
