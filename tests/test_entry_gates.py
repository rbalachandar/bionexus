import importlib.util
import json
from pathlib import Path

import pytest

STUDY = Path(__file__).parents[1] / "case-studies" / "08-proteinbase-entry"


def _mod(name):
    spec = importlib.util.spec_from_file_location(name, STUDY / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


gates = _mod("entry_gates")
sel = _mod("diversity_select")


def test_gate_rules_refuse_and_explain():
    ok = gates.check_sequence("M*" + "A" * 10)
    assert not ok["pass"] and any("non-standard" in r for r in ok["reasons"])
    assert not gates.check_sequence("A" * 300)["pass"]
    assert not gates.check_sequence("A" * 60 + "C" * 10)["pass"]
    good = gates.check_sequence("MGS" + "ADEFGHIKLMNPQRSTVWY" * 8)  # no native C
    assert good["pass"], good["reasons"]


def test_near_copy_detection():
    unit = "ADGHLNIKPQSTVWYEFM" * 12
    binder = "M" + unit[:180]
    near = binder[:160] + binder[:20]            # duplicated tail, zero novel
    # 5-mers near-identical; the >=10-mutations proxy is containment,
    # not edit count — a sequence that is 0.95 the same 5-mer soup is
    # a near-copy regardless of where the changes sit
    far = "MKFFAALLSSGG" + "QPKTRYQPRKHTSQNVWCGD" * 4
    assert gates.too_close_to_binders(near, [binder])
    assert not gates.too_close_to_binders(far, [binder])


def test_diversity_picks_distinct():
    items = [("a", gates._kmers("AAAAA" * 20)),
             ("b", gates._kmers("AAAAA" * 20)),      # twin of a
             ("c", gates._kmers("WKMTVPELKMTVPELKM" * 3))]
    picks = sel.select_diverse(items, 2)
    assert set(picks) == {"a", "c"} or set(picks) == {"b", "c"}


def test_replay_artifact_exists_and_honest():
    r = json.loads((STUDY / "replay_results.json").read_text())
    for tgt, d in r.items():
        assert d["hit_plddt_top"] < d["hit_baseline"]        # negative kept
        assert abs(d["hit_gated_random"] - d["hit_baseline"]) < 0.015


def test_runpack_jobrunner_mock_flow(tmp_path):
    import hashlib
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "jobrunner", Path(__file__).parents[1] /
        "case-studies/08-proteinbase-entry/runpack/jobrunner.py")
    jr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(jr)
    U1 = "MADGHLNIKPQSTVWYEW" * 10          # cysteine-free, 180aa: good
    U2 = "MQPKTRYHNSVAWLEGFA" * 9           # cysteine-free, 162aa: good
    K = "MWELIFVTSQPKINIHGDAL" * 9          # an INDEPENDENT known binder
    fasta = tmp_path / "d.fasta"
    fasta.write_text(">short\nMABCDEFGH\n"
                     ">good1\n" + U1 + "\n"
                     ">good2\n" + U2 + "\n"
                     ">tooclose\n" + K[:160] + K[:20] + "\n"
                     ">toocys\n" + "MADCADCGDA" * 20 + "\n"
                     ">toolong\n" + "MA" * 200 + "\n")
    binders = tmp_path / "b.fasta"
    binders.write_text(">known\n" + K + "\n")
    work = tmp_path / "work"
    jr.main(["--fasta", str(fasta), "--binders", str(binders),
             "--n-slots", "2", "--work", str(work)])
    man = json.loads((work / "submission_manifest.json").read_text())
    ids = {r["id"] for r in man["selected"]}
    assert ids == {"good1", "good2"}        # only clean designs survive all 3 stages
    reasons = {r["id"]: r["gate_reasons"] for r in man["rejected_sample"]}
    assert any("outside" in x for x in reasons["toolong"])
    assert any("near-copy" in x for x in reasons["tooclose"])
    assert any("cysteine" in x.lower() for x in reasons["toocys"])
    body = {k: v for k, v in man.items() if k != "sha256_of_manifest_body"}
    assert man["sha256_of_manifest_body"] == hashlib.sha256(
        json.dumps(body, sort_keys=True).encode()).hexdigest()
