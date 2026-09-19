"""Shared rendering for the experiment detail page."""
from __future__ import annotations

import re
import time
from pathlib import Path

import streamlit as st

PAGES_EXP = None       # Overview injects at import
WIZARD_PAGE = None      # Overview injects at import
START_DIALOG = None     # Overview injects at import

def halt_banner() -> None:
    """Operator stop-condition banner. This is a HUMAN decision recorded
    via `bn halt` (or the button below) — deliberately not an instrument
    or agent event, and the copy must keep that distinction clear."""
    import time as _time
    from bionexus.governance import HaltSwitch
    hs = HaltSwitch()
    halt = hs.engaged()
    if not halt:
        return
    age = _time.time() - halt.get("ts", _time.time())
    _when = (f"{age / 60:.0f} min ago" if age < 86400
             else f"{age / 86400:.1f} days ago")
    from bionexus import ui
    col_txt, col_btn = st.columns([6, 1])
    with col_txt:
        st.markdown(
            f"{ui.icon('halt', 14, 'refused')} "
            f"{ui.small(f'<b>Halted by operator</b> — a human pressed '
                       'stop (not an instrument error; the lab may be '
                       'fine). New lab submissions are refused · reason: '
                       f"{halt.get('reason', chr(8212))} · engaged "
                       f"{_when}")}",
            unsafe_allow_html=True)
    if col_btn.button("Clear halt", key="aenv-halt-clear"):
        hs.clear()
        st.toast("Halt cleared — lab submissions flow again",
                 icon=":material/check_circle:")
        st.rerun()


def render_experiment_pipeline(logf: Path, problem_id: str | None,
                                running: bool, store, eid: str) -> None:
    """Live view: when the experiment is running the whole block refreshes
    every 3s (provenance, cards, log), so stages move without user action."""
    if running:
        @st.fragment(run_every=3)
        def _live():
            _pipeline_body(logf, problem_id, running, store, eid)
        _live()
    else:
        _pipeline_body(logf, problem_id, running, store, eid)


def _pipeline_body(logf: Path, problem_id: str | None,
                   running: bool, store, eid: str) -> None:
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    branch = f"problem/{problem_id}" if problem_id else None
    recs = []
    if branch and Path("bionexus.db").exists():
        try:
            recs = SqliteProvenanceStore("bionexus.db").branch_records(branch)
        except Exception:
            recs = []
    cand2round = {cand: rnd for rnd, cands in _round_markers(recs)
                  for cand in cands}

    cand2round = {cand: rnd for rnd, cands in _round_markers(recs)
                  for cand in cands}
    render_dmta(recs, logf)
    st.markdown("")

    proposed: dict[str, dict] = {}
    filtered: dict[str, dict] = {}
    run_map: dict[str, list[str]] = {}   # hypothesis_id -> run ids (provenance)
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
            hid = d.get("hypothesis_id") or art_id or d.get("candidate", "?")
            proposed[hid] = {**d, "candidate": d.get("candidate") or art_meta.get("candidate"),
                             "predicted": d.get("predicted") or art_meta.get("predicted"),
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
                               "observed": d.get("observed") or d.get("ic50_um"),
                               "ci": d.get("observed_ci"),
                               "derivation": d.get("derivation"),
                               "evidence": d.get("evidence_run_id")}
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

    from bionexus import ui
    tested_by_cand = {v.get("candidate"): v for v in tested.values()
                      if v.get("candidate")}
    if proposed:
        st.markdown("### Hypothesis pipeline")
        for hid, hp in proposed.items():
            sel = filtered.get(hid)
            cand = str(hp.get("candidate", hid))
            # statements embed their own "{cid} ({src}) — " label; the
            # card header already shows the candidate — strip it
            stmt = str(hp.get("statement", ""))
            stmt = re.sub(rf"^{re.escape(cand)}\s*(\([^)]*\))?\s*[—-]\s*",
                          "", stmt)
            verd = tested.get(hid) or tested_by_cand.get(cand, {})
            v = (verd.get("verdict") or "").lower()
            ci = verd.get("ci")
            ci_txt = (f" (95% CI {ci[0]}–{ci[1]})" if ci else "")
            from bionexus.derivation import metric_label as _mlbl
            _unit_lbl = _mlbl(((verd.get("derivation") or {}).get("derived")
                               or {}).get("metric"))
            _margin = ""
            _thr = (hp.get("criteria") or {}).get("threshold")
            if ci and _thr and None not in ci and ci[1] > ci[0]:
                width = ci[1] - ci[0]
                edge = min(abs(ci[0] - _thr), abs(ci[1] - _thr))
                _margin = (" · borderline: CI spans the gate"
                           if ci[0] <= _thr <= ci[1] else
                           (" · narrow margin" if edge < width else " · clear margin"))
            if v == "confirmed":
                icon, stage = ui.icon("verdict", 15, "confirmed"), (
                    "confirmed by orthogonal assay"
                                     + (f" — {_unit_lbl} {verd.get('observed')}{ci_txt}"
                                        if verd.get("observed") is not None else "")
                                     + _margin)
            elif v == "validated":
                icon, stage = ui.icon("verdict", 15, "confirmed"), (
                    "validated (preliminary)"
                                     + (f" — {_unit_lbl} {verd.get('observed')}{ci_txt}"
                                        if verd.get("observed") is not None else "")
                                     + _margin)
            elif v == "inconclusive":
                icon, stage = ui.icon("verdict", 15, "resolved"), (
                    "inconclusive — CI straddles the threshold"
                                     + (f" ({_unit_lbl} {verd.get('observed')}{ci_txt})"
                                        if verd.get("observed") is not None else ""))
            elif v in ("refuted", "invalidated"):
                icon, stage = ui.icon("verdict", 15, "resolved"), ("refuted"
                                     + (f" ({_unit_lbl} {verd.get('observed')}{ci_txt})"
                                        if verd.get("observed") is not None else "")
                                     + _margin)
            elif refused.get(str(hp.get("candidate"))):
                icon, stage = ui.icon("gate-closed", 15, "refused"), (
                    "refused by gate — "
                                      + refused[str(hp.get("candidate"))][:70])
            elif run_map.get(hid):
                icon, stage = ui.icon("instrument", 15, "progress"), "in lab"
            elif sel and sel.get("selected"):
                icon, stage = ui.icon("clock", 15, "human-action"), (
                    "selected — awaiting submission")
            elif sel:
                icon, stage = ui.icon("gate-closed", 15, "provenance"), (
                    "not selected")
            else:
                icon, stage = ui.icon("hypothesis", 15, "teal"), "proposed"
            with st.container(border=True):
                c1, c2 = st.columns([4, 2])
                c1.markdown(f"{icon} <b>{hp.get('candidate', hid)}"
                            f"</b> \u2014 {stmt}",
                            unsafe_allow_html=True)
                c2.caption(stage, unsafe_allow_html=True)
                crit = hp.get("criteria") or {}
                from bionexus.derivation import criteria_label, metric_label
                _cit = ""
                if hp.get("citation"):
                    _st = hp.get("citation_status", "unverified")
                    _ci = {"verified": (ui.icon("evidence", 13, "autonomous"), ""),
                           "invalid": (ui.icon("evidence", 13, "refused"),
                                       " FABRICATED"),
                           "check-failed": (ui.icon("evidence", 13,
                                                    "provenance"), "?"),
                           "unverified": (ui.icon("evidence", 13,
                                                  "provenance"),
                                          "")}.get(_st)
                    _icon = (_ci[0] + _ci[1]) if _ci else _st
                    _cit = f" · {_icon} {hp['citation']}" + (
                        f" ({hp['citation_detail']})"
                        if hp.get("citation_detail") else "")
                if hp.get("mechanism"):
                    st.caption(f"mechanism: {hp['mechanism']}{_cit}",
                               unsafe_allow_html=True)
                elif _cit:
                    st.caption(_cit[3:], unsafe_allow_html=True)
                if hp.get("refutation_condition"):
                    st.caption(f"refuted if: {hp['refutation_condition']}")
                meta_bits = [f"predicted: {hp.get('predicted', '—')}"]
                if crit.get("threshold") is not None:
                    meta_bits.append(
                        "gate: " + criteria_label(crit.get("metric"),
                                                  crit.get("direction"),
                                                  crit["threshold"]))
                _tested_round = cand2round.get(str(hp.get("candidate", hid)))
                if cand2round:
                    if _tested_round:
                        meta_bits.append(
                            f"tested in round {_tested_round}"
                            + (" (carried from round 1)"
                               if _tested_round > 1 else ""))
                    elif not verd:
                        meta_bits.append("not yet in a round")
                if hp.get("rationale"):
                    meta_bits.append(f"rationale: {hp['rationale']}")
                if sel and sel.get("selected"):
                    meta_bits.append(f"selected: {sel.get('reason', '')}")
                if verd:
                    _ml = metric_label(((verd.get("derivation") or {})
                                        .get("derived") or {}).get("metric")
                                       or crit.get("metric"))
                    bits = [f"{_ml}: {verd.get('observed')}"
                            if verd.get("observed") is not None else ""]
                    if verd.get("evidence"):
                        bits.append(f"evidence: `{verd['evidence']}`")
                    meta_bits.append(" · ".join(b for b in bits if b))
                _m = ((verd.get("derivation") or {}).get("derived")
                      or {}).get("method")
                if _m:
                    meta_bits.append(f"method: {_m}")
                if hp.get("ts"):
                    meta_bits.append("proposed "
                                     + time.strftime("%m-%d %H:%M",
                                                     time.localtime(hp["ts"])))
                st.caption(" · ".join(meta_bits))
                if run_map.get(hid):
                    run_bits = []
                    for rid in run_map[hid]:
                        t = run_ts.get(rid)
                        when = time.strftime("%H:%M", time.localtime(t)) if t else "?"
                        inst = run_instr.get(rid) or "lab"
                        run_bits.append(f"`{rid}` ({when} · {inst})")
                    st.caption(f"{ui.icon('instrument', 13, 'provenance')} "
                               "runs: " + " · ".join(run_bits),
                               unsafe_allow_html=True)
        unlinked = [r for r in recs if r.event_type.value == "lab_run"
                    and r.decision and r.decision.get("run_id")
                    and r.decision["run_id"] not in
                    {x for v in run_map.values() for x in v}]
        if unlinked:
            st.caption(f"{ui.icon('instrument', 13, 'human-action')} "
                       f"{len(unlinked)} run(s) awaiting result analysis: "
                       + ", ".join(f"`{u.decision['run_id']}`" for u in unlinked[-4:]),
                       unsafe_allow_html=True)

    from bionexus.governance import HaltSwitch as _HS
    _halt_hist = _HS().history(limit=3)
    _had_halt = any(d.get("kind") == "halt_refusal" for _, d in gov_events)
    if gov_events or (_halt_hist and _had_halt):
        # attribution: gate lines must name their subject (docs/UX.md §6)
        _samp2cand = {str(hp.get("candidate")): hp for hp in proposed.values()}
        with st.expander(f"Harness decisions — what the code allowed or "
                         f"refused ({len(gov_events)})", expanded=_had_halt):
            for _ts, d in sorted(gov_events)[-15:]:
                k = d.get("kind")
                _subj = (", ".join(_samp2cand[s].get("candidate", s)
                                   for s in d.get("samples", [])
                                   if s in _samp2cand)
                         or ", ".join(d.get("samples", []))
                         or d.get("title") or "")
                _prefix = f"{_subj} · " if _subj else ""
                if k == "halt_refusal":
                    st.markdown(
                        f"{ui.tagged('gate-closed', 'REFUSED', 'refused')} — {_prefix}"
                        f"{(d.get('halt') or {}).get('reason', '')} — "
                        "submission refused; a human must clear it",
                        unsafe_allow_html=True)
                elif k == "authorization":
                    col = d.get("column")
                    _icon = {"never": ("gate-closed", "refused"),
                             "human": ("human", "human-action"),
                             "autonomous": ("gate-open",
                                            "autonomous")}.get(
                        col, ("gate-open", "provenance"))
                    st.markdown(
                        f"{ui.icon(_icon[0], 14, _icon[1])} "
                        f"<b style=\"color:{ui.COLORS[_icon[1]]}\">"
                        f"{str(col).upper()}</b> — {_prefix}"
                        f"{d.get('reason', '')}",
                        unsafe_allow_html=True)
                elif k == "failure-mode":
                    st.markdown(
                        f"{ui.tagged('fault', 'PHYSICAL FAULT', 'fault')} — "
                        f"{_prefix}{d.get('evidence', '')} — "
                        f"{d.get('action', '')}",
                        unsafe_allow_html=True)
            for _h in reversed(_halt_hist):
                _mins = max(0, (_h.get("cleared_ts", 0)
                                - _h.get("ts", 0)) / 60)
                st.markdown(
                    f"{ui.icon('history', 14, 'provenance')} "
                    f"<b style=\"color:{ui.COLORS['provenance']}\">"
                    f"Operator halt episode</b> — "
                    f"{_h.get('reason', chr(8212))} — engaged and cleared "
                    f"after {_mins:.0f} min by "
                    f"{_h.get('cleared_by', 'operator')}",
                    unsafe_allow_html=True)
            if _had_halt and _HS().engaged() is None:
                st.caption("the halt above has been cleared; submissions "
                           "flow again — proposals above were refused "
                           "while it was engaged and never ran")
    if gates:
        st.caption(f"{ui.icon('gate-open', 13, 'provenance')} {gates} gate "
                   "decision(s)", unsafe_allow_html=True)



def resume_wizard(e: dict) -> None:
    from bionexus.readiness import (ExperimentReadinessReview, ReviewVerdict)
    p = e["payload"]
    st.session_state["exp_id"] = e["id"]
    st.session_state["problem"] = p.get("problem")
    if p.get("exp_def"):
        ed = p["exp_def"]
        st.session_state["exp_def"] = (
            ed if isinstance(ed, ExperimentDefinition)
            else ExperimentDefinition.model_validate(ed))
    if p.get("readiness"):
        rd = dict(p["readiness"])
        rd["verdict"] = ReviewVerdict(rd["verdict"])
        st.session_state["readiness"] = (
            rd if isinstance(rd, ExperimentReadinessReview)
            else ExperimentReadinessReview.model_validate(rd))
    st.session_state["selected"] = p.get("selected", [])
    st.session_state["plate_data"] = None
    st.session_state["step"] = STATUS_STEP.get(e["status"], 1)


def _leaf_pid(root_id: str, leaf_id: str) -> str:
    """Preferred campaign branch id for a leaf. Single-node trees (root
    is its own leaf) may run on problem/<root> OR problem/<root>-<root>
    (run_tree's formula) — see _pid_aliases."""
    if leaf_id == root_id:
        return f"{root_id}-{root_id}" if _has_doubled_branch(root_id) \
            else root_id
    return f"{root_id}-{leaf_id}"


def _has_doubled_branch(root_id: str) -> bool:
    from pathlib import Path as _P
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    if not _P("bionexus.db").exists():
        return True                      # run_tree convention is default
    store = SqliteProvenanceStore("bionexus.db")
    return bool(store.branch_records(f"problem/{root_id}-{root_id}"))


def _pid_aliases(root_id: str, leaf_id: str) -> set[str]:
    """All pid forms a leaf's campaign may be registered under."""
    doubled = f"{root_id}-{leaf_id}"
    if leaf_id == root_id:
        return {root_id, doubled}
    return {doubled}


def collect_problem_trees():
    """All serialized problem trees with live status, for the Overview.
    Returns (trees, leaf_problem_ids) where trees is a list of
    (tree, alloc, leaf_stats, rollup, rollup_recorded)."""
    from pathlib import Path as _Path

    if not _Path("bionexus.db").exists():
        return [], set()
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.problem_tree import ProblemTree

    full = SqliteProvenanceStore("bionexus.db")
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
    _status_color = {"achieved": "autonomous", "partial": "human-action",
                     "failed": "refused", "open": "provenance"}
    trees, leaf_pids = [], set()
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
            # campaigns run on problem/{root}-{leaf}; the slash form only
            # carries the leaf-complete marker
            aliases = _pid_aliases(tree.root.id, leaf.id)
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
                                   "blocked": blocked}
            leaf_pids.update(_pid_aliases(tree.root.id, leaf.id))
        trees.append((tree, alloc, leaf_stats, tree.rollup(),
                      bool(rollup_rec)))
    return trees, leaf_pids


def _row_status(e: dict) -> str:
    """Registry status for log-less runs (tree leaves), log/pid-derived
    status for launched campaigns."""
    ag = e["payload"].get("agent") or {}
    if not ag:
        return e["status"].replace("_", " ")
    log = ag.get("log") or ""
    from pathlib import Path as _P
    logf = _P(log)
    if log and logf.is_file() and "CAMPAIGN COMPLETE" in logf.read_text(
            errors="replace"):
        return "completed"
    pid = ag.get("pid")
    if pid:
        import os
        try:
            os.kill(pid, 0)
            return "running"
        except OSError:
            return "interrupted"
    return e["status"]


def render_experiment_navigator(all_rows: list | None = None) -> None:
    """The Experiments view IS the navigator: problem trees as
    hierarchies. Labels stay short and may repeat across trees — clicks
    map by node POSITION (return_index), and tooltips carry lineage."""

    sel_prog = st.session_state.pop("ws_program_sel", None)
    if sel_prog:
        doc = sel_prog.get("doc") or {}
        with st.container(border=True):
            st.markdown(f"**Program: {sel_prog['name']}**")
            st.markdown(f"**Objective:** {doc.get('objective', chr(8212))}")
            st.markdown(f"**Gate:** {sel_prog.get('gate', chr(8212))} - "
                        f"**Mode:** {sel_prog.get('mode', chr(8212))}")
            atts = sel_prog.get("attachments") or []
            st.caption(f"{len(atts)} attached experiment(s) - expand the "
                       "program node below to open them")
    try:
        import streamlit_antd_components as sac
    except ImportError:
        st.info("streamlit-antd-components is not installed - "
                "navigator unavailable (`pip install "
                "streamlit-antd-components`)")
        return
    trees, _leaf_pids = collect_problem_trees()
    items, idx2eid = [], {}
    idx2program: dict[int, dict] = {}
    counter = {"i": 0}

    # programs first: shared roots (any modality), visible to everyone
    # on the service. Experiments launched under a program attach as
    # its children (linkage lands with leaf attachment)
    from bionexus import program as program_cfg
    rows_by_eid = {e["id"]: e for e in (all_rows or [])}
    def reserve() -> int:
        i = counter["i"]
        counter["i"] += 1
        return i

    # campaign rows launched from a program carry payload["program"]
    # and render nested under that program (program -> campaign -> leaves)
    prog_rows: dict[str, list] = {}
    for e in (all_rows or []):
        pn = (e.get("payload") or {}).get("program")
        if pn:
            prog_rows.setdefault(pn, []).append(e)

    for prog in program_cfg.list_programs():
        gate = prog.get("gate_summary", "")
        kids = []
        status_tally: dict[str, int] = {}
        for a in prog.get("attachments", []):
            e = rows_by_eid.get(a.get("eid"))
            if not e:
                continue                     # archived -> not shown
            s = _row_status(e)
            status_tally[s] = status_tally.get(s, 0) + 1
            i = reserve()
            idx2eid[i] = e["id"]
            kids.append(sac.TreeItem(
                e["question"][:60] or e["id"],
                icon="smart_toy" if (e["payload"].get("agent") or {})
                else "person",
                description=s, tooltip=a.get("question", "")))
        pname = prog.get("name", prog["slug"])
        camp = prog_rows.get(pname, []) + prog_rows.get(prog["slug"], [])
        camp_ids = {a.get("eid") for a in prog.get("attachments", [])}
        camp = [e for e in camp if e["id"] not in camp_ids]
        if camp:
            ckids = []
            for e in camp:
                s = _row_status(e)
                status_tally[s] = status_tally.get(s, 0) + 1
                i = reserve()
                idx2eid[i] = e["id"]
                ckids.append(sac.TreeItem(
                    e["question"][:60] or e["id"], icon="smart_toy",
                    description=s, tooltip=e["id"]))
            kids.append(sac.TreeItem(
                f"Autonomous campaign ({len(camp)})", icon="group",
                description=f"{len(camp)} experiment(s)",
                children=ckids))
        tally = " · ".join(f"{n_} {s}" for s, n_ in
                           sorted(status_tally.items(),
                                  key=lambda kv: -kv[1]))
        desc = gate + (f" · {tally}" if tally
                       else " · no experiments yet")
        i = reserve()
        idx2program[i] = {"name": prog.get("name", prog["slug"]),
                          "doc": prog.get("program") or {},
                          "mode": prog.get("mode", "autonomous"),
                          "gate": gate,
                          "attachments": prog.get("attachments", []),
                          "rows_by_eid": rows_by_eid}
        items.append(sac.TreeItem(
            prog.get("name", prog["slug"]), icon="activity",
            description=desc, tooltip=gate, children=kids or None))

    for tree, alloc, leaf_stats, rollup, _rec in trees:
        eid_by_pid = {}
        for e in (all_rows or []):
            p = (e["payload"].get("agent") or {}).get("problem_id")
            if p:
                eid_by_pid[p] = e["id"]
        # a fully-retired tree (every leaf archived) leaves the workspace;
        # its experiments remain in the Archived section
        if tree.leaves() and all(
                _leaf_pid(tree.root.id, lf.id) not in eid_by_pid
                for lf in tree.leaves()):
            continue
        rstatus = rollup.get(tree.root.id, "open")
        total = sum(alloc.get(l.id, 0) for l in tree.leaves())
        root_name = tree.root.objective

        def chain(nid):
            """parent chain of objectives, root first."""
            out, cur = [], nid
            while cur:
                out.append(tree.nodes[cur].objective)
                cur = tree.nodes[cur].parent
            return " \u25b8 ".join(reversed(out))

        def build(nid) -> sac.TreeItem:
            # reserve the index FIRST: widget positions are pre-order
            # (parent before children), so must our mapping be
            i = reserve()
            n = tree.nodes[nid]
            kids = tree.children(nid)
            st_word = rollup.get(nid, n.status)
            icon = {"achieved": "check-circle", "partial": "hourglass",
                    "failed": "x-circle"}.get(st_word, "circle")
            lineage = chain(nid)
            gate = (f" \u00b7 gate {n.metric} "
                    f"{'\u2264' if n.direction == 'min' else '\u2265'}"
                    f"{n.gate:g}") if n.metric else ""
            children = [build(k.id) for k in kids]
            if kids:
                sub_leaves = tree.subtree_leaves(nid)
                sub = sum(alloc.get(l.id, 0) for l in sub_leaves)
                # a group is as clickable as its subtree: if every leaf
                # beneath it is archived, the group retires with them
                all_gone = all(f"{tree.root.id}-{l.id}" not in eid_by_pid
                               for l in sub_leaves)
                return sac.TreeItem(
                    n.objective, icon="diagram-2",
                    description=f"{st_word} \u00b7 budget {sub} runs"
                                + (" \u00b7 archived" if all_gone else ""),
                    tooltip=f"{lineage}{gate}", children=children,
                    disabled=all_gone)
            pid = _leaf_pid(tree.root.id, nid)
            ls = leaf_stats.get(nid, {})
            if pid in eid_by_pid:
                idx2eid[i] = eid_by_pid[pid]
            return sac.TreeItem(
                n.objective, icon="droplet",
                description=(f"{st_word} \u00b7 "
                             f"{ls.get('runs', 0)}/"
                             f"{alloc.get(nid, 0)} runs"),
                tooltip=(f"{lineage}{gate} \u00b7 problem statement: "
                         f"{ls.get('statement') or n.objective}"),
                disabled=pid not in eid_by_pid)

        root_i = reserve()
        root_children = [build(k.id)
                         for k in tree.children(tree.root.id)]
        root_leaves = tree.leaves()
        root_gone = all(_leaf_pid(tree.root.id, l.id) not in eid_by_pid
                        for l in root_leaves)
        # a SINGLE-NODE tree (no sub-problems): the root itself is the
        # experiment and must be clickable, not a dead group header
        if not root_children and root_leaves:
            leaf = root_leaves[0]
            pid = f"{tree.root.id}-{leaf.id}"
            st_word = rstatus
            ls = leaf_stats.get(leaf.id, {})
            if pid in eid_by_pid:
                idx2eid[root_i] = eid_by_pid[pid]
            items.append(sac.TreeItem(
                root_name, icon="droplet",
                description=(f"{st_word} \u00b7 "
                             f"{alloc.get(leaf.id, 0)} runs"),
                tooltip=root_name,
                disabled=pid not in eid_by_pid))
        else:
            items.append(sac.TreeItem(
                root_name, icon="activity",
                description=f"{rstatus} \u00b7 budget {total} runs"
                            + (" \u00b7 archived" if root_gone else ""),
                tooltip=root_name, children=root_children,
                disabled=root_gone))

    # standalone experiments (wizard/manual, single agent runs) group
    # under one collapsible node — the workspace shows auto AND manual
    # without a flat dump at the top level
    tree_leaf_pids = {_leaf_pid(t.root.id, lf.id)
                      for t, _a, _l, _r, _rr in trees
                      for lf in t.leaves()}
    # standalone experiments grouped by who defines the problem:
    # autonomous campaigns (LLM-defined) vs guided (user-defined)
    prog_tags = set(prog_rows)
    standalone = [e for e in (all_rows or [])
                  if (e["payload"].get("agent") or {}).get("problem_id")
                  not in tree_leaf_pids
                  and (e.get("payload") or {}).get("program") not in prog_tags]
    groups = {"Autonomous campaigns": ([], "smart_toy"),
              "Guided experiments": ([], "person")}
    for e in standalone:
        ag = e["payload"].get("agent") or {}
        groups["Autonomous campaigns" if ag
               else "Guided experiments"][0].append((e, ag))
    for group_name, (entries, group_icon) in groups.items():
        if not entries:
            continue
        gi = reserve()
        kids = []
        for e, ag in entries:
            status = _row_status(e)
            i = reserve()
            idx2eid[i] = e["id"]
            kids.append(sac.TreeItem(
                e["question"][:60] or e["id"], icon=group_icon,
                description=status, tooltip=e["id"]))
        items.append(sac.TreeItem(
            f"{group_name} ({len(entries)})", icon="group",
            description=f"{len(entries)} experiment(s)",
            children=kids))

    if not program_cfg.list_programs():
        st.info("Create a program first — open **Program** above, define "
                "the objective, metric, gate and execution mode, then "
                "save. Experiments can only be launched under a program.")
        return

    picked = sac.tree(items=items, open_all=True, label="",
                      return_index=True, show_line=True)
    # sac.tree may return an int or a list of indices depending on
    # selection state — normalize before the lookup
    idx = None
    if isinstance(picked, (list, tuple)):
        idx = picked[0] if picked else None
    elif picked is not None:
        idx = picked
    if idx is not None and idx2eid.get(idx):
        st.session_state["view_experiment"] = idx2eid[idx]
        st.switch_page(PAGES_EXP)
        return
    # program node selected -> remember it and rerun so the definition
    # renders ABOVE the tree (immediately visible)
    prog_sel = idx2program.get(idx) if idx is not None else None
    if prog_sel:
        st.session_state["ws_program_sel"] = prog_sel
        st.rerun()


def _dmta_counts(recs) -> dict:
    """DMTA phase counts for a slice of provenance records. Test counts
    unique lab_run submissions (one submission = one run = one analyzed
    export); Analyze counts verdict-bearing decisions, deduplicated."""
    c = {"proposed": 0, "selected": 0, "submitted": 0, "refused": 0,
         "runs": 0, "verdicts": 0,
         "validated": 0, "confirmed": 0, "inconclusive": 0,
         "refuted": 0}
    # a hypothesis earns ONE verdict: its latest. Preliminary + orthogonal
    # confirmation events collapse into the final call
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
            c["runs"] += 1          # one submission -> one analyzed export
        elif et == "gate_decision":
            k = d.get("kind")
            if k in ("halt_refusal", "safety_refusal", "authorization",
                     "synthesis_failed") \
                    and d.get("column") != "autonomous":
                c["refused"] += 1
        elif et in ("hypothesis_validated", "hypothesis_invalidated",
                    "hypothesis_tested") and d.get("verdict"):
            cand = ((r.artifact.metadata or {}).get("candidate")
                    if r.artifact else None) or d.get("candidate")
            if cand:
                final[str(cand)] = d["verdict"]
            else:
                orphan += 1
    c["verdicts"] = len(final) + orphan
    for v in final.values():
        c[v if v != "invalidated" else "refuted"] += 1
    return c


def _dmta_chip_row(counts: dict, label: str,
                   design_note: str = "") -> None:
    """One DMTA chip row (4 full-width cells)."""
    from bionexus import ui
    design_line = (f"{counts['proposed']} proposed \u00b7 "
                   f"{counts['selected']} selected")
    if design_note:
        design_line = design_note
    cells = [
        (ui.icon("hypothesis", 15, "teal"), "Design", design_line),
        (ui.icon("gate-open", 15, "ink"), "Make",
         f"{counts['submitted']} submitted"
         + (f" \u00b7 {counts['refused']} refused"
            if counts["refused"] else "")),
        (ui.icon("instrument", 15, "progress"), "Test",
         f"{counts['runs']} run(s) analyzed"),
        (ui.icon("verdict", 15, "confirmed" if counts["confirmed"]
                 else ("resolved" if counts["verdicts"] else "provenance")),
         "Analyze", f"{counts['verdicts']} verdict(s)"),
    ]
    accent = {"Design": "teal", "Make": "ink", "Test": "teal",
              "Analyze": "confirmed" if counts["confirmed"]
              else ("resolved" if counts["verdicts"] else "provenance")}
    cols = st.columns(4)
    for col, (icon, name, line) in zip(cols, cells):
        c = ui.COLORS[accent[name]]
        col.markdown(
            f'<div style="border:1px solid {ui.COLORS["provenance"]};'
            f'border-left:3px solid {c};border-radius:6px;'
            f'background:{ui.COLORS["card"]};padding:8px 14px;'
            f'width:100%;box-sizing:border-box">'
            f'{icon} <b>{label} \u00b7 {name}</b><br>'
            f'<span style="color:{ui.COLORS["provenance"]}">{line}'
            f"</span></div>",
            unsafe_allow_html=True)




def _round_markers(recs) -> list[tuple[int, list[str]]]:
    """[(round_no, [candidates])] sorted by round, from round_start
    markers."""
    markers = [(int((r.decision or {}).get("round", 0)),
                [str(c) for c in (r.decision or {}).get("candidates") or []])
               for r in recs
               if r.event_type.value == "stage_transition"
               and (r.decision or {}).get("kind") == "round_start"]
    return sorted(markers)


def render_dmta(recs, logf) -> None:
    """The DMTA loop as structure: a cumulative chip row, and — when the
    campaign ran multiple rounds (round_start markers in provenance) —
    one chip row per round. Representation rule (docs/UX.md): ONE branch
    per sub-problem; rounds live inside the experiment page, never as
    separate branches."""
    from bionexus import ui

    # round markers with their carried candidates
    markers = _round_markers(recs)
    multi = len(markers) >= 2

    _dmta_chip_row(_dmta_counts(recs),
                   "All rounds" if multi else "DMTA")

    if multi:
        st.caption("")
        # attribute by CANDIDATE, not by timestamp windows: marker k
        # lists round k+1's tested candidates; runs and verdicts belong
        # to the round of their candidate. Robust even when selection
        # events and markers interleave
        cand2round = {}
        for rnd, cands in markers:
            for cand in cands:
                cand2round[cand] = rnd
        run2cand: dict[str, str] = {}
        verdict_by_cand: dict[str, dict] = {}
        for r in recs:
            d = r.decision or {}
            et = r.event_type.value
            cand = ((r.artifact.metadata or {}).get("candidate")
                    if r.artifact else None) or d.get("candidate")
            if et == "hypothesis_tested" and d.get("run_id") and cand:
                run2cand[d["run_id"]] = str(cand)
            if et.startswith("hypothesis_") and d.get("verdict") and cand:
                verdict_by_cand[str(cand)] = d
        all_c = _dmta_counts(recs)
        rows = []
        for rnd, cands in markers:
            cand_set = set(cands)
            runs = sum(1 for rid, cand in run2cand.items()
                       if cand in cand_set)
            v_conf = sum(1 for cand in cand_set
                         if verdict_by_cand.get(cand, {}).get("verdict")
                         == "confirmed")
            v_ref = sum(1 for cand in cand_set
                        if verdict_by_cand.get(cand, {}).get("verdict")
                        in ("refuted", "invalidated"))
            v_incon = sum(1 for cand in cand_set
                          if verdict_by_cand.get(cand, {}).get("verdict")
                          == "inconclusive")
            v_val = sum(1 for cand in cand_set
                        if verdict_by_cand.get(cand, {}).get("verdict")
                        == "validated")
            design = (f"{all_c['proposed']} proposed \u00b7 "
                      f"{all_c['selected']} selected"
                      if rnd == 1 else
                      f"{len(cands)} carried from previous round: "
                      + ", ".join(sorted(cand_set)))
            analyze = (f"{v_conf} confirmed \u00b7 {v_val} validated"
                       if v_conf or v_val else
                       (f"{v_incon} inconclusive" if v_incon else
                        (f"{v_ref} refuted" if v_ref else "pending")))
            rows.append({"round": rnd, "design": design,
                         "make": f"{runs} submitted",
                         "test": f"{runs} run(s) analyzed",
                         "analyze": analyze})
        st.dataframe(rows, hide_index=True)
        st.caption(f"{ui.icon('history', 12, 'provenance')} the Analyze "
                   "of each round feeds the Design of the next \u2014 "
                   "that loop closure is the DMTA cycle",
                   unsafe_allow_html=True)

    all_c = _dmta_counts(recs)
    if all_c["verdicts"]:
        st.caption(f"{all_c['validated']} validated \u00b7 "
                   f"{all_c['confirmed']} confirmed \u00b7 "
                   f"{all_c['inconclusive']} inconclusive \u00b7 "
                   f"{all_c['refuted']} refuted")


def lineage_caption(problem_id: str | None) -> str:
    """Breadcrumb for a tree leaf: root \u25b8 ... \u25b8 this node, plus
    its gate. Sourced from provenance (the serialized tree), so it is
    correct for old and new runs alike. Empty for non-tree branches."""
    from pathlib import Path as _Path
    if not problem_id or not _Path("bionexus.db").exists():
        return ""
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.problem_tree import ProblemTree
    full = SqliteProvenanceStore("bionexus.db")
    for br in full.branches():
        if not br.startswith("problem/") or br.count("/") != 1:
            continue
        for r in full.branch_records(br):
            env = (r.decision or {}).get("environment") or {}
            if env.get("kind") != "problem-tree":
                continue
            try:
                tree = ProblemTree.model_validate(env["tree"])
            except Exception:
                continue
            prefix = tree.root.id + "-"
            if problem_id.startswith(prefix):
                nid = problem_id[len(prefix):]
                if nid not in tree.nodes:
                    return ""
                chain, cur = [], nid
                while cur:
                    chain.append(tree.nodes[cur].objective)
                    cur = tree.nodes[cur].parent
                n = tree.nodes[nid]
                gate = (f" \u00b7 gate {n.metric} "
                        f"{'\u2264' if n.direction == 'min' else '\u2265'}"
                        f"{n.gate:g}") if n.metric else ""
                return " \u25b8 ".join(reversed(chain)) + gate
    return ""
