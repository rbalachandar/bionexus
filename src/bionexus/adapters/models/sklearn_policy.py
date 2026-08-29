"""Real property-model policies (optional deps: rdkit + scikit-learn).

MorganFingerprintRF is the standard cheminformatics baseline: 2048-bit Morgan
fingerprints (radius 2) + Random Forest. This is the row a real model must beat.
"""
from __future__ import annotations

import math


class MorganFingerprintRF:
    name = "morgan2048-rf"

    def __init__(self, n_estimators: int = 300, n_bits: int = 2048, radius: int = 2, seed: int = 0):
        self.n_estimators, self.n_bits, self.radius, self.seed = n_estimators, n_bits, radius, seed

    def _fp(self, smiles: str) -> list[float]:
        from rdkit import Chem
        from rdkit.Chem import rdFingerprintGenerator

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return [0.0] * self.n_bits
        gen = rdFingerprintGenerator.GetMorganGenerator(radius=self.radius, fpSize=self.n_bits)
        return [float(b) for b in gen.GetFingerprint(mol).ToBitString()]

    def fit(self, data: list[tuple[str, float]]) -> None:
        from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

        X = [self._fp(s) for s, _ in data]
        y = [v for _, v in data]
        if all(float(v).is_integer() and v in (0.0, 1.0) for v in set(y)):
            self.task = "classification"
            self.model = RandomForestClassifier(n_estimators=self.n_estimators,
                                                random_state=self.seed, n_jobs=-1,
                                                class_weight="balanced")
        else:
            self.task = "regression"
            self.model = RandomForestRegressor(n_estimators=self.n_estimators,
                                               random_state=self.seed, n_jobs=-1)
        self.model.fit(X, y)

    def predict(self, smiles: str) -> float:
        if self.task == "classification":
            return float(self.model.predict_proba([self._fp(smiles)])[0][1])
        return float(self.model.predict([self._fp(smiles)])[0])
