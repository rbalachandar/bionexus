"""Simulated lab devices — liquid handler and sequencer (7).

Like the imaging plate reader: seeded physics, realistic failure modes, and raw
evidence on disk. Agents see executed logs / FASTQ files, not oracles.

Requires numpy (extra `lab-imaging`).
"""
from __future__ import annotations

import hashlib
import random
from pathlib import Path
from typing import Any

try:
    import numpy as np
except ImportError as exc:  # pragma: no cover
    raise ImportError("device sims require numpy: pip install bionexus[lab-imaging]") from exc

from bionexus.core.contracts import ProtocolSubmission


def _seed(*parts: Any) -> int:
    return int(hashlib.sha256(":".join(str(p) for p in parts).encode()).hexdigest()[:8], 16)


# ------------------------------------------------------------- liquid handler

class LiquidHandlerSim:
    """Simulated 8-channel liquid handler (Opentrons-class).

    Physics: requested volume -> delivered volume with percent error growing as
    volume shrinks (real pipettes are worst at low volumes), optional carryover
    when a tip is reused after a concentrated reagent.

    `execute(protocol)` returns the *executed* transfer log — the ground truth
    of what actually landed in each well, not what was requested.
    """

    name = "liquid-handler-sim"

    def __init__(self, seed: int = 7, cv_percent: float = 5.0, carryover_prob: float = 0.03,
                 min_volume_ul: float = 2.0):
        self.seed = seed
        self.cv = cv_percent
        self.carryover_prob = carryover_prob
        self.min_volume_ul = min_volume_ul

    def execute(self, protocol: ProtocolSubmission) -> dict[str, Any]:
        rng = random.Random(_seed("lh", self.seed, protocol.protocol_id))
        transfers: list[dict[str, Any]] = []
        carryover = 0.0
        for step in sorted(protocol.steps, key=lambda s: s.seq):
            if step.op.value != "dispense":
                continue
            requested = float(step.params.get("volume_ul", 10.0))
            delivered = requested * (1.0 + rng.gauss(0, self.cv / 100.0))
            # low-volume penalty: below min spec, systematic under-delivery
            if requested < self.min_volume_ul:
                delivered *= requested / self.min_volume_ul
            if carryover and rng.random() < self.carryover_prob:
                delivered += carryover * rng.uniform(0.01, 0.05)
            carryover = delivered
            transfers.append({
                "step": step.seq,
                "requested_ul": round(requested, 3),
                "delivered_ul": round(delivered, 3),
                "error_percent": round(100 * (delivered - requested) / max(requested, 1e-9), 2),
                "carryover": carryover > requested * 0.05,
                "below_spec": requested < self.min_volume_ul,
            })
        executed_vol = sum(t["delivered_ul"] for t in transfers)
        requested_vol = sum(t["requested_ul"] for t in transfers)
        return {
            "transfers": transfers,
            "total_requested_ul": round(requested_vol, 2),
            "total_delivered_ul": round(executed_vol, 2),
            "global_error_percent": round(100 * (executed_vol - requested_vol)
                                          / max(requested_vol, 1e-9), 2),
            "evidence": f"transfers={len(transfers)}, cv={self.cv}%",
        }


# ------------------------------------------------------------------- sequencer

COMPLEMENT = str.maketrans("ACGT", "TGCA")


class SequencerSim:
    """Simulated short-read sequencer: sample -> reads -> variant calling.

    Given a reference and a true genotype (list of (position, alt) mutations,
    0-based), emits seeded reads with substitution errors and configurable
    coverage, writes FASTQ, then `call_variants` re-derives the genotype from
    the reads. Agents get FASTQ evidence; the truth stays in the device.
    """

    name = "sequencer-sim"

    def __init__(self, seed: int = 7, read_length: int = 50, error_rate: float = 0.01):
        self.seed = seed
        self.read_length = read_length
        self.error_rate = error_rate

    def sequence(self, sample_id: str, reference: str,
                 mutations: list[tuple[int, str]], coverage: int = 30) -> dict[str, Any]:
        truth = list(reference)
        for pos, alt in mutations:
            truth[pos] = alt
        truth_genome = "".join(truth)
        rng = random.Random(_seed("seq", self.seed, sample_id))
        reads: list[dict[str, Any]] = []
        n_reads = max(1, coverage * len(reference) // self.read_length)
        for _ in range(n_reads):
            start = rng.randrange(0, max(1, len(truth_genome) - self.read_length + 1))
            seq = truth_genome[start:start + self.read_length]
            seq = "".join(
                c if rng.random() >= self.error_rate else rng.choice("ACGT")
                for c in seq
            )
            qual = "".join(chr(33 + max(20, min(40, int(rng.gauss(35, 4))))) for _ in seq)
            reads.append({"seq": seq, "qual": qual, "start": start})
        fq = self.write_fastq(sample_id, reads)
        return {"sample_id": sample_id, "fastq": fq, "reads": reads,
                "reference": reference, "coverage": coverage}

    def write_fastq(self, sample_id: str, reads: list[dict], path: str | Path | None = None) -> str:
        lines: list[str] = []
        for i, r in enumerate(reads):
            # alignment start embedded in the header (poor-man's SAM tag)
            lines += [f"@{sample_id}:{i} start={r['start']}", r["seq"], "+", r["qual"]]
        text = "\n".join(lines) + "\n"
        if path:
            Path(path).write_text(text)
        return text

    @staticmethod
    def call_variants(fastq: str, reference: str,
                      min_var_fraction: float = 0.2) -> list[dict[str, Any]]:
        """Pileup variant caller: reads align via the `start=` header tag."""
        lines = fastq.splitlines()
        piles: list[dict[str, int]] = [dict() for _ in reference]
        for i in range(0, len(lines) - 3, 4):
            header, seq = lines[i], lines[i + 1]
            if not set(seq) <= set("ACGT"):
                continue
            start = 0
            for tok in header.split():
                if tok.startswith("start="):
                    start = int(tok.split("=")[1])
            for off, base in enumerate(seq):
                pos = start + off
                if pos >= len(reference):
                    break
                piles[pos][base] = piles[pos].get(base, 0) + 1
        calls: list[dict[str, Any]] = []
        for pos, pile in enumerate(piles):
            total = sum(pile.values())
            if total == 0:
                continue
            ref_base = reference[pos]
            alt_base = max((b for b in pile if b != ref_base),
                           key=lambda b: pile[b], default=None)
            if alt_base is None:
                continue
            frac = pile[alt_base] / total
            if frac >= min_var_fraction:
                calls.append({"position": pos, "ref": ref_base, "alt": alt_base,
                              "fraction": round(frac, 3)})
        return calls
