"""DMTA / verdict tallies and series rollups over a campaign's records."""
from __future__ import annotations

from typing import Any


# ------------------------------------------------------------- dmta counts
def dmta_counts(recs) -> dict:
    """DMTA phase counts for a slice of provenance records. Test counts
    unique lab_run submissions (one submission = one run = one analyzed
    export); Analyze counts verdict-bearing decisions, deduplicated —
    a hypothesis earns ONE verdict: its latest. Port of
    webview._dmta_counts."""
    c = {"proposed": 0, "selected": 0, "submitted": 0, "refused": 0,
         "runs": 0, "verdicts": 0,
         "validated": 0, "confirmed": 0, "inconclusive": 0,
         "refuted": 0}
    final: dict[str, str] = {}
    orphan = 0
    for r in recs:
        d = r.decision or {}
        et = r.event_type.value
        if et == "hypothesis_proposed":
            c["proposed"] += 1
        elif et == "hypotheses_filtered":
            c["selected"] += sum(1 for x in d.get("decisions", [])
                                 if x.get("selected"))
        elif et == "lab_run" and d.get("run_id"):
            c["submitted"] += 1
            c["runs"] += 1
        elif et == "gate_decision":
            k = d.get("kind")
            if k in ("halt_refusal", "safety_refusal", "authorization",
                     "synthesis_failed") \
                    and d.get("column") != "autonomous":
                c["refused"] += 1
        elif et in ("hypothesis_validated", "hypothesis_invalidated",
                    "hypothesis_inconclusive",
                    "hypothesis_tested") and d.get("verdict"):
            hid = d.get("hypothesis_id") \
                or (r.artifact.artifact_id if r.artifact else None)
            if not hid:
                orphan += 1
                continue
            final[hid] = str(d.get("verdict"))
    for v in final.values():
        c["verdicts"] += 1
        if v in ("validated", "confirmed"):
            c[v] += 1
        elif v == "invalidated":
            c["refuted"] += 1
        elif v in ("inconclusive", "refuted"):
            c[v] += 1
    return c


def verdict_tally(recs) -> dict[str, int]:
    """Final verdicts — one per hypothesis (latest wins) — bucketed for
    the workspace chips. CONFIRMED means orthogonal agreement was recorded;
    a preliminary `validated` is NOT confirmed — it counts as preliminary.
    refuted = invalidated/refuted; inconclusive = abstention."""
    t = {"confirmed": 0, "preliminary": 0, "refuted": 0, "inconclusive": 0}
    final: dict[str, str] = {}
    for r in recs:
        d = r.decision or {}
        if r.event_type.value in ("hypothesis_validated",
                                  "hypothesis_invalidated",
                                  "hypothesis_inconclusive",
                                  "hypothesis_tested") and d.get("verdict"):
            hid = d.get("hypothesis_id") \
                or (r.artifact.artifact_id if r.artifact else None)
            if hid:
                final[hid] = str(d.get("verdict"))
    for v in final.values():
        if v == "confirmed":
            t["confirmed"] += 1
        elif v == "validated":
            t["preliminary"] += 1
        elif v in ("refuted", "invalidated", "failed"):
            t["refuted"] += 1
        else:
            t["inconclusive"] += 1
    return t


def series_view(recs) -> list[dict[str, Any]]:
    """S-T1 chemotype/SAR series rollup for the workbench: per-series
    verdict counts + matched-pair SAR table. Grouping backend
    (Murcko/family/exact-id) stamps itself — see proef.series."""
    from proef.series import series_summary
    return series_summary(recs)


def round_markers(recs) -> list[tuple[int, list[str]]]:
    """[(round_no, [candidates])] sorted by round, from round_start
    markers."""
    markers = [(int((r.decision or {}).get("round", 0)),
                [str(c) for c in (r.decision or {}).get("candidates") or []])
               for r in recs
               if r.event_type.value == "stage_transition"
               and (r.decision or {}).get("kind") == "round_start"]
    return sorted(markers)
