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
    "metric": "ic50",
    "unit": "µM",
    "direction": "min",            # min = lower is better
    "gate_value": 20.0,
}

GATE_LABELS = {p.value: p for p in CriterionPhase}


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
        return (f"{doc['program']} · {obj} · gate: {doc['metric']} "
                f"{gate_symbol(doc)} {float(doc.get('gate_value', 20.0)):g} "
                f"{doc.get('unit', '')}").rstrip()
    return (f"{doc['program']} · {doc['target']} · gate: {doc['gate']} "
            f"(IC50 ≤ {gate_threshold_um(doc):g} µM)")


def tpp(doc: dict | None = None):
    doc = doc or load()
    return standard_small_molecule_tpp(
        doc["program"], doc["target"], ic50_nm=doc["lead_ic50_nm"])
