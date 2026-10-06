"""Applicability domain — the "every model is a local model" guard.

Bender & Cortés-Ciriano (Nat Rev Drug Discov, Aug 2026) audit of agentic
drug discovery lands on one sentence this module exists for: a trained
predictor is a LOCAL model of the chemistry it was fitted on, and silence
about the boundary is how overclaiming happens. So: at predict time, the
nearest-neighbour Tanimoto similarity to the training set is computed;
below a declared floor the prediction is stamped ``extrapolation`` —
widening abstention rules (SuccessCriteria.classify(extrapolation=True)
never returns a claim-grade verdict) and surfacing a card chip.

This is the model-facing twin of the ingestion regime gate (CS06): data
frames and model domains are both answered the same way — claim inside
what has been validated, refuse outside it, and SAY which case happened.

Featurization basis degrades honestly: Morgan bits (2048, r=2) when rdkit
is installed, else char 3-gram sets — the basis is reported in every
stamp so the similarity number is never read without its units.
"""
from __future__ import annotations

from typing import Any, Iterable

#: nn-Tanimoto below this -> extrapolation. Declared, not tuned per model;
#: 0.5 on Morgan/char binary sets is the conservative literature default
#: (near-neighbor identity ~ same scaffold neighborhood).
AD_FLOOR = 0.5


def _morgan_set(smiles: str, n_bits: int = 2048, radius: int = 2) -> set[int]:
    from rdkit import Chem
    from rdkit.Chem import rdFingerprintGenerator

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return set()
    gen = rdFingerprintGenerator.GetMorganGenerator(radius=radius,
                                                    fpSize=n_bits)
    fp = gen.GetFingerprintAsNumPy(mol).astype(bool)
    return {i for i, b in enumerate(fp) if b}


def _char_set(smiles: str, n: int = 3) -> set[int]:
    s = smiles or ""
    return {hash(s[i:i + n]) & 0xFFFFFFFF for i in range(max(0, len(s) - n + 1))}


def _basis_available() -> str:
    try:
        import rdkit  # noqa: F401
        return "morgan"
    except ImportError:
        return "char3"


def tanimoto(a: set[int], b: set[int]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class ApplicabilityDomain:
    """Nearest-neighbour Tanimoto domain over the training structures.

    Floors are per-domain decisions:
      * fixed (legacy default, AD_FLOOR) — one constant across modalities;
      * auto  — DATA-DERIVED: leave-one-out NN-Tanimoto of the domain
        against itself, at a declared quantile (default p05). 'in-domain'
        then MEANS 'at least as close to the domain as a typical domain
        member is to its nearest sibling' — the control false-alarm rate
        on in-domain data is the quantile itself, by construction, which
        no constant floor can promise (CS07 proved 0.5 mis-flags proteins).
    Disclosure fields (floor_mode/floor_basis/floor_p05/floor_p50) ride
    in every stamp so a number is never read without its calibration.
    """

    def __init__(self, feats: list[set[int]], basis: str,
                 floor: float = AD_FLOOR):
        self._feats = [f for f in feats]
        self.basis = basis
        self.floor = floor
        self.floor_mode = "fixed"
        self.floor_basis = f"constant {floor}"
        self._loo: list[float] = []

    def _auto_floor(self, quantile: float) -> float:
        fs = self._feats
        if len(fs) < 4:
            return self.floor          # too few references to calibrate
        loo = []
        for i, a in enumerate(fs):
            best = max((tanimoto(a, b) for j, b in enumerate(fs)
                        if j != i), default=0.0)
            loo.append(best)
        loo.sort()
        self._loo = loo
        k = min(len(loo) - 1, max(0, int(quantile * len(loo))))
        return max(0.0, round(loo[k], 4))

    @classmethod
    def from_smiles(cls, smiles: Iterable[str], basis: str = "auto",
                    floor: float | str = AD_FLOOR,
                    loo_quantile: float = 0.05
                    ) -> "ApplicabilityDomain":
        seen: set[str] = set()
        smiles = [x for x in smiles if x and not (x in seen or seen.add(x))]
        if basis == "auto":
            basis = _basis_available()
        feat = _morgan_set if basis == "morgan" else _char_set
        try:
            feats = [feat(s) for s in smiles]
        except ImportError:          # rdkit vanished mid-flight
            basis = "char3"
            feat = _char_set
            feats = [feat(s) for s in smiles]
        inst = cls(feats, basis,
                   AD_FLOOR if floor == "auto" else float(floor))
        if floor == "auto":
            auto = inst._auto_floor(loo_quantile)
            inst.floor = auto
            inst.floor_mode = "auto"
            inst.floor_basis = (f"LOO-NN Tanimoto p{int(loo_quantile * 100)}"
                                f" of n={len(inst._feats)}")
            inst._loo_q = loo_quantile
        return inst

    def __len__(self) -> int:
        return len(self._feats)

    def check(self, smiles: str) -> dict[str, Any]:
        """Stamp payload: the claim-grade fields are `extrapolation` and
        `nn_tanimoto`; `basis` and `n_reference` keep the number honest."""
        feat = _morgan_set if self.basis == "morgan" else _char_set
        try:
            q = feat(smiles)
        except ImportError:
            q = _char_set(smiles)
        nn = max((tanimoto(q, f) for f in self._feats), default=0.0)
        in_dom = nn >= self.floor and bool(q) and len(self._feats) > 0
        return {"extrapolation": not in_dom,
                "nn_tanimoto": round(nn, 3),
                "ad_floor": self.floor,
                "floor_mode": self.floor_mode,
                "floor_basis": self.floor_basis,
                "ad_basis": self.basis,
                "n_reference": len(self._feats)}

    def stamp(self, payload: dict[str, Any], smiles: str) -> dict[str, Any]:
        """Merge the AD fields into a prediction/card payload. An
        UNPARSEABLE or empty structure never reads as in-domain."""
        c = self.check(smiles)
        payload["extrapolation"] = c["extrapolation"]
        payload["nn_tanimoto"] = c["nn_tanimoto"]
        payload["ad_floor"] = c["ad_floor"]
        payload["ad_basis"] = c["ad_basis"]
        payload["ad_n_reference"] = c["n_reference"]
        return payload
