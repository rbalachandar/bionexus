#!/usr/bin/env python3
"""Write the API's OpenAPI document for the generated TypeScript client.

    python scripts/export_openapi.py            # -> web/openapi.json
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from proef.api.app import app  # noqa: E402

doc = app.openapi()
# the typed workbench contract only; the legacy routes are being retired
doc["paths"] = {p: v for p, v in doc["paths"].items() if p.startswith("/api/v1")}
out = ROOT / "web" / "openapi.json"
out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
print(f"wrote {out} ({len(doc['paths'])} paths)")
