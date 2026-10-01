"""Taste distillation — what distinguishes hypotheses scientists accept?

The Anthropic ART campaign treats its own hypothesis stream as an object
of study: which of thousands of agent reports were judged worth testing,
and what features did the keepers share? This module closes the same loop
over BioNexus's own provenance: every portfolio decision (selected or
rejected, with recorded reasons) is evidence about selection taste.

Output is a report of observed accept-rate deltas and DETERMINISTIC
amendment suggestions. Tighten-only by construction: the report proposes
prompt amendments for human review and never writes to prompts, gates,
or the agent's tool surface (same invariant as the advisory tier).
"""
from __future__ import annotations

from pathlib import Path

PROVENANCE_DB = "bionexus.db"


def _features(recs) -> tuple[dict[str, dict], list[dict]]:
    """(hypothesis_id -> feature map, [filter decisions]) from one
    branch's records."""
    feats: dict[str, dict] = {}
    decisions: list[dict] = []
    for r in recs:
        if r.event_type.value == "hypothesis_proposed" and r.artifact:
            d = r.decision or {}
            meta = r.artifact.metadata or {}
            cit = d.get("citation") or d.get("citation_detail") or ""
            feats[r.artifact.artifact_id] = {
                "candidate": str(meta.get("candidate")
                                 or d.get("candidate") or "?"),
                "mechanism": bool(d.get("mechanism")),
                "refutation": bool(d.get("refutation_condition")),
                "citation": bool(cit),
                "citation_verified": (d.get("citation_status")
                                      or meta.get("citation_status"))
                                     == "verified",
                "rationale": bool(d.get("rationale")),
                "family": str(d.get("family") or ""),
            }
        elif r.event_type.value == "hypotheses_filtered":
            decisions.extend((r.decision or {}).get("decisions", []))
    return feats, decisions


def fold_taste(feats_all: dict[str, dict],
               decisions_all: list[dict]) -> dict:
    """Aggregate feature rows + filter decisions into a taste report
    ({n, accepted, overall_rate, by_feature, families, amendments}).
    One decision per hypothesis (latest wins)."""
    # fold: one decision per hypothesis (latest wins)
    by_hid: dict[str, dict] = {}
    for d in decisions_all:
        by_hid[d.get("hypothesis_id")] = d
    rows = []
    for hid, d in by_hid.items():
        f = feats_all.get(hid)
        if not f:
            continue
        rows.append({**f, "selected": bool(d.get("selected")),
                     "reason": d.get("reason") or ""})
    n = len(rows)
    acc = sum(1 for r in rows if r["selected"])
    overall = acc / n if n else 0.0

    def rate(key: str) -> dict:
        with_f = [r for r in rows if r[key]]
        without = [r for r in rows if not r[key]]
        rw = (sum(1 for r in with_f if r["selected"]) / len(with_f)
              if with_f else None)
        rwo = (sum(1 for r in without if r["selected"]) / len(without)
               if without else None)
        return {"n": len(with_f), "rate": round(rw, 3) if rw is not None
                else None, "rate_without": round(rwo, 3) if rwo is not None
                else None}

    by_feature = {k: rate(k) for k in
                  ("mechanism", "refutation", "citation",
                   "citation_verified", "rationale")}

    fams: dict[str, dict] = {}
    for r in rows:
        if not r["family"]:
            continue
        f = fams.setdefault(r["family"], {"n": 0, "accepted": 0})
        f["n"] += 1
        f["accepted"] += 1 if r["selected"] else 0

    amendments: list[str] = []
    for key, label in (("mechanism", "a stated mechanism"),
                       ("citation_verified", "a VERIFIED citation"),
                       ("refutation", "a refutation condition")):
        s = by_feature[key]
        if s["rate"] is None or s["rate_without"] is None:
            continue
        if s["rate"] > s["rate_without"] * 1.3 and s["n"] >= 3:
            amendments.append(
                f"hypotheses with {label} are accepted "
                f"{s['rate'] / max(s['rate_without'], 1e-9):.1f}x more "
                f"({s['rate']:.0%} vs {s['rate_without']:.0%}) — keep "
                f"demanding it in the agent prompt")
        elif s["rate"] < s["rate_without"] * 0.7 and s["n"] >= 3:
            amendments.append(
                f"hypotheses with {label} are accepted LESS "
                f"({s['rate']:.0%} vs {s['rate_without']:.0%}) — review "
                f"whether the requirement adds noise")
    dead = [fam for fam, f in fams.items()
            if f["n"] >= 3 and f["accepted"] == 0]
    for fam in dead:
        amendments.append(
            f"family '{fam}' proposed {fams[fam]['n']}x, never selected — "
            f"consider excluding it from proposal prompts")
    return {"n": n, "accepted": acc,
            "overall_rate": round(overall, 3) if n else 0.0,
            "by_feature": by_feature, "families": fams,
            "amendments": amendments}


def taste_report(db_path: str | Path | None = None) -> dict:
    """Aggregate accept/reject rates by hypothesis feature across all
    provenance branches. Returns {n, accepted, overall_rate, by_feature,
    families, amendments} — amendments are strings, advisory only."""
    db_path = db_path or PROVENANCE_DB
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    store = SqliteProvenanceStore(str(db_path))
    feats_all: dict[str, dict] = {}
    decisions_all: list[dict] = []
    for br in store.branches():
        if not br.startswith("problem/"):
            continue
        try:
            recs = store.branch_records(br)
        except Exception:
            continue
        feats, decisions = _features(recs)
        feats_all.update(feats)
        decisions_all.extend(decisions)
    return fold_taste(feats_all, decisions_all)


def render_taste(report: dict) -> str:
    """Human-readable taste report (bn taste)."""
    if not report["n"]:
        return "no portfolio decisions with feature data yet — run a " \
               "campaign first"
    lines = [f"portfolio decisions: {report['n']} "
             f"({report['accepted']} accepted, "
             f"{report['overall_rate']:.0%} overall)"]
    labels = {"mechanism": "mechanism stated", "refutation": "refutation "
              "condition", "citation": "citation present",
              "citation_verified": "citation VERIFIED",
              "rationale": "rationale present"}
    for key, label in labels.items():
        s = report["by_feature"][key]
        if s["rate"] is not None:
            base = f"  {label}: {s['rate']:.0%} accepted (n={s['n']})"
            if s["rate_without"] is not None:
                base += f" vs {s['rate_without']:.0%} without"
            lines.append(base)
    dead = {f: v for f, v in report["families"].items()
            if v["n"] >= 3 and v["accepted"] == 0}
    if dead:
        lines.append("never-selected families: "
                     + ", ".join(sorted(dead)))
    if report["amendments"]:
        lines.append("proposed amendments (advisory — human review "
                     "required, nothing is applied):")
        lines.extend(f"  • {a}" for a in report["amendments"])
    else:
        lines.append("no amendment suggestions at current sample size")
    return "\n".join(lines)
