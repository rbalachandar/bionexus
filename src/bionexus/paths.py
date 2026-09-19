"""Shared local-state paths for the CLI surface (all under .data/)."""
from __future__ import annotations

import os
from pathlib import Path

# Tests redirect this to an isolated temp dir (tests/conftest.py) so
# running pytest can never pollute the user's workbench registry.
DATA_DIR = Path(os.environ.get("BIONEXUS_DATA_DIR", ".data"))
CAMPAIGN_DIR = DATA_DIR / "campaigns"
EXPORT_DIR = DATA_DIR / "exports"


def ensure_dirs() -> None:
    for d in (DATA_DIR, CAMPAIGN_DIR, EXPORT_DIR):
        d.mkdir(parents=True, exist_ok=True)
