"""Safety engine — the non-bypassable policy layer for physical actions (P6).

Agents never call a LabAdapter directly; core's LabGateway checks every
ProtocolSubmission against configured rules first. Rules are declarative and
registered by the operator, not by agents.
"""
from __future__ import annotations

import fnmatch
from typing import Any, Protocol

from bionexus.core.contracts import ProtocolSubmission


class SafetyRule(Protocol):
    """A single declarative check. Returns None if approved, else a reason."""

    name: str

    def check(self, protocol: ProtocolSubmission) -> str | None: ...


class MaxBslRule:
    """Reject protocols whose reagents exceed the allowed biosafety level."""

    def __init__(self, max_bsl: int = 2):
        self.name = f"max_bsl_{max_bsl}"
        self.max_bsl = max_bsl

    def check(self, protocol: ProtocolSubmission) -> str | None:
        for reagent in protocol.reagents:
            if reagent.bsl_level > self.max_bsl:
                return (
                    f"reagent '{reagent.name}' has BSL-{reagent.bsl_level} "
                    f"> allowed BSL-{self.max_bsl}"
                )
        return None


class ForbiddenComboRule:
    """Reject protocols combining forbidden reagent pairs (glob patterns)."""

    def __init__(self, forbidden_pairs: list[tuple[str, str]]):
        self.name = "forbidden_combos"
        self.pairs = [(a.lower(), b.lower()) for a, b in forbidden_pairs]

    def check(self, protocol: ProtocolSubmission) -> str | None:
        names = [r.name.lower() for r in protocol.reagents]
        for a_pat, b_pat in self.pairs:
            for a in names:
                for b in names:
                    if a == b:
                        continue
                    if fnmatch.fnmatch(a, a_pat) and fnmatch.fnmatch(b, b_pat):
                        return f"forbidden reagent combination: '{a}' + '{b}'"
        return None


class MaxStepsRule:
    """Guard against runaway agent-generated protocols."""

    def __init__(self, max_steps: int = 100):
        self.name = f"max_steps_{max_steps}"
        self.max_steps = max_steps

    def check(self, protocol: ProtocolSubmission) -> str | None:
        if len(protocol.steps) > self.max_steps:
            return f"protocol has {len(protocol.steps)} steps > max {self.max_steps}"
        return None


class ToxicophoreRule:
    """Molecule-level safety: samples carrying a SMILES in
    metadata['smiles'] are screened against curated structural alerts.
    Hard alerts always refuse; medium alerts refuse unless the sample
    declares matching intent (metadata['intent'], e.g. 'covalent warhead').
    Without RDKit the rule reports 'unverified' honestly and does not block
    (installation-gated depth, P1)."""

    name = "toxicophores"

    def check(self, protocol: ProtocolSubmission) -> str | None:
        from bionexus.adapters.bio.tox_alerts import screen_smiles
        for sample in protocol.samples:
            smi = (sample.metadata or {}).get("smiles")
            if not smi:
                continue
            out = screen_smiles(smi, (sample.metadata or {}).get("intent", ""))
            if out["refuse"]:
                from bionexus.adapters.bio.tox_alerts import RULES_VERSION
                return (f"sample '{sample.sample_id}' carries "
                        f"{len(out['refuse'])} toxicophore alert(s) "
                        f"[rules {RULES_VERSION}]: "
                        + "; ".join(f"{h['alert']} ({h['note']})"
                                    for h in out["refuse"][:3]))
        return None


class DurcTargetRule:
    """Dual-use screen on everything a protocol names: title, samples,
    reagents. Text-level, always on, no dependencies."""

    name = "durc_screen"

    def check(self, protocol: ProtocolSubmission) -> str | None:
        from bionexus.adapters.bio.tox_alerts import durc_screen
        blob = " ".join([protocol.title]
                        + [s.sample_id for s in protocol.samples]
                        + [r.name for r in protocol.reagents])
        hits = durc_screen(blob)
        if hits:
            return ("names a select agent / regulated toxin family: "
                    + ", ".join(hits) + " — dual-use review required")
        return None


class SafetyEngine:
    """Evaluates rules in order; first rejection wins. Operators compose rules;
    agents can only ever receive (approved, reason)."""

    def __init__(self, rules: list[Any] | None = None):
        self.rules: list[Any] = list(rules) if rules else [
            MaxBslRule(max_bsl=2),
            MaxStepsRule(max_steps=100),
            DurcTargetRule(),
            ToxicophoreRule(),
        ]

    def add_rule(self, rule: Any) -> None:
        self.rules.append(rule)

    def check(self, protocol: ProtocolSubmission) -> tuple[bool, str | None]:
        for rule in self.rules:
            reason = rule.check(protocol)
            if reason is not None:
                return False, f"[{rule.name}] {reason}"
        return True, None


class LabGateway:
    """The ONLY path from agents to a LabAdapter. Enforces safety (P6), records
    provenance for every run (P5). Agents see this, never the raw adapter."""

    def __init__(self, lab: Any, safety: SafetyEngine, store: Any, actor: Any,
                 advisory: Any = None, governance: Any = None,
                 approver: Any = None):
        self.lab = lab
        self.safety = safety
        self.store = store
        self.actor = actor
        self.advisory = advisory
        self.governance = governance   # {"matrix":..., "halt":...}
        self.approver = approver

    def submit(self, protocol: ProtocolSubmission) -> tuple[str | None, str | None]:
        """Returns (run_id, rejection_reason). run_id is None when rejected."""
        from bionexus.core.contracts import EventType
        from bionexus.core.interfaces import record_for
        # halts are checked FIRST, before anything the agent can influence
        if self.governance is not None:
            halt = self.governance["halt"].engaged()
            if halt:
                self.store.append(record_for(
                    protocol.envelope, EventType.gate_decision, self.actor,
                    decision={"kind": "halt_refusal", "halt": halt,
                              "title": protocol.title}))
                return None, ("[halt] operator stop-condition engaged: "
                              f"{halt.get('reason', '')} — all submissions "
                              "refused until cleared by a human")
        approved, reason = self.safety.check(protocol)
        if not approved:
            self.store.append(record_for(
                protocol.envelope, EventType.gate_decision, self.actor,
                decision={"kind": "safety_refusal", "reason": reason,
                          "samples": sorted({sp.sample_id
                                             for sp in protocol.samples})}))
            return None, reason
        # authorization matrix: three columns, enforced in code
        if self.governance is not None:
            column, why = self.governance["matrix"].classify(protocol)
            if column != "autonomous" or "SOP" in why:
                self.store.append(record_for(
                    protocol.envelope, EventType.gate_decision, self.actor,
                    decision={"kind": "authorization", "column": column,
                              "reason": why, "title": protocol.title,
                              "samples": sorted({sp.sample_id
                                                 for sp in protocol.samples})}))
            if column == "never":
                return None, f"[authorization: NEVER] {why}"
            if column == "human":
                ok = bool(self.approver(protocol.title)) if self.approver \
                    else False
                if not ok:
                    return None, ("[authorization: HUMAN required] "
                                  + (f"declined: {why}" if ok is False and
                                     self.approver else
                                     f"no approver configured: {why}"))
        # tighten-only advisory tier: runs solely on gate-passed protocols;
        # may add flags or escalate to human review, never clears a refusal
        if self.advisory is not None:
            from bionexus.core.contracts import EventType
            from bionexus.core.interfaces import record_for
            adv = self.advisory.review(protocol)
            if adv.get("flags") or adv.get("escalate"):
                self.store.append(record_for(
                    protocol.envelope, EventType.gate_decision, self.actor,
                    decision={"kind": "advisory", "advisory": True,
                              "flags": adv["flags"],
                              "escalated": bool(adv.get("escalate"))}))
            if adv.get("escalate"):
                self.store.append(record_for(
                    protocol.envelope, EventType.gate_decision, self.actor,
                    decision={"kind": "advisory_escalation",
                              "reason": "escalated to human review",
                              "samples": sorted({f.get("sample", "?")
                                                  for f in adv["flags"]})}))
                return None, ("[advisory] escalated to human review: "
                              + "; ".join(f"{f['sample']}: {f['alert']}"
                                          for f in adv["flags"][:2]))
        run_id = self.lab.submit_protocol(protocol)
        from bionexus.core.contracts import EventType, InstrumentInfo
        from bionexus.core.interfaces import record_for

        samples = [s for s in protocol.samples if not s.sample_id.startswith("ctrl")]
        controls = [s for s in protocol.samples if s.sample_id.startswith("ctrl")]
        def _conc_um(v: Any) -> float:
            try:
                return float(str(v).strip().rstrip("uMµ").strip())
            except ValueError:
                return 0.0
        concs = sorted({_conc_um(s.concentration) for s in samples if s.concentration})
        self.store.append(
            record_for(
                protocol.envelope,
                EventType.lab_run,
                self.actor,
                artifact=None,
                decision={
                    "run_id": run_id,
                    "protocol_id": protocol.protocol_id,
                    "title": protocol.title,
                    "assay": getattr(protocol.assay_type, "value",
                                     str(protocol.assay_type)),
                    "instrument": getattr(self.lab, "name", "lab"),
                    "instrument_version": getattr(self.lab, "version", None),
                    "n_samples": len(samples),
                    "n_controls": len(controls),
                    "replicates": getattr(self.lab, "replicates", None),
                    "concentrations": concs,
                },
            )
        )
        return run_id, None

    def results(self, envelope: Any, run_id: str) -> AssayResult:
        result = self.lab.fetch_results(run_id)
        result.envelope = envelope
        return result

    def capabilities(self) -> dict[str, Any]:
        return self.lab.list_capabilities()
