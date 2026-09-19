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
