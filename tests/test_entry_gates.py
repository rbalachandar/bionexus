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
    import importlib.util
    import hashlib
    spec = importlib.util.spec_from_file_location(
        "jobrunner", Path(__file__).parents[1] /
        "case-studies/08-proteinbase-entry/runpack/jobrunner.py")
    jr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(jr)
    fasta = tmp_path / "d.fasta"
    fasta.write_text(">short\nMABCDEFGH\n"
                     ">good1\n" + "MADGHLNIKPQSTVWYEF" * 10 + "\n"
                     ">good2\n" + "MQPKTRYHNSVAWLEGFC" * 9 + "\n"
                     ">tooclose\n" + "MADGHLNIKPQSTVWYEF" * 10 + "\n"
                     ">toolong\n" + "MA" * 200 + "\n")
    binders = tmp_path / "b.fasta"
    binders.write_text(">known\n" + "MADGHLNIKPQSTVWYEF" * 10 + "\n")
    work = tmp_path / "work"
    jr.main(["--fasta", str(fasta), "--binders", str(binders),
             "--n-slots", "2", "--work", str(work)])
    man = json.loads((work / "submission_manifest.json").read_text())
    ids = {r["id"] for r in man["selected"]}
    assert "tooclose" not in ids          # near-copy rule enforced
    assert "toolong" not in ids           # length rule enforced
    assert "good1" in ids and "good2" in ids
    reasons = {r["id"]: r["gate_reasons"] for r in man["rejected_sample"]}
    assert any("outside" in x for x in reasons.get("toolong", []))
    assert any("near-copy" in x for x in reasons.get("tooclose", []))
    body = {k: v for k, v in man.items() if k != "sha256_of_manifest_body"}
    assert man["sha256_of_manifest_body"] == hashlib.sha256(
        json.dumps(body, sort_keys=True).encode()).hexdigest()
