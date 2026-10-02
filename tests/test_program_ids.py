"""Program ids: every program gets a stable human id (PRG-001, …)."""
from bionexus.wizard_store import WizardStore


def test_program_ids_mint_and_backfill(tmp_path, monkeypatch):
    db = str(tmp_path / "wizard.db")
    monkeypatch.setenv("BIONEXUS_DATA_DIR", str(tmp_path))
    ws = WizardStore(db)
    ws.upsert_program("alpha", "Alpha", {"objective": "a"})
    ws.upsert_program("beta", "Beta", {"objective": "b"})
    ws.upsert_program("alpha", "Alpha", {"objective": "a2"})  # refresh: keep id
    assert ws.get_program("alpha")["program_id"] == "PRG-001"
    assert ws.get_program("beta")["program_id"] == "PRG-002"

    # legacy programs without ids are backfilled on open, in creation order
    ws2 = WizardStore(db)
    assert ws2.get_program("alpha")["program_id"] == "PRG-001"
    ws2.upsert_program("gamma", "Gamma", {})
    assert ws2.get_program("gamma")["program_id"] == "PRG-003"
