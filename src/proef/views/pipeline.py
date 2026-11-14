"""Pipeline cards: the per-hypothesis stage view of one experiment."""
from __future__ import annotations

import re

from proef.views.counts import round_markers


# ---------------------------------------------------- hypothesis pipeline
_VERDICT_EVENTS = ("hypothesis_validated", "hypothesis_invalidated",
                   "hypothesis_inconclusive")


def pipeline_data(recs) -> dict:
    """The computation behind the Hypothesis Pipeline: maps of
    proposed/filtered/tested/refused hypotheses plus run attribution.
    Verdicts are payload-driven and RECENCY-WINS: the last verdict-bearing
    record for a hypothesis is its state — a confirmation that refutes (or
    abstains) supersedes the preliminary call it reviewed, on every surface.
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
    seq = 0
    for r in recs:
        seq += 1
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
            # legacy verdict-bearing 'tested' records (pre-2026-10 event
            # map): still verdicts, still recency-wins
            if d.get("verdict"):
                cand = (d.get("candidate") or art_meta.get("candidate")
                        or "")
                key = hid or cand
                if key:
                    tested[key] = {
                        "verdict": d["verdict"],
                        "candidate": cand,
                        "observed": d.get("observed"),
                        "ci": d.get("observed_ci"),
                        "derivation": d.get("derivation"),
                        "seq": seq,
                        "evidence": d.get("evidence_run_id")
                        or d.get("run_id")}
        elif et in _VERDICT_EVENTS:
            hid = d.get("hypothesis_id") or d.get("id") or art_id
            cand = (d.get("candidate") or art_meta.get("candidate")
                    or "")
            if hid:
                prev = tested.get(hid) or {}
                tested[hid] = {"verdict": d.get("verdict", et),
                               "candidate": cand,
                               "observed": d.get("observed")
                               or d.get("ic50_um"),
                               "ci": d.get("observed_ci"),
                               "proxy_evidence": d.get("evidence"),
                               "extrapolation":
                                   bool(d.get("extrapolation")),
                               "derivation": d.get("derivation"),
                               "seq": seq,
                               "evidence": d.get("evidence_run_id")}
        elif et == "stage_transition" \
                and str(d.get("stage", "")).startswith("round-") \
                and d.get("verdicts"):
            # round-complete markers carry the AUTHORITATIVE per-candidate
            # verdict AS OF THE ROUND END — recency-wins, so a later round
            # (or the same round's final state) replaces an earlier marker;
            # a confirmation landing after the marker is a LATER record and
            # wins on its own key
            for cand, v in (d.get("verdicts") or {}).items():
                key = f"cand::{cand}"
                cur = tested.get(key) or {}
                tested[key] = {"verdict": str(v),
                               "candidate": str(cand),
                               "observed": cur.get("observed"),
                               "ci": cur.get("ci"),
                               "derivation": cur.get("derivation"),
                               "seq": seq,
                               "evidence": cur.get("evidence")}
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


def _tested_by_candidate(tested: dict) -> dict:
    """Latest tested record per candidate (highest seq wins)."""
    out: dict = {}
    for v in tested.values():
        c = v.get("candidate")
        if not c:
            continue
        cur = out.get(c)
        if not cur or v.get("seq", 0) >= cur.get("seq", 0):
            out[c] = v
    return out


def _merge_verdict(verd: dict, verd_c: dict) -> dict:
    """Whichever record is MORE RECENT wins on status — the candidate-keyed
    round roll-up may postdate the hid-keyed readout, and vice versa (a
    confirmation record is hid-keyed and terminal). The terminal verdict
    wins on STATUS; the preliminary readout's observed/CI is kept when the
    terminal record carries none (round roll-ups don't repeat the number)."""
    if not (verd_c.get("verdict")
            and verd_c.get("seq", 0) >= verd.get("seq", 0)):
        return verd
    return {**verd, **verd_c,
            "observed": verd_c.get("observed")
            if verd_c.get("observed") is not None else verd.get("observed"),
            "ci": verd_c.get("ci") or verd.get("ci"),
            "evidence": verd_c.get("evidence") or verd.get("evidence"),
            "derivation": verd_c.get("derivation") or verd.get("derivation"),
            "proxy_evidence": verd_c.get("proxy_evidence")
            or verd.get("proxy_evidence"),
            "extrapolation": verd_c.get("extrapolation")
            or verd.get("extrapolation")}


def _card_state(v, *, hid, cand, sel, refused, run_map, unit_lbl, observed,
                ci_txt, margin, ad_chip) -> tuple[str, str]:
    """(state, stage text) for one card — the pipeline state machine."""
    obs_txt = (f" — {unit_lbl} {observed}{ci_txt}"
               if observed is not None else "")
    paren = (f" ({unit_lbl} {observed}{ci_txt})"
             if observed is not None else "")
    if v == "confirmed":
        return "confirmed", "confirmed by orthogonal assay" + obs_txt + margin
    if v == "validated":
        return "validated", "validated (preliminary)" + obs_txt + margin
    if v == "inconclusive":
        return "inconclusive", ("inconclusive — CI straddles the threshold"
                                + paren + ad_chip)
    if v in ("refuted", "invalidated"):
        return "refuted", "refuted" + paren + margin
    if refused.get(str(cand)):
        return "refused", "refused by gate — " + refused[str(cand)][:70]
    if run_map.get(hid):
        return "in_lab", "in lab"
    if sel and sel.get("selected"):
        return "selected", "selected — awaiting submission"
    if sel:
        return "not_selected", "not selected"
    return "proposed", "proposed"


def _gate_label(hp: dict, verd: dict):
    from proef.derivation import criteria_label
    crit = hp.get("criteria") or {}
    gate_lbl = (criteria_label(crit.get("metric"), crit.get("direction"),
                               crit["threshold"])
                if crit.get("threshold") is not None else None)
    evd = (verd or {}).get("proxy_evidence")
    if gate_lbl and isinstance(evd, dict) and evd.get("resolved"):
        n = evd["rungs"]
        gate_lbl += (f" · {n} proxy rung{'s' if n != 1 else ''} "
                     "from clinical")
    elif gate_lbl and isinstance(evd, dict) and not evd.get("resolved"):
        gate_lbl += " · proxy chain unresolved (distance unknown)"
    return gate_lbl, evd


def _card_statement(hp: dict, head) -> str:
    stmt = str(hp.get("statement", ""))
    # the label is often a truncation of the statement itself —
    # strip any leading duplication before cosmetics
    if stmt.startswith(str(head)):
        stmt = stmt[len(str(head)):].strip(" —-·:")
    return re.sub(rf"^{re.escape(str(head))}\s*(\([^)]*\))?\s*[—-]\s*",
                  "", stmt) or head   # statement was the label itself


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
    tested_by_cand = _tested_by_candidate(tested)
    from proef.derivation import metric_label
    cards = []
    for hid, hp in proposed.items():
        sel = filtered.get(hid)
        cand = hp.get("candidate")
        head = cand or hid
        verd = _merge_verdict(tested.get(hid) or {},
                              tested_by_cand.get(str(cand), {}))
        v = (verd.get("verdict") or "").lower()
        ci = verd.get("ci")
        ci_txt = (f" (95% CI {ci[0]}–{ci[1]})" if ci else "")
        _der = verd.get("derivation") or {}
        unit_lbl = metric_label(
            (_der.get("derived") or {}).get("metric")
            or _der.get("criteria_metric") or _der.get("metric"))
        margin = _ci_margin(ci, (hp.get("criteria") or {}).get("threshold"))
        ad_chip = ""
        if verd.get("extrapolation"):
            ad_chip = (" · stamped extrapolation — value came from a model "
                       "beyond its applicability domain")
            margin += ad_chip
        observed = verd.get("observed")
        state, stage = _card_state(
            v, hid=hid, cand=cand, sel=sel, refused=refused, run_map=run_map,
            unit_lbl=unit_lbl, observed=observed, ci_txt=ci_txt,
            margin=margin, ad_chip=ad_chip)
        crit = hp.get("criteria") or {}
        _pb = hp.get("predicted_by")
        if isinstance(_pb, dict) and (_pb.get("ad") or {}).get("extrapolation"):
            _pb = {**_pb, "note": ("prediction came from a model OUTSIDE its "
                                   "applicability domain — treated as a "
                                   "question to test, never as evidence")}
        gate_lbl, _evd = _gate_label(hp, verd)
        cards.append({
            "key": hid,
            "candidate": cand,
            "head": str(head),
            "statement": _card_statement(hp, head),
            "rationale": hp.get("rationale"),
            "predicted": hp.get("predicted"),
            "predicted_by": _pb,
            "mechanism": hp.get("mechanism"),
            "citation": hp.get("citation"),
            "citation_status": hp.get("citation_status"),
            "citation_detail": hp.get("citation_detail"),
            "refutation_condition": hp.get("refutation_condition"),
            "gate_label": gate_lbl,
            "evidence": _evd,
            "threshold": crit.get("threshold"),
            "verdict": {"status": v or None,
                        "observed": observed,
                        "extrapolation": bool(verd.get("extrapolation")),
                        "ci": list(ci) if ci else None,
                        "unit_label": unit_lbl,
                        "margin": margin.strip(" ·")} if verd else None,
            "stage": stage,
            "state": state,
            "round": cand2round.get(str(cand)),
            "selected": bool(sel and sel.get("selected")),
        })
    return cards


def _sandbox_summary(recs) -> dict | None:
    """The sandbox receipt (S-T3 #4): if the experiment ran inside a
    sandbox, the chain says which, with what policy, how many sealed
    ops — None (rendered as nothing) when it didn't."""
    info = None
    for r in recs:
        d = r.decision or {}
        et = r.event_type.value
        if et == "sandbox_create":
            info = {"type": d.get("type") or "docker",
                    "sandbox_id": d.get("sandbox_id") or d.get("created"),
                    "policy": {k: d.get(k) for k in
                               ("network", "memory", "cpus", "pids_limit")
                               if d.get(k)},
                    "execs": 0, "snapshots": 0, "forks": 0,
                    "destroyed": False}
        elif info and et == "sandbox_exec":
            info["execs"] += 1
        elif info and et == "sandbox_snapshot":
            info["snapshots"] += 1
        elif info and et == "sandbox_fork":
            info["forks"] += 1
        elif info and et == "sandbox_destroy":
            info["destroyed"] = True
    return info


def _rounds_with_verdicts(recs) -> list[dict]:
    """Rounds with tested candidates AND the round's verdict map (from
    the round-N-complete stage markers). When a round was chosen by a
    batch-acquisition policy, its Selection rides along as `selection` —
    the "why this plate" answer for the workbench."""
    rounds = [{"round": n, "candidates": c, "verdicts": {}}
              for n, c in round_markers(recs)]
    by_round = {rd["round"]: rd for rd in rounds}
    for r in recs:
        dec = r.decision or {}
        stage = str(dec.get("stage", ""))
        if r.event_type.value == "stage_transition" \
                and stage.startswith("round-") and dec.get("verdicts"):
            try:
                n = int(stage.split("-")[1])
            except (ValueError, IndexError):
                continue
            if n in by_round:
                by_round[n]["verdicts"] = {str(k): str(v) for k, v
                                           in (dec.get("verdicts") or {}).items()}
        if dec.get("kind") == "acquisition_selection":
            try:
                n = int(dec.get("round", 0))
            except (TypeError, ValueError):
                continue
            if n in by_round:
                by_round[n]["selection"] = {
                    "policy": dec.get("policy"),
                    "policy_version": dec.get("policy_version"),
                    "target": dec.get("target"),
                    "direction": dec.get("direction"),
                    "k": dec.get("k"),
                    "picks": dec.get("picks") or [],
                    "refusals": dec.get("refusals") or [],
                    "note": dec.get("note", "")}
    return rounds
