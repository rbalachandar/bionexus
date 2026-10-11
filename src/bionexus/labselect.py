"""Capability-matched lab selection inside the OPERATOR's fence (S-T5).

Division of authority — mirroring the tighten-only safety doctrine:

  * The PROGRAM CREATOR declares the pool of permitted instruments
    (consent for physical action is a human act; nobody downstream may
    add to the fence).
  * The MATCHER selects which pool member can serve the experiment's
    declared needs, deterministically, and RECORDS the rationale —
    including every refusal reason of the ones not chosen.
  * AGENTS may recommend, never re-fence.

Nothing is ever selected outside the pool, and a simulated instrument is
never silently preferred away from validated hardware: ordering is
hardware_validated -> declared order, and `simulated` is recorded on the
decision so the workbench can badge it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LabRequirement:
    """What the experiment needs — from the hypothesis/readout spec."""
    assay_types: frozenset = frozenset()
    readouts: frozenset = frozenset()
    max_bsl: int = 2
    physical: bool = True          # False = analysis-only campaign

    @staticmethod
    def build(spec: dict | None) -> "LabRequirement":
        s = dict(spec or {})
        return LabRequirement(
            assay_types=frozenset(s.get("assay_types") or ()),
            readouts=frozenset(s.get("readouts") or ()),
            max_bsl=int(s.get("max_bsl", 2)),
            physical=bool(s.get("physical", True)))


def normalize_caps(adapter: Any) -> dict:
    """One capability vocabulary from heterogeneous adapters: legacy
    dicts, sensor readouts, or MCP-declared typed tools."""
    raw = dict(adapter.list_capabilities() or {})
    assays = {str(a) for a in raw.get("assays") or []}
    readouts = {str(r) for r in raw.get("measures") or []}
    readouts |= {str(r) for r in raw.get("modalities") or []}
    if raw.get("readout"):
        readouts.add(str(raw["readout"]))
        assays.add("sensor")
    for t in raw.get("tools") or []:          # MCP profiles
        if t.get("read_only"):
            readouts.add(str(t["name"]))
    return {
        "assay_types": assays,
        "readouts": readouts,
        "bsl_max": raw.get("bsl_max"),
        "simulated": bool(raw.get("simulated")
                          or raw.get("adapter_simulated", False)
                          # virtual labs don't self-label in legacy dicts;
                          # their names do
                          or getattr(adapter, "name", "") in (
                              "simulator", "imaging-simulator")),
        "simulator": raw.get("simulated") is None and (
            raw.get("adapter_simulated") or getattr(adapter, "name", "")
            in ("simulator", "imaging-simulator")),
        "hardware_validated": bool(raw.get("hardware_validated", False)),
        "kind": str(raw.get("kind", "")),
    }


@dataclass
class Selection:
    lab: Any
    name: str
    rationale: dict = field(default_factory=dict)


def select_lab(pool: list, req: LabRequirement):
    """pool: [(name, adapter)] -> (Selection | None, refusals). Always
    returns the refusals list (why each DECLINED instrument was declined)
    — the decision record is as informative when selection succeeds.
    Deterministic: eligible = capability-superset AND BSL-compatible;
    ordered hardware-validated first, then pool order (operator intent)."""
    if req.physical and not pool:
        return None, [{"name": None, "why": ["empty pool — physical "
                                             "campaign has no permitted "
                                             "instruments"]}]
    eligible, refusals = [], []
    for name, lab in pool:
        caps = normalize_caps(lab)
        why = []
        missing_a = [a for a in req.assay_types if a not in caps["assay_types"]]
        missing_r = [r for r in req.readouts if r not in caps["readouts"]
                     and r not in caps["assay_types"]]
        if not req.physical:
            pass
        else:
            if missing_a:
                why.append(f"no assay: {', '.join(sorted(missing_a))}")
            if missing_r:
                why.append(f"no readout: {', '.join(sorted(missing_r))}")
            if caps["bsl_max"] is not None and caps["bsl_max"] < req.max_bsl:
                why.append(f"BSL ceiling {caps['bsl_max']} < {req.max_bsl}")
        if why:
            refusals.append({"name": name, "why": why})
        else:
            eligible.append((name, lab, caps))
    if not eligible:
        return None, refusals
    # deterministic: hardware-validated before simulated; pool (operator
    # declaration) order breaks remaining ties
    eligible.sort(key=lambda e: (not e[2]["hardware_validated"],))
    name, lab, caps = eligible[0]
    return Selection(
        lab=lab, name=name,
        rationale={"requirement": {
                       "assay_types": sorted(req.assay_types),
                       "readouts": sorted(req.readouts),
                       "max_bsl": req.max_bsl,
                       "physical": req.physical},
                   "chosen": {"name": name, "simulated": caps["simulated"]},
                   "order_rule": "hardware-validated first, then declared "
                                 "order; capability-superset required",
                   "declined": refusals}), refusals


def build_pool(entries: list[dict]) -> list:
    """Operator-declared pool from config:
      {"adapter": "pkg.mod:Class", "options": {...}}
      {"simulator": {"seed": 42}}
      {"mcp": {"command": [...], "profile": "ezo|mettler|ika" | {...}}}
    """
    from bionexus.core.registry import import_string
    pool = []
    for i, e in enumerate(entries or []):
        if "simulator" in e:
            from bionexus.adapters.lab.simulator import SimulatorLab
            opts = dict(e.get("options") or {})
            opts.update({k: v for k, v in (e["simulator"] or {}).items()})
            pool.append((f"simulator-{i}", SimulatorLab(**opts)))
        elif "adapter" in e:
            cls = import_string(e["adapter"])
            name = e.get("name") or e["adapter"].rsplit(":", 1)[-1]
            pool.append((f"{name}-{i}", cls(**(e.get("options") or {}))))
        elif "mcp" in e:
            from bionexus.mcp_instrument import (McpLabAdapter,
                                                 LABMCP_IKA_PROFILE,
                                                 LABMCP_METTLER_PROFILE,
                                                 REFERENCE_EZO_PROFILE)
            m = e["mcp"]
            prof = m.get("profile")
            prof = {"ezo": REFERENCE_EZO_PROFILE,
                    "mettler": LABMCP_METTLER_PROFILE,
                    "ika": LABMCP_IKA_PROFILE}.get(prof, prof or {})
            label = str(m.get("command", ["mcp"])[0]).rsplit("/", 1)[-1]
            pool.append((f"{label}-{i}",
                         McpLabAdapter(command=list(m["command"]),
                                       profile=prof or None)))
        else:
            raise ValueError(f"unrecognized lab pool entry: {e!r}")
    return pool
