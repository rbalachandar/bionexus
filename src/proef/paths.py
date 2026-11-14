"""Shared local-state paths for the CLI surface (all under .data/)."""
from __future__ import annotations

import os
from pathlib import Path

# Tests redirect this to an isolated temp dir (tests/conftest.py) so
# running pytest can never pollute the user's workbench registry.
DATA_DIR = Path(os.environ.get("PROEF_DATA_DIR", ".data"))
CAMPAIGN_DIR = DATA_DIR / "campaigns"
EXPORT_DIR = DATA_DIR / "exports"
APPROVALS_FILE = DATA_DIR / "approvals.jsonl"   # gate-mode inbox, one place


def ensure_dirs() -> None:
    for d in (DATA_DIR, CAMPAIGN_DIR, EXPORT_DIR):
        d.mkdir(parents=True, exist_ok=True)


def migrate_legacy_workspace(cwd: Path | None = None) -> bool:
    """One-time, non-destructive: a workspace created under the old name keeps its
    ledger. Renames bionexus.db (+ WAL/SHM) to proef.db when proef.db does not exist.
    Run it while no other process has the old file open. Record contents are never touched."""
    base = cwd or Path(".")
    old, new = base / "bionexus.db", base / "proef.db"
    if not old.exists() or new.exists():
        return False
    for suffix in ("", "-wal", "-shm"):
        src = base / ("bionexus.db" + suffix)
        if src.exists():
            src.rename(base / ("proef.db" + suffix))
    return True
