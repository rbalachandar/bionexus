"""Device card tests — structured capabilities + operator knowledge."""
from bionexus.core.device_card import (DeviceCard, builtin_card, load_card,
                                       save_operator_tags, to_agent_text)


def test_builtin_card_from_capabilities():
    card = builtin_card("sim-01", "Sim plate reader",
                        {"assays": ["binding", "enzymatic"], "bsl_max": 2})
    assert card.protocols == ["binding", "enzymatic"]
    assert any("BSL-2" in s.limit for s in card.safety_limits)
    assert card.adjusts  # temperature + volume knobs declared


def test_operator_tags_merge_dedupe(tmp_path, monkeypatch):
    monkeypatch.setattr("bionexus.core.device_card.DEVICE_DIR", tmp_path)
    card = builtin_card("d1", "Device 1", {"assays": ["binding"]})
    card = save_operator_tags("d1", ["note A", "note B"], base=card)
    card = save_operator_tags("d1", ["note A", "note C"], base=card)
    assert card.notes == ["note A", "note B", "note C"]
    loaded = load_card("d1", base=builtin_card("d1", "Device 1", {"assays": ["binding"]}))
    assert loaded is not None and "note C" in loaded.notes
    assert loaded.source == "interview"


def test_agent_text_contains_all_sections():
    card = builtin_card("d2", "Device 2", {"assays": ["binding"], "bsl_max": 2})
    card.merge_operator_tags(["quirk: arm hits shelf past 90 degrees"])
    txt = to_agent_text(card)
    for section in ("DEVICE:", "supports protocols", "measures:",
                    "adjusts:", "safety limits", "operator knowledge",
                    "arm hits shelf"):
        assert section in txt


def test_load_card_missing_returns_base(tmp_path, monkeypatch):
    monkeypatch.setattr("bionexus.core.device_card.DEVICE_DIR", tmp_path)
    base = builtin_card("d3", "Device 3", {})
    assert load_card("d3", base=base) is base
    assert load_card("nope") is None
