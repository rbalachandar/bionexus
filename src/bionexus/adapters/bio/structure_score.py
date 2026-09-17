"""Structure-model scoring — the biologics Design-phase BioTool.

Scores a protein sequence for predicted structural stability and model
confidence. Two backends:

- "stub": deterministic offline score (hash-seeded) — for tests and the
  virtual lab. Honest label: it is a placeholder number, not a real
  prediction; `model_version` says so.
- "http": POSTs the sequence to a configured endpoint (e.g. an ESMFold/
  ESM-compatible server). The endpoint and key come from options —
  no keys in code.

Implements the BioTool protocol (capability c.fm.predict_structure).
"""
from __future__ import annotations

import hashlib
import json
import random
from typing import Any

from bionexus.core.contracts.models import (ToolInvocation, ToolName,
                                            ToolResult)

STUB_VERSION = "structure-stub-v1"


class StructureScorer:
    name = "structure-scorer"
    capabilities = (ToolName.fm_predict_structure,)

    def __init__(self, backend: str = "stub",
                 endpoint: str | None = None, api_key: str | None = None):
        if backend not in ("stub", "http"):
            raise ValueError(f"unknown backend {backend!r}")
        if backend == "http" and not endpoint:
            raise ValueError("http backend requires an endpoint")
        self.backend = backend
        self.endpoint = endpoint
        self.api_key = api_key

    def score(self, sequence: str) -> dict[str, Any]:
        seq = (sequence or "").strip().upper()
        if self.backend == "stub":
            seed = int(hashlib.sha256(seq.encode()).hexdigest()[:8], 16)
            rng = random.Random(seed)
            confidence = round(55 + rng.random() * 40, 1)     # pLDDT-ish
            stability = round(rng.random(), 3)
            return {"stability_score": stability,
                    "confidence": confidence,
                    "aggregation_risk": round(1 - stability, 3),
                    "backend": STUB_VERSION}
        # http backend: minimal JSON POST, tolerant of ESM-like servers
        import urllib.request
        req = urllib.request.Request(
            self.endpoint,
            data=json.dumps({"sequence": seq}).encode(),
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {self.api_key}"}
                        if self.api_key else {})})
        with urllib.request.urlopen(req, timeout=60) as resp:
            out = json.loads(resp.read())
        return {"stability_score": float(out.get("stability_score",
                                                 out.get("mean_plddt", 0))
                                            / 100 if "mean_plddt" in out
                                            else out.get("stability_score", 0)),
                "confidence": float(out.get("confidence",
                                            out.get("mean_plddt", 0))),
                "aggregation_risk": float(out.get("aggregation_risk", 0)),
                "backend": f"http:{self.endpoint}"}

    # ---- BioTool protocol -------------------------------------------------
    def invoke(self, invocation: ToolInvocation) -> ToolResult:
        seq = invocation.args.get("sequence", "")
        try:
            out = self.score(str(seq))
            return ToolResult(envelope=invocation.envelope,
                              invocation_id=invocation.invocation_id,
                              status="succeeded", output=out,
                              model_version=out.get("backend"))
        except Exception as exc:                     # noqa: BLE001
            return ToolResult(envelope=invocation.envelope,
                              invocation_id=invocation.invocation_id,
                              status="failed",
                              output={"error": str(exc)[:200]})
