"""ProteinDesignLabAdapter — protein binder design through BioNexus's
hypothesis pipeline, not around it.

Architecture (mirrors the small-molecule DMTA loop, modality-agnostic):

  Layer 1 GENERATE  BindCraft produces candidate sequences (batch output,
                    no per-sequence provenance — they're candidates, not claims)
  Layer 2 FLOOR     quality floor: sequence sanity, minimum pLDDT — physics,
                    not a limit. ALL survivors become hypotheses (free: they're
                    claims, not commitments)
  Layer 3 HYPOTHESIZE  every floor-passing design is provenance-chained as a
                    hypothesis via HypothesisTracker (predicted_by: bindcraft)
  Layer 4 PRIORITIZE  screening budget allocated by diversity + confidence
                    signal — the GPU constraint lives HERE, not at the
                    hypothesis layer
  Layer 5 SCREEN    Boltz-1 interface confidence per prioritized design;
                    CI-aware verdicts only for screened designs; unscreened
                    hypotheses stay 'proposed' — visible, never discarded

The agent proposes the design STRATEGY (target, hotspots, scaffold hints);
this adapter executes it; BioNexus's verdict machinery scores the results.
"""
from __future__ import annotations

import random
import random
import tempfile
from pathlib import Path
from typing import Any

from bionexus.core.contracts.models import (
    AssayResult, Envelope, InstrumentInfo, Measurement, ProtocolSubmission,
    QCInfo, RunStatus,
)


class ProteinDesignLabAdapter:
    """LabAdapter for protein binder design (BindCraft + Boltz-1)."""

    name = "protein-design"

    def __init__(self, mock: bool = False, seed: int = 42,
                 work_dir: str | None = None,
                 bindcraft_dir: str | None = None,
                 boltz_venv: str | None = None,
                 min_plddt: float = 0.6,
                 quality_floor: dict[str, Any] | None = None):
        self.mock = mock
        self.seed = seed
        self.work_dir = Path(work_dir or tempfile.mkdtemp(prefix="prot-design-"))
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.bindcraft_dir = bindcraft_dir
        self.boltz_venv = boltz_venv
        self.min_plddt = min_plddt
        self.quality_floor = quality_floor or {}
        self._runs: dict[str, dict[str, Any]] = {}

    def list_capabilities(self) -> dict[str, Any]:
        return {
            "assays": ["protein_binder_design"],
            "modalities": ["protein"],
            "make_tool": "BindCraft (AF2 backprop + ProteinMPNN)",
            "test_tool": "Boltz-1 (interface confidence)",
            "throughput": "~8 designs/hour on RTX 3090",
            "hypothesis_model": "all quality-passing designs become hypotheses; "
                                "budget constrains screening, not proposing",
        }

    def generate(self, target_pdb: str, hotspot: str,
                 lengths: tuple[int, int], n_attempts: int,
                 run_id: str) -> list[dict[str, Any]]:
        """Layer 1: BindCraft (or mock) generates candidate designs."""
        if self.mock:
            rng = random.Random(self.seed)
            return [{"name": f"mock-{run_id}-{i:03d}",
                     "sequence": "".join(rng.choice("ACDEFGHIKLMNPQRSTVWY")
                                          for _ in range(rng.randint(70, 120))),
                     "plddt": round(rng.uniform(0.3, 1.0), 3)}
                    for i in range(n_attempts)]
        raise NotImplementedError("real BindCraft: see runpack/jobrunner.py")

    def apply_quality_floor(self, designs: list[dict[str, Any]],
                            ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Layer 2: quality floor. Returns (passing, rejected)."""
        passing, rejected = [], []
        for d in designs:
            reasons = []
            if d.get("plddt", 0) < self.min_plddt:
                reasons.append(f"pLDDT {d['plddt']} < {self.min_plddt}")
            seq = d.get("sequence", "")
            if len(seq) < 40 or len(seq) > 250:
                reasons.append(f"length {len(seq)} outside [40, 250]")
            if set(seq) - set("ACDEFGHIKLMNPQRSTVWY"):
                reasons.append("non-standard residues")
            if reasons:
                d["rejection_reasons"] = reasons
                rejected.append(d)
            else:
                passing.append(d)
        return passing, rejected

    def prioritize(self, designs: list[dict[str, Any]],
                   budget: int) -> list[dict[str, Any]]:
        """Layer 4: allocate screening budget by diversity + confidence.
        Farthest-first over aa k-mer sets among the top-confidence designs.
        Designs NOT selected stay as untested hypotheses — never discarded."""
        if len(designs) <= budget:
            return designs
        ranked = sorted(designs, key=lambda d: -d.get("plddt", 0))
        picked = [ranked[0]]
        remaining = ranked[1:]
        while len(picked) < budget and remaining:
            best_i, best_min_sim = 0, 2.0
            for i, cand in enumerate(remaining):
                sims = [self._seq_sim(cand["sequence"], p["sequence"])
                        for p in picked[-20:]]  # vs last 20 picks
                min_sim = min(sims) if sims else 0.0
                if min_sim < best_min_sim:
                    best_min_sim = min_sim
                    best_i = i
            picked.append(remaining.pop(best_i))
        return picked

    @staticmethod
    def _seq_sim(a: str, b: str, k: int = 3) -> float:
        ka = {hash(a[i:i+k]) for i in range(max(0, len(a) - k + 1))}
        kb = {hash(b[i:i+k]) for i in range(max(0, len(b) - k + 1))}
        if not ka or not kb:
            return 0.0
        return len(ka & kb) / len(ka | kb)

    def screen(self, designs: list[dict[str, Any]],
               target_sequence: str) -> list[dict[str, Any]]:
        """Layer 5: Boltz-1 interface confidence (or mock)."""
        if self.mock:
            rng = random.Random(self.seed + 2)
            for d in designs:
                d["iptm"] = round(rng.random(), 3)
                d["uncertainty"] = round(rng.random() * 0.08, 4)
            return designs
        raise NotImplementedError("real Boltz: see runpack/jobrunner.py")

    # ---- convenience: full pipeline ----------------------------------------

    def run_design_cycle(self, tracker, problem, target_sequence: str,
                         n_attempts: int = 100, screening_budget: int = 50,
                         iptm_gate: float = 0.7,
                         ) -> dict[str, Any]:
        """Full design cycle: generate → floor → hypothesize → prioritize
        → screen → verdict. ALL floor-passing designs become hypotheses;
        only screened designs get verdicts; the rest stay 'proposed' —
        visible in the series view, ready for the next budget round."""
        from bionexus.core.hypothesis import SuccessCriteria

        designs = self.generate(target_sequence, "56", (70, 120), n_attempts, "cycle")
        passing, rejected = self.apply_quality_floor(designs)

        criteria = SuccessCriteria(metric="iptm", direction="max",
                                   threshold=iptm_gate)
        hypotheses = []
        for d in passing:
            h = tracker.propose(
                statement=f"Binder {d['name']} binds target (ipTM ≥ {iptm_gate})",
                candidate=d["name"],
                assay_type="protein_binder",
                predicted=f"ipTM ≥ {iptm_gate}",
                predicted_value=d.get("plddt"),
                rationale="BindCraft design (predicted_by: bindcraft, "
                          "protein-design adapter)",
                branch_id=f"problem/{problem.problem_id}",
                predicted_by={"source": "bindcraft", "policy": "AF2-backprop+MPNN"},
            )
            hypotheses.append((h, d))

        prioritized = self.prioritize(passing, screening_budget)
        prio_names = {d["name"] for d in prioritized}

        screened = self.screen([d for d in prioritized], target_sequence)
        screen_by_name = {d["name"]: d for d in screened}

        verdicts = {"confirmed": 0, "refuted": 0, "abstained": 0,
                     "proposed": 0}
        for h, d in hypotheses:
            s = screen_by_name.get(d["name"])
            if s and d["name"] in prio_names:
                verdict = criteria.classify(s["iptm"], None)
                h.status = {"validated": "validated",
                            "invalidated": "invalidated",
                            "inconclusive": "inconclusive"}[verdict]
                verdicts[h.status] = verdicts.get(h.status, 0) + 1
            elif d["name"] not in prio_names:
                verdicts["proposed"] = verdicts.get("proposed", 0) + 1

        return {"hypotheses": hypotheses, "verdicts": verdicts,
                "screened": screen_by_name, "prioritized": prio_names,
                "rejected_by_floor": len(rejected),
                "n_generated": len(designs),
                "n_hypotheses": len(passing)}
