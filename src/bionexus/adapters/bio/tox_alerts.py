"""Molecular structural alerts + DURC screening.

The SafetyEngine historically inspected *protocols* (BSL, reagents, steps) —
never *molecules*. This module gives it molecule-level vision: curated
toxicophore SMARTS alerts (Murakami/Benigni-style classics) and a DURC
(Dual-Use Research of Concern) text screen against the select-agent families.

RDKit is optional (P1): without it, `screen_smiles` reports
`status="no-rdkit"` and the gate passes with an explicit unverified marker —
never silently pretends to have checked.
"""
from __future__ import annotations

import re

# (name, smarts, severity, note)
#   hard   -> always refuse (non-negotiable mutagen/alkylator classes)
#   medium -> refuse unless the hypothesis declares matching intent
#             (e.g. a covalent-warhead program screening an acrylamide)
ALERTS: list[tuple[str, str, str, str]] = [
    ("aromatic_nitro",      "c[N+](=O)[O-]",                "hard",
     "mutagenicity (DNA adducts after reduction)"),
    ("aromatic_amine_vic",  "Nc1ccc(N)cc1",                 "hard",
     "p-phenylenediamine: methemoglobinemia/redox"),
    ("hydroquinone",        "Oc1ccc(O)cc1",                 "medium",
     "redox cycling / quinone formation"),
    ("quinone",             "O=C1C=CC(=O)C=C1",             "hard",
     "redox cycling, Michael acceptor"),
    ("hydrazine",           "[NX3][NX3]",                   "hard",
     "mutagenicity"),
    ("azo",                 "N=N",                          "hard",
     "azo: reductive cleavage to aromatic amines"),
    ("acyl_halide",         "C(=O)Cl",                      "hard",
     "acylating agent"),
    ("sulfonyl_halide",     "S(=O)(=O)Cl",                  "hard",
     "sulfonylating agent"),
    ("isocyanate",          "N=C=O",                        "hard",
     "protein haptenation"),
    ("azide",               "[N-][N+]#N",                   "hard",
     "nitrene precursor / explosive handle"),
    ("aziridine",           "C1NC1",                        "hard",
     "direct alkylator"),
    ("mustard_like",        "Cl[CX4][CX4][NX3]",            "hard",
     "nitrogen-mustard motif: alkylator"),
    ("alpha_haloketone",    "O=C[CH2]Cl",                   "hard",
     "reactive alkylator"),
    ("epoxide",             "C1OC1",                        "medium",
     "alkylating strain electrophile"),
    ("michael_acceptor",    "C=C[CHX3][CX3]=[OX1]",         "medium",
     "Michael acceptor (enone/enal/enoate)"),
    ("acrylamide",          "C=CC(=O)N",                    "medium",
     "soft thiol electrophile"),
    ("vinyl_sulfonamide",   "C=CS(=O)(=O)",                 "medium",
     "covalent warhead (BTK-style intent)"),
    ("aldehyde_aromatic",   "[cH][CX3H](=O)",               "medium",
     "Schiff-base hapten"),
]

_SELECT_AGENTS = [
    "variola", "smallpox", "bacillus anthracis", "anthrax", "yersinia pestis",
    "plague", "francisella tularensis", "tularensis", "burkholderia mallei",
    "burkholderia pseudomallei", "clostridium botulinum", "botulinum toxin",
    "ebola", "marburg", "lassa", "nipah", "hendra",
    "rickettsia prowazekii", "coxiella burnetii",
    "coccidioides immitis", "avian influenza", "h5n1",
    "ricin", "ricinus communis", "staphylococcal enterotoxin b",
    "severe acute respiratory syndrome coronavirus 2", "sars-coronavirus",
]


def screen_smiles(smiles: str, intent: str = "") -> dict:
    """Toxicophore screen. Returns {status, hits:[{alert,severity,note}]}
    where status is 'checked' | 'no-rdkit'. `intent` (free text, e.g. the
    hypothesis mechanism) downgrades matching medium alerts to warnings."""
    try:
        from rdkit import Chem, RDLogger
        RDLogger.DisableLog("rdApp.*")
    except ImportError:
        return {"status": "no-rdkit", "hits": [], "refuse": []}
    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return {"status": "checked", "hits": [], "refuse": [],
                "note": "unparseable structure"}
    intent_l = (intent or "").lower()
    covalent_intent = any(w in intent_l for w in
                          ("covalent", "warhead", "irreversible"))
    hits, refuse = [], []
    for name, smarts, severity, note in ALERTS:
        try:
            patt = Chem.MolFromSmarts(smarts)
            if patt is not None and mol.HasSubstructMatch(patt):
                downgraded = (severity == "medium" and covalent_intent)
                h = {"alert": name, "severity": "warning" if downgraded
                     else severity, "note": note}
                hits.append(h)
                if severity == "hard" or (severity == "medium"
                                          and not downgraded):
                    refuse.append(h)
        except Exception:
            continue
    return {"status": "checked", "hits": hits, "refuse": refuse}


def durc_screen(text: str) -> list[str]:
    """Cheap, always-on: does this text name a select agent / toxin family?"""
    t = (text or "").lower()
    return [a for a in _SELECT_AGENTS if re.search(re.escape(a), t)]
