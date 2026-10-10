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
    if isinstance(doc, dict):
        # manifests come in two dialects; a dict without "entries" is the
        # CS07 (source/derived) shape, handled by verify() directly
        return doc.get("entries", [])
    return doc


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
    problems = []
    import gzip
    entries = _entries(study)
    if entries:
        for e in entries:
            p = study / "fixtures" / (e["path"] + ".gz")
            if not p.exists():
                problems.append(f"missing: {e['path']}")
            elif _sha_bytes(gzip.decompress(p.read_bytes())) != e["sha256"]:
                problems.append(f"CHECKSUM MISMATCH: {e['path']}")
        return not problems, problems
    # second manifest dialect (CS07-style MANIFEST.json: source + derived
    # files with raw sha256 and row counts) — both shapes must verify
    m = study / "fixtures" / "MANIFEST.json"
    if m.exists():
        doc = json.loads(m.read_text())
        for name, spec in (doc.get("derived") or {}).items():
            p = study / "fixtures" / (name + ".gz")
            if not p.exists():
                problems.append(f"missing: {name}")
                continue
            raw = gzip.decompress(p.read_bytes())
            if _sha_bytes(raw) != spec["sha256_raw"]:
                problems.append(f"CHECKSUM MISMATCH: {name}")
            elif spec.get("rows") and raw.count(b"\n") - 1 != spec["rows"]:
                problems.append(f"ROW COUNT: {name}")
        src_sha = (doc.get("source") or {}).get("sha256")
        return (not problems), problems
    return False, ["no manifest — run `bn fixtures freeze`"]


# ------------------------------------------------------------- materialize

def materialize(study_dir: str | Path) -> int:
    """Restore frozen fixtures to their live cache locations. The frozen
    copy is CHECKSUM-VERIFIED against the manifest before and after
    materializing — a corrupt or edited .gz never becomes a cache file,
    and an existing cache file that does not match the manifest is
    replaced, not trusted. Returns the number of cache files written."""
    import gzip
    study = Path(study_dir)
    root = study.resolve().parents[1]
    entries = _entries(study)
    if not entries:
        raise FileNotFoundError("no fixtures manifest — run "
                                "`bn fixtures freeze` first")
    # 1. verify every frozen file BEFORE restoring any of it
    ok, problems = verify(study)
    if not ok:
        raise ValueError("fixture integrity check failed: "
                         + "; ".join(problems[:4]))
    n = 0
    for e in entries:
        if not e.get("target"):
            continue
        target = root / e["target"]
        src = study / "fixtures" / (e["path"] + ".gz")
        data = gzip.decompress(src.read_bytes())
        if _sha_bytes(data) != e["sha256"]:
            raise ValueError(f"fixture decompress mismatch: {e['path']}")
        if not target.exists() or target.read_bytes() != data:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            n += 1
    return n
