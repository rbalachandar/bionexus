"""ChEMBL-derived gate tests — pure math + labeled fallback (offline)."""
import csv

from bionexus.adapters.databases import chembl_gates as G


def _acts(n, lo=6.0, hi=9.0):
    # uniform pIC50 actives between lo and hi
    return [lo + (hi - lo) * i / (n - 1) for i in range(n)]


def test_derive_gates_top_quartile_and_10x():
    pic50s = _acts(400, 6.0, 9.0)
    hit, lead, med = G.derive_gates(pic50s)
    # top quartile of 6..9 is pIC50 ~8.25 -> 10^(9-8.25) ~= 5.6 nM
    assert 5.0 < hit < 6.5
    assert abs(lead - max(1.0, hit / 10)) < 0.1   # 10x, floored at 1 nM
    assert med > 6.0


def test_derive_gates_too_thin_returns_none():
    assert G.derive_gates(_acts(30)) is None
    assert G.derive_gates([5.0] * 500) is None      # nothing counts as active


def test_suggest_fallback_is_labeled(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "lookup_targets",
                        lambda name: (_ for _ in ()).throw(OSError("offline")))
    prof = G.suggest("MAP4K1")
    assert prof.source == "fallback"
    assert prof.hit_ic50_nm == G.CONVENTIONAL_HIT_NM
    assert "offline" in prof.basis


def test_suggest_chembl_path(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "lookup_targets", lambda name: ["CHEMBL203"])

    def fake_fetch(cid, **kw):
        p = tmp_path / "acts.csv"
        with p.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["smiles", "pic50", "assay"])
            w.writeheader()
            for i, pic in enumerate(_acts(200, 6.0, 8.0)):
                w.writerow({"smiles": f"C{i}", "pic50": f"{pic:.3f}",
                            "assay": "a"})
        return p
    monkeypatch.setattr(G, "fetch_target_activities", fake_fetch)
    prof = G.suggest("EGFR")
    assert prof.source == "chembl"
    assert prof.chembl_id == "CHEMBL203"
    assert prof.hit_ic50_nm < 1000.0            # EGFR actives are potent
    assert "top-quartile" in prof.basis
