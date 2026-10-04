"""Institutional-memory ingestion — the inverse of `bn prove --eln`.

What the lab learned BEFORE BioNexus existed must count. `ingest_eln`
reads an ELN-style CSV — either the export format itself (bn prove
--eln) or a simple lab table (candidate,outcome,observed_uM,...) — and
feeds two places:

1. the flywheel: negative memory ("ALREADY RULED OUT") and family
   priors now include pre-BioNexus history, with the import source
   stamped into evidence_run so history never masquerades as a live run;
2. the provenance chain (optional): one gate_decision record per
   scientific row under external/<file>, carrying the file's sha256 —
   imports are auditable, and an edited-after-export CSV is LOUDLY
   flagged (export_eln writes a .sha256 sidecar; we verify against it).

Nothing is silently dropped: every skipped row is reported with a
reason. Simulated/external data must say so (P-conventions).
"""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path
from typing import Any

VERDICT_MAP = {  # lab vocabularies -> flywheel outcome
    "confirmed": "confirmed", "validated": "validated", "active": "validated",
    "hit": "validated",
    "invalidated": "invalidated", "refuted": "refuted", "failed": "invalidated",
    "rejected": "invalidated", "abandoned": "invalidated", "dead": "invalidated",
    "inconclusive": "inconclusive", "abstained": "inconclusive",
    "tested": "tested",
}
_ALIASES = {"outcome": "verdict", "result": "verdict", "status": "verdict",
            "ic50_uM": "observed_uM", "ic50": "observed_uM",
            "observed": "observed_uM", "potency_uM": "observed_uM",
            "ci_low_uM": "ci95_low_uM", "ci_high_uM": "ci95_high_uM",
            "compound": "candidate", "compound_id": "candidate",
            "family_id": "family", "assay_type": "assay"}


def _num(s: Any) -> float | None:
    try:
        return float(s) if s not in ("", None) else None
    except (TypeError, ValueError):
        return None


def read_eln_csv(path: str | Path) -> list[dict[str, str]]:
    """Rows normalized onto the ELN export column names (alias-mapped,
    case-insensitive headers, BOM-tolerant)."""
    p = Path(path)
    raw = p.read_bytes()
    text = raw.decode("utf-8-sig", errors="replace")
    out: list[dict[str, str]] = []
    for row in csv.DictReader(text.splitlines()):
        norm = {}
        for k, v in row.items():
            if k is None:
                continue
            kk = k.strip().lower()
            for alias, target in _ALIASES.items():
                if kk == alias.lower():
                    kk = target.lower()
                    break
            norm[kk] = (v or "").strip()
        # ELN columns already lowercase; canonicalize the canonical names
        for col in ("candidate", "verdict", "family", "assay", "observed_uM",
                    "ci95_low_uM", "ci95_high_uM", "threshold", "run_id",
                    "event", "branch", "record_hash"):
            norm.setdefault(col, norm.get(col, ""))
        out.append(norm)
    return out


def ingest_eln(path: str | Path, *, flywheel: Any, store: Any = None,
               problem_id: str | None = None, dry_run: bool = False,
               branch_root: str = "external") -> dict[str, Any]:
    """Import an ELN CSV into flywheel memory (+ provenance chain).

    Returns {source, sha256, checksum_match, rows, ingested,
    provenance_written, skipped:[{row, reason}]}."""
    p = Path(path)
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    sidecar = p.with_suffix(p.suffix + ".sha256")
    checksum_match: bool | None = None
    if sidecar.exists():  # written by export_eln: the detached seal
        expected = sidecar.read_text().split()[0] if sidecar.stat().st_size else ""
        checksum_match = (expected == digest)
    rows = read_eln_csv(p)
    source_tag = f"eln:{p.name}:{digest[:8]}"
    summary: dict[str, Any] = {"source": str(p), "sha256": digest,
                               "checksum_match": checksum_match,
                               "rows": len(rows), "ingested": 0,
                               "provenance_written": 0, "skipped": []}
    if checksum_match is False:
        summary["skipped"].append(
            {"row": -1, "reason": "WARNING: .sha256 sidecar does not match "
                                  "the CSV — the export was edited after "
                                  "`bn prove --eln`; values were still "
                                  "imported, but treat them as unsealed"})

    records = []
    for i, row in enumerate(rows):
        cand = row.get("candidate") or ""
        verdict = (row.get("verdict") or "").lower()
        if not cand:
            if verdict:  # a scientific verdict with no candidate: unusable
                summary["skipped"].append(
                    {"row": i, "reason": "no candidate column"})
            continue     # non-scientific event (problem_defined, review...)
        if not verdict:
            continue     # structural row (proposed without verdict, gate...)
        outcome = VERDICT_MAP.get(verdict)
        if outcome is None:
            summary["skipped"].append(
                {"row": i, "reason": f"unknown verdict '{verdict}'"})
            continue
        observed = _num(row.get("observed_uM"))
        lo, hi = _num(row.get("ci95_low_uM")), _num(row.get("ci95_high_uM"))
        ci = (lo, hi) if lo is not None and hi is not None else None
        run = row.get("run_id") or ""
        if not dry_run:
            flywheel.submit(cand, row.get("family") or None,
                            row.get("assay") or "imported", outcome,
                            observed, ci, problem_id=problem_id,
                            threshold=_num(row.get("threshold")),
                            evidence_run=(f"{run};{source_tag}" if run
                                          else source_tag))
        summary["ingested"] += 1
        records.append({"candidate": cand, "outcome": outcome,
                        "observed": observed, "ci": list(ci) if ci else None,
                        "family": row.get("family", ""),
                        "assay": row.get("assay", ""),
                        "threshold": _num(row.get("threshold")),
                        "original_run_id": run,
                        "original_record_hash": row.get("record_hash", "")})

    if store is not None and records and not dry_run:
        from bionexus.core.contracts import Envelope, EventType
        from bionexus.core.interfaces import record_for, system_actor
        branch = f"{branch_root}/{p.stem}"
        env = Envelope(experiment_branch_id=branch)
        store.append(record_for(
            env, EventType.gate_decision, system_actor("ingest"),
            decision={"kind": "external_outcomes_imported",
                      "source_file": p.name, "source_sha256": digest,
                      "checksum_match": checksum_match,
                      "n_records": len(records), "problem_id": problem_id}))
        for rec in records:
            store.append(record_for(
                env, EventType.gate_decision, system_actor("ingest"),
                decision={"kind": "external_outcome", "imported": True,
                          "data_origin": f"imported from {source_tag}",
                          "problem_id": problem_id, **rec}))
        summary["provenance_written"] = len(records) + 1
    return summary
