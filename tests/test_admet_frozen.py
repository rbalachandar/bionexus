"""The frozen TDC ADMET tier: integrity first, then the ladder."""
import hashlib
import json
from pathlib import Path

FROZEN = Path("src/bionexus/adapters/data/frozen/admet")


def test_manifest_checksums_hold():
    man = json.loads((FROZEN / "MANIFEST.json").read_text())
    assert len(man["entries"]) == 6
    for e in man["entries"]:
        b = (FROZEN / e["path"]).read_bytes()
        assert hashlib.sha256(b).hexdigest() == e["sha256"], e["path"]
        assert len(b) == e["bytes"]
    assert "10.5281/zenodo.10372419" in man["provenance"]
    assert set(man["citations"]) == {"caco2_wang", "hia_hou", "bbb_martins"}


def test_loaders_yield_splits_and_types():
    from bionexus.adapters.data.admet import ADMETSplitDataset
    tr = list(ADMETSplitDataset("caco2_wang").train())
    te = list(ADMETSplitDataset("caco2_wang").test())
    assert (len(tr), len(te)) == (728, 182)         # TDC 80/20 scaffold folds
    assert ADMETSplitDataset("hia_hou").task == "classification"
    ys = [y for _, y in te]
    assert min(ys) < 0  # log-permeability regression scale
    binary = {y for _, y in ADMETSplitDataset("bbb_martins").test()}
    assert binary <= {0.0, 1.0}
    assert len(list(ADMETSplitDataset("hia_hou").test())) == 117


def test_ladder_clears_bars_on_canonical_folds():
    from bionexus.evals.harness import run_split_pinned_task
    r = run_split_pinned_task("bbb_martins", min_score=0.65)
    assert r.passed and r.metrics["splits"] == "TDC canonical scaffold (20% test)"
    assert r.metrics["best_policy"] == "char3gram-ridge"
