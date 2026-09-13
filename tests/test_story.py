"""Story page + figures — the narrative must stay computable and safe."""
import pytest


def test_figures_deterministic_and_labeled():
    pytest.importorskip("pandas")
    from bionexus import figures
    a = figures.get("recovery")
    assert a == figures.get("recovery")
    assert "<svg" in a and "adaptive (Bayesian)" in a
    assert "<svg" in figures.get("stability")
    assert "<svg" in figures.get("evidence")


def test_story_render_bare():
    pytest.importorskip("pandas")
    from bionexus import story
    story.render()          # bare mode: must not raise


def test_narrative_trust_summary_renders():
    pytest.importorskip("pandas")
    from pathlib import Path
    from bionexus import narrative
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.core.contracts import Envelope, EventType
    from bionexus.core.interfaces import record_for, system_actor
    store = SqliteProvenanceStore()
    a = system_actor("t")
    env = Envelope(experiment_branch_id="problem/p1")
    store.append(record_for(env, EventType.hypothesis_proposed, a,
                            decision={"citation": "PMID:1",
                                      "citation_status": "verified"},
                            artifact=None))
    store.append(record_for(env, EventType.gate_decision, a,
                            decision={"kind": "advisory", "advisory": True,
                                      "flags": [{"sample": "X",
                                                 "alert": "acrylamide"}]}))
    narrative.render_trust(store.branch_records("problem/p1"),
                           ["submission for X rejected: [rules safety-rules-v1]"])


def test_verdict_rendering_is_metric_generic():
    """Columns and derivation lines must be generated from the records:
    a qPCR experiment must NOT show IC50/µM anywhere."""
    pytest.importorskip("pandas")
    from types import SimpleNamespace as NS

    from bionexus.derivation import build

    def rec(cand, metric, observed, ci, thr, der, run):
        return NS(event_type=NS(value="hypothesis_validated"),
                  artifact=NS(artifact_id="h", metadata={"candidate": cand}),
                  decision={"verdict": "validated", "metric": metric,
                            "observed": observed, "observed_ci": ci,
                            "threshold": thr, "evidence_run_id": run,
                            "derivation": der})

    qpcr = [rec("sh-KRAS-3", "fold_change", 0.31, None, 0.5,
                build("QuantStudio 5", "qpcr-v2", "Ct",
                      {"wells": 384, "replicates": 4},
                      "fold_change", "delta-delta-Ct"), "qs5-88")]
    from pathlib import Path as P
    script = P("/tmp/_metric_generic_test.py")
    script.write_text(
        "import sys; sys.path.insert(0,'src')\n"
        "from types import SimpleNamespace as NS\n"
        "from bionexus.derivation import build\n"
        "from bionexus import narrative\n"
        "def rec(c,m,o,c2,t,d,r):\n"
        "    return NS(event_type=NS(value='hypothesis_validated'),\n"
        "              artifact=NS(artifact_id='h', metadata={'candidate': c}),\n"
        "              decision={'verdict':'validated','metric':m,'observed':o,\n"
        "                      'observed_ci':c2,'threshold':t,'evidence_run_id':r,\n"
        "                      'derivation':d})\n"
        "narrative.render([rec('sh-KRAS-3','fold_change',0.31,None,0.5,"
        "build('QuantStudio 5','qpcr-v2','Ct',{'wells':384,'replicates':4},"
        "'fold_change','delta-delta-Ct'),'qs5-88')], [])\n")
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(script), default_timeout=60).run()
    assert not at.exception
    cols = []
    for df in at.main.dataframe:
        v = df.value
        c = list(v.columns) if hasattr(v, "columns") else (
            list(v[0].keys()) if isinstance(v, list) and v else [])
        if any("verdict" in str(x) for x in c):
            cols = c
    assert cols and "estimated fold change" in cols
    assert "95% CI" not in cols                    # no CI in records -> no column
    text = " ".join(x.value for x in at.main.caption)
    assert "Ct" in text and "QuantStudio 5" in text
    assert "µM" not in text and "IC50" not in text
