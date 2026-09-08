"""Evidence-based potency gates — suggest TPP thresholds from ChEMBL.

Instead of folklore constants, ask the published data: for a target's
reported binding activities (IC50, assay type B), the suggested HIT gate is
the top-quartile potency among known actives (pIC50 ≥ 6), and the LEAD gate
is 10× tighter. Falls back to conventional values (1 µM / 50 nM) when the
network or the data isn't there — the fallback is always labeled.
"""
from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass

from bionexus.adapters.data.chembl import fetch_target_activities

SEARCH = "https://www.ebi.ac.uk/chembl/api/data/target/search.json"
CONVENTIONAL_HIT_NM = 1000.0
CONVENTIONAL_LEAD_NM = 50.0
MIN_ACTIVES = 50


@dataclass
class TargetProfile:
    target: str
    chembl_id: str | None
    n_activities: int
    median_pic50: float | None
    hit_ic50_nm: float
    lead_ic50_nm: float
    basis: str
    source: str          # chembl | fallback

    def as_dict(self) -> dict:
        return asdict(self)


def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        raise ValueError("empty")
    idx = max(0, min(len(sorted_vals) - 1, int(q * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


def derive_gates(pic50s: list[float]) -> tuple[float, float, float] | None:
    """(hit_nm, lead_nm, median) from published pIC50s, or None if too thin."""
    actives = sorted(p for p in pic50s if p >= 6.0)
    if len(actives) < MIN_ACTIVES:
        return None
    top_quartile = _percentile(actives, 0.75)
    hit_nm = 10 ** (9.0 - top_quartile)
    lead_nm = max(1.0, hit_nm / 10.0)
    median = sum(actives) / len(actives)
    return round(hit_nm, 1), round(lead_nm, 1), median


def lookup_targets(name: str) -> list[str]:
    """Search ChEMBL by name; prefer SINGLE PROTEIN targets, exact pref_name
    first (gene symbols like EGFR otherwise hit interaction complexes and
    stale duplicate entries)."""
    url = f"{SEARCH}?q={urllib.parse.quote(name)}&limit=20"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
        data = json.loads(r.read())
    targets = [t for t in data.get("targets", []) if t.get("target_chembl_id")]
    singles = [t for t in targets if t.get("target_type") == "SINGLE PROTEIN"]
    exact = [t for t in singles
             if (t.get("pref_name") or "").lower() == name.lower()]
    ordered = exact + [t for t in singles if t not in exact] + \
        [t for t in targets if t not in singles]
    return [t["target_chembl_id"] for t in ordered]


def lookup_target(name: str) -> str | None:
    ids = lookup_targets(name)
    return ids[0] if ids else None


def suggest(target_name: str, chembl_id: str | None = None) -> TargetProfile:
    """Best-effort evidence-based gates; never raises — degrades to labeled
    conventional defaults."""
    try:
        candidates = [chembl_id] if chembl_id else lookup_targets(target_name)
        if not candidates:
            raise ValueError(f"no ChEMBL target matches '{target_name}'")
        cid, gates, pic50s = None, None, []
        last_note = ""
        for c in candidates[:5]:            # stale duplicates can be thin
            try:
                path = fetch_target_activities(c, max_records=5000)
                import csv
                with open(path) as f:
                    pic50s = [float(r["pic50"]) for r in csv.DictReader(f)
                              if r.get("pic50")]
            except Exception:
                continue
            gates = derive_gates(pic50s)
            if gates:
                cid = c
                break
            last_note = (f"{c}: only "
                         f"{sum(1 for p in pic50s if p >= 6.0)} actives")
        if gates is None:
            raise ValueError(f"no candidate had >= {MIN_ACTIVES} actives "
                             f"({last_note or 'no data'})")
        hit, lead, med = gates
        return TargetProfile(
            target=target_name, chembl_id=cid, n_activities=len(pic50s),
            median_pic50=round(med, 2), hit_ic50_nm=hit, lead_ic50_nm=lead,
            basis=(f"{len(pic50s)} published activities for {cid} · "
                   f"hit gate = top-quartile potency of known actives "
                   f"(median pIC50 {med:.1f}) · lead = 10× tighter"),
            source="chembl")
    except Exception as exc:
        return TargetProfile(
            target=target_name, chembl_id=None, n_activities=0,
            median_pic50=None, hit_ic50_nm=CONVENTIONAL_HIT_NM,
            lead_ic50_nm=CONVENTIONAL_LEAD_NM,
            basis=f"conventional defaults ({exc})", source="fallback")
