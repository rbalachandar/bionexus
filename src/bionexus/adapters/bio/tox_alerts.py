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

import json
import re
from pathlib import Path

# Rules live in VERSIONED DATA (safety_rules.json), not code — the list
# scales by editing data (and later ingesting Benigni/Bosa + Toxtree
# rulebooks wholesale), diffs in git, and the version rides along in every
# gate decision so an audit knows WHICH rule set judged a molecule.
_RULES_PATH = Path(__file__).parent / "safety_rules.json"


def _load_rules() -> dict:
    try:
        return json.loads(_RULES_PATH.read_text())
    except Exception:
        return {"version": "builtin-fallback", "alerts": _FALLBACK,
                "select_agents": _FALLBACK_AGENTS}


# (name, smarts, severity, note)

_RULES = _load_rules()
RULES_VERSION = _RULES["version"]
ALERTS = [(a["name"], a["smarts"], a["severity"], a["note"])
          for a in _RULES["alerts"]]
_SELECT_AGENTS = _RULES["select_agents"]


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


# minimal fallback if the data file is missing (never silent: version says so)
_FALLBACK = [a for a in ALERTS if a[0] in ("aromatic_nitro", "aziridine",
                                           "mustard_like", "hydrazine")]
_FALLBACK_AGENTS = ["bacillus anthracis", "variola", "ebola", "yersinia pestis"]
