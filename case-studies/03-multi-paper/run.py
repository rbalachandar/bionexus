"""CASE STUDY 03 — Multi-paper blind reproduction (post-cutoff ChEMBL papers).

Extends case study 02 into a pattern of evidence: several 2025 papers, each
held out ENTIRELY (all values excluded from training and from the agent),
reproduced with the same protocol:

  - quantitative: Morgan+RF trained on all OTHER measurements for that target,
    scored against the paper's published values (Spearman, RMSE, EF@10%)
  - hypothesis (with --llm): contamination probe per paper; blind agent names
    the core scaffold class and ranks compounds; we check the named class
    against the paper's dominant Murcko scaffold and score its ranking

Usage:
    python run.py            # RF-only quantitative rows (no LLM needed)
    python run.py --llm      # + agent hypothesis/ranking rows (env required)
"""
from __future__ import annotations

import json
import math
import re as _re_title
import statistics
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

# default: top screened papers (see screen_papers.py -> papers_found.json);
# override with --docs CHEMBL...,CHEMBL...
PAPERS = {
    "CHEMBL6087414": "2025 paper, target CHEMBL392, 45 compounds",
    "CHEMBL6087416": "2025 paper, A2A adenosine receptor, 40 compounds",
    "CHEMBL6087417": "2025 paper, target CHEMBL614245, 53 compounds",
    "CHEMBL6087407": "2025 paper, target CHEMBL4508, 67 compounds",
    "CHEMBL6087413": "2025 paper, target CHEMBL614388, 31 compounds",
}
FOUND = Path(__file__).parent / "papers_found.json"
CACHE = Path(__file__).parent / ".cache"
ACTIVE_PIC50 = 6.5   # ~IC50 <= 316 nM

# scaffold-class markers for automated hypothesis-match checks
CORE_MARKERS = {
    "quinoline": ["quinoline"], "quinazoline": ["quinazolin"],
    "pyrazine": ["pyrazine"], "pyrimidine": ["pyrimidin"],
    "pyrazole": ["pyrazole", "pyrazol"], "thiazole": ["thiazol"],
    "triazole": ["triazol"], "indole": ["indol"], "benzene": ["phenyl", "benzene", "aryl"],
    "morpholine": ["morpholin"], "piperazine": ["piperazin"], "sulfonamide": ["sulfonamid"],
}


def chembl(path: str, tries: int = 8, soft: bool = False):
    for i in range(tries):
        try:
            req = urllib.request.Request(
                "https://www.ebi.ac.uk/chembl/api/data" + path,
                headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=90) as r:  # noqa: S310
                return json.loads(r.read())
        except Exception:
            if i == tries - 1:
                if soft:
                    return {}
                raise
            time.sleep(5 * (i + 1))


def _cache_valid(rows: list[dict]) -> bool:
    return len(rows) > 0


def fetch_doc_activities(doc_id: str) -> list[dict]:
    CACHE.mkdir(exist_ok=True)
    f = CACHE / f"doc_{doc_id}.json"
    if f.exists():
        cached = json.loads(f.read_text())
        if _cache_valid(cached):
            return cached
        f.unlink()  # poisoned by a soft-failure earlier — refetch
    out, p = [], (f"/activity.json?document_chembl_id={doc_id}&limit=1000")
    while p:
        d = chembl(p)
        out += d.get("activities", [])
        nxt = d.get("page_meta", {}).get("next") or ""
        p = nxt.replace("https://www.ebi.ac.uk", "")
        if not p or not d.get("activities"):
            break
    f.write_text(json.dumps(out))
    return out


def fetch_target_pool(target_id: str, exclude_doc: str, cap: int = 20000) -> list[tuple[str, float]]:
    CACHE.mkdir(exist_ok=True)
    f = CACHE / f"pool_{target_id}.json"
    if f.exists() and _cache_valid(json.loads(f.read_text())):
        rows = json.loads(f.read_text())
    else:
        rows, p = [], (f"/activity.json?target_chembl_id={target_id}"
                       "&limit=1000")
        while p and len(rows) < cap:
            d = chembl(p, soft=True)
            if not d.get("activities"):
                break
            for a in d.get("activities", []):
                smi, val = a.get("canonical_smiles"), a.get("standard_value")
                if a.get("standard_units") == "nM" and smi and val:
                    try:
                        v = float(val)
                    except ValueError:
                        continue
                    if 0 < v < 1e5:
                        rows.append([smi, -math.log10(v * 1e-9)])
            nxt = d.get("page_meta", {}).get("next") or ""
            p = nxt.replace("https://www.ebi.ac.uk", "")
            if not p or not d.get("activities"):
                break
        f.write_text(json.dumps(rows))
    return [(s, p) for s, p in rows
            if not _from_doc(s, exclude_doc)]


def _from_doc(smi: str, doc: str) -> bool:
    # cheap: cached doc sets are checked by caller via compound sets
    return False


def pic50(a: dict) -> float | None:
    if a.get("standard_type") not in ("IC50", "Ki", "EC50", "AC50"):
        return None
    units, val = a.get("standard_units"), a.get("standard_value")
    if not val or units not in ("nM", "uM", "µM", "M"):
        return None
    try:
        v = float(val)
    except ValueError:
        return None
    nm = v * 1e9 if units in ("M",) else (v * 1000.0 if units in ("uM", "µM") else v)
    return -math.log10(nm * 1e-9) if 0 < nm < 1e6 else None


def dominant_scaffold(smiles_list: list[str]) -> str:
    from rdkit import Chem
    from rdkit.Chem.Scaffolds import MurckoScaffold
    sc = defaultdict(int)
    for s in smiles_list:
        m = Chem.MolFromSmiles(s)
        if m:
            sc[MurckoScaffold.MurckoScaffoldSmiles(mol=m)] += 1
    return max(sc, key=lambda k: sc[k]) if sc else ""


CORE_SMARTS = {
    "benzene": "c1ccccc1", "pyridine": "c1ccncc1", "pyrimidine": "c1ncncc1",
    "pyrazine": "c1cnccn1", "pyrazole": "c1cnnc1", "thiazole": "c1cscn1",
    "imidazole": "c1cnc[nH]1", "indole": "c1ccc2[nH]ccc2c1",
    "quinoline": "c1ccc2ncccc2c1", "morpholine": "O1CCNCC1",
    "piperazine": "N1CCNCC1", "trifluoromethyl": "C(F)(F)F",
    "sulfonamide": "S(=O)(=O)N", "amide": "C(=O)N",
}


def scaffold_markers(scaffold: str, smiles_sample: list[str]) -> list[str]:
    from rdkit import Chem
    m = Chem.MolFromSmiles(scaffold)
    probes = {name: Chem.MolFromSmarts(smi) for name, smi in CORE_SMARTS.items()}
    out = []
    for name, patt in probes.items():
        if patt is None:
            continue
        hit = m is not None and m.HasSubstructMatch(patt)
        if not hit and name in ("trifluoromethyl", "sulfonamide", "amide",
                                "morpholine", "piperazine"):
            # substituent markers: check the compounds themselves
            hit = any(Chem.MolFromSmiles(s) and
                      Chem.MolFromSmiles(s).HasSubstructMatch(patt)
                      for s in smiles_sample[:30])
        if hit:
            out.append(name)
    return out


def main() -> None:
    from bionexus import fixtures
    _n = fixtures.materialize(Path(__file__).parent)
    if _n:
        print(f"[fixtures] restored {_n} frozen data file(s)")
    use_llm = "--llm" in sys.argv
    from bionexus.adapters.models.sklearn_policy import MorganFingerprintRF
    from bionexus.benchmark import roc_auc, spearman, spearman_ci  # noqa: F401

    papers = dict(PAPERS)
    if "--docs" in sys.argv:
        ids = sys.argv[sys.argv.index("--docs") + 1].split(",")
        found = json.loads(FOUND.read_text()) if FOUND.exists() else []
        meta = {f["doc"]: f for f in found}
        papers = {i: meta.get(i, {}).get("title", i) for i in ids}

    results = {}
    agent = None
    if use_llm:
        from bionexus.adapters.models.anthropic_provider import AnthropicProvider
        agent = AnthropicProvider()

    for doc_id, label in papers.items():
        print(f"\n=== {doc_id} — {label} ===")
        acts = fetch_doc_activities(doc_id)
        # primary target = most measured activities in this doc
        by_target = defaultdict(list)
        for a in acts:
            p = pic50(a)
            if p is not None and a.get("target_chembl_id"):
                by_target[a["target_chembl_id"]].append((a["canonical_smiles"], p))
        if not by_target:
            print("   no usable nM values — skipped")
            continue
        # primary target = most UNIQUE compounds (>= 12 required)
        uniq = {t: len({s for s, _ in v}) for t, v in by_target.items()}
        eligible = {t: n for t, n in uniq.items() if n >= 12}
        if not eligible:
            print(f"   no target with >=12 unique compounds (best: {max(uniq.values()) if uniq else 0}) — skipped")
            continue
        target = max(eligible, key=lambda k: eligible[k])
        paper = list(dict.fromkeys(by_target[target]))  # dedupe by smiles order-stable
        smis = [s for s, _ in paper]
        dom = dominant_scaffold(smis)
        markers = scaffold_markers(dom, smis)
        print(f"   target {target}: {len(paper)} unique compounds; dominant "
              f"scaffold markers: {markers or 'acyclic/mixed'}")

        # hold out the paper entirely from the target pool
        paper_set = set(smis)
        pool = [(s, p) for s, p in fetch_target_pool(target, doc_id) if s not in paper_set]
        print(f"   training pool (other papers): {len(pool)}")
        row: dict = {"paper": label, "n_paper": len(paper), "n_train": len(pool),
                     "scaffold_markers": markers}
        if len(pool) >= 200 and len(paper) >= 10:
            model = MorganFingerprintRF(n_estimators=300)
            model.fit(pool)
            preds = [model.predict(s) for s, _ in paper]
            truth = [p for _, p in paper]
            pool_mean = sum(p for _, p in pool) / len(pool)
            row["baseline_rmse"] = round(math.sqrt(sum((pool_mean - t) ** 2
                                                        for t in truth) / len(truth)), 3)
            rho, ci_lo, ci_hi = spearman_ci(preds, truth)
            row["rf_spearman"] = round(rho, 3)
            row["rf_spearman_ci95"] = [ci_lo, ci_hi]
            row["rf_rmse"] = round(math.sqrt(sum((a - b) ** 2 for a, b in zip(preds, truth))
                                             / len(truth)), 3)
            top_n = max(1, len(preds) // 10)
            top = sorted(zip(preds, truth), key=lambda t: -t[0])[:top_n]
            base = sum(1 for t in truth if t >= ACTIVE_PIC50) / len(truth)
            hit = sum(1 for _, t in top if t >= ACTIVE_PIC50) / len(top)
            row["rf_ef10"] = round(hit / base, 2) if base > 0 else None
            print(f"   RF: spearman={row['rf_spearman']:+.3f} rmse={row['rf_rmse']:.2f} "
                  f"EF@10%={row['rf_ef10']}x (base {base:.2f})")

            # scaffold-leakage check: retrain with training rows removed that
            # share a Murcko scaffold with ANY paper compound — how much of
            # the score is scaffold memory rather than generalization?
            from rdkit import Chem
            from rdkit.Chem.Scaffolds import MurckoScaffold

            def _scaf(s):
                m = Chem.MolFromSmiles(s)
                return (MurckoScaffold.MurckoScaffoldSmiles(mol=m)
                        if m else None)
            paper_scafs = {_scaf(s) for s in smis} - {None}
            clean = [(s, v) for s, v in pool if _scaf(s) not in paper_scafs]
            row["n_scaffold_overlap"] = len(pool) - len(clean)
            if len(clean) >= 200:
                model2 = MorganFingerprintRF(n_estimators=300)
                model2.fit(clean)
                row["rf_spearman_scaffoldclean"] = round(
                    spearman([model2.predict(s) for s, _ in paper], truth), 3)
                print(f"   scaffold-clean RF: spearman="
                      f"{row['rf_spearman_scaffoldclean']:+.3f} "
                      f"({row['n_scaffold_overlap']} overlapping rows removed)")
        else:
            print("   insufficient training data — RF row skipped")

        if agent and row.get("rf_spearman") is not None:
            row.update(run_agent_rows(agent, doc_id, label, paper[:45], markers))

        results[doc_id] = row

    out = Path(__file__).parent / "results.json"
    out.write_text(json.dumps(results, indent=1))
    print(f"\nresults: {out}")


def run_agent_rows(agent, doc_id: str, label: str, sample: list[tuple[str, float]],
                   markers: list[str]) -> dict:
    """Contamination probe + blind hypothesis + blind ranking for one paper."""
    from bionexus.benchmark import spearman
    from bionexus.core.contracts import Envelope, ToolInvocation

    out: dict = {}
    doc_meta = chembl(f"/document/{doc_id}.json")
    title, doi = doc_meta.get("title", ""), doc_meta.get("doi", "")
    probe = agent.generate(
        ToolInvocation(envelope=Envelope(experiment_branch_id="cs03"),
                       tool="c.kb.search_literature"),
        f"Do you have specific knowledge of this paper? Title: '{title}' DOI: {doi}. "
        "Answer yes/no + one sentence on what you know about its compounds.").output["text"]
    known = probe.strip().lower().startswith("yes")
    out["contamination"] = "CONTAMINATED" if known else "clean"

    from bionexus.probes import variant_contamination
    tokens = [w for w in _re_title.findall(r"[a-z]+", title.lower())
              if len(w) >= 8][:6]
    vc = variant_contamination(agent, tokens, [s for s, _ in sample[:3]])
    out["contamination_variants"] = vc["verdict"]
    out["contamination_variant_hits"] = (f"{vc['n_mapped_to_paper']}/"
                                         f"{vc['n_variants_probed']}")

    smis = "\n".join(f"{i+1}. {s}" for i, (s, _) in enumerate(sample))
    resp = agent.generate(
        ToolInvocation(envelope=Envelope(experiment_branch_id="cs03"),
                       tool="c.fm.generate_molecules"),
        "You are a medicinal chemist. Below are structures from a kinase/metabolic "
        "series; measurements are hidden.\n\n" + smis +
        "\n\n1. Name the core scaffold class of this series.\n"
        "2. Score each compound 0-100 for likely potency (pIC50 > 6.5).\n"
        'Reply ONLY with JSON: {"core": "...", "scores": [{"index":1,"score":50}, ...]}').output["text"]
    try:
        import re
        doc = json.loads(re.search(r"\{.*\}", resp, re.S).group(0))
    except Exception:
        out["agent_note"] = "unparseable response"
        return out
    core = doc.get("core", "").lower()
    matched = [m for m in markers if m in core]
    out["agent_core"] = doc.get("core", "")
    out["hypothesis_match"] = bool(matched)
    scores = {int(x["index"]): float(x["score"]) for x in doc.get("scores", [])}
    agent_scores = [scores.get(i + 1, 50.0) for i in range(len(sample))]
    truth = [p for _, p in sample]
    out["agent_spearman"] = round(spearman(agent_scores, truth), 3)
    print(f"   agent: contamination={out['contamination']} core='{out['agent_core'][:50]}' "
          f"match={out['hypothesis_match']} spearman={out['agent_spearman']:+.3f}")
    return out


if __name__ == "__main__":
    main()
