"""DLS analysis — hydrodynamic radius from autocorrelation exports.

Parses dynamic-light-scattering autocorrelation curves (tau vs g2) and
computes, per measurement:

- translational decay rate Gamma from a linear cumulant fit of
  ln(g2 - 1) over the first half-decade of tau
- hydrodynamic radius Rh via the Stokes-Einstein relation:
      Rh = k_B * T / (6 * pi * eta * Gamma)
  (water defaults: T = 298.15 K, eta = 0.890 cP; configurable)
- a polydispersity flag from the late-tau residual: multi-modal
  (aggregated) samples bend the tail upward and fail the linear fit

Rh is an intensity-weighted estimate, not a distribution reconstruction
(CONTIN/regularized inversion needs the full correlation matrix and is
out of scope for a dependency-light core). Aggregation screening — the
biologics Make/Test boundary — is exactly what this estimate is for.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path

# water, 25 C
K_B = 1.380649e-23          # J/K
TEMP_K = 298.15
ETA = 0.00089               # Pa*s
# standard optical configuration: 660 nm laser, n = 1.33, 173 deg
# backscatter — q = 4*pi*n*sin(theta/2)/lambda
WAVELENGTH_NM = 660.0
N_MEDIUM = 1.33
ANGLE_DEG = 173.0


def _q_scattering() -> float:
    import math
    theta = math.radians(ANGLE_DEG)
    return 4 * math.pi * N_MEDIUM * math.sin(theta / 2) / \
        (WAVELENGTH_NM * 1e-9)          # 1/m


def _num(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def read_dls(path: str | Path, temp_k: float = TEMP_K,
             viscosity: float = ETA) -> dict:
    curves: dict[str, list[tuple[float, float]]] = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.DictReader(fh)
        fields = {k.lower().strip(): k for k in (reader.fieldnames or [])}
        tau_col = next((fields[s] for s in ("tau", "time", "lag", "t")
                        if s in fields), None)
        g2_col = next((fields[s] for s in ("g2", "correlation",
                                           "autocorrelation", "g2-1")
                       if s in fields), None)
        if not tau_col or not g2_col:
            raise ValueError("DLS export needs tau + correlation columns; "
                             f"saw {reader.fieldnames}")
        id_col = next((fields[s] for s in ("sample", "measurement", "well",
                                           "id") if s in fields), None)
        for row in reader:
            tau, g2 = _num(row.get(tau_col)), _num(row.get(g2_col))
            if tau is None or g2 is None or tau <= 0:
                continue
            key = str(row.get(id_col, "measurement")) if id_col else "meas"
            curves.setdefault(key, []).append((tau, g2))

    results = []
    for name, pts in sorted(curves.items()):
        pts.sort()
        # cumulant-style linear fit on ln(g2-1) for tau in the first
        # decade where g2 > baseline
        # fit where the signal is still decaying: g2-1 above 10% of its
        # dynamic range — late taus are pure baseline and skew the slope
        g2max = max(g2 for _t, g2 in pts)
        fit_pts = [(t, math.log(max(g2 - 1.0, 1e-9))) for t, g2 in pts
                   if g2 > 1.0 + 0.1 * (g2max - 1.0)]
        fit_pts = fit_pts[:max(3, len(fit_pts))]
        if len(fit_pts) < 3:
            results.append({"measurement": name, "rh_nm": None,
                            "pdi_flag": None, "points": len(pts),
                            "note": "no decaying correlation above "
                                    "baseline — no particles detected"})
            continue
        xs = [t for t, _y in fit_pts]          # linear tau
        ys = [y for _t, y in fit_pts]
        n = len(xs)
        sx, sy = sum(xs), sum(ys)
        sxx = sum(x * x for x in xs)
        sxy = sum(x * y for x, y in zip(xs, ys))
        denom = n * sxx - sx * sx
        slope = (n * sxy - sx * sy) / denom if denom else 0.0
        gamma = max(-slope / 2.0, 1e-6)     # decay rate, 1/s (g2 model)
        # Stokes-Einstein with the standard q: Rh = k_B*T*q^2 / (6*pi*eta*Gamma)
        q = _q_scattering()
        rh_m = (K_B * temp_k * q * q) / (6 * math.pi * viscosity * gamma)
        rh_nm = round(rh_m * 1e9, 2)
        # polydispersity: residual of the tail against the linear fit
        tail = pts[int(len(pts) * 0.6):]
        pred = {t: 1 + math.exp(-2 * gamma * t) for t, _g in pts}
        tail_dev = [abs(g2 - pred.get(t, g2)) for t, g2 in tail
                    if t in pred]
        pdi = (sum(tail_dev) / len(tail_dev)) if tail_dev else 0.0
        results.append({"measurement": name, "rh_nm": rh_nm,
                        "pdi_flag": "aggregated" if pdi > 0.1
                                    else "monodisperse",
                        "points": len(pts), "note": ""})
    return {"source": str(path), "temp_k": temp_k,
            "viscosity_pa_s": viscosity, "curves": results}
