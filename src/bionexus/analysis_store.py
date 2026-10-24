"""Analysis-session persistence + artifact storage (generic lifecycle).

One row per analysis in the wizard store's SQLite DB (same store the
guided experiment registry uses), one JSON doc per session. Artifacts live
under DATA_DIR/analyses/<id>/ with GENERATED names — the user's filename
is sanitized display metadata only and never a storage path.

Immutable revisions: changing the config (or the source bytes on
re-upload) creates a NEW revision inside the doc; a stored analysis result
is never rewritten.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any

from bionexus.core.contracts.analysis import (AnalysisArtifact,
                                              HumanDisposition)
from bionexus.paths import DATA_DIR
from bionexus.wizard_store import WizardStore

MAX_UPLOAD_BYTES = 32 * 1024 * 1024
ALLOWED_SUFFIXES = {".csv", ".tsv", ".txt", ".xlsx", ".npy"}


def ensure_tables() -> None:
    ws = _ws()
    ws._conn.execute("""
        CREATE TABLE IF NOT EXISTS analysis_sessions (
            id TEXT PRIMARY KEY,
            profile TEXT NOT NULL,
            state TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1,
            doc TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )""")
    ws._conn.commit()


def _ws() -> WizardStore:
    return WizardStore()


def artifact_dir(aid: str) -> Path:
    d = DATA_DIR / "analyses" / aid
    d.mkdir(parents=True, exist_ok=True)
    return d


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def store_artifact(aid: str, kind: str, filename: str, content: bytes) -> AnalysisArtifact:
    """Persist upload bytes unchanged under a generated name; digest binds
    the chain to the bytes. Oversized/disallowed uploads are typed errors."""
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError(f"unsupported upload type: {suffix or '(none)'}")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError(f"upload exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit")
    from bionexus.labread import sanitize_label
    d = artifact_dir(aid)
    name = f"{kind}-{uuid.uuid4().hex[:8]}{suffix}"
    path = d / name
    path.write_bytes(content)
    return AnalysisArtifact(
        kind=kind, storage_path=str(path),
        original_name=sanitize_label(Path(filename).name, 80),
        sha256=sha256_of(path), size=len(content))


def create(aid: str, profile: str, config: dict, source: AnalysisArtifact,
           layout: AnalysisArtifact | None, preview: dict) -> tuple[str, dict]:
    """Create a session (with its pre-generated id) from an upload + its
    preview payload."""
    ensure_tables()
    now = time.time()
    doc: dict[str, Any] = {
        "profile": profile,
        "config": config,
        "artifacts": {"source": source.model_dump(),
                      "layout": layout.model_dump() if layout else None},
        "dispositions": [],
        "revisions": [{"revision": 1, "config": config,
                       "source_sha256": source.sha256,
                       "layout_sha256": layout.sha256 if layout else None,
                       "at": now}],
        "preview": preview,
        "result": None,
    }
    ws = _ws()
    ws._conn.execute(
        "INSERT INTO analysis_sessions VALUES (?,?,?,?,?,?,?)",
        (aid, profile, str(preview.get("state") or "preview_ready"), 1,
         json.dumps(doc), now, now))
    ws._conn.commit()
    return aid, doc


def _load_row(aid: str):
    row = _ws()._conn.execute(
        "SELECT profile, state, revision, doc FROM analysis_sessions "
        "WHERE id=?", (aid,)).fetchone()
    if not row:
        raise KeyError(f"analysis session {aid} not found")
    return row


def get(aid: str) -> dict:
    profile, state, revision, doc = _load_row(aid)
    d = json.loads(doc)
    return {"id": aid, "profile": profile, "state": state,
            "revision": revision, **d}


def list_recent(limit: int = 50) -> list[dict]:
    ensure_tables()
    rows = _ws()._conn.execute(
        "SELECT id, profile, state, revision, updated_at FROM "
        "analysis_sessions ORDER BY updated_at DESC LIMIT ?",
        (limit,)).fetchall()
    return [{"id": r[0], "profile": r[1], "state": r[2], "revision": r[3],
             "updated_at": r[4]} for r in rows]


def update(aid: str, state: str, doc_mutate=None, bump_revision: bool = False
           ) -> dict:
    """Persist a transition. doc_mutate(d) edits the doc in place;
    bump_revision opens a NEW immutable revision for a config change."""
    profile, _state, revision, doc = _load_row(aid)
    d = json.loads(doc)
    if doc_mutate:
        doc_mutate(d)
    if bump_revision:
        revision += 1
        d["revisions"].append({
            "revision": revision, "config": d.get("config"),
            "source_sha256": (d.get("artifacts", {}).get("source") or {}).get("sha256"),
            "layout_sha256": (d.get("artifacts", {}).get("layout") or {}).get("sha256"),
            "at": time.time()})
    ws = _ws()
    ws._conn.execute(
        "UPDATE analysis_sessions SET state=?, revision=?, doc=?, "
        "updated_at=? WHERE id=?",
        (state, revision, json.dumps(d), time.time(), aid))
    ws._conn.commit()
    return {"id": aid, "profile": profile, "state": state,
            "revision": revision, **d}


def add_disposition(aid: str, disposition: HumanDisposition) -> dict:
    def _mutate(d: dict):
        d.setdefault("dispositions", []).append(disposition.model_dump())
    return update(aid, "reviewed", _mutate)


def reconfigure(aid: str, config: dict, new_preview: dict) -> dict:
    """A changed scientific configuration opens a NEW revision; the stored
    result stays with the revision that produced it."""
    def _mutate(d: dict):
        d["config"] = config
        d["preview"] = new_preview
        d["result"] = None
    # a confirmed config advances the session; a profile hold passes through
    pstate = str(new_preview.get("state") or "preview_ready")
    state = "configured" if pstate == "preview_ready" else pstate
    return update(aid, state, _mutate, bump_revision=True)


def store_result(aid: str, result: dict) -> dict:
    def _mutate(d: dict):
        d["result"] = result
    return update(aid, str(result.get("state") or "analyzed"), _mutate)
