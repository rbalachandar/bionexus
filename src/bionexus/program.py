"""Program profile — the TPP one level above experiments.

Hierarchy: Program (TPP) ▸ Problem (objective + constraints) ▸ Hypothesis
(success criteria) ▸ Experiment (evidence). The program is node-local state
(.data/program.json); the wizard and the launch dialog read their default
potency bar from it so the TPP actually *governs* things instead of being a
poster on the wall.
"""
from __future__ import annotations

import json
from pathlib import Path

from bionexus.tpp import CriterionPhase, standard_small_molecule_tpp

PATH = Path(".data/program.json")

DEFAULT = {
    "program": "My-Program",
    "target": "MAP4K1",
    "gate": "hit",                 # which phase this campaign is screening against
    "hit_ic50_nm": 1000.0,         # hit gate: any signal worth following
    "lead_ic50_nm": 50.0,          # lead gate: worth investing chemistry in
    # custom-problem mode: ANY metric, not just small-molecule IC50.
    # when custom is true the IC50 fields above are ignored and the gate
    # is (metric, direction, gate_value, unit) with a free-text objective.
    "custom": False,
    "objective": "",
    "modality": "",                # e.g. small molecule, biologic, cell
                                   # therapy, agrochemical, material —
                                   # free text; the flow is modality-agnostic
    "metric": "ic50",
    "unit": "µM",
    "direction": "min",            # min = lower is better
    "gate_value": 20.0,
}

GATE_LABELS = {p.value: p for p in CriterionPhase}


# ------------------------------------------------------ program registry
# Programs are first-class shared records in the provenance store: every
# user of a shared service sees the same program roots. program.json
# remains only the LOCAL pointer to the active program (wizard defaults).

def _slug(name: str) -> str:
    import re as _re
    s = _re.sub(r"[^a-zA-Z0-9]+", "-", (name or "program").lower()).strip("-")
    return s[:48] or "program"


def save_program_record(doc: dict) -> str:
    """Register/refresh a program as a shared provenance root. Returns
    the program branch id (programs/<slug>)."""
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.core.contracts import Envelope, EventType
    from bionexus.core.interfaces import record_for, system_actor
    slug = _slug(doc.get("program"))
    branch = f"programs/{slug}"
    # relational row: the query source for the workspace
    from bionexus.wizard_store import WizardStore
    WizardStore().upsert_program(slug, doc.get("program", slug), doc)
    store = SqliteProvenanceStore("bionexus.db")
    store.append(record_for(
        Envelope(experiment_branch_id=branch),
        EventType.problem_defined, system_actor("program"),
        decision={"kind": "program_root", "program_id": slug,
                  "name": doc.get("program", slug),
                  "mode": doc.get("mode", "autonomous"),
                  "program": doc,
                  "gate_summary": gate_summary(doc)}))
    return branch


def attach_experiment(program_name: str, eid: str, problem_id: str,
                      question: str, status: str = "executing") -> str | None:
    """Attach an experiment to a program root: it becomes a leaf of the
    program's tree in the shared registry instead of a free-standing
    node. Append-only: the latest record carries the attachment list."""
    slug = _slug(program_name)
    existing = {x["slug"]: x for x in list_programs()}
    if slug not in existing:
        return None
    from bionexus.wizard_store import WizardStore
    WizardStore().link_experiment(slug, eid, role="leaf",
                                  campaign_root=problem_id or None,
                                  question=question, status=status)
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.core.contracts import Envelope, EventType
    from bionexus.core.interfaces import record_for, system_actor
    prev = existing[slug]
    attachments = [a for a in prev.get("attachments", [])
                   if a.get("eid") != eid]
    attachments.append({"eid": eid, "problem_id": problem_id,
                        "question": question[:120], "status": status,
                        "ts": __import__("time").time()})
    store = SqliteProvenanceStore("bionexus.db")
    store.append(record_for(
        Envelope(experiment_branch_id=f"programs/{slug}"),
        EventType.problem_defined, system_actor("program"),
        decision={"kind": "program_root", "program_id": slug,
                  "program": prev.get("program", {}),
                  "gate_summary": prev.get("gate_summary", ""),
                  "attachments": attachments}))
    return branch_of(slug)


def record_launch(program_name: str, root_id: str, objective: str = "") -> None:
    """Link a campaign's problem-tree root to a program (append-only).
    This single record is what nests the tree under the program in the
    workspace: Program -> Autonomous campaign -> problem tree."""
    slug = _slug(program_name)
    from bionexus.wizard_store import WizardStore
    WizardStore().link_experiment(slug, root_id, role="campaign",
                                  campaign_root=root_id,
                                  question=objective)
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.core.contracts import Envelope, EventType
    from bionexus.core.interfaces import record_for, system_actor
    SqliteProvenanceStore("bionexus.db").append(record_for(
        Envelope(experiment_branch_id=f"programs/{slug}"),
        EventType.problem_defined, system_actor("program"),
        decision={"kind": "program_launch", "program_id": slug,
                  "name": program_name, "root": root_id,
                  "objective": (objective or "")[:120]}))


def link_leaf(program_name: str, eid: str, campaign_root: str,
              question: str, status: str = "executing") -> None:
    """Register a campaign leaf under a program (relational only — the
    provenance audit trail is written by the campaign itself)."""
    slug = _slug(program_name)
    from bionexus.wizard_store import WizardStore
    WizardStore().link_experiment(slug, eid, role="leaf",
                                  campaign_root=campaign_root,
                                  question=question, status=status)


def launches_by_program() -> dict:
    """program name -> list of linked problem-tree root ids (relation)."""
    from bionexus.paths import DATA_DIR
    if not (DATA_DIR / "wizard.db").exists():
        return {}
    from bionexus.wizard_store import WizardStore
    ws = WizardStore()
    out: dict = {}
    for p in ws.db_programs():
        for l in ws.program_links(p["slug"]):
            if l["role"] == "campaign" and l["campaign_root"]:
                out.setdefault(p["name"], []).append(l["campaign_root"])
    return out


def links_for(program_name: str) -> list[dict]:
    """All program_experiments relations for a program slug."""
    from bionexus.wizard_store import WizardStore
    return WizardStore().program_links(_slug(program_name))


def branch_of(slug: str) -> str:
    return f"programs/{slug}"


def attachments_for(program_name: str) -> list[dict]:
    slug = _slug(program_name)
    for x in list_programs():
        if x["slug"] == slug:
            return x.get("attachments", [])
    return []


def list_programs() -> list[dict]:
    """Programs from the relational tables; first call migrates any
    legacy provenance-only programs into them."""
    from bionexus.wizard_store import WizardStore
    ws = WizardStore()
    if ws.db_program_count() == 0 and Path("bionexus.db").exists():
        _migrate_from_provenance(ws)
    out = []
    for p in ws.db_programs():
        doc = p["doc"]
        slug = p["slug"]
        attachments = [{"eid": l["eid"], "question": l["question"],
                        "status": l["status"]}
                       for l in ws.program_links(slug)
                       if l["role"] == "leaf"]
        out.append({"branch": f"programs/{slug}", "slug": slug,
                    "name": p["name"], "program": doc,
                    "mode": doc.get("mode", "autonomous"),
                    "gate_summary": gate_summary(doc),
                    "attachments": attachments})
    return out


def _migrate_from_provenance(ws) -> None:
    """One-time: seed the relational programs table from legacy
    provenance-only program records."""
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    store = SqliteProvenanceStore("bionexus.db")
    for br in store.branches():
        if not br.startswith("programs/") or br.count("/") != 1:
            continue
        recs = store.branch_records(br)
        latest = next((r.decision or {} for r in reversed(recs)
                       if (r.decision or {}).get("kind") == "program_root"),
                      None)
        if not latest:
            continue
        slug = br.split("/", 1)[1]
        doc = latest.get("program", {})
        name = latest.get("name", latest.get("program_id", slug))
        ws.upsert_program(slug, name, doc)
        for a in latest.get("attachments", []):
            if a.get("eid"):
                ws.link_experiment(slug, a["eid"], role="leaf",
                                   campaign_root=a.get("problem_id"),
                                   question=a.get("question", ""),
                                   status=a.get("status", "executing"))


def load() -> dict:
    if PATH.exists():
        try:
            doc = {**DEFAULT, **json.loads(PATH.read_text())}
            return doc
        except Exception:
            pass
    return dict(DEFAULT)


def save(doc: dict) -> dict:
    merged = {**DEFAULT, **doc}
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(merged, indent=1))
    return merged


def is_custom(doc: dict | None = None) -> bool:
    return bool((doc or load()).get("custom"))


def gate_threshold_um(doc: dict | None = None) -> float:
    """The potency bar for the selected gate, in µM (the lab unit).
    Custom problems: the gate value in its own unit (numeric only)."""
    doc = doc or load()
    if doc.get("custom"):
        return float(doc.get("gate_value", 20.0))
    nm = doc["hit_ic50_nm"] if doc["gate"] == "hit" else doc["lead_ic50_nm"]
    return float(nm) / 1000.0


def gate_metric(doc: dict | None = None) -> str:
    return str((doc or load()).get("metric") or "ic50")


def gate_unit(doc: dict | None = None) -> str:
    return str((doc or load()).get("unit") or "µM")


def gate_direction(doc: dict | None = None) -> str:
    return str((doc or load()).get("direction") or "min")


def gate_symbol(doc: dict | None = None) -> str:
    return "≤" if gate_direction(doc) == "min" else "≥"


def gate_summary(doc: dict | None = None) -> str:
    doc = doc or load()
    if doc.get("custom"):
        obj = doc.get("objective") or doc.get("target")
        mod = f"[{doc['modality']}] " if doc.get("modality") else ""
        return (f"{doc['program']} · {mod}{obj} · gate: {doc['metric']} "
                f"{gate_symbol(doc)} {float(doc.get('gate_value', 20.0)):g} "
                f"{doc.get('unit', '')}").rstrip()
    return (f"{doc['program']} · {doc['target']} · gate: {doc['gate']} "
            f"(IC50 ≤ {gate_threshold_um(doc):g} µM)")


def tpp(doc: dict | None = None):
    doc = doc or load()
    return standard_small_molecule_tpp(
        doc["program"], doc["target"], ic50_nm=doc["lead_ic50_nm"])
