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
