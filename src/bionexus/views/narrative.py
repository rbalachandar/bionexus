"""The experiment narrative / lab-diary read-model."""
from __future__ import annotations

from pathlib import Path
from typing import Any


# --------------------------------------------------------- narrative data
def narrative_data(recs, log_lines=(), data_dir=".data") -> dict:
    """Read-model for 'The record of this run'. Port of narrative.render:
    portfolio, gates, make, test, evidence, verdicts, reviewer, trust.
    Sections with no data come back as None so the FE can skip them."""
    def _proposed():
        return [r for r in recs
                if r.event_type.value == "hypothesis_proposed"
                and r.decision]

    def _candidate(r):
        d = r.decision or {}
        cand = d.get("candidate")
        if cand:
            return str(cand)
        if r.artifact:
            return str((r.artifact.metadata or {}).get("candidate") or "")
        return ""

    out: dict[str, Any] = {"title": "The record of this run"}

    # portfolio scores
    filt = next((r for r in recs
                 if r.event_type.value == "hypotheses_filtered"), None)
    if filt:
        id2cand = {}
        for r in _proposed():
            hid = (r.decision or {}).get("hypothesis_id")
            if hid:
                id2cand[hid] = _candidate(r)
            if r.artifact:
                id2cand[r.artifact.artifact_id] = _candidate(r)
        out["portfolio"] = [{
            "hypothesis": id2cand.get(d.get("hypothesis_id"),
                                      d.get("hypothesis_id", "?")),
            "score": d.get("score"),
            "selected": bool(d.get("selected")),
            "reason": d.get("reason", "")}
            for d in (filt.decision or {}).get("decisions", [])]

    # gates / refusals
    refusals = [l for l in log_lines if "rejected" in l]
    advs = [r for r in recs
            if (r.decision or {}).get("kind") == "advisory"]
    durc = [r for r in recs
            if (r.decision or {}).get("kind") == "durc_refusal"]
    if refusals or advs or durc:
        out["gates"] = {
            "refusals": [l.replace("[campaign] ", "")
                         .replace("[agent] ", "") for l in refusals],
            "advisories": [{
                "flags": [{
                    "sample": f.get("sample"),
                    "alert": f.get("alert"),
                    "declared_intent": f.get("declared_intent")}
                    for f in (a.decision or {}).get("flags", [])]}
                for a in advs],
            "durc": [", ".join((d.decision or {}).get("agents", []))
                     for d in durc]}

    # make / test
    runs = [r for r in recs if r.event_type.value == "lab_run"
            and (r.decision or {}).get("run_id")]
    make_refusals = [r for r in recs
                     if r.event_type.value == "gate_decision"
                     and (r.decision or {}).get("kind") in
                     ("safety_refusal", "halt_refusal", "authorization",
                      "durc_refusal", "operator_declined",
                      "synthesis_failed", "stability_failed")
                     and (r.decision or {}).get("column") != "autonomous"]
    synth = [r for r in recs if r.event_type.value == "synthesis_complete"]
    bio_qc = [r for r in recs
              if r.event_type.value == "stage_transition"
              and (r.decision or {}).get("kind") == "bioprocess_qc"]
    if runs or make_refusals:
        make: dict[str, Any] = {}
        if bio_qc:
            make["bio_qc"] = [{
                "candidate": (r.decision or {}).get("candidate", "?"),
                "lot": (r.decision or {}).get("lot", "—"),
                "aggregation_risk": (r.decision or {}).get(
                    "aggregation_risk", "—"),
                "t_half_h": (r.decision or {}).get("t_half_h", "—"),
                "passed": bool((r.decision or {}).get("ok"))}
                for r in bio_qc]
        if synth:
            make["synthesis"] = [{
                "candidate": (r.decision or {}).get("candidate", "?"),
                "lot": (r.decision or {}).get("lot", "—"),
                "yield_pct": (r.decision or {}).get("yield_pct", "—"),
                "purity": (r.decision or {}).get("purity", "—"),
                "passed": bool((r.decision or {}).get("ok"))}
                for r in synth]
        make["no_synthesis_note"] = bool(runs and not synth)
        if runs:
            make["runs"] = [{
                "run_id": (r.decision or {}).get("run_id"),
                "title": ((r.decision or {}).get("title") or "—")[:48],
                "assay": (r.decision or {}).get("assay", "—"),
                "n_samples": (r.decision or {}).get("n_samples", "—"),
                "concentrations": (r.decision or {}).get(
                    "concentrations") or [],
                "replicates": (r.decision or {}).get("replicates", "—"),
                "n_controls": (r.decision or {}).get("n_controls", "—"),
                "instrument": (r.decision or {}).get("instrument", "lab"),
                "instrument_version": (r.decision or {}).get(
                    "instrument_version")}
                for r in runs]
            d0 = runs[0].decision or {}
            make["protocol_summary"] = (
                f"dispense {d0.get('n_samples', '?')} sample well(s) at "
                f"{d0.get('replicates', '?')} replicates per concentration "
                f"({', '.join(str(c) for c in d0.get('concentrations') or [])}"
                f" µM) plus {d0.get('n_controls', '?')} controls, incubate, "
                f"then read on {d0.get('instrument', 'the reader')}")
        if make_refusals:
            make["refused_count"] = len(make_refusals)
        out["make"] = make

    # verdicts (last per candidate) + derivation descriptions
    last: dict[str, dict] = {}
    for r in recs:
        if r.event_type.value.startswith("hypothesis_"):
            d = r.decision or {}
            cand = _candidate(r)
            if cand and d.get("verdict"):
                last[cand] = d
    if last:
        from bionexus.derivation import criteria_label, metric_label
        _metrics = [d.get("metric") for d in last.values() if d.get("metric")]
        mlabel = metric_label(_metrics[0] if _metrics else None)
        has_ci = any(d.get("observed_ci") for d in last.values())
        rows = []
        for c, d in sorted(last.items()):
            row: dict = {"candidate": c, "verdict": d.get("verdict"),
                         "estimated_label": f"estimated {mlabel}",
                         "estimated": d.get("observed")}
            if has_ci:
                row["ci95"] = ("–".join(str(x) for x in d["observed_ci"])
                               if d.get("observed_ci") else "—")
            if d.get("threshold") is not None:
                row["gate"] = criteria_label(
                    d.get("metric"), None,
                    d.get("threshold")).replace("= ", "")
            row["evidence_run"] = d.get("evidence_run_id") or "never ran"
            rows.append(row)
        out["verdicts"] = {
            "rows": rows,
            "derivations": [
                {"candidate": c,
                 "description": __import__(
                     "bionexus.derivation",
                     fromlist=["describe"]).describe(d.get("derivation"))}
                for c, d in sorted(last.items())],
            "claimed": sum(1 for d in last.values()
                           if d.get("verdict") in ("validated",
                                                   "confirmed")),
            "abstained": sum(1 for d in last.values()
                             if d.get("verdict") in ("inconclusive",
                                                     "proposed"))}

    # reviewer
    reviews = [r for r in recs
               if r.event_type.value == "stage_transition"
               and (r.decision or {}).get("kind") == "review_report"]
    if reviews:
        d = reviews[-1].decision or {}
        reviewer: dict[str, Any] = {
            "review": d.get("review", "reviewer-v1"),
            "critical": d.get("critical", 0),
            "warnings": d.get("warnings", 0),
            "verdicts_reviewed": d.get("verdicts_reviewed", 0),
            "findings": [{"severity": f.get("severity", "?"),
                          "kind": f.get("kind", "?"),
                          "candidate": f.get("candidate"),
                          "detail": f.get("detail", "")}
                         for f in (d.get("findings") or [])]}
        llm = [r for r in recs
               if r.event_type.value == "stage_transition"
               and (r.decision or {}).get("kind") == "review_report_llm"]
        if llm:
            ld = llm[-1].decision or {}
            reviewer["llm"] = {
                "model": ld.get("model", "?"),
                "unavailable": ld.get("unavailable"),
                "prompt_hash": ld.get("prompt_hash", ""),
                "flags": [{"kind": f.get("kind", "?"),
                           "candidate": f.get("candidate"),
                           "detail": f.get("detail", "")}
                          for f in (ld.get("flags") or [])]}
        out["reviewer"] = reviewer

    # trust checks
    cstates = [(r.decision or {}).get("citation_status")
               for r in _proposed() if (r.decision or {}).get("citation")]
    n_flags = sum(len((a.decision or {}).get("flags", [])) for a in advs)
    checks = []
    if cstates:
        ok = sum(1 for c in cstates if c == "verified")
        bad = sum(1 for c in cstates if c == "invalid")
        checks.append(f"citations: {ok} verified, {bad} invalid, "
                      f"{len(cstates) - ok - bad} unverified")
    if durc:
        checks.append("dual-use screening refused this branch's work")
    if n_flags:
        checks.append(f"advisory flags raised (non-blocking): {n_flags}")
    abstained = sum(1 for d in last.values()
                    if d.get("verdict") in ("inconclusive", "proposed"))
    if abstained:
        checks.append(f"{abstained} verdict(s) abstained — CI straddled "
                      "the gate; abstention is reported, not hidden")
    from bionexus.adapters.bio.tox_alerts import RULES_VERSION
    checks.append(f"safety rules: {RULES_VERSION}")
    out["trust"] = {"checks": checks}

    # evidence: recorded plate files for this branch's runs
    run_ids = {d.get("run_id") for r in recs
               if (d := r.decision or {})
               and r.event_type.value == "lab_run" and d.get("run_id")}
    run2cand: dict[str, str] = {}
    for r in recs:
        d = r.decision or {}
        if r.event_type.value == "hypothesis_tested" and d.get("run_id"):
            cand = (d.get("candidate")
                    or ((r.artifact.metadata or {}).get("candidate")
                        if r.artifact else None)) or d.get("candidate")
            if cand:
                run2cand[d["run_id"]] = cand
    import glob
    branch = ""
    if recs:
        env = getattr(recs[0], "envelope", None)
        branch = getattr(env, "experiment_branch_id", "") or ""
    pid = branch.split("/", 1)[1] if "/" in branch else branch
    items = []
    for rid in sorted(run_ids):
        hits = (glob.glob(f"**/{pid}/**/{rid}.csv", root_dir=data_dir,
                          recursive=True)
                or glob.glob(f"**/{pid}/{rid}.csv", root_dir=data_dir,
                             recursive=True)
                or glob.glob(f"**/{rid}.csv", root_dir=data_dir,
                             recursive=True))
        if hits:
            items.append({"run_id": rid,
                          "path": str(Path(data_dir) / hits[0]),
                          "candidate": run2cand.get(rid, rid),
                          "verdict": (last.get(run2cand.get(rid, ""), {})
                                      .get("verdict"))})
    out["evidence"] = {
        "curves": items,          # FE renders these client-side
        "svg_fallback": bool(items),
        "empty_note": None if items else
        "No recorded plate files found for these runs — evidence "
        "curves unavailable (honestly shown, not simulated)."}
    return out
