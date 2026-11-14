"""BoTorch Gaussian-process policy (optional deps: torch + botorch + rdkit).

Posterior PROVIDER, not a decision layer: it hands `proef.acquisition` a
real epistemic (mean, sd) per candidate instead of the RF tree-spread proxy,
and stays out of every other import path. The acquisition still does ranking,
AD veto, diversity and budget; GP optimization (`optimize_acqf`) is not used
here — its Monte-Carlo randomness would break the byte-exact-replay guarantee
that evals and `proef campaign reproduce` rely on. We only take the posterior.

Determinism: manual_seed makes the (fit, predict) pair reproducible on the
same machine; `noise="fixed"` skips the learned-noise optimizer so the result
is bit-identical, not merely same-seed.
"""
from __future__ import annotations

import numpy as np


class GaussianProcessPolicy:
    name = "morgan-gp"

    def __init__(self, n_bits: int = 2048, radius: int = 2, seed: int = 0,
                 noise: float | str = "fit", nu: float = 2.5,
                 lengthscale: float | None = 256.0):
        # These are NOT defaults-by-taste: the CS04 coverage check found an
        # un-tuned GP pathologically overconfident (1-sigma coverage ~0.06
        # with fixed noise/lengthscale=64, ~0.00 with lengthscale=n_dim),
        # i.e. an uncertainty that is FICTION. Fitted noise + a ~sqrt-scale
        # lengthscale is the starting point that got coverage near nominal.
        # A GP does not hand you calibrated sd for free — you earn it by
        # tuning against held-out outcomes, which is why this provider is
        # opt-in and never the campaign default.
        self.n_bits, self.radius, self.seed = n_bits, radius, seed
        self.noise = noise
        self.nu, self.lengthscale = nu, lengthscale

    # ------------------------------------------------------------ features
    def _fp(self, smiles: str) -> list[float]:
        from rdkit import Chem
        from rdkit.Chem import rdFingerprintGenerator
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return [0.0] * self.n_bits
        gen = rdFingerprintGenerator.GetMorganGenerator(
            radius=self.radius, fpSize=self.n_bits)
        return [float(b) for b in gen.GetFingerprint(mol).ToBitString()]

    # ---------------------------------------------------------------- fit
    def fit(self, data: list[tuple[str, float]]) -> None:
        import torch
        from proef.ad import ApplicabilityDomain
        from proef.adapters.models.gp_policy_gp import _SimpleGP
        from botorch.fit import fit_gpytorch_mll
        from gpytorch.mlls import ExactMarginalLogLikelihood

        torch.manual_seed(self.seed)
        X = torch.tensor([self._fp(s) for s, _ in data], dtype=torch.float)
        y = torch.tensor([v for _, v in data], dtype=torch.float)   # (n,), not (n,1)
        self.y_mean = float(y.mean())
        self.y_std = float(y.std()) if float(y.std()) > 0 else 1.0
        yz = (y - self.y_mean) / self.y_std
        dim = X.shape[1]
        init_ls = self.lengthscale or float(dim)
        gp = _SimpleGP(X, yz, dim=dim, nu=self.nu, lengthscale=init_ls)
        if self.noise == "fit":
            mll = ExactMarginalLogLikelihood(gp.likelihood, gp)
            fit_gpytorch_mll(mll)
        else:                                # fixed noise => no optimizer, exact reruns
            fixed = 1e-3 if self.noise == "fixed" else float(self.noise)
            gp.likelihood.noise = float(fixed)
        gp.eval()
        self._gp = gp
        self.ad = ApplicabilityDomain.from_smiles([s for s, _ in data],
                                                  basis="morgan")

    # ------------------------------------------------------------- predict
    def predict_with_sd(self, smiles: str) -> tuple[float, float]:
        """(mean, sd) in the ORIGINAL y-units — the epistemic spread the
        acquisition wants; sd is the GP posterior std, not a heuristic."""
        import torch
        X = torch.tensor([self._fp(smiles)], dtype=torch.float)
        with torch.no_grad():
            mvn = self._gp(X)              # eval-mode forward = posterior MVN
            mu = float(mvn.mean.item()) * self.y_std + self.y_mean
            sd = float(mvn.variance.sqrt().item()) * self.y_std
        return mu, sd

    def predict(self, smiles: str) -> float:
        return self.predict_with_sd(smiles)[0]

    def predict_with_ad(self, smiles: str) -> tuple[float, dict]:
        mu, sd = self.predict_with_sd(smiles)
        return mu, self.ad.check(smiles)
