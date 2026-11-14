"""Minimal exact GP (gpytorch) used by gp_policy.GaussianProcessPolicy.

Small on purpose: constant mean, Matern(ν, ARD-off) kernel, Gaussian
likelihood. ARD-off + a fixed `lengthscale` init keeps it from burning
compute chasing per-dimension lengthscales over a 2048-bit fingerprint —
a deliberate, stated approximation, not an oversight; the acquisition needs
a usable epistemic sd, not the most-tuned GP in the literature.
"""
from __future__ import annotations

import gpytorch
import torch


class _SimpleGP(gpytorch.models.ExactGP):
    def __init__(self, train_X: torch.Tensor, train_Y: torch.Tensor,
                 dim: int, nu: float = 2.5, lengthscale: float = 64.0):
        super().__init__(train_X, train_Y,
                         gpytorch.likelihoods.GaussianLikelihood())
        self.mean_module = gpytorch.means.ConstantMean()
        self.covar_module = gpytorch.kernels.ScaleKernel(
            gpytorch.kernels.MaternKernel(
                nu=nu, ard_num_dims=None,
                lengthscale_prior=None,
                lengthscale_constraint=gpytorch.constraints.Positive(),
            ).initialize(lengthscale=lengthscale)
        )

    def forward(self, x: torch.Tensor):
        return gpytorch.distributions.MultivariateNormal(
            self.mean_module(x), self.covar_module(x))

    def transform_inputs(self, X: torch.Tensor) -> torch.Tensor:
        # we standardize y ourselves and leave X raw, so this pass-through
        # is what botorch's fit-closure expects from a Model
        return X
