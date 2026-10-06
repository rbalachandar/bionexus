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
