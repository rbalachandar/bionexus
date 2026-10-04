"""series — think in series, not singletons (S-T1 chemotype/SAR view).

Med-chem reasoning is SERIES reasoning: proposed -> tested -> judged
grouped by chemotype, with per-series verdict rollups and matched-pair
tables (congeners differing by one substitution, delta-IC50 WITH CIs).
The per-compound hypothesis remains the epistemic atom; this module is
only the VIEW, and it aggregates honestly:

- grouping keys, in priority order: explicit family (modality-agnostic
  hook — biologics/sequences use this), then Bemis-Murcko scaffold from
  SMILES when rdkit is the backend, then ungrouped singletons.
  The backend used is STAMPED on every series so a "same chemotype"
  claim is never made on exact-duplicate grouping.
- rollups reuse the verdict vocabulary (confirmed / preliminary /
  refuted / abstained); abstentions are counted, never averaged away.
- matched pairs classify delta-log10-IC50 against the retention band
  (default 3.2-fold): a CI straddling the band boundary ABSTAINS —
  the same small-n physics as every verdict in this repo.
"""
from __future__ import annotations

import math
from typing import Any

from bionexus.benchmark import SCAFFOLD_BACKEND, scaffold

RETAIN_FOLD = 3.2          # "retains potency" = within this fold-change
_TLOG = math.log10(RETAIN_FOLD)


def _norm_verdict(v: str | None) -> str:
    s = (v or "").lower()
    if s == "confirmed":
        return "confirmed"
    if s in ("validated",):
        return "preliminary"
    if s in ("refuted", "invalidated", "failed"):
        return "refuted"
    if s in ("", "proposed", "designed"):
        return "proposed"
    return "abstained"


def chemotype_key(member: dict[str, Any]) -> tuple[str, str]:
    """(key, kind) for one member: family > Murcko scaffold > singleton."""
    fam = (member.get("family") or "").strip()
    if fam:
        return fam, "family"
    smi = member.get("smiles") or ""
    if smi and SCAFFOLD_BACKEND == "rdkit":
        k = scaffold(smi)
        if k:
            return k, "chemotype:Murcko"
    return (member.get("candidate") or member.get("hypothesis_id")
            or smi), "ungrouped"


def build_series(members: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """members: [{candidate, hypothesis_id?, smiles?, family?, verdict,
    observed, ci}] -> {key: {kind, label, members, rollup}}.

    Verdict counts follow views.verdict_tally semantics; a series whose
    members abstain reports the abstentions — it does not roll up to a
    false confidence."""
    series: dict[str, dict[str, Any]] = {}
    for m in members:
        key, kind = chemotype_key(m)
        s = series.setdefault(key, {"key": key, "kind": kind,
                                    "members": [],
                                    "rollup": {"confirmed": 0,
                                               "preliminary": 0,
                                               "refuted": 0,
                                               "abstained": 0,
                                               "proposed": 0}})
        v = _norm_verdict(m.get("verdict"))
        s["rollup"][v] += 1
        s["members"].append({**m, "verdict_norm": v})
    for s in series.values():
        r = s["rollup"]
        s["n_tested"] = sum(1 for m in s["members"]
                            if m["verdict_norm"] != "proposed")
        s["n_members"] = len(s["members"])
        s["label"] = (f"{r['confirmed']} confirmed, {r['refuted']} refuted, "
                      f"{r['preliminary']} preliminary, "
                      f"{r['abstained']} abstained"
                      + (f", {r['proposed']} proposed (untested)"
                         if r["proposed"] else ""))
        s["chemotype_backend"] = ("rdkit-Murcko" if SCAFFOLD_BACKEND == "rdkit"
                                  else "none(exact-id fallback)")
    return series


def _se_from_ci(point: float, ci: Any) -> float | None:
    """log10 standard error from a 95% CI on the IC50 scale."""
    if not ci or point <= 0:
        return None
    lo, hi = (ci[0], ci[1]) if isinstance(ci, (list, tuple)) and len(ci) == 2 \
        else (None, None)
    if not lo or not hi or lo <= 0 or hi <= 0:
        return None
    return (math.log10(hi) - math.log10(lo)) / (2 * 1.96)


def matched_pairs(series: dict[str, Any],
                  retain_fold: float = RETAIN_FOLD) -> list[dict[str, Any]]:
    """Congener pairs with both members holding measured IC50s:
    delta = log10(IC50_a / IC50_b) with a propagated 95% CI, classified
    against the retention band (<= retain_fold change = 'retained';
    CI beyond = 'loss'/'gain'; CI straddling the boundary = ABSTAINED).
    a is the alphabetically-first candidate: positive delta means
    a is the weaker (higher IC50) congener."""
    t = math.log10(retain_fold)
    meas = [m for m in series["members"]
            if isinstance(m.get("observed"), (int, float)) and m["observed"] > 0]
    pairs = []
    for i in range(len(meas)):
        for j in range(i + 1, len(meas)):
            a, b = sorted((meas[i], meas[j]),
                          key=lambda m: str(m.get("candidate")))
            da = math.log10(a["observed"])
            db = math.log10(b["observed"])
            delta = da - db
            sea, seb = _se_from_ci(a["observed"], a.get("ci")), \
                _se_from_ci(b["observed"], b.get("ci"))
            if sea is not None and seb is not None:
                hw = 1.96 * math.hypot(sea, seb)
            else:
                hw = 0.0  # CIs not recorded: point estimate alone, disclosed
            lo, hi = delta - hw, delta + hw
            if hi < -t:
                call = "gain"            # a meaningfully stronger
            elif lo > t:
                call = "loss"            # a meaningfully weaker
            elif lo >= -t and hi <= t:
                call = "retained"
            else:
                call = "abstained"       # CI straddles a band boundary
            pairs.append({
                "a": a.get("candidate"), "b": b.get("candidate"),
                "ic50_a": a["observed"], "ic50_b": b["observed"],
                "delta_log10": round(delta, 3),
                "ci95": [round(lo, 3), round(hi, 3)] if hw else None,
                "fold_a_over_b": round(10 ** delta, 3),
                "call": call,
                "cited_cis": hw > 0,
            })
    return pairs


def _collect(recs):
    """(latest verdicts per hypothesis, family-claim markers) from the
    chain. One pass; verdict records supersede proposed (recency wins,
    payload-driven — same reading rule as every verdict surface here)."""
    latest: dict[str, dict[str, Any]] = {}
    smiles_by: dict[str, str] = {}
    family_by: dict[str, str] = {}
    claims: dict[str, dict[str, Any]] = {}
    verdict_events = ("hypothesis_validated", "hypothesis_invalidated",
                      "hypothesis_inconclusive", "hypothesis_tested")
    for r in recs:
        d = r.decision or {}
        art = (r.artifact.metadata if r.artifact else {}) or {}
        et = r.event_type.value
        cand = d.get("candidate") or art.get("candidate")
        key = d.get("hypothesis_id") or art.get("hypothesis_id") or cand
        if d.get("smiles") or art.get("smiles"):
            if cand:
                smiles_by[cand] = d.get("smiles") or art.get("smiles")
        if d.get("family") or art.get("family"):
            if cand:
                family_by[cand] = d.get("family") or art.get("family")
        if et == "hypothesis_proposed" and d.get("family_id"):
            claims[d["family_id"]] = {
                "family_id": d["family_id"],
                "parent_statement": d.get("parent_statement", ""),
                "kind": d.get("kind", "mechanistic"),
                "retain_fold": d.get("retain_fold"),
                "n_variants": d.get("n_variants", 0)}
            continue
        if et == "hypothesis_proposed" and key and key not in latest:
            latest[key] = {"hypothesis_id": key, "candidate": cand or key,
                           "verdict": None, "observed": None, "ci": None,
                           "smiles": d.get("smiles") or "",
                           "family": d.get("family") or ""}
        if et in verdict_events and d.get("verdict") and key:
            if d.get("claim_kind") == "series-derived":
                continue  # a derived CLAIM verdict is not a member datum
            prev = latest.get(key) or {}
            latest[key] = {
                "hypothesis_id": key, "candidate": cand or key,
                "verdict": d.get("verdict"),
                "observed": d.get("observed") or d.get("ic50_um"),
                "ci": d.get("observed_ci") or d.get("ic50_ci"),
                "smiles": d.get("smiles") or smiles_by.get(cand or "", ""),
                "family": d.get("family") or family_by.get(cand or "", ""),
                "seq": prev.get("seq", 0),
            }
    return latest, claims


def resolve_series_claims(recs, retain_fold: float = RETAIN_FOLD,
                          ) -> list[dict[str, Any]]:
    """Derive verdicts for family-tagged claims from their members'
    CI-aware verdicts.

    A series claim is NEVER directly tested — its status is derived, and
    the derivation cannot manufacture confidence: abstention dominates
    (any straddling CI, any unresolved member, any point-only pair that
    looks like loss/gain ⇒ inconclusive); refutation requires a CI fully
    beyond the retention band. Tree-rollup vocabulary translated:
    achieved≡confirmed, downgraded-by-unresolved⇒inconclusive, never
    refuted-from-absence. Statuses: confirmed | refuted | inconclusive |
    open (not enough resolved evidence to even abstain-meaningfully).
    """
    latest, claims = _collect(recs)
    out = []
    for fid, claim in claims.items():
        fold = float(claim.get("retain_fold") or retain_fold)
        t = math.log10(fold)
        members = [m for m in latest.values() if m.get("family") == fid]
        base = {"family_id": fid, "parent_statement": claim["parent_statement"],
                "kind": claim["kind"], "retain_fold": fold,
                "derived": True,
                "derived_from": sorted(
                    (str(m["candidate"]), str(m["verdict"]))
                    for m in members)}
        if not members:
            out.append({**base, "status": "open",
                        "reason": "no member hypotheses on the chain"})
            continue
        n_res = sum(1 for m in members if m["verdict"] is not None)
        if n_res == 0:
            out.append({**base, "status": "open",
                        "reason": f"all {len(members)} members untested/"
                                  "proposed — a series claim abstains until"
                                  " members resolve"})
            continue
        ser = build_series(members)
        s = ser.get(fid) or next(iter(ser.values()))
        if claim.get("kind") == "series":
            pairs = matched_pairs(s, retain_fold=fold)
            measured = [m for m in members
                        if isinstance(m.get("observed"), (int, float))
                        and m["observed"] > 0]
            if len(measured) < 2:
                out.append({**base, "status": "inconclusive", "pairs": pairs,
                            "reason": "fewer than 2 members measured — "
                                      "retention needs congeners to compare"})
                continue
            if any(p["call"] == "abstained" for p in pairs):
                status, reason = "inconclusive", \
                    "a congener pair's CI straddles the retention band — " \
                    "the series claim abstains with it"
            elif any(p["call"] in ("gain", "loss") and not p["cited_cis"]
                     for p in pairs):
                status, reason = "inconclusive", \
                    "a beyond-band pair has no CIs on record — cannot call " \
                    "loss without uncertainty"
            elif any(p["call"] in ("gain", "loss") for p in pairs):
                status, reason = "refuted", \
                    "a congener pair's CI lies fully beyond the " \
                    f"{retain_fold}-fold retention band"
            elif pairs and all(p["call"] == "retained" for p in pairs):
                status, reason = "confirmed", (
                    f"all {len(pairs)} measured congener pairs retain "
                    f"potency within {fold}x (CIs on record)")
            else:
                status, reason = "inconclusive", \
                    "members resolved but no comparable pairs with CIs"
            out.append({**base, "status": status, "reason": reason,
                        "pairs": pairs})
        else:
            # mechanistic family rollup: any member refuted refutes the
            # shared claim; confirmation needs every tested member
            ref = sum(1 for m in members if m["verdict"] in
                      ("refuted", "invalidated", "failed"))
            conf = sum(1 for m in members if m["verdict"] == "confirmed")
            abst = sum(1 for m in members if m["verdict"] in
                       ("inconclusive", "validated"))
            if ref:
                status, reason = "refuted", f"{ref} member(s) refuted"
            elif conf and abst == 0 and n_res == len(members) \
                    and all(m["verdict"] == "confirmed" for m in members):
                status, reason = "confirmed", \
                    f"all {conf} members confirmed"
            else:
                status, reason = "inconclusive", \
                    f"{abst} abstention(s)/preliminar(y|ies) block " \
                    "family-level confirmation"
            out.append({**base, "status": status, "reason": reason,
                        "counts": {"confirmed": conf, "refuted": ref,
                                   "blocked": abst}})
    return sorted(out, key=lambda c: c["family_id"])


def series_summary(recs) -> list[dict[str, Any]]:
    """Provenance-records-first builder: verdicts (recency-wins per
    hypothesis), observed IC50 + CI, and structure keys pulled from
    hypothesis_proposed / synthesis / verdict payloads. Feeds the
    workbench rollup and the diary. Family series carry their derived
    claim status (resolve_series_claims) when one exists."""
    latest, claims = _collect(recs)
    claim_status = {c["family_id"]: c for c in resolve_series_claims(recs)}
    members = list(latest.values())
    series = build_series(members)
    out = []
    for s in series.values():
        out.append({"key": s["key"][:48], "kind": s["kind"],
                    "backend": s["chemotype_backend"],
                    "n_members": len(s["members"]),
                    "rollup": s["rollup"], "label": s["label"],
                    "members": sorted(
                        ({"candidate": m.get("candidate"),
                          "verdict": m.get("verdict_norm"),
                          "observed": m.get("observed")}
                         for m in s["members"]),
                        key=lambda x: str(x["candidate"])),
                    "matched_pairs": matched_pairs(s),
                    "claim_status": (claim_status.get(s["key"], {})
                                     .get("status") if s["kind"] == "family"
                                     else None),
                    "claim_reason": (claim_status.get(s["key"], {})
                                     .get("reason") if s["kind"] == "family"
                                     else None)})
    out.sort(key=lambda x: (-x["rollup"]["confirmed"],
                           -x["n_members"], str(x["key"])))
    return out
