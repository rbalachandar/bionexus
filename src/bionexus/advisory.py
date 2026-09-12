"""Advisory AI tox review — the tighten-only tier (Trust-T2 step 3).

Runs AFTER the deterministic gate has passed. It can add flags and demand
human review; it can NEVER clear a refusal (it never sees one — refusals
return before it runs). Its verdict is recorded as an advisory gate_decision
either way, so the audit shows what was noticed, not just what was enforced.

Backend: heuristic (ignored-intent electrophile re-check, alert stacking).
With BIONEXUS_ADVISORY_LLM=1 and a configured provider, an LLM pass adds
free-text concerns on top — still advisory-only.
"""
from __future__ import annotations

import os


class AdvisoryReviewer:
    name = "advisory-tox"

    def __init__(self, provider=None):
        self.provider = provider
        if provider is None and os.environ.get("BIONEXUS_ADVISORY_LLM") == "1":
            try:
                from bionexus.adapters.models.anthropic_provider import (
                    AnthropicProvider)
                self.provider = AnthropicProvider()
            except Exception:
                self.provider = None

    def review(self, protocol) -> dict:
        from bionexus.adapters.bio.tox_alerts import screen_smiles
        flags, escalate = [], False
        for sample in protocol.samples:
            smi = (sample.metadata or {}).get("smiles")
            if not smi:
                continue
            # intent='' -> medium alerts are NOT downgraded here: what the
            # deterministic gate let through on declared intent, we re-look at
            out = screen_smiles(smi, intent="")
            intent_declared = (sample.metadata or {}).get("intent")
            for h in out.get("refuse", []):
                flags.append({"sample": sample.sample_id,
                              "alert": h["alert"], "note": h["note"],
                              "declared_intent": intent_declared or None})
            if len(out.get("refuse", [])) >= 2:
                escalate = True       # stacking alerts demand a human
        if self.provider is not None:
            extra = self._llm_pass(protocol)
            flags.extend(extra)
            if any(f.get("severity") == "escalate" for f in extra):
                escalate = True
        return {"flags": flags, "escalate": escalate}

    def _llm_pass(self, protocol) -> list[dict]:
        from bionexus.core.contracts import Envelope, ToolInvocation
        smis = [(s.sample_id, (s.metadata or {}).get("smiles", ""))
                for s in protocol.samples
                if (s.metadata or {}).get("smiles")]
        if not smis:
            return []
        try:
            txt = self.provider.generate(
                ToolInvocation(envelope=Envelope(experiment_branch_id="advisory"),
                               tool="c.fm.predict_admet"),
                "You are a conservative medicinal-chemistry safety reviewer. "
                "List structural safety concerns for these compounds as JSON: "
                '{"concerns":[{"sample":"...","concern":"...","severity":'
                '"info|escalate"}]}. Empty list if none.\n\n'
                + "\n".join(f"{i}: {s}" for i, s in smis)).output["text"]
            import json, re
            doc = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
            return [{"sample": c.get("sample", "?"), "alert": "llm-concern",
                     "note": c.get("concern", "")[:160],
                     "severity": c.get("severity", "info")}
                    for c in doc.get("concerns", [])]
        except Exception:
            return []          # advisory failure must never block or crash
