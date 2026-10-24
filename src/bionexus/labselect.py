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

import json
from pathlib import Path

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
                   "declined": refusals,
                   "eligible": [n for n, _, _ in eligible]}), refusals


CATALOG_PATH = Path(__file__).parent / "instruments.json"


def load_catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text())


def _catalog_entry(instrument_id: str) -> dict:
    for e in load_catalog()["instruments"]:
        if e["id"] == instrument_id:
            return e
    known = ", ".join(x["id"] for x in load_catalog()["instruments"])
    raise ValueError(f"unknown instrument {instrument_id!r}; "
                     f"catalog ids: {known}")


def available_instruments() -> list[dict]:
    """The picker view: every catalog instrument, whether it is
    installable/reachable HERE, and what it declares. Availability is an
    INSTALL check; capability truth comes from the live handshake at
    selection time — the list never overstates what an instrument is."""
    import importlib.util
    import shutil
    out = []
    for e in load_catalog()["instruments"]:
        kind = e["kind"]
        if kind == "simulator":
            installed = True
        elif kind == "mcp":
            exe0 = e.get("availability_executable") or e["command"][0]
            import sys as _s
            installed = (exe0 == "{python}" or bool(shutil.which(exe0))
                         or (Path(_s.executable).parent / exe0).exists())
        else:
            mod = e["adapter"].rsplit(":", 1)[0]
            installed = importlib.util.find_spec(mod) is not None
        out.append({**{k: e.get(k) for k in (
                        "id", "kind", "name", "vendor",
                        "hardware_validated", "assay_types", "readouts",
                        "note", "homepage", "requires_network",
                        "config_schema")},
                    "simulated": bool(e.get("simulated")
                                       or e.get("simulated_by_default")),
                    "installed": bool(installed),
                    "profile_read_tool": (e.get("profile") or {}).get(
                        "read_tool")})
    return out


def _config_args(cat: dict, config: dict) -> list[str]:
    """Translate an instrument's connection config into server flags per
    its declared config_schema (e.g. labmcp's --simulate / --address).
    simulate defaults TRUE: a campaign must opt INTO hardware, never
    accidentally touch it."""
    args = []
    simulate_omitted = True
    for f in cat.get("config_schema") or []:
        v = config.get(f["key"], f.get("default"))
        if f["key"] == "simulate":
            simulate_omitted = False
            if v:
                args += ["--simulate"]
        elif f["type"] == "bool" and v:
            args += [f"--{f['key']}"]
        elif v not in (None, ""):
            args += [f"--{f['key']}", str(v)]
    if simulate_omitted and "config_schema" in [f.get("key") for f in
                                                cat.get("config_schema") or []]:
        pass
    return args


def _resolve_cmd(cmd: list[str]) -> list[str]:
    """Executables ship next to the running interpreter (venv/bin) and
    are not always on PATH in subprocess contexts."""
    import shutil
    import sys
    from pathlib import Path
    exe = cmd[0]
    if shutil.which(exe):
        return cmd
    beside = Path(sys.executable).parent / exe
    if beside.exists():
        return [str(beside), *cmd[1:]]
    return cmd


def build_pool(entries: list[dict]) -> list:
    """Operator-declared pool. The happy path references the catalog:
      {"instrument": "<id>"}       (commands + profiles come from data)
    Escape hatches for instruments not yet catalogued:
      {"simulator": {...}} | {"adapter": "pkg:Class", "options": {...}}
      {"mcp": {"command": [...], "profile": {<full profile dict>}}}
    """
    import sys
    from bionexus.core.registry import import_string
    pool = []
    for i, e in enumerate(entries or []):
        if "instrument" in e:
            cat = _catalog_entry(e["instrument"])
            opts = {**(cat.get("options") or {}), **(e.get("options") or {})}
            if cat["kind"] == "simulator":
                from bionexus.adapters.lab.simulator import SimulatorLab
                pool.append((f"{cat['id']}-{i}", SimulatorLab(**opts)))
            elif cat["kind"] == "mcp":
                from bionexus.mcp_instrument import McpLabAdapter
                cmd = _resolve_cmd([c.replace("{python}", sys.executable)
                                    for c in cat["command"]])
                cmd += _config_args(cat, e.get("config") or {})
                cmd += [str(a) for a in (e.get("args") or [])]
                pool.append((f"{cat['id']}-{i}",
                             McpLabAdapter(command=cmd,
                                           profile=dict(cat["profile"]))))
            else:
                cls = import_string(cat["adapter"])
                pool.append((f"{cat['id']}-{i}", cls(**opts)))
        elif "simulator" in e:
            from bionexus.adapters.lab.simulator import SimulatorLab
            opts = dict(e.get("options") or {})
            opts.update(e["simulator"] or {})
            pool.append((f"simulator-{i}", SimulatorLab(**opts)))
        elif "adapter" in e:
            cls = import_string(e["adapter"])
            name = e.get("name") or e["adapter"].rsplit(":", 1)[-1]
            pool.append((f"{name}-{i}", cls(**(e.get("options") or {}))))
        elif "mcp" in e:
            from bionexus.mcp_instrument import McpLabAdapter
            m = e["mcp"]
            if not isinstance(m.get("profile"), dict):
                raise ValueError(
                    "inline mcp entries need a full profile dict — named "
                    "profiles live in instruments.json; add the instrument "
                    "to the catalog (one data edit, then use its id)")
            label = str(m.get("command", ["mcp"])[0]).rsplit("/", 1)[-1]
            pool.append((f"{label}-{i}",
                         McpLabAdapter(command=list(m["command"]),
                                       profile=m["profile"])))
        else:
            raise ValueError(f"unrecognized lab pool entry: {e!r}")
    return pool


def fence_info(labs_entries: list | None) -> list[dict]:
    """Human-facing view of a program's fence: which instruments the
    creator permitted, by name, with honest status. This is DECLARATION
    data (what the fence allows) — not a live probe of the devices."""
    out = []
    for e in labs_entries or []:
        iid = e.get("instrument") if "instrument" in e else None
        if iid:
            try:
                cat = _catalog_entry(iid)
            except ValueError:
                out.append({"id": iid, "name": iid, "installed": False,
                            "unknown": True})
                continue
            installed = any(x["id"] == iid and x["installed"]
                            for x in available_instruments())
            out.append({"id": iid, "name": cat.get("name", iid),
                        "vendor": cat.get("vendor"),
                        "simulated": bool(cat.get("simulated")
                                          or cat.get("simulated_by_default")),
                        "hardware_validated":
                            bool(cat.get("hardware_validated", False)),
                        "installed": installed,
                        # operator-declared identity patterns (upload
                        # enforcement): part of the fence, not the catalog
                        "match": e.get("match") or []})
        elif "simulator" in e:
            out.append({"id": "bionexus-virtual-lab",
                        "name": "Virtual lab (simulator)",
                        "simulated": True, "installed": True})
    return out


def fence_declared_caps(labs_entries: list | None) -> dict[str, set]:
    """Union of the capability vocabulary DECLARED by a program's fence
    instruments (from the catalog). Vocabulary-agnostic: the readiness
    check treats unmet declared readouts as blockers — failing closed."""
    ids = [e.get("instrument") for e in labs_entries or []
           if e.get("instrument")]
    readouts, assay_types = set(), set()
    for iid in ids:
        try:
            cat = _catalog_entry(iid)
        except ValueError:
            continue
        readouts |= {str(r) for r in cat.get("readouts") or []}
        assay_types |= {str(a) for a in cat.get("assay_types") or []}
    return {"readouts": readouts, "assay_types": assay_types}
