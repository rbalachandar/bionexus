"""Program (TPP) verdicts and the workspace read-model."""
from __future__ import annotations

from pathlib import Path

from bionexus.views.counts import round_markers, series_view, verdict_tally
from bionexus.views.ids import leaf_pid, resolve_problem, row_status
from bionexus.views.trees import problem_trees
from bionexus.views import ids as _ids


def program_verdict(trees: list) -> dict:
    """Consolidated outcome for a program objective, rolled up
    deterministically from its problem tree(s). Honest about
    uncertainty: unresolved leaves downgrade the claim, and the gate is
    only called 'met' when a leaf actually measured the gate metric."""
    if not trees:
        return {"status": "no-tree",
                "reason": "no problem tree — launch with decompose on, "
                          "or link a campaign",
                "leaves": 0, "resolved": 0, "gate": None}
    leaves_n = 0
    resolved = 0
    root_status = "achieved"
    gates: list[dict] = []
    for t in trees:
        parents = {n["parent"] for n in t["nodes"] if n["parent"]}
        leaves = [n for n in t["nodes"] if n["id"] not in parents]
        leaves_n += len(leaves)
        resolved += sum(1 for l in leaves
                        if l["status"] in ("achieved", "partial", "failed",
                                           "inconclusive"))
        rs = t["rollup"].get(t["root_id"], "")
        order = {"achieved": 0, "inconclusive": 1, "partial": 2, "failed": 3}
        if order.get(rs, 2) > order.get(root_status, 2):
            root_status = rs
        # gate check: a leaf measuring the tree-root metric
        root_metric = next((n.get("metric") for n in t["nodes"]
                            if n["id"] == t["root_id"]), None)
        if root_metric:
            gleaf = next((l for l in leaves if l.get("metric") == root_metric),
                         None)
            if gleaf:
                gmap = {"achieved": "met", "partial": "near",
                        "failed": "missed"}
                gates.append({"status": gmap.get(gleaf["status"],
                                                 "unexercised"),
                              "leaf": gleaf["objective"],
                              "metric": root_metric})
    if resolved == 0:
        status, reason = "inconclusive", \
            "no sub-problem campaigns have resolved yet"
    elif root_status == "achieved" and resolved == leaves_n:
        status, reason = "supported", \
            f"all {leaves_n} sub-problem campaigns resolved positive"
    elif root_status == "failed":
        status, reason = "refuted", \
            "the decisive sub-problems failed — the objective as posed " \
            "does not hold on current evidence"
    elif root_status == "inconclusive":
        status, reason = "inconclusive", \
            "the decisive sub-problems abstained — borderline evidence " \
            "neither supports nor refutes the objective; higher-power " \
            "experiments are needed, not a verdict"
    else:
        status, reason = "partial", \
            f"{resolved} of {leaves_n} sub-problem campaigns resolved, " \
            "with mixed or pending evidence"
    if 0 < resolved < leaves_n:
        reason += f" — {leaves_n - resolved} unresolved"
    root_metric = next((n.get("metric") for t in trees for n in t["nodes"]
                        if n["id"] == t["root_id"] and n.get("metric")), None)
    evidence_distance = None
    if root_metric:
        from bionexus.proxy import evidence_line
        evidence_distance = evidence_line(root_metric)
    return {"status": status, "reason": reason, "leaves": leaves_n,
            "resolved": resolved, "gate": gates[0] if gates else None,
            "evidence_distance": evidence_distance}


def program_policy(p: dict, doc: dict) -> dict:
    """Termination policy for the program's autonomous loop (brief ->
    actions -> evidence -> brief). The orchestrator pauses — escalates
    to a human — when the objective is decided, the gate is called, or
    the evidence/cycle budget is spent. Manual redraft overrides."""
    pol = {**{"max_runs": 200, "max_cycles": 5},
           **(doc.get("policy") or {})}
    v = p.get("verdict") or {}
    runs = sum((l or {}).get("runs", 0) for l in p.get("links", [])
               if not l.get("campaign_root"))
    for t in p.get("trees") or []:
        runs += sum(ls.get("runs", 0)
                    for ls in (t.get("leaf_stats") or {}).values())
    cycles = ((doc.get("brief") or {}).get("cycle")) or 0
    reasons = []
    if (doc.get("brief") or {}).get("conclusion"):
        reasons.append("brief issued a conclusion — human sign-off "
                       "required")
    if v.get("status") in ("supported", "refuted"):
        reasons.append(f"objective {v['status']} — decided, not pending")
    g = v.get("gate")
    if g and g.get("status") in ("met", "missed"):
        reasons.append(f"gate {g.get('metric')} {g.get('status')}")
    if runs >= pol["max_runs"]:
        reasons.append(f"evidence budget reached "
                       f"({runs} / {pol['max_runs']} runs)")
    if cycles >= pol["max_cycles"]:
        reasons.append(f"loop cycle budget reached "
                       f"({cycles} / {pol['max_cycles']})")
    return {"status": "escalated" if reasons else "active",
            "reason": "; ".join(reasons),
            "runs": runs, "cycles": cycles, "limits": pol}


def labselect_fence(labs_entries) -> list[dict]:
    """Program fence -> human names (delegates to labselect.fence_info;
    never raises — a broken catalog must not kill the workspace)."""
    try:
        from bionexus.labselect import fence_info
        return fence_info(labs_entries)
    except Exception:
        return []


def workspace(wizard_store,
              provenance_db: str | Path | None = None,
              include_archived: bool = False) -> dict:
    provenance_db = provenance_db or _ids.PROVENANCE_DB
    """Workspace read-model: programs (with links + status tallies),
    campaign groups for unlinked rows, archived expander list."""
    from bionexus import program as program_cfg
    rows = wizard_store.ongoing() + wizard_store.finished(500)
    archived = [e for e in rows if (e["payload"] or {}).get("archived")]
    live = [e for e in rows if not (e["payload"] or {}).get("archived")]
    rows_by_eid = {e["id"]: e for e in live}
    trees, leaf_pids = problem_trees(provenance_db)

    # retired-tree filter (as the workbench had it): a tree whose every
    # leaf lost its registry row leaves the workspace — provenance and
    # the Archived section still hold the history
    live_leaf_pids = set()
    for e in live:
        pid = (e["payload"].get("agent") or {}).get("problem_id")
        if pid:
            live_leaf_pids.add(pid)
    def _leaves(t):
        parents = {n["parent"] for n in t["nodes"] if n["parent"]}
        return [n for n in t["nodes"] if n["id"] not in parents]
    trees = [t for t in trees if not _leaves(t) or any(
        leaf_pid(t["root_id"], leaf["id"]) in live_leaf_pids
        for leaf in _leaves(t))]

    # map leaf -> experiment eid so the FE can link sub-problems
    pid_to_eid = {}
    for e in live:
        pid = (e["payload"].get("agent") or {}).get("problem_id")
        if pid:
            pid_to_eid[pid] = e["id"]
    for t in trees:
        for leaf in _leaves(t):
            for pid in [f'{t["root_id"]}-{leaf["id"]}',
                        f'{t["root_id"]}-{leaf["id"]}-{leaf["id"]}']:
                if pid in pid_to_eid:
                    t.setdefault("leaf_stats", {}).setdefault(
                        leaf["id"], {})["eid"] = pid_to_eid[pid]

    programs = []
    linked_eids: set = set()
    prog_roots: dict[str, set] = {}
    # per-link execution stats: branch resolution mirrors the SSE watcher
    # (campaign announcement -> payload -> program relation -> agent log),
    # record reads are cached per branch
    prov = None
    if Path(provenance_db).exists():
        try:
            from bionexus.adapters.store.sqlite import get_store
            prov = get_store(str(provenance_db))
        except Exception:
            prov = None
    try:
        from bionexus.autoloop import announced_branches
        branch_map = announced_branches()
    except Exception:
        branch_map = {}
    stats_cache: dict[str, dict] = {}
    recs_by_branch: dict[str, list] = {}

    def link_stats(eid, e, l) -> dict:
        if eid in stats_cache:
            return stats_cache[eid]
        out = {"runs": 0, "rounds_done": 0, "rounds_planned": None,
               "verdicts": {"confirmed": 0, "preliminary": 0,
                            "refuted": 0, "inconclusive": 0},
               "candidates": [], "branch": None}
        try:
            spec = wizard_store.get_campaign_spec(eid)
            out["rounds_planned"] = (spec or {}).get("rounds")
        except Exception:
            pass
        payload = (e or {}).get("payload") or {}
        ag = payload.get("agent") or {}
        pid = branch_map.get(eid) or ag.get("problem_id") \
            or l.get("campaign_root")
        if not pid and ag.get("log") and Path(ag["log"]).is_file():
            pid = resolve_problem({}, Path(ag["log"]))
        if prov is not None and pid:
            key = f"problem/{pid}"
            if key not in stats_cache:
                try:
                    recs = prov.branch_records(key)
                except Exception:
                    recs = []
                recs_by_branch[key] = recs
                cands: list[str] = []
                for _n, cs in round_markers(recs):
                    for c in cs:
                        if str(c) not in cands:
                            cands.append(str(c))
                stats_cache[key] = {
                    "runs": sum(1 for r in recs
                                if r.event_type.value == "lab_run"
                                and (r.decision or {}).get("run_id")),
                    "rounds_done": len(round_markers(recs)),
                    "verdicts": verdict_tally(recs),
                    "series": series_view(recs),
                    "candidates": cands,
                    "branch": pid,
                }
            out = {**out, **stats_cache[key]}
        stats_cache[eid] = out
        return out

    for p in program_cfg.list_programs():
        links = program_cfg.links_for(p["slug"])
        # campaign-root links nest trees under the program — kept out of
        # atts (roots are containers, not experiments) but needed for
        # tree linkage
        prog_roots[p["slug"]] = {
            l["campaign_root"] for l in links
            if l["role"] == "campaign" and l.get("campaign_root")}
        atts = []
        tally: dict[str, int] = {}
        for l in links:
            linked_eids.add(l["eid"])
            if l["role"] != "leaf":
                continue               # campaign roots are containers
            e = rows_by_eid.get(l["eid"])
            st = row_status(e) if e else (l.get("status") or "archived")
            tally[st] = tally.get(st, 0) + 1
            atts.append({"eid": l["eid"], "role": l["role"],
                         "campaign_root": l["campaign_root"],
                         "question": l["question"] or
                         (e or {}).get("question"),
                         "status": st,
                         "live": e is not None,
                         **link_stats(l["eid"], e, l)})
        doc = p.get("program") or {}
        # per-program taste: accept-rate deltas over this program's own
        # portfolio decisions (advisory read-only)
        try:
            from bionexus.taste import _features, fold_taste
            feats_all: dict[str, dict] = {}
            decisions_all: list[dict] = []
            for a in atts:
                recs = recs_by_branch.get(f"problem/{a.get('branch')}")
                if not recs:
                    continue
                f, d = _features(recs)
                feats_all.update(f)
                decisions_all.extend(d)
            taste = fold_taste(feats_all, decisions_all)
        except Exception:
            taste = {"n": 0, "accepted": 0, "overall_rate": 0.0,
                     "by_feature": {}, "families": {}, "amendments": []}
        programs.append({
            "slug": p["slug"], "name": p["name"],
            "pid": doc.get("program_id", p["slug"]),
            "objective": doc.get("objective"),
            "gate_summary": p.get("gate_summary"),
            "modality": doc.get("modality"),
            "mode": doc.get("mode", "autonomous"),
            "fence": labselect_fence(doc.get("labs")),
            "links": atts,
            "tally": tally,
            "taste": taste,
            # program doc snapshot — used later for brief/policy; carrying
            # it on the view dict prevents stale-doc leakage across the
            # loop iterations (the brief shown on the wrong program)
            "_doc": doc})

    # trees not linked to any program render at top level
    linked_roots = {r for roots in prog_roots.values() for r in roots}
    for t in trees:
        t["linked_program"] = next(
            (slug for slug, roots in prog_roots.items()
             if t["root_id"] in roots), None)
        t["is_linked"] = bool(t["linked_program"]) or \
            t["root_id"] in linked_roots

    # programs whose launch decomposed render their problem tree(s) inside
    # the card (sub-problems as sub-trees, leaves as experiment rows);
    # multiple decomposed launches -> multiple trees
    for p in programs:
        roots = {a["campaign_root"] for a in p["links"]
                 if a.get("campaign_root")}
        p["trees"] = [t for t in trees
                      if t["root_id"] in roots
                      or t.get("linked_program") == p["slug"]]
        p["tree"] = p["trees"][0] if p["trees"] else None
        p["verdict"] = program_verdict(p["trees"])
        pdoc = p.pop("_doc", {})
        p["policy"] = program_policy(p, pdoc)
        br = pdoc.get("brief")
        if br and br.get("launched"):
            # live status for each launched next-action campaign
            br = {**br, "launched_status": {
                i: (row_status(rows_by_eid[e]) if e in rows_by_eid
                    else "running")
                for i, e in br["launched"].items()}}
        p["brief"] = br

    standalone = [e for e in live
                  if (e["payload"].get("agent") or {}).get("problem_id")
                  not in leaf_pids and e["id"] not in linked_eids]
    groups = {"autonomous": [], "guided": []}
    for e in standalone:
        groups["autonomous" if (e["payload"].get("agent") or {})
               else "guided"].append(
            {"eid": e["id"], "question": e["question"],
             "status": row_status(e),
             **link_stats(e["id"], e, {})})
    return {"programs": programs, "trees": trees,
            "experiments_total": len(live),
            "groups": {k: v for k, v in groups.items() if v},
            "archived": [{"eid": e["id"], "question": e["question"]}
                         for e in archived] if include_archived else []}
