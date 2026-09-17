"""Assay analysis adapter tests: ELISA, DSF, DLS — synthetic instrument
exports with known ground truth, parsed and checked against it."""
from pathlib import Path

import pytest


# ---------------------------------------------------------------- ELISA
def _write_elisa(tmp_path: Path) -> Path:
    p = tmp_path / "elisa.csv"
    rows = ["Well,Sample,Conc,OD"]
    # blanks ~0.08; positive sample S1 (max od 1.4); negative S2 (0.1)
    for i, od in enumerate((0.08, 0.09, 0.07)):
        rows.append(f"A{i + 1},blank,0,{od}")
    for i, (dil, od) in enumerate(((10, 1.40), (100, 0.90), (1000, 0.07),
                                   (10000, 0.05))):
        rows.append(f"B{i + 1},S1,{dil},{od}")
    rows.append("C1,S2,0,0.10")
    p.write_text("\n".join(rows) + "\n")
    return p


def test_elisa_cutoff_titer_and_calls(tmp_path):
    from bionexus.assays.elisa import read_elisa
    out = read_elisa(_write_elisa(tmp_path))
    assert out["cutoff"] == pytest.approx(0.095, abs=0.02)
    by = {r["sample"]: r for r in out["results"]}
    assert by["S1"]["call"] == "positive"
    assert by["S1"]["max_od"] == 1.4
    assert by["S1"]["titer"] == 100          # highest dilution >= cutoff
    assert by["S2"]["call"] == "negative"


# ------------------------------------------------------------------ DSF
def _write_dsf(tmp_path: Path, tm_true: float = 65.0) -> Path:
    import math
    p = tmp_path / "dsf.csv"
    rows = ["Well,Temperature,Fluorescence"]
    lo, hi = 40.0, 90.0
    n = 100
    for i in range(n):
        t = lo + (hi - lo) * i / (n - 1)
        f = 20 + 80 / (1 + math.exp(-(t - tm_true) / 2.0))
        rows.append(f"A1,{t:.2f},{f:.3f}")
    p.write_text("\n".join(rows) + "\n")
    return p


def test_dsf_tm_from_melt_curve(tmp_path):
    from bionexus.assays.dsf import read_dsf
    out = read_dsf(_write_dsf(tmp_path, tm_true=65.0))
    c = out["curves"][0]
    assert c["tm"] == pytest.approx(65.0, abs=1.0)
    assert c["span"] > 50


def test_dsf_flat_curve_is_honest(tmp_path):
    p = tmp_path / "flat.csv"
    p.write_text("Temperature,Fluorescence\n" +
                 "".join(f"{40 + i},{50.0}\n" for i in range(20)))
    from bionexus.assays.dsf import read_dsf
    out = read_dsf(p)
    assert out["curves"][0]["tm"] is None
    assert "flat" in out["curves"][0]["note"]


# ------------------------------------------------------------------ DLS
def _write_dls(tmp_path: Path, gamma: float = 5.8e4) -> Path:
    import math
    p = tmp_path / "dls.csv"
    rows = ["Sample,Tau,Correlation"]
    for i in range(60):
        tau = 1e-6 * (1.15 ** i)
        g2 = 1 + 0.8 * math.exp(-2 * gamma * tau)
        rows.append(f"M1,{tau:.3e},{g2:.6f}")
    p.write_text("\n".join(rows) + "\n")
    return p


def test_dls_rh_from_autocorrelation(tmp_path):
    from bionexus.assays.dls import read_dls
    out = read_dls(_write_dls(tmp_path, gamma=5.8e4))
    c = out["curves"][0]
    assert c["rh_nm"] == pytest.approx(2.7, rel=0.15)   # gamma=5.8e4 @ standard q
    assert c["pdi_flag"] == "monodisperse"


def test_dls_aggregated_flag(tmp_path):
    # aggregated samples show a slow second component: high tail
    import math
    gamma = 5.8e4
    p = tmp_path / "agg.csv"
    rows = ["Sample,Tau,Correlation"]
    for i in range(60):
        tau = 1e-6 * (1.15 ** i)
        g2 = 1 + 0.8 * math.exp(-2 * gamma * tau)
        tail_boost = 0.15 if i > 40 else 0.0
        rows.append(f"M1,{tau:.3e},{g2 + tail_boost:.6f}")
    p.write_text("\n".join(rows) + "\n")
    from bionexus.assays.dls import read_dls
    out = read_dls(p)
    assert out["curves"][0]["pdi_flag"] in ("aggregated", "monodisperse")
    # the flag must exist either way; strict assert on threshold behavior:
    assert out["curves"][0]["pdi_flag"] == "aggregated"
