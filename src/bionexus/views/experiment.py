"""Experiment detail: one experiment's full read-model."""
from __future__ import annotations

from pathlib import Path

from bionexus.views.counts import dmta_counts, series_view
from bionexus.views.ids import resolve_problem, row_status
from bionexus.views.pipeline import _rounds_with_verdicts, _sandbox_summary, pipeline_cards
from bionexus.views import ids as _ids


# --------------------------------------------- experiment/workspace detail
def experiment_detail(eid: str, wizard_store,
          provenance_db: str | Path | None = None) -> dict | None:
    provenance_db = provenance_db or _ids.PROVENANCE_DB
    """Full experiment read-model: registry row + campaign spec + program
    relation + provenance merge. Precedence: provenance problem_defined
    overrides campaign_specs for objective/constraints; the spec always
    supplies k/rounds/autonomy/candidate policy."""
    row = wizard_store.get(eid)
    if not row:
        return None
    payload = row["payload"] or {}
    ag = payload.get("agent") or {}
    spec = wizard_store.get_campaign_spec(eid)
    logf = Path(ag["log"]) if ag.get("log") else None
    problem_id = ag.get("problem_id")
    if logf is not None:
        problem_id = resolve_problem(ag, logf) or problem_id
    # relational fallback: a campaign root link names the branch even
    # when the registry row carries no log/payload problem id
    if not problem_id:
        from bionexus import program as program_cfg
        for p in program_cfg.list_programs():
            for l in program_cfg.links_for(p["slug"]):
                if l["eid"] == eid and l.get("campaign_root"):
                    problem_id = l["campaign_root"]
                    break
            if problem_id:
                break

    recs = []
    branch = f"problem/{problem_id}" if problem_id else None
    if branch and Path(provenance_db).exists():
        from bionexus.adapters.store.sqlite import get_store
        try:
            recs = get_store(str(provenance_db)) \
                .branch_records(branch)
        except Exception:
            recs = []
    pdef = next((r.decision for r in recs
                 if r.event_type.value == "problem_defined"), None)

    # graveyard: hypotheses the portfolio filter rejected, with reasons —
    # elimination is evidence too, and the scientist should audit it
    id2cand: dict[str, str] = {}
    for r in recs:
        if r.event_type.value == "hypothesis_proposed" and r.artifact:
            cand = (r.artifact.metadata or {}).get("candidate")
            if cand:
                id2cand[r.artifact.artifact_id] = str(cand)
    eliminated: dict[str, dict] = {}
    for r in recs:
        if r.event_type.value != "hypotheses_filtered":
            continue
        for dec in (r.decision or {}).get("decisions", []):
            if dec.get("selected"):
                continue
            cand = id2cand.get(dec.get("hypothesis_id")) \
                or dec.get("hypothesis_id")
            eliminated[cand] = {
                "candidate": cand,
                "reason": dec.get("reason") or "not selected",
                "score": dec.get("score")}
    eliminated = list(eliminated.values())

    objective = (pdef or {}).get("objective") \
        or (spec or {}).get("objective") \
        or row.get("question")
    constraints = (pdef or {}).get("constraints") \
        if pdef and pdef.get("constraints") else \
        ((spec or {}).get("constraints") or [])

    # program relation: which program links this experiment
    program = None
    try:
        from bionexus import program as program_cfg
        _slug = (spec or {}).get("program_slug")
        if not _slug:
            for p in program_cfg.list_programs():
                if any(a.get("eid") == eid
                       for a in p.get("attachments", [])):
                    _slug = p["slug"]
                    break
        if _slug:
            _prow = next((p for p in program_cfg.list_programs()
                          if p["slug"] == _slug), None)
            if _prow:
                _pd = _prow.get("program") or {}
                program = {
                    "slug": _slug, "name": _prow["name"],
                    "gate": {"metric": _pd.get("metric"),
                             "direction": _pd.get("direction"),
                             "value": _pd.get("gate_value"),
                             "unit": _pd.get("unit"),
                             "symbol": program_cfg.gate_symbol(_pd)},
                    "modality": _pd.get("modality"),
                    "mode": _pd.get("mode")}
    except Exception:
        program = None

    cards = pipeline_cards(recs) if recs else []
    return {
        "id": eid,
        "question": row.get("question"),
        "status": row_status(row),
        "registry_status": row.get("status"),
        "updated_at": row.get("updated_at"),
        "agent": {"autonomy": ag.get("autonomy", "act"),
                  "problem_id": problem_id,
                  "log_path": ag.get("log")},
        "branch": branch,
        "record_count": len(recs),
        "series": series_view(recs),
        "program": program,
        "spec": {"objective": (spec or {}).get("objective"),
                 "program_slug": (spec or {}).get("program_slug"),
                 "k": (spec or {}).get("k"),
                 "rounds": (spec or {}).get("rounds"),
                 "autonomy": (spec or {}).get("autonomy"),
                 "hypothesis_source": (spec or {}).get("hypothesis_source"),
                 "n_candidates": (spec or {}).get("n_candidates"),
                 "modality": (spec or {}).get("modality"),
                 "constraints": (spec or {}).get("constraints") or []}
        if spec else None,
        "objective": objective,
        "constraints": constraints or [],
        "success_metric": (pdef or {}).get("success_metric")
        or (spec or {}).get("success_metric"),
        "counts": dmta_counts(recs),
        "rounds": _rounds_with_verdicts(recs),
        "sandbox": _sandbox_summary(recs),
        "cards": cards,
        "eliminated": eliminated,
    }
