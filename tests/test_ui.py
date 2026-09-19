"""UI vocabulary helpers: icons render, tokens resolve, missing is empty."""
from bionexus.ui import COLORS, icon, small, tagged


def test_icons_render_with_token_colors():
    for name in ("program", "hypothesis", "gate-open", "gate-closed",
                 "halt", "human", "clock", "fault", "history",
                 "instrument", "verdict", "evidence"):
        svg = icon(name, 15, "ink")
        assert "<svg" in svg and name, name
        assert ":color:" not in svg
    assert "#a3402f" in icon("halt", 15, "refused")
    assert "#1f7a86" in icon("gate-open", 15, "autonomous")


def test_tagged_pairs_icon_word_color():
    html = tagged("human", "HUMAN", "human-action")
    assert "HUMAN" in html and "#b07d2b" in html
    assert "<svg" in html          # color never alone: icon + word


def test_missing_icon_is_empty_not_fake():
    assert icon("no-such-icon") == ""


def test_all_tokens_resolve():
    for token in ("refused", "human-action", "autonomous", "fault",
                  "provenance", "progress", "confirmed", "resolved"):
        assert token in COLORS or COLORS.get(token)
    assert small("x", "provenance") == \
        '<small style="color:#8a867c">x</small>'


def test_tree_mapper_positional_alignment():
    """sac.tree(return_index=True) numbers every node in DFS pre-order
    (streamlit_antd_components ParseItems.multi). _TreeMapper.flat must
    align exactly: container nodes -> None, leaves -> their meta. This
    is the regression test for the off-by-N that made program clicks
    open unrelated experiments."""
    from streamlit_antd_components.utils.parser import ParseItems

    from bionexus.webview import _TreeMapper

    m = _TreeMapper()

    def leaf(label, eid):
        return m.emit(label, icon="droplet", meta=eid)

    # program node: container (None) with campaign group -> leaves
    def prog():
        def camp_kids():
            return [leaf("problem 1", "exp-1"), leaf("problem 2", "exp-2")]
        camp = m.emit("Autonomous campaign (2)", icon="group",
                      build_children=camp_kids)
        return camp

    program = m.emit("Material-3", icon="activity", meta=None,
                     build_children=lambda: [prog()])
    # standalone leaf at top level
    standalone = leaf("solo run", "exp-3")

    # parse with the LIBRARY's own keying and cross-check every node
    _r, kv = ParseItems(m.items).multi()
    labels_by_idx = {idx: v for idx, v in kv.items()}
    assert len(m.flat) == len(labels_by_idx)
    for idx, meta in enumerate(m.flat):
        label = labels_by_idx[idx]
        if meta is None:
            assert label in ("Material-3", "Autonomous campaign (2)")
        elif meta == "exp-1":
            assert label == "problem 1"
        elif meta == "exp-2":
            assert label == "problem 2"
        elif meta == "exp-3":
            assert label == "solo run"
        else:
            raise AssertionError(f"unexpected meta {meta!r}")
    # the specific user-reported failure: clicking the program node must
    # NOT resolve to an experiment id
    program_idx = next(i for i, l in labels_by_idx.items()
                       if l == "Material-3")
    assert m.flat[program_idx] is None
    assert standalone is not None


def test_program_relations_roundtrip(tmp_path, monkeypatch):
    """Programs live in relational tables (programs,
    program_experiments); the workspace reads relations, not payload
    tags or JSON blobs. Roundtrip: save -> link -> list -> campaign
    grouping."""
    import sqlite3

    from bionexus import program as program_cfg
    from bionexus.wizard_store import WizardStore

    ws = WizardStore()
    doc = {"program": "Rel-1", "objective": "find X", "custom": True,
           "modality": "material", "metric": "strength", "direction": "max",
           "gate_value": 60, "unit": "MPa", "mode": "autonomous"}
    branch = program_cfg.save_program_record(doc)
    assert branch == "programs/rel-1"

    # relation rows: campaign root + leaf
    program_cfg.record_launch("Rel-1", "root-abc", "find X")
    program_cfg.link_leaf("Rel-1", "exp-1", "root-abc", "sub-problem 1",
                          "verdict_recorded")
    program_cfg.link_leaf("Rel-1", "exp-2", campaign_root=None,
                          question="single experiment")

    progs = program_cfg.list_programs()
    p = next(x for x in progs if x["slug"] == "rel-1")
    assert p["name"] == "Rel-1"
    leaf_eids = {a["eid"] for a in p["attachments"]}
    assert {"exp-1", "exp-2"} <= leaf_eids

    roots = program_cfg.launches_by_program().get("Rel-1", [])
    assert "root-abc" in roots

    links = program_cfg.links_for("rel-1")
    campaigns = [l["eid"] for l in links if l["role"] == "campaign"]
    leaves = [l["eid"] for l in links if l["role"] == "leaf"]
    assert "root-abc" in campaigns
    assert "exp-1" in leaves

    tables = {r[0] for r in ws._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"programs", "program_experiments", "experiments"} <= tables


def test_campaign_spec_roundtrip():
    """Launch details are captured relationally (campaign_specs) and
    readable by the experiment page before provenance catches up."""
    from bionexus.wizard_store import WizardStore

    ws = WizardStore()
    eid = "spec-test-1"
    ws._conn.execute(
        "INSERT OR REPLACE INTO experiments VALUES (?,?,?,?,?,?)",
        (eid, 0, 0, "executing", "test campaign", "{}"))
    ws._conn.commit()
    ws.set_campaign_spec(
        eid, objective="find X", program_slug="rel-1",
        constraints=[{"name": "x", "description": "x >= 5"}],
        success_metric="x gate", k=2, rounds=3, autonomy="act",
        hypothesis_source="agent", n_candidates=0, modality="material")
    spec = ws.get_campaign_spec(eid)
    assert spec["objective"] == "find X"
    assert spec["program_slug"] == "rel-1"
    assert spec["constraints"][0]["name"] == "x"
    assert spec["hypothesis_source"] == "agent"
    assert spec["n_candidates"] == 0
    assert spec["rounds"] == 3
