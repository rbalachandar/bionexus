"""Pure read-models for the web API (P0.1).

Extracted from webview.py so the FastAPI layer can serve the same
information the Streamlit UI renders — without importing streamlit.
Every function here is JSON-able-in, JSON-able-out and unit-tested
against real campaign branches (tests/test_views.py).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from bionexus.paths import DATA_DIR

PROVENANCE_DB = "bionexus.db"


# --------------------------------------------------------------- row status
def row_status(e: dict) -> str:
    """Registry status for log-less runs (tree leaves), log/pid-derived
    status for launched campaigns. Port of webview._row_status."""
    ag = e["payload"].get("agent") or {}
    if not ag:
        return e["status"].replace("_", " ")
    log = ag.get("log") or ""
    logf = Path(log)
    if log and logf.is_file() and "CAMPAIGN COMPLETE" in logf.read_text(
            errors="replace"):
        return "completed"
    pid = ag.get("pid")
    if pid:
        try:
            os.kill(pid, 0)
            return "running"
        except OSError:
            return "interrupted"
    return e["status"]


# ------------------------------------------------------- problem id helpers
def has_doubled_branch(root_id: str,
                       db_path: str | Path = PROVENANCE_DB) -> bool:
    """run_tree convention (problem/<root>-<root>) is the default when
    no provenance exists yet."""
    if not Path(db_path).exists():
        return True
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    return bool(SqliteProvenanceStore(str(db_path)).branch_records(
        f"problem/{root_id}-{root_id}"))


def leaf_pid(root_id: str, leaf_id: str,
             db_path: str | Path = PROVENANCE_DB) -> str:
    """Preferred campaign branch id for a leaf. Single-node trees (root
    is its own leaf) may run on problem/<root> OR problem/<root>-<root>."""
    if leaf_id == root_id:
        return f"{root_id}-{root_id}" if has_doubled_branch(
            root_id, db_path) else root_id
    return f"{root_id}-{leaf_id}"


def pid_aliases(root_id: str, leaf_id: str) -> set[str]:
    """All pid forms a leaf's campaign may be registered under."""
    doubled = f"{root_id}-{leaf_id}"
    if leaf_id == root_id:
        return {root_id, doubled}
    return {doubled}


def resolve_problem(meta: dict, logf: Path) -> str | None:
    """Latest prob-* id for a campaign: explicit metadata wins; else the
    log is searched (problem-registration lines first, then any
    CAMPAIGN COMPLETE-style token). Port of Overview._resolve_problem."""
    problem_id = meta.get("problem_id")
    if logf and str(logf) != "." and Path(logf).is_file():
        txt = Path(logf).read_text(errors="replace")
        m = re.findall(r"problem (prob-\w+):", txt) \
            or re.findall(r"\b(prob-[0-9a-f]+)\b", txt)
        latest = m[-1] if m else None
        if latest and latest != problem_id:
            problem_id = latest
    return problem_id


# ------------------------------------------------------------- dmta counts
def dmta_counts(recs) -> dict:
    """DMTA phase counts for a slice of provenance records. Test counts
    unique lab_run submissions (one submission = one run = one analyzed
    export); Analyze counts verdict-bearing decisions, deduplicated —
    a hypothesis earns ONE verdict: its latest. Port of
    webview._dmta_counts."""
    c = {"proposed": 0, "selected": 0, "submitted": 0, "refused": 0,
         "runs": 0, "verdicts": 0,
         "validated": 0, "confirmed": 0, "inconclusive": 0,
         "refuted": 0}
    final: dict[str, str] = {}
    orphan = 0
    for r in recs:
        d = r.decision or {}
        et = r.event_type.value
        if et == "hypothesis_proposed":
            c["proposed"] += 1
        elif et == "hypotheses_filtered":
            c["selected"] += sum(1 for x in d.get("decisions", [])
                                 if x.get("selected"))
        elif et == "lab_run" and d.get("run_id"):
            c["submitted"] += 1
            c["runs"] += 1
        elif et == "gate_decision":
            k = d.get("kind")
            if k in ("halt_refusal", "safety_refusal", "authorization",
                     "synthesis_failed") \
                    and d.get("column") != "autonomous":
                c["refused"] += 1
        elif et in ("hypothesis_validated", "hypothesis_invalidated",
                    "hypothesis_tested") and d.get("verdict"):
            hid = d.get("hypothesis_id") \
                or (r.artifact.artifact_id if r.artifact else None)
            if not hid:
                orphan += 1
                continue
            final[hid] = str(d.get("verdict"))
    for v in final.values():
        c["verdicts"] += 1
        if v in ("validated", "confirmed"):
            c[v] += 1
        elif v in ("inconclusive", "refuted"):
            c[v] += 1
    return c


def round_markers(recs) -> list[tuple[int, list[str]]]:
    """[(round_no, [candidates])] sorted by round, from round_start
    markers."""
    markers = [(int((r.decision or {}).get("round", 0)),
                [str(c) for c in (r.decision or {}).get("candidates") or []])
               for r in recs
               if r.event_type.value == "stage_transition"
               and (r.decision or {}).get("kind") == "round_start"]
    return sorted(markers)


# ------------------------------------------------------------- problem trees
def problem_trees(db_path: str | Path = PROVENANCE_DB) -> tuple[list, set]:
    """All serialized problem trees with live status, as JSON-able
    dicts. Returns (trees, leaf_problem_ids); each tree is
    {root, nodes, alloc, leaf_stats, rollup, has_rollup, objective}
    where nodes carry id/parent/objective/status and leaves carry their
    campaign pids. Port of webview.collect_problem_trees."""
    if not Path(db_path).exists():
        return [], set()
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.problem_tree import ProblemTree
    full = SqliteProvenanceStore(str(db_path))
    roots = []
    for br in full.branches():
        if not br.startswith("problem/") or br.count("/") != 1:
            continue
        recs = full.branch_records(br)
        for r in recs:
            env = (r.decision or {}).get("environment") or {}
            if env.get("kind") == "problem-tree":
                roots.append((br, recs))
                break
    trees: list[dict] = []
    leaf_pids: set[str] = set()
    for br, recs in roots:
        tree = None
        rollup_rec = None
        for r in recs:
            d = r.decision or {}
            env = d.get("environment") or {}
            if env.get("kind") == "problem-tree":
                try:
                    tree = ProblemTree.model_validate(env["tree"])
                except Exception:
                    continue
            if d.get("kind") == "tree-rollup" and d.get("tree"):
                rollup_rec = d
        if tree is None:
            continue
        alloc = tree.allocation()
        leaf_stats: dict[str, dict] = {}
        for leaf in tree.leaves():
            aliases = pid_aliases(tree.root.id, leaf.id)
            lrecs = []
            for a in aliases:
                lrecs = full.branch_records(f"problem/{a}")
                if lrecs:
                    break
            lrecs = lrecs or full.branch_records(
                leaf.branch(tree.root.id)) or []
            runs = sum(1 for r in lrecs if r.event_type.value == "lab_run")
            verdicts: dict[str, str] = {}
            blocked = None
            for r in lrecs:
                d = r.decision or {}
                v = d.get("verdict")
                hid = (d.get("hypothesis_id")
                       or (r.artifact.artifact_id if r.artifact else None))
                if v and hid:
                    verdicts[hid] = v
                if d.get("kind") == "halt_refusal" or (
                        d.get("kind") == "authorization"
                        and d.get("column") != "autonomous"):
                    blocked = d.get("kind")
            statement = ""
            for r in lrecs:
                if r.event_type.value == "problem_defined" and r.decision:
                    statement = (r.decision.get("success_metric")
                                 or r.decision.get("objective") or "")
                    break
            if verdicts:
                tree.set_leaf_status(leaf.id, verdicts)
            leaf_stats[leaf.id] = {"runs": runs, "hyp": len(verdicts),
                                   "statement": statement,
                                   "ok": sum(1 for v in verdicts.values()
                                             if v in ("validated",
                                                      "confirmed")),
                                   "blocked": blocked,
                                   "pids": sorted(aliases)}
            leaf_pids.update(aliases)
        nodes = [{"id": n.id, "parent": n.parent,
                  "objective": n.objective, "status": n.status,
                  "metric": n.metric, "direction": n.direction,
                  "gate": n.gate}
                 for n in tree.nodes.values()]
        trees.append({
            "root_id": tree.root.id,
            "objective": tree.root.objective,
            "nodes": nodes,
            "alloc": dict(alloc),
            "leaf_stats": leaf_stats,
            "rollup": tree.rollup(),
            "has_rollup": bool(rollup_rec),
            "branch": br,
        })
    return trees, leaf_pids


def wizard_db_path() -> Path:
    """The registry DB path, honoring BIONEXUS_DATA_DIR."""
    return DATA_DIR / "wizard.db"


# ---------------------------------------------------- hypothesis pipeline
def _verdict_rank(v) -> int:
    """Terminal verdicts outrank preliminary ones."""
    v = str(v or "").lower()
    return {"confirmed": 3, "refuted": 3, "invalidated": 3,
            "validated": 2, "inconclusive": 1}.get(v, 0)


def pipeline_data(recs) -> dict:
    """The computation behind the Hypothesis Pipeline: maps of
    proposed/filtered/tested/refused hypotheses plus run attribution.
    Port of the bookkeeping half of webview._pipeline_body."""
    proposed: dict[str, dict] = {}
    filtered: dict[str, dict] = {}
    run_map: dict[str, list[str]] = {}
    tested: dict[str, dict] = {}
    refused: dict[str, str] = {}
    gates = 0
    gov_events: list[tuple] = []
    run_ts: dict[str, float] = {}
    run_instr: dict[str, str] = {}
    for r in recs:
        d = r.decision or {}
        et = r.event_type.value
        art_id = r.artifact.artifact_id if r.artifact else None
        art_meta = r.artifact.metadata if r.artifact else {}
        ts = getattr(getattr(r, "envelope", None), "created_at", None)
        if et == "lab_run" and d.get("run_id"):
            run_ts[d["run_id"]] = ts or 0
        if et == "hypothesis_proposed":
            # variant records carry statement/predicted but no candidate
            # (candidates are attributed later, at synthesis/round time);
            # fall back to a numbered label, never the string "None"
            _stmt0 = str(d.get("statement")
                         or d.get("parent_statement") or "")
            hid = (d.get("hypothesis_id") or art_id
                   or d.get("candidate") or _stmt0[:48]
                   or f"hyp-{len(proposed) + 1}")
            proposed[hid] = {**d,
                             "candidate": d.get("candidate")
                             or art_meta.get("candidate"),
                             "statement": _stmt0,
                             "predicted": d.get("predicted")
                             or art_meta.get("predicted"),
                             "ts": ts}
        elif et == "hypotheses_filtered":
            for dec in d.get("decisions", []):
                if dec.get("hypothesis_id"):
                    filtered[dec["hypothesis_id"]] = dec
        elif et == "lab_run" and d.get("run_id"):
            run_ts[d["run_id"]] = ts or 0
            run_instr[d["run_id"]] = d.get("instrument", "")
        elif et == "hypothesis_tested":
            hid = d.get("hypothesis_id") or art_id
            if d.get("run_id"):
                run_map.setdefault(hid, []).append(d["run_id"])
            # verdict-bearing reads (confirmation analyses) carry no
            # hypothesis_id: identity lives in the artifact metadata
            if d.get("verdict"):
                cand = (d.get("candidate") or art_meta.get("candidate")
                        or "")
                key = hid or cand
                if key:
                    tested.setdefault(key, {
                        "verdict": d["verdict"],
                        "candidate": cand,
                        "observed": d.get("observed"),
                        "ci": d.get("observed_ci"),
                        "derivation": d.get("derivation"),
                        "evidence": d.get("evidence_run_id")
                        or d.get("run_id")})
        elif et in ("hypothesis_validated", "hypothesis_invalidated"):
            hid = d.get("hypothesis_id") or d.get("id") or art_id
            cand = (d.get("candidate") or art_meta.get("candidate")
                    or "")
            if hid:
                tested[hid] = {"verdict": d.get("verdict", et),
                               "candidate": cand,
                               "observed": d.get("observed")
                               or d.get("ic50_um"),
                               "ci": d.get("observed_ci"),
                               "derivation": d.get("derivation"),
                               "evidence": d.get("evidence_run_id")}
        elif et == "stage_transition" \
                and str(d.get("stage", "")).startswith("round-") \
                and d.get("verdicts"):
            # round-complete markers carry the AUTHORITATIVE per-candidate
            # verdict (confirmation records may lack any hypothesis_id /
            # candidate linkage)
            for cand, v in (d.get("verdicts") or {}).items():
                key = f"cand::{cand}"
                cur = tested.get(key)
                if not cur or _verdict_rank(v) >= _verdict_rank(
                        cur.get("verdict")):
                    tested[key] = {"verdict": str(v),
                                   "candidate": str(cand),
                                   "observed": None, "ci": None,
                                   "derivation": None, "evidence": None}
        elif et == "gate_decision":
            if d.get("kind") in ("safety_refusal", "operator_declined",
                                 "advisory_escalation"):
                for sm in d.get("samples", []):
                    refused[sm] = d.get("reason", "refused")
            else:
                gates += 1
                if d.get("kind") in ("halt_refusal", "authorization",
                                     "failure-mode"):
                    gov_events.append((ts or 0, d))
    return {"proposed": proposed, "filtered": filtered,
            "run_map": run_map, "tested": tested, "refused": refused,
            "gates": gates, "gov_events": gov_events,
            "run_ts": run_ts, "run_instr": run_instr}


def _ci_margin(ci, threshold) -> str:
    """Margin text for a CI against a pre-registered gate."""
    if ci and threshold and None not in ci and ci[1] > ci[0]:
        width = ci[1] - ci[0]
        edge = min(abs(ci[0] - threshold), abs(ci[1] - threshold))
        if ci[0] <= threshold <= ci[1]:
            return " · borderline: CI spans the gate"
        return (" · narrow margin" if edge < width else " · clear margin")
    return ""


def pipeline_cards(recs) -> list[dict]:
    """Card dicts for the Hypothesis Pipeline, in proposed order.
    State machine: confirmed/validated/inconclusive/refuted/refused/
    in_lab/selected/not_selected/proposed. Port of the decision half of
    webview._pipeline_body."""
    data = pipeline_data(recs)
    proposed, filtered = data["proposed"], data["filtered"]
    tested, refused = data["tested"], data["refused"]
    run_map = data["run_map"]
    cand2round = {cand: rnd for rnd, cands in round_markers(recs)
                  for cand in cands}
    tested_by_cand: dict = {}
    for _v in tested.values():
        _c = _v.get("candidate")
        if not _c:
            continue
        _cur = tested_by_cand.get(_c)
        if not _cur or _verdict_rank(_v.get("verdict")) >= _verdict_rank(
                _cur.get("verdict")):
            tested_by_cand[_c] = _v
    from bionexus.derivation import criteria_label, metric_label
    cards = []
    for hid, hp in proposed.items():
        sel = filtered.get(hid)
        cand = hp.get("candidate")
        head = cand or hid
        stmt = str(hp.get("statement", ""))
        stmt = re.sub(rf"^{re.escape(str(head))}\s*(\([^)]*\))?\s*[—-]\s*",
                      "", stmt)
        verd = tested.get(hid) or {}
        verd_c = tested_by_cand.get(str(cand), {})
        # a candidate-keyed terminal verdict (orthogonal confirmation /
        # round roll-up) outranks an earlier preliminary hid-keyed one
        if _verdict_rank(verd_c.get("verdict")) > _verdict_rank(
                verd.get("verdict")):
            verd = verd_c
        v = (verd.get("verdict") or "").lower()
        ci = verd.get("ci")
        ci_txt = (f" (95% CI {ci[0]}–{ci[1]})" if ci else "")
        unit_lbl = metric_label(((verd.get("derivation") or {})
                                 .get("derived") or {}).get("metric"))
        margin = _ci_margin(ci, (hp.get("criteria") or {}).get("threshold"))
        observed = verd.get("observed")
        obs_txt = (f" — {unit_lbl} {observed}{ci_txt}"
                   if observed is not None else "")
        if v == "confirmed":
            state = "confirmed"
            stage = "confirmed by orthogonal assay" + obs_txt + margin
        elif v == "validated":
            state = "validated"
            stage = "validated (preliminary)" + obs_txt + margin
        elif v == "inconclusive":
            state = "inconclusive"
            stage = "inconclusive — CI straddles the threshold" \
                    + f" ({unit_lbl} {observed}{ci_txt})" \
                    if observed is not None else \
                    "inconclusive — CI straddles the threshold"
        elif v in ("refuted", "invalidated"):
            state = "refuted"
            stage = "refuted" + f" ({unit_lbl} {observed}{ci_txt})" \
                if observed is not None else "refuted"
            stage = "refuted" + (f" ({unit_lbl} {observed}{ci_txt})"
                                 if observed is not None else "") + margin
        elif refused.get(str(cand)):
            state = "refused"
            stage = ("refused by gate — "
                     + refused[str(cand)][:70])
        elif run_map.get(hid):
            state = "in_lab"
            stage = "in lab"
        elif sel and sel.get("selected"):
            state = "selected"
            stage = "selected — awaiting submission"
        elif sel:
            state = "not_selected"
            stage = "not selected"
        else:
            state = "proposed"
            stage = "proposed"
        crit = hp.get("criteria") or {}
        cards.append({
            "key": hid,
            "candidate": cand,
            "head": str(head),
            "statement": stmt,
            "predicted": hp.get("predicted"),
            "mechanism": hp.get("mechanism"),
            "citation": hp.get("citation"),
            "citation_status": hp.get("citation_status"),
            "citation_detail": hp.get("citation_detail"),
            "refutation_condition": hp.get("refutation_condition"),
            "gate_label": criteria_label(crit.get("metric"),
                                         crit.get("direction"),
                                         crit["threshold"])
            if crit.get("threshold") is not None else None,
            "threshold": crit.get("threshold"),
            "verdict": {"status": v or None,
                        "observed": observed,
                        "ci": list(ci) if ci else None,
                        "unit_label": unit_lbl,
                        "margin": margin.strip(" ·")} if verd else None,
            "stage": stage,
            "state": state,
            "round": cand2round.get(str(cand)),
            "selected": bool(sel and sel.get("selected")),
        })
    return cards


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
