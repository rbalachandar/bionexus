"""Shared CS08 artifact loaders — one shape for the three scripts.

Raw tree: .data/cs08-designs/night1/
  boltz_predictions/<name>/confidence_<name>_model_0.json
  ctrl_predictions/<name>/confidence_<name>_model_0.json
  boltz_in2/<name>.yaml + controls_in/<name>.yaml (chain A = the binder)
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def load_scores(pred_dir: str | Path) -> dict[str, dict]:
    """{prediction-name: confidence dict}; name is the per-target dir."""
    out = {}
    for f in sorted(Path(pred_dir).glob("*/confidence_*.json")):
        out[f.parent.name] = json.loads(f.read_text())
    return out


def binder_seqs(yaml_dir: str | Path) -> dict[str, str]:
    """{stem: chain-A sequence} from generated Boltz YAML inputs."""
    out = {}
    for p in sorted(Path(yaml_dir).glob("*.yaml")):
        m = re.search(r"id: A\n      sequence: (\w+)", p.read_text())
        if m:
            out[p.stem] = m.group(1)
    return out


GATE, BAND = 0.7, 0.05   # pre-registered gate + declared single-prediction band


def verdict(iptm: float, gate: float = GATE, band: float = BAND) -> str:
    """ONE verdict mechanism for every CS08 artifact. Mirrors
    SuccessCriteria.classify(direction=max) exactly: the 4dp-rounded
    95% band can veto certainty — lo >= gate confirms, hi < gate
    refutes, straddling abstains. (Three scripts previously computed
    this three ways; a code review caught the drift.)"""
    lo, hi = round(iptm - band, 4), round(iptm + band, 4)
    if lo >= gate:
        return "confirm_predicted"
    if hi < gate:
        return "refute_predicted"
    return "abstain"
