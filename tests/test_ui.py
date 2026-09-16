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
