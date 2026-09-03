"""Shared local-state paths for the CLI surface (all under .data/)."""
from __future__ import annotations

from pathlib import Path

DATA_DIR = Path(".data")
CAMPAIGN_DIR = DATA_DIR / "campaigns"
EXPORT_DIR = DATA_DIR / "exports"


def ensure_dirs() -> None:
    for d in (DATA_DIR, CAMPAIGN_DIR, EXPORT_DIR):
        d.mkdir(parents=True, exist_ok=True)
