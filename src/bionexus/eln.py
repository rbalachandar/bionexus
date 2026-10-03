"""ELN export — provenance into the lab's system of record.

Flattens a provenance branch into an electronic-lab-notebook-friendly CSV
(one row per event, key scientific fields lifted out of the decision blob)
plus a lossless JSON sidecar. Column names follow common ELN conventions
(Benchling/SISSYO importers map these with minimal or no transformation).
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

COLUMNS = ["timestamp", "branch", "event", "actor", "artifact_id",
           "statement", "candidate", "family", "verdict", "observed_uM",
           "ci95_low_uM", "ci95_high_uM", "threshold", "run_id",
           "instrument", "instrument_version", "assay", "record_hash",
           "detail"]


def branch_to_rows(records: list) -> list[dict]:
    rows = []
    for r in records:
        d = r.decision or {}
        art = r.artifact
        meta = (art.metadata if art else {}) or {}
        ci = d.get("observed_ci") or [None, None]
        conf = d.get("confirmation") or {}
        der = d.get("derivation") or {}
        design = (d.get("design") or {}).get("mode") if isinstance(
            d.get("design"), dict) else None
        _mb = (der.get("measured_by") if isinstance(der, dict)
               else "") or ""
        import re as _re
        _m = _re.match(r"^(.*?)\s*\(([^)]+)\)$", _mb)
        instrument = (d.get("instrument")
                      or (_m.group(1) if _m else _mb))
        inst_ver = (d.get("instrument_version")
                    or (_m.group(2) if _m else ""))
        rows.append({
            "timestamp": f"{r.envelope.created_at:.0f}",
            "branch": r.envelope.experiment_branch_id,
            "event": r.event_type.value,
            "actor": (r.actor.id + "/" + r.actor.kind.value) if r.actor else "",
            "artifact_id": art.artifact_id if art else "",
            "statement": d.get("statement") or meta.get("statement", ""),
            "candidate": meta.get("candidate") or d.get("candidate", ""),
            "family": meta.get("family") or d.get("family_id", ""),
            "verdict": d.get("verdict", ""),
            "observed_uM": d.get("observed", ""),
            "ci95_low_uM": ci[0] if ci else "",
            "ci95_high_uM": ci[1] if len(ci or []) > 1 else "",
            "threshold": d.get("threshold", ""),
            "run_id": d.get("run_id") or d.get("evidence_run_id", ""),
            "instrument": instrument,
            "instrument_version": inst_ver,
            "assay": d.get("assay") or design or "",
            "record_hash": r.record_hash or "",
            "detail": json.dumps({k: v for k, v in d.items()
                                  if k in ("rationale", "mechanism",
                                           "refutation_condition", "citation",
                                           "objective", "reason", "verdict",
                                           "confirmation")
                                  or k.startswith("n_")},
                                 sort_keys=True)[:2000],
        })
    return rows


def export_eln(records: list, out_csv: str | Path,
               out_json: str | Path | None = None) -> Path:
    rows = branch_to_rows(records)
    p = Path(out_csv)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    if out_json:
        Path(out_json).write_text(json.dumps(rows, indent=1))
    # detached checksum: editing the flat CSV silently is detectable
    import hashlib
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    p.with_suffix(p.suffix + ".sha256").write_text(
        f"{digest}  {p.name}\n")
    return p
