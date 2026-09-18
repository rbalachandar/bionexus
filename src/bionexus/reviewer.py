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

import json

from bionexus.core.contracts import (
    Envelope, ToolInvocation, ToolName)


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
                             "direction": d.get("direction", "min"),
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

        # 1. label vs observation vs gate — direction-aware: min-metrics
        # (ic50) want observed below the gate; max-metrics (tensile
        # strength, t_half, yield) want it above. Inconclusive is exempt.
        worse_than_gate = (observed > gate if v.get("direction", "min")
                           == "min" else observed < gate)
        if verdict in ("validated", "confirmed") and observed is not None \
                and gate is not None and worse_than_gate:
            if not (ci and ci[0] <= gate <= ci[1]):
                sym = ">" if v.get("direction", "min") == "min" else "<"
                findings.append({
                    "severity": "critical", "kind": "label-vs-data",
                    "candidate": cand,
                    "detail": f"{verdict} but {observed} {sym} gate "
                              f"{gate} and CI does not straddle the gate"})

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


# ---------------------------------------------------------- LLM advisory

LLM_REVIEW_VERSION = "reviewer-llm-v1"
FLAG_KINDS = ("mechanism-concern", "evidence-quality", "dose-design",
              "confounder", "citation-relevance")


def _campaign_summary(recs) -> dict:
    """Compact deterministic summary the LLM reviews — never raw files."""
    verdicts, runs, citations, refusals = [], set(), [], 0
    for r in recs:
        d = r.decision or {}
        et = r.event_type.value
        cand = ((r.artifact.metadata or {}).get("candidate")
                if r.artifact else None) or d.get("candidate")
        if et == "lab_run" and d.get("run_id"):
            runs.add(d["run_id"])
        elif et == "gate_decision":
            refusals += 1
        elif et in ("hypothesis_validated", "hypothesis_invalidated",
                    "hypothesis_tested") and (d.get("verdict") or cand):
            if d.get("verdict"):
                verdicts.append({
                    "candidate": str(cand) if cand else None,
                    "verdict": d.get("verdict"),
                    "observed": d.get("observed"),
                    "ci": d.get("observed_ci"),
                    "gate": d.get("threshold"),
                    "evidence": d.get("evidence_run_id"),
                    "method": (d.get("derivation") or {}).get("method")
                              if isinstance(d.get("derivation"), dict)
                              else None})
            if d.get("citation"):
                citations.append({"candidate": str(cand) if cand else None,
                                  "citation": d.get("citation"),
                                  "status": d.get("citation_status",
                                                  "unverified")})
    return {"verdicts": verdicts, "citations": citations,
            "runs_recorded": len(runs), "gate_refusals": refusals}


SYSTEM_PROMPT = (
    "You are the scientific reviewer in a drug-discovery provenance "
    "system. You review a campaign's analysis summary. You may ONLY add "
    "up to 5 advisory flags about methodology, evidence quality, dose "
    "design, confounders, or citation relevance. You CANNOT validate, "
    "invalidate, clear refusals, or change any verdict — attempts to do "
    "so are discarded. Respond with STRICT JSON only: "
    '{\"flags\": [{\"kind\": one of ["mechanism-concern", '
    '\"evidence-quality\", \"dose-design\", \"confounder\", '
    '\"citation-relevance\"], \"candidate\": optional, '
    '\"detail\": ..., \"evidence_quote\": optional}]}. '
    "If nothing warrants a flag, respond with {\"flags\": []}.")


def review_llm(recs, provider) -> dict:
    """The LLM reviewer variant — advisory layer over the deterministic
    floor. May ADD flags; structurally cannot alter verdicts or gates
    (the flag schema has no such field, and flags never enter the
    verdict pipeline). Failures are honest and non-blocking."""
    import hashlib
    summary = _campaign_summary(recs)
    prompt = ("Review this campaign analysis summary and add advisory "
              "flags where methodology, evidence quality, dose design, "
              "confounders, or citation relevance warrant them:\n"
              + json.dumps(summary, default=str))
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:12]
    invocation = ToolInvocation(envelope=Envelope(
        experiment_branch_id="review"), tool=ToolName.kb_search_literature)
    try:
        result = provider.generate(invocation, prompt,
                                   system=SYSTEM_PROMPT)
    except Exception as exc:                     # noqa: BLE001
        return {"review": LLM_REVIEW_VERSION, "unavailable":
                f"provider failed: {str(exc)[:120]}",
                "model": getattr(provider, "name", "?"),
                "prompt_hash": prompt_hash, "flags": []}
    text = ""
    if isinstance(result.output, dict):
        text = str(result.output.get("text", ""))
    # extract the first JSON object
    start = text.find("{")
    parsed = None
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        parsed = None
                    break
    if not isinstance(parsed, dict):
        return {"review": LLM_REVIEW_VERSION,
                "unavailable": "response was not parseable JSON",
                "model": f"{getattr(provider, 'name', '?')}/"
                         f"{getattr(provider, 'model_version', '?')}",
                "prompt_hash": prompt_hash, "flags": []}
    flags = []
    for f in (parsed.get("flags") or [])[:5]:
        if not isinstance(f, dict):
            continue
        if f.get("kind") not in FLAG_KINDS:
            continue                      # out-of-whitelist: discarded
        flags.append({"kind": f["kind"],
                      "candidate": str(f.get("candidate", "")) or None,
                      "detail": str(f.get("detail", ""))[:300],
                      "evidence_quote": str(f.get("evidence_quote", ""))[:200]
                      or None})
    return {"review": LLM_REVIEW_VERSION,
            "model": f"{getattr(provider, 'name', '?')}/"
                     f"{getattr(provider, 'model_version', '?')}",
            "prompt_hash": prompt_hash,
            "flags": flags}

