"""Single source of truth for the dose-response curve model.

Every IC50 path (the plate-reader fit, the adaptive dose designer, the
simulators, the eval generators) uses the SAME forward model — a logistic in
log10(conc) with slope fixed at 1 and bottom at 0:

    r(c) = rmax / (1 + IC50 / c)

— and the same search window, so two entry points cannot disagree about
what an IC50 means or where "out of range" begins.
"""
from __future__ import annotations

# IC50 search window (log10 uM): 0.001 .. ~316 uM. A fit pinned at either
# edge is a range statement ("<=" / ">"), never a measured IC50.
GRID_LOG_LO = -3.0
GRID_LOG_HI = 2.5
GRID_FLOOR_UM = 10 ** GRID_LOG_LO
GRID_CEIL_UM = 10 ** GRID_LOG_HI


def hill_response(conc: float, ic50: float, rmax: float = 100.0,
                  eps: float = 1e-9) -> float:
    """Response at `conc` for the slope-1 / bottom-0 model. `eps` only guards
    conc=0 (simulators historically use 1e-6; the fit uses 1e-9)."""
    return rmax / (1.0 + ic50 / max(conc, eps))
