#!/usr/bin/env python3
"""S-T4 story, runnable: one sensor, one gate, two transports, one truth.

A bioreactor must hold pH >= 7.20. The probe reads 7.35. Uncalibrated,
that number must NOT buy a validated verdict — and it doesn't, through
either transport (direct wire adapter or an MCP subprocess). The
transport swap changes nothing: identical readings, identical verdicts,
hash chain intact.

    .venv/bin/python examples/ezo_sensor_campaign.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from test_ezo_campaign_mcp import _campaign, _direct_probe, _mcp_adapter  # noqa: E402


def show(tag: str, r: dict) -> None:
    print(f"{tag:22s} reading {r['value']:.3f} pH  "
          f"±u {r['uncertainty']:.3f}  CI {r['ci'][0]:.3f}-{r['ci'][1]:.3f} "
          f"-> {r['verdict'].upper():12s} chain {'OK' if r['chain_ok'] else 'BROKEN'}")


def main() -> int:
    print("gate: pH >= 7.20 (pre-registered)  |  sample truth: 7.35\n")
    show("serial, uncalibrated", _campaign(_direct_probe(False), "serial-sim"))
    show("serial, calibrated", _campaign(_direct_probe(True), "serial-sim"))
    a = _mcp_adapter(False)
    mcp_uncal = _campaign(a, "mcp-stdio")
    a.close()
    show("MCP, uncalibrated", mcp_uncal)
    b = _mcp_adapter(True)
    mcp_cal = _campaign(b, "mcp-stdio")
    b.close()
    show("MCP, calibrated", mcp_cal)
    print("\nSame reading, opposite epistemics: the verdict tracks the "
          "instrument's calibration state, not the number. And serial vs "
          "MCP transport: identical — governance owns the difference.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
