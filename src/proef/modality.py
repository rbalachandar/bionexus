"""Modality packs — how the DMTA flow specializes per therapeutic
modality. The framework is modality-agnostic; a pack is the thin layer
that words the flow and supplies modality-specific safety/assay adapters.

A pack: {production verb (Make), safety rule names (gate), test assays
(Test), notes}. Registering a new modality = one entry here plus real
adapters — not framework changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModalityPack:
    name: str
    production_action: str            # Make wording (virtual adapter)
    test_assays: tuple[str, ...]      # the modality's readouts
    safety_rule_names: tuple[str, ...] = field(
        default=("durc_screen", "sequence_screen", "toxicophores"))
    notes: str = ""


PACKS: dict[str, ModalityPack] = {
    "small molecule": ModalityPack(
        name="small molecule",
        production_action="synthesized",
        test_assays=("binding dose-response", "counterscreen"),
        safety_rule_names=("toxicophores", "durc_screen"),
        notes="classic chem DMTA; structural alerts on SMILES"),
    "biologic": ModalityPack(
        name="biologic",
        production_action="expressed and purified",
        test_assays=("binding dose-response", "immunogenicity",
                     "aggregation", "thermal stability"),
        safety_rule_names=("sequence_screen", "durc_screen"),
        notes="Design = sequences + structure models; Make = "
              "bioprocessing batches; immunogenicity/aggregation need "
              "real-assay adapters (virtual lab runs binding only)"),
    "cell therapy": ModalityPack(
        name="cell therapy",
        production_action="engineered and expanded",
        test_assays=("potency", "sterility", "phenotype stability"),
        safety_rule_names=("sequence_screen", "durc_screen"),
        notes="slowest Make of any modality — Design-phase pressure is "
              "highest (get the construct right before committing)"),
    "mRNA": ModalityPack(
        name="mRNA",
        production_action="transcribed and encapsulated",
        test_assays=("expression", "stability", "immunogenicity"),
        safety_rule_names=("sequence_screen", "durc_screen")),
"material": ModalityPack(
        name="material",
        production_action="produced",
        test_assays=("property sweep",),
        safety_rule_names=("durc_screen",),
        notes="Analyze reads any registered metric (tensile strength, "
              "conductivity, heat resistance) against the program gate; "
              "sweep simulator + analysis adapter shipped "
              "(assays/simulate.simulate_property_sweep, "
              "assays.properties.read_property_sweep)"),
    "agrochemical": ModalityPack(
        name="agrochemical",
        production_action="synthesized",
        test_assays=("organism dose-response", "phytotoxicity"),
        safety_rule_names=("toxicophores", "durc_screen"),
        notes="same chemical DMTA; Test targets organisms, not humans — "
              "the standard dose-response engine (SimulatorLab, Hill "
              "fits, CIs) applies unchanged")
}


def get_pack(modality: str) -> ModalityPack | None:
    """Case- and whitespace-tolerant lookup (mRNA pack included)."""
    m = (modality or "").strip()
    if not m:
        return None
    return PACKS.get(m) or next(
        (p for k, p in PACKS.items() if k.lower() == m.lower()), None)
