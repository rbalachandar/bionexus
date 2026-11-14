"""Simulate the biologics readouts — synthetic instrument exports with
known ground truth, for pipeline validation without physical machines.

- DLS: Brownian motion + scattering physics per the Raynals approach —
  each particle size contributes exp(-Gamma_i * tau) to the FIELD
  correlation; g2 = 1 + beta * |sum(w_i g1_i)|^2. A distribution of
  sizes produces a Tikhonov-style multi-exponential decay. Deterministic
  under a seed; noise is Gaussian.
- ELISA: 4-parameter logistic (4PL) antigen-antibody saturation —
  response = bottom + (top - bottom) / (1 + (conc/ec50)^hill), plus
  blank wells and Gaussian noise.
- DSF: two-state Boltzmann unfolding — fraction folded = 1/(1 +
  exp((T - Tm)/steepness)), folded + unfolded baselines, Gaussian noise.

Every simulator returns (rows, truth): `rows` are CSV-ready instrument
lines, `truth` is the ground truth the matching analysis adapter must
recover. roundtrip tests assert exactly that.
"""
from __future__ import annotations

import math
import random

# water, 25 C, standard 660 nm / 173 deg backscatter (matches assays.dls)
K_B = 1.380649e-23
TEMP_K = 298.15
ETA = 0.00089
Q_SCATTERING = 2.528e7            # 1/m (see assays.dls._q_scattering)


def _gamma_for_rh(rh_nm: float) -> float:
    """Translational decay rate of a particle with hydrodynamic radius
    rh_nm: Gamma = D * q^2, D = k_B*T / (6*pi*eta*Rh)."""
    d = (K_B * TEMP_K) / (6 * math.pi * ETA * (rh_nm * 1e-9))
    return d * Q_SCATTERING ** 2


# ------------------------------------------------------------------- DLS

def simulate_dls(species: list[tuple[float, float]],
                 beta: float = 0.8,
                 n_points: int = 60,
                 tau_start_s: float = 1e-6,
                 tau_growth: float = 1.15,
                 noise: float = 0.004,
                 seed: int = 7,
                 sample_id: str = "M1") -> tuple[list[dict], dict]:
    """species = [(rh_nm, weight), ...] (weights need not sum to 1).
    Returns (rows, truth)."""
    rh_list = [rh for rh, _w in species]
    truth = {
        "rh_intensity_weighted_nm": round(
            sum(rh * w for rh, w in species) / sum(w for _r, w in species),
            3),
        "gammas": [round(_gamma_for_rh(rh), 1) for rh, _w in species],
        "species": species, "seed": seed}
    rng = random.Random(seed)
    rows = []
    tau = tau_start_s
    for _i in range(n_points):
        g1 = sum(w * math.exp(-_gamma_for_rh(rh) * tau)
                 for rh, w in species)
        g2 = 1.0 + beta * g1 * g1 + rng.gauss(0, noise)
        rows.append({"Sample": sample_id, "Tau": f"{tau:.3e}",
                     "Correlation": f"{max(g2, 1.0):.6f}"})
        tau *= tau_growth
    return rows, truth


# ----------------------------------------------------------------- ELISA

def simulate_elisa(top: float = 1.5, bottom: float = 0.08,
                   ec50: float = 120.0, hill: float = 1.2,
                   dilutions: list[int] | None = None,
                   n_blanks: int = 3, blank_od: float = 0.08,
                   noise: float = 0.01,
                   seed: int = 11,
                   sample_id: str = "S1") -> tuple[list[dict], dict]:
    """4PL antigen-antibody saturation over a dilution series. The
    dilution column is 1/dilution-factor order as in real serology
    exports (lowest concentration first)."""
    dilutions = dilutions or [0.001, 0.01, 0.1, 1.0, 10.0]
    rng = random.Random(seed)

    def well(i: int) -> str:
        # standard 96-well coordinates: A1.. row-major (12 columns)
        return f"{chr(65 + i // 12)}{i % 12 + 1}"

    rows = [{"Well": well(i), "Sample": "blank", "Conc": "0",
             "OD": f"{blank_od + rng.gauss(0, noise):.4f}"}
            for i in range(n_blanks)]
    truth = {"top": top, "bottom": bottom, "ec50": ec50, "hill": hill,
             "seed": seed}
    for i, dil in enumerate(dilutions):
        resp = bottom + (top - bottom) / (1 + (dil / ec50) ** hill)
        rows.append({"Well": well(n_blanks + i), "Sample": sample_id,
                     "Conc": str(dil),
                     "OD": f"{max(resp + rng.gauss(0, noise), 0):.4f}"})
    return rows, truth


# ------------------------------------------------- materials property sweep

def simulate_property_sweep(formulations: list[float],
                            optimum: float = 6.0,
                            peak_value: float = 85.0,
                            width: float = 2.5,
                            noise: float = 1.5,
                            seed: int = 13,
                            metric: str = "tensile_strength_mpa",
                            param: str = "crosslinker_pct") -> tuple[
        list[dict], dict]:
    """Materials Design-of-Experiments: a property responds to a
    formulation parameter through a smooth peak (quadratic around the
    optimum) — tensile strength vs crosslinker density, conductivity vs
    dopant ratio, etc. Deterministic; truth carries the true optimum so
    the analysis adapter can be checked against it."""
    rng = random.Random(seed)
    rows, values = [], []
    for i, x in enumerate(formulations):
        v = peak_value - ((x - optimum) / width) ** 2 * 10
        v = max(0.0, v + rng.gauss(0, noise))
        values.append(v)
        rows.append({"Sample": f"F{i + 1}", param: f"{x:g}",
                     metric: f"{v:.2f}"})
    return rows, {"true_optimum": optimum, "peak_value": peak_value,
                  "metric": metric, "param": param,
                  "measured_best": formulations[max(range(len(values)),
                                                    key=values.__getitem__)],
                  "measured_best_value": round(max(values), 2),
                  "seed": seed}


# ------------------------------------------------------------------ DSF

def simulate_dsf(tm: float = 65.0, steepness: float = 2.0,
                 folded_baseline: float = 20.0,
                 unfolded_baseline: float = 100.0,
                 t_range: tuple[float, float] = (40.0, 90.0),
                 n_points: int = 100, noise: float = 0.6,
                 seed: int = 3,
                 well: str = "A1") -> tuple[list[dict], dict]:
    """Two-state Boltzmann unfolding: fraction folded =
    1 / (1 + exp((T - Tm)/steepness)); signal = folded*base_f +
    unfolded*base_u + noise."""
    rng = random.Random(seed)
    rows, truth = [], {"tm": tm, "steepness": steepness, "seed": seed}
    lo, hi = t_range
    for i in range(n_points):
        t = lo + (hi - lo) * i / (n_points - 1)
        folded = 1.0 / (1.0 + math.exp((t - tm) / steepness))
        signal = (folded_baseline * folded
                  + unfolded_baseline * (1 - folded)
                  + rng.gauss(0, noise))
        rows.append({"Well": well, "Temperature": f"{t:.2f}",
                     "Fluorescence": f"{signal:.3f}"})
    return rows, truth
