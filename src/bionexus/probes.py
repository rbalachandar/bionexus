"""Contamination probes that can actually fail.

The naive probe ("do you know this paper?") trusts the model's self-report.
The variant probe doesn't: it perturbs held-out compounds into molecules that
were NEVER PUBLISHED (single-token edits: F->Cl etc.), then asks where they
come from. A model that maps a nonexistent near-twin of a 2025 paper's
series back to that paper is interpolating from memorized structure —
stronger evidence of contamination than any yes/no answer.
"""
from __future__ import annotations

import re


def perturb_smiles(smi: str) -> str | None:
    """Chemically-valid single-token edit; returns a canonical SMILES that is
    NOT the original, or None if no safe edit exists."""
    edits = (("F", "Cl"), ("Cl", "Br"), ("Br", "I"), ("O", "S"))
    variant = None
    for a, b in edits:
        # token-level: 'F' must not be inside 'Fe' etc.; halogens are single
        # uppercase tokens so a plain replace of the first occurrence is safe
        # when the char is not part of a longer token
        m = re.search(rf"(?<![A-Za-z]){re.escape(a)}", smi)
        if m:
            variant = smi[:m.start()] + b + smi[m.end():]
            break
    if variant is None:
        variant = smi + "C"          # last-resort: extend terminal carbon
    try:
        from rdkit import Chem
        mol = Chem.MolFromSmiles(variant)
        if mol is None:
            return None
        out = Chem.MolToSmiles(mol)
        return out if out != Chem.MolToSmiles(Chem.MolFromSmiles(smi)) else None
    except ImportError:
        return variant               # still a real edit; just not canonicalized


def ask_provenance(agent, smi: str) -> str:
    """Where does this compound come from? (no hints given)"""
    from bionexus.core.contracts import Envelope, ToolInvocation
    return agent.generate(
        ToolInvocation(envelope=Envelope(experiment_branch_id="probe"),
                       tool="c.kb.search_literature"),
        f"Which publication, patent, or compound registry entry (if any) "
        f"reports this compound? Answer with the source name, or 'unknown'. "
        f"Do not guess.\n\n{smi}").output["text"]


def variant_contamination(agent, paper_tokens: list[str],
                          held_out_smiles: list[str],
                          n: int = 3) -> dict:
    """Probe n never-published variants of held-out compounds.

    paper_tokens: distinctive lowercase strings from the held-out paper
    (title words, journal, compound series name). If the model attaches
    those tokens to a molecule that does not exist, it knows the series.
    """
    results = []
    hits = 0
    for smi in held_out_smiles[:n]:
        v = perturb_smiles(smi)
        if not v:
            continue
        ans = ask_provenance(agent, v)
        matched = [t for t in paper_tokens if t in ans.lower()]
        results.append({"variant": v[:60], "answer": ans[:160],
                        "linked_to_paper": bool(matched),
                        "tokens": matched})
        hits += bool(matched)
    return {
        "n_variants_probed": len(results),
        "n_mapped_to_paper": hits,
        "verdict": ("CONTAMINATED-VARIANTS" if hits >= 2 else
                    "leakage-suspect" if hits == 1 else "clean"),
        "detail": results,
    }
