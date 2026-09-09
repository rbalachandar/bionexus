"""Case-study data fixtures — byte-reproducible reproductions.

The blind-reproduction studies depend on live ChEMBL data; databases move,
and "we reproduced the paper" quietly rots. Freeze captures the exact bytes
used (checksummed manifest + files committed under
case-studies/<study>/fixtures/); materialize restores them into the caches
the study scripts read, so a fresh clone reproduces offline, identically.

    bn fixtures freeze <study-dir>      # capture current caches (dev)
    bn fixtures verify  <study-dir>     # checksum audit (CI)
    bn fixtures materialize <study-dir> # restore caches if missing (run.py)
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

MANIFEST = "manifest.json"


def _sha(p: Path) -> str:
    return _sha_bytes(p.read_bytes())


def _sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _entries(study: Path) -> list[dict]:
    if not (study / "fixtures" / MANIFEST).exists():
        return []
    doc = json.loads((study / "fixtures" / MANIFEST).read_text())
    return doc["entries"] if isinstance(doc, dict) else doc


# ------------------------------------------------------------------ freeze

def freeze(study_dir: str | Path, sources: list[tuple[str, Path]]) -> dict:
    """sources: [(relpath_in_fixtures, live_path)] — copies + manifests.
    Live paths are recorded repo-root-relative when possible."""
    study = Path(study_dir)
    root = study.resolve().parents[1]
    fx = study / "fixtures"
    fx.mkdir(parents=True, exist_ok=True)
    entries = []
    for rel, src in sources:
        if not src.exists():
            print(f"  skip (missing): {src}")
            continue
        dst = fx / (rel + ".gz")
        dst.parent.mkdir(parents=True, exist_ok=True)
        import gzip
        dst.write_bytes(gzip.compress(src.read_bytes(), compresslevel=9))
        try:
            target = str(Path(src).resolve().relative_to(root))
        except ValueError:
            target = str(src)
        entries.append({"path": rel, "sha256": _sha(src),
                        "bytes": src.stat().st_size, "target": target})
    manifest = {"frozen_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
                "entries": sorted(entries, key=lambda e: e["path"])}
    (fx / MANIFEST).write_text(json.dumps(manifest, indent=1))
    return manifest


# ------------------------------------------------------------------ verify

def verify(study_dir: str | Path) -> tuple[bool, list[str]]:
    study = Path(study_dir)
    entries = _entries(study)
    if not entries:
        return False, ["no manifest — run `bn fixtures freeze`"]
    problems = []
    import gzip
    for e in entries:
        p = study / "fixtures" / (e["path"] + ".gz")
        if not p.exists():
            problems.append(f"missing: {e['path']}")
        elif _sha_bytes(gzip.decompress(p.read_bytes())) != e["sha256"]:
            problems.append(f"CHECKSUM MISMATCH: {e['path']}")
    return not problems, problems


# ------------------------------------------------------------- materialize

def materialize(study_dir: str | Path) -> int:
    """Copy frozen files to their live cache locations unless already
    present. Live paths are recorded in the manifest as 'target'."""
    study = Path(study_dir)
    root = study.resolve().parents[1]
    n = 0
    for e in _entries(study):
        if not e.get("target"):
            continue
        target = root / e["target"]
        src = study / "fixtures" / (e["path"] + ".gz")
        if not src.exists():
            continue
        if not target.exists():
            import gzip
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(gzip.decompress(src.read_bytes()))
            n += 1
    return n
