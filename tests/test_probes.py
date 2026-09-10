"""Variant contamination probe tests (offline, stub agent)."""
import pytest

from bionexus.probes import perturb_smiles, variant_contamination

rdkit = pytest.importorskip("rdkit", reason="perturbation validity needs rdkit")

from rdkit import Chem


def test_perturb_is_valid_and_different():
    for smi in ["Fc1ccccc1", "CC(=O)Oc1ccccc1C(=O)O", "C1CCCCC1"]:
        v = perturb_smiles(smi)
        assert v and v != Chem.MolToSmiles(Chem.MolFromSmiles(smi))
        assert Chem.MolFromSmiles(v) is not None


def test_variant_probe_flags_a_memorizing_stub():
    class Stub:
        def generate(self, inv, prompt):
            class R: output = {"text": "This is from the HPK1 pyrazine "
                                       "carboxamide series, J Med Chem."}
            return R()
    out = variant_contamination(Stub(), ["hpk1", "pyrazine carboxamide"],
                                ["Fc1ccccc1", "CC(=O)Oc1ccccc1C(=O)O"])
    assert out["verdict"] == "CONTAMINATED-VARIANTS"


def test_variant_probe_clean_on_honest_stub():
    class Stub:
        def generate(self, inv, prompt):
            class R: output = {"text": "unknown"}
            return R()
    out = variant_contamination(Stub(), ["hpk1"], ["Fc1ccccc1"])
    assert out["verdict"] == "clean"
