"""Guided wizard sessions (P2.3): the 6-step flow as a stateless API.

State lives in the wizard_sessions table (one JSON doc per session);
each step is one endpoint call. Provenance is recorded on the
experiment's wizard branch via wizard_chain.record_wizard_event.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from bionexus.paths import DATA_DIR
from bionexus.wizard_store import WizardStore

UPLOAD_DIR = DATA_DIR / "wizard-uploads"


def ensure_tables() -> None:
    ws = WizardStore()
    ws._conn.execute("""
        CREATE TABLE IF NOT EXISTS wizard_sessions (
            id TEXT PRIMARY KEY,
            eid TEXT,
            step INTEGER NOT NULL,
            doc TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )""")
    ws._conn.commit()


def _ws() -> WizardStore:
    return WizardStore()


def create_session(question: str, target: str, claim: str) -> dict:
    """Step 1: define the problem; creates the registry experiment too."""
    from bionexus.experiment import ClaimType
    if claim not in {c.value for c in ClaimType}:
        claim = ClaimType.causal_modification.value
    ensure_tables()
    ws = _ws()
    eid = ws.create(question, claim, target)
    sid = f"wsn-{uuid.uuid4().hex[:8]}"
    doc = {"question": question, "target": target, "claim": claim,
           "eid": eid, "controls": [], "selected": []}
    now = time.time()
    ws._conn.execute(
        "INSERT INTO wizard_sessions VALUES (?,?,?,?,?,?)",
        (sid, eid, 2, json.dumps(doc), now, now))
    ws._conn.commit()
    ws.set_status(eid, "designing") if hasattr(ws, "set_status") else None
    return {"sid": sid, "eid": eid, "step": 2}


def _load(sid: str) -> tuple[dict, dict]:
    row = _ws()._conn.execute(
        "SELECT eid, step, doc FROM wizard_sessions WHERE id=?",
        (sid,)).fetchone()
    if not row:
        raise KeyError(f"wizard session {sid} not found")
    return json.loads(row[2]), {"step": row[1]}


def _save(sid: str, eid: str, step: int, doc: dict) -> None:
    ws = _ws()
    ws._conn.execute(
        "UPDATE wizard_sessions SET eid=?, step=?, doc=?, updated_at=? "
        "WHERE id=?", (eid, step, json.dumps(doc, default=str), time.time(),
                       sid))
    ws._conn.commit()


def design(sid: str, site: str | None, half_life: int, edited_frac: bool,
           mimetic: bool, controls: list[str], mechanism: str = "",
           refutation: str = "", citation: str = "") -> dict:
    """Step 2: build the ExperimentDefinition, run the readiness review,
    verify the citation, record experiment_defined provenance."""
    from bionexus.experiment import (BiologicalSystem, ClaimType,
                                          DeliveryConditions,
                                          ExperimentDefinition,
                                          Intervention, ReadoutSpec)
    from bionexus.readiness import review_experiment
    doc, _ = _load(sid)
    eid = doc["eid"]
    claim = doc.get("claim") or "causal_modification"
    exp = ExperimentDefinition(
        scientific_question=doc.get("question", "user experiment"),
        claim_type=claim,
        intervention=Intervention(kind="user_defined",
                                  target=doc.get("target", "user-target"),
                                  site=site or None),
        system=BiologicalSystem(cell_line="user",
                                target_half_life_min=half_life),
        delivery=DeliveryConditions(method="user",
                                    per_cell_loading_measured=True),
        readout=ReadoutSpec(assay="user",
                            measures_edited_fraction=edited_frac,
                            distinguishes_modified_from_mimetic=mimetic),
        controls=controls)
    review = review_experiment(exp)
    extras: dict[str, Any] = {"mechanism": mechanism,
                              "refutation_condition": refutation,
                              "citation": citation}
    if citation:
        from bionexus import citations
        res = citations.verify(citation)
        extras["citation_status"] = res["status"]
        extras["citation_detail"] = res["detail"]
    doc.update({"site": site, "half_life": half_life,
                "edited_frac": edited_frac, "mimetic": mimetic,
                "controls": controls, "exp_def": exp.model_dump(mode="json"),
                "readiness": {"verdict": review.verdict.value,
                              "findings": [f.model_dump(mode="json")
                                           for f in review.findings]},
                **extras})
    _save(sid, eid, 3, doc)
    from bionexus.wizard_chain import record_wizard_event
    from bionexus.core.contracts import EventType
    record_wizard_event(eid, EventType.experiment_defined, {
        "statement": exp.scientific_question,
        "claim_type": exp.claim_type.value,
        "target": exp.intervention.target,
        "controls": exp.controls,
        **extras})
    return {"step": 3, "readiness": doc["readiness"]}


def execute(sid: str) -> dict:
    """Step 3 -> 4: readiness passed; mark executing."""
    doc, _ = _load(sid)
    if doc.get("readiness", {}).get("verdict") == "blocked":
        raise ValueError("readiness blocked — redesign first")
    _save(sid, doc["eid"], 4, doc)
    _ws().set_status(doc["eid"], "executing")
    return {"step": 4}


def upload(sid: str, filename: str, content: bytes) -> dict:
    """Step 5: store the instrument export and read it."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    doc, _ = _load(sid)
    path = UPLOAD_DIR / f"{sid}-{filename}"
    path.write_bytes(content)
    from bionexus.labread import read_plate
    r = read_plate(path)
    doc["plate"] = {"path": str(path), "format": r.format,
                    "n_wells": len(r.records), "z_prime": r.z_prime,
                    "samples": list(r.analysis["compounds"]),
                    "compounds": {c: {"ic50_um": dd.get("ic50_um"),
                                      "ic50_ci": dd.get("ic50_ci"),
                                      "n_points": dd.get("n_points"),
                                      "fit_quality": dd.get("fit_quality", "")}
                                  for c, dd in
                                  r.analysis["compounds"].items()}}
    _save(sid, doc["eid"], 6, doc)
    from bionexus.core.contracts import EventType
    from bionexus.wizard_chain import record_wizard_event
    record_wizard_event(doc["eid"], EventType.evaluation, {
        "artifact": "uploaded instrument export", "format": r.format,
        "n_wells": len(r.records), "z_prime": r.z_prime,
        "fits": {c: dd.get("ic50_um")
                 for c, dd in r.analysis["compounds"].items()}})
    return {"step": 6, "plate": {k: v for k, v in doc["plate"].items()
                                 if k != "path"}}


def analyze(sid: str, selected: list[str]) -> dict:
    """Step 6: record the hit selection as the session verdict."""
    doc, _ = _load(sid)
    doc["selected"] = selected
    _save(sid, doc["eid"], 6, doc)
    _ws().set_status(doc["eid"], "completed")
    from bionexus.core.contracts import EventType
    from bionexus.wizard_chain import record_wizard_event
    record_wizard_event(doc["eid"], EventType.gate_decision, {
        "kind": "wizard_verdict", "hits": selected,
        "plate": doc.get("plate", {}).get("samples")})
    return {"step": 6, "selected": selected, "done": True}


def get_session(sid: str) -> dict:
    doc, meta = _load(sid)
    safe = {k: v for k, v in doc.items() if k != "plate"}
    safe["plate"] = {k: v for k, v in (doc.get("plate") or {}).items()
                     if k != "path"}
    return {"sid": sid, "eid": doc["eid"], "step": meta["step"], **safe}
