"""bn connect — device discovery for scientists who shouldn't know "adapter".

`bn connect scan <dir>` inspects a folder (e.g. a network share a plate reader
auto-exports to), detects formats with the same engine as `bn read`, and prints
a ready-to-use configuration. `bn connect robot <ip>` probes an Opentrons
robot's HTTP API. No vocabulary required: the tool names the device it found.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def scan_share(directory: str | Path, max_files: int = 50) -> dict[str, Any]:
    """Detect what instruments are writing into a share/outbox."""
    from bionexus.labread import detect_format

    d = Path(directory)
    if not d.is_dir():
        raise FileNotFoundError(f"not a directory: {d}")
    found: dict[str, list[str]] = {}
    files = [f for f in sorted(d.iterdir()) if f.is_file()][: max_files]
    for f in files:
        fmt = detect_format(f)
        if fmt != "unknown":
            found.setdefault(fmt, []).append(f.name)
    suggestions = []
    if found.get("long") or found.get("grid") or found.get("xlsx"):
        suggestions.append({
            "device": "plate reader (auto-exporting to this share)",
            "adapter": "PlateReaderShare",
            "usage": f"PlateReaderShare(share_dir={str(d)!r})  "
                     "— or just: bn read <file>, bn watch <dir>"})
    if found.get("npy"):
        suggestions.append({
            "device": "BioNexus imaging evidence",
            "adapter": "ImagingSimulatorLab",
            "usage": "read via read_plate(<file>.npy) or bn read"})
    if not suggestions:
        suggestions.append({
            "device": "nothing recognized yet",
            "adapter": "SimulatorLab",
            "usage": "start with the virtual lab: bn sim"})
    return {"directory": str(d), "scanned": len(files), "formats": found,
            "suggestions": suggestions}


def probe_robot(ip: str, port: int = 31950, timeout: int = 5) -> dict[str, Any]:
    """Check an Opentrons robot is reachable and identify it."""
    import json
    import urllib.request

    base = ip if ip.startswith("http") else f"http://{ip}:{port}"
    try:
        with urllib.request.urlopen(f"{base.rstrip('/')}/health", timeout=timeout) as r:
            info = json.loads(r.read())
        return {"reachable": True, "name": info.get("name"),
                "api_version": info.get("apiVersion"),
                "adapter": "OpentronsLab",
                "usage": f'OpentronsLab(base_url="{base}") — pair with '
                         "LabGateway(SafetyEngine)"}
    except Exception as exc:
        return {"reachable": False, "error": str(exc)[:120], "base_url": base}


def format_scan(result: dict[str, Any]) -> str:
    lines = [f"scanned {result['scanned']} files in {result['directory']}"]
    for fmt, names in result["formats"].items():
        lines.append(f"  {fmt:6} x{len(names):<3} e.g. {names[0]}")
    lines.append("  →")
    for s in result["suggestions"]:
        lines.append(f"  device:   {s['device']}")
        lines.append(f"  setup:    {s['usage']}")
    return "\n".join(lines)
