"""Device cards — structured capability descriptors + operator knowledge.

The machine-readable half of what an MHS-style driver reference file gives
an agent: what a device measures, what can be adjusted, and which safety
limits are enforced — plus natural-language tags captured from the operator
(the things that are NOT in any manual: "arm hits the shelf if rotated
past 90°", "slot 3 reader is flaky above 30 °C").

Cards are plain pydantic; `to_agent_text()` renders the reference file an
agent reads before operating the device.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

DEVICE_DIR = Path(".data/devices")


class Measurement(BaseModel):
    quantity: str                    # "temperature", "absorbance", "rfu"
    unit: str = ""
    range: tuple[float, float] | None = None


class Adjustment(BaseModel):
    parameter: str                   # "temperature_setpoint", "dispense_volume"
    unit: str = ""
    range: tuple[float, float] | None = None


class SafetyLimit(BaseModel):
    limit: str                       # "max 40 °C", "BSL-2 only"
    enforced_by: str = "device"      # device | gateway | operator


class DeviceCard(BaseModel):
    device_id: str
    name: str
    kind: str = "lab instrument"     # plate reader, robot, microscope, ...
    measures: list[Measurement] = Field(default_factory=list)
    adjusts: list[Adjustment] = Field(default_factory=list)
    safety_limits: list[SafetyLimit] = Field(default_factory=list)
    protocols: list[str] = Field(default_factory=list)   # assay types supported
    notes: list[str] = Field(default_factory=list)       # operator tags (NL)
    source: str = "builtin"          # builtin | operator | interview

    def merge_operator_tags(self, notes: list[str],
                            source: str = "operator") -> "DeviceCard":
        seen = set(self.notes)
        for n in notes:
            if n not in seen:
                self.notes.append(n)
                seen.add(n)
        self.source = source
        return self


def builtin_card(device_id: str, name: str, capabilities: dict[str, Any]) -> DeviceCard:
    """Adapt an adapter's legacy capabilities dict into a structured card."""
    assays = capabilities.get("assays", [])
    return DeviceCard(
        device_id=device_id, name=name,
        measures=[Measurement(quantity="absorbance/rfu", unit="OD/RFU")],
        adjusts=[Adjustment(parameter="incubation_temperature", unit="°C",
                            range=(20.0, 45.0)),
                 Adjustment(parameter="dispense_volume", unit="µL",
                            range=(5.0, 200.0))],
        safety_limits=[SafetyLimit(limit=f"BSL-{capabilities.get('bsl_max', 1)} "
                                            f"work only", enforced_by="gateway")],
        protocols=[str(a) for a in assays],
    )


def card_path(device_id: str) -> Path:
    DEVICE_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in device_id.lower() if c.isalnum() or c in "-_")
    return DEVICE_DIR / f"{safe}.json"


def save_operator_tags(device_id: str, notes: list[str],
                       base: DeviceCard | None = None) -> DeviceCard:
    card = base or DeviceCard(device_id=device_id, name=device_id)
    card.merge_operator_tags(notes)
    card_path(device_id).write_text(json.dumps(card.model_dump(), indent=1))
    return card


def load_card(device_id: str, base: DeviceCard | None = None) -> DeviceCard | None:
    p = card_path(device_id)
    if not p.exists():
        return base
    doc = json.loads(p.read_text())
    card = DeviceCard.model_validate(doc)
    if base:  # builtin facts win for structure; operator notes layer on top
        base.merge_operator_tags(card.notes, source="interview")
        return base
    return card


def to_agent_text(card: DeviceCard) -> str:
    """The reference file: everything an agent needs before operating."""
    lines = [f"DEVICE: {card.name} ({card.kind}, id {card.device_id})"]
    if card.protocols:
        lines.append(f"supports protocols: {', '.join(card.protocols)}")
    if card.measures:
        lines.append("measures: " + "; ".join(
            f"{m.quantity}" + (f" [{m.unit}]" if m.unit else "")
            + (f" range {m.range[0]}–{m.range[1]}" if m.range else "")
            for m in card.measures))
    if card.adjusts:
        lines.append("adjusts: " + "; ".join(
            f"{a.parameter}" + (f" [{a.unit}]" if a.unit else "")
            + (f" range {a.range[0]}–{a.range[1]}" if a.range else "")
            for a in card.adjusts))
    if card.safety_limits:
        lines.append("safety limits (hard, enforced): " + "; ".join(
            f"{s.limit} (via {s.enforced_by})" for s in card.safety_limits))
    if card.notes:
        lines.append("operator knowledge (natural language, not in any manual):")
        lines.extend(f"  - {n}" for n in card.notes)
    return "\n".join(lines)
