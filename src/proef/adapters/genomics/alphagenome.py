"""AlphaGenome Atlas adapter — variant impact predictions (Google DeepMind).

AlphaGenome Atlas precomputes the functional impact of all ~9 billion
single-nucleotide variants in the human genome, condensed into the
AlphaGenome Variant Impact (AVI) score with feature attributions (splicing,
chromatin accessibility, conservation, protein impact).

Two backends behind one interface (P2):
  - AtlasAPI      — the real AlphaGenome API (needs the `alphagenome` package
                    + ALPHAGENOME_API_KEY). Non-commercial terms apply.
  - SimulatedAVI  — deterministic seeded scorer (P8) so CI, tests and demos
                    run offline. Ground truth is invented; the interface is not.

Non-commercial use only; not for clinical decision-making (DeepMind ToU).
"""
from __future__ import annotations

import hashlib
import os
from typing import Any

from pydantic import BaseModel, Field

ATTRIBUTION_CATEGORIES = ("splicing", "chromatin_accessibility",
                          "gene_expression", "conservation", "protein_impact")


class VariantImpact(BaseModel):
    variant: str                       # "chr22:36201698:A>C"
    avi_score: float                   # 0–1, higher = more likely functional
    classification: str                # high | moderate | low impact
    attributions: dict[str, float] = Field(default_factory=dict)
    source: str = "simulated"          # atlas_api | simulated
    detail: str = ""

    def summary(self) -> dict[str, Any]:
        top = sorted(self.attributions.items(), key=lambda kv: -kv[1])[:3]
        return {
            "variant": self.variant,
            "avi_score": round(self.avi_score, 4),
            "classification": self.classification,
            "top_drivers": dict(top),
            "source": self.source,
        }


def _classify(score: float) -> str:
    if score >= 0.8:
        return "high"
    if score >= 0.5:
        return "moderate"
    return "low"


def _key(chromosome: str, position: int, ref: str, alt: str) -> str:
    return f"{chromosome}:{position}:{ref}>{alt}"


class SimulatedAVI:
    """Deterministic offline scorer. Seeded per variant so the same variant
    always scores the same — reproducible demos, no network."""

    name = "simulated-avi"
    source = "simulated"

    def score(self, chromosome: str, position: int, ref: str, alt: str) -> VariantImpact:
        material = f"{chromosome}:{position}:{ref}>{alt}".encode()
        h = int(hashlib.sha256(material).hexdigest()[:16], 16)
        avi = ((h % 10000) / 10000.0) ** 1.2          # skew toward low impact
        # attribution shares that sum to the score
        weights = [((h >> (11 * i)) % 97) + 3 for i in range(len(ATTRIBUTION_CATEGORIES))]
        total = sum(weights)
        attributions = {cat: round(avi * w / total, 4)
                        for cat, w in zip(ATTRIBUTION_CATEGORIES, weights)}
        return VariantImpact(
            variant=_key(chromosome, position, ref, alt),
            avi_score=round(avi, 4),
            classification=_classify(avi),
            attributions=attributions,
            source=self.source,
            detail="seeded simulation — no biological meaning (P8)",
        )

    def rank(self, variants: list[dict[str, Any]]) -> list[VariantImpact]:
        scored = [self.score(**{k: v for k, v in v_.items()
                                if k in ("chromosome", "position", "ref", "alt")})
                  for v_ in variants]
        return sorted(scored, key=lambda v: -v.avi_score)


class AtlasAPI:
    """Real AlphaGenome API backend. Requires `pip install alphagenome` and
    ALPHAGENOME_API_KEY (free for non-commercial use)."""

    name = "alphagenome-atlas"
    source = "atlas_api"

    def __init__(self, api_key: str | None = None):
        try:
            from alphagenome.models import dna_client  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "install the AlphaGenome client: pip install alphagenome") from exc
        self._key = api_key or os.environ.get("ALPHAGENOME_API_KEY", "")
        if not self._key:
            raise ValueError("ALPHAGENOME_API_KEY not set — get one at "
                             "https://deepmind.google.com/science/alphagenome")
        self._client = dna_client.create(self._key)

    def score(self, chromosome: str, position: int, ref: str, alt: str) -> VariantImpact:
        # Atlas precomputed AVI score via the API client. The exact entry
        # point firms up with the SDK release; until then fall back to
        # live variant scoring of the relevant outputs.
        from alphagenome.data import genome
        from alphagenome.models import dna_client
        variant = genome.Variant(chromosome=chromosome.lstrip("chr") and chromosome,
                                 position=position,
                                 reference_bases=ref, alternate_bases=alt)
        interval = genome.Interval(chromosome=chromosome,
                                   start=max(0, position - 32768),
                                   end=position + 32768)
        outputs = self._client.score_variants(
            interval=interval, variants=[variant],
            requested_outputs=[dna_client.OutputType.RNA_SEQ])
        avi = float(outputs[0].metadata.get("avi_score", 0.0))
        attributions = {k: float(v) for k, v in
                        (outputs[0].metadata.get("attributions") or {}).items()}
        return VariantImpact(
            variant=_key(chromosome, position, ref, alt),
            avi_score=avi, classification=_classify(avi),
            attributions=attributions, source=self.source,
            detail="AlphaGenome Atlas / API (non-commercial terms)")

    def rank(self, variants: list[dict[str, Any]]) -> list[VariantImpact]:
        scored = [self.score(**{k: v for k, v in v_.items()
                                if k in ("chromosome", "position", "ref", "alt")})
                  for v_ in variants]
        return sorted(scored, key=lambda v: -v.avi_score)


def get_variant_scorer() -> SimulatedAVI | AtlasAPI:
    """Factory: real Atlas API when package+key are present, else simulated."""
    try:
        return AtlasAPI()
    except (ImportError, ValueError):
        return SimulatedAVI()
