"""ADMET prediction panel — rule-based + extensible.

Two tiers:
  1. Rule-based filters that work without any external dependency
     (Lipinski RO5, Veber, PAINS alert list as SMARTS-free heuristics)
  2. RDKit-computed descriptors when rdkit is installed (optional dep)

The panel returns structured ADMET predictions that feed into the readiness
review and the TPP evaluation. Model-based predictors (QSAR, ML) implement the
same `ADMETPredictor` protocol and are registered alongside.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ADMETResult:
    smiles: str
    mw_da: float | None = None
    logp: float | None = None
    tpsa: float | None = None
    hbd: int | None = None
    hba: int | None = None
    rotatable_bonds: int | None = None
    lipinski_violations: int = 0
    veber_violations: int = 0
    pains_alerts: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    @property
    def passes_lipinski(self) -> bool:
        return self.lipinski_violations <= 1

    @property
    def passes_veber(self) -> bool:
        return (self.rotatable_bonds is not None and self.rotatable_bonds <= 10 and
                self.tpsa is not None and self.tpsa <= 140)

    @property
    def has_pains(self) -> bool:
        return bool(self.pains_alerts)

    def summary(self) -> dict[str, Any]:
        return {
            "smiles": self.smiles,
            "mw_da": self.mw_da,
            "logp": self.logp,
            "tpsa": self.tpsa,
            "hbd": self.hbd, "hba": self.hba,
            "rotatable_bonds": self.rotatable_bonds,
            "lipinski_violations": self.lipinski_violations,
            "lipinski_pass": self.passes_lipinski,
            "veber_pass": self.passes_veber,
            "pains_alerts": self.pains_alerts,
            "flags": self.flags,
        }


class ADMETPredictor(Protocol):
    """Protocol for any ADMET prediction backend."""

    def predict(self, smiles: str) -> ADMETResult: ...


# ------------------------------------------------ rule-based (no RDKit)

# Known PAINS-like substructure patterns (SMARTS-free string heuristics).
_PAINS_PATTERNS: list[tuple[str, str]] = [
    ("rhodanine", r"O=C1SCC(=S)S1"),
    ("cyanoacrylate", r"C=C\(C#N\)C(=O)"),
    ("hydroxyphenylhydrazide", r"Nc1ccc(O)cc1C(=O)"),
    ("catechol_methyl_sulfate", r"OS\(=O\)\(=O\)OC"),
]

_SIMPLE_MW_FACTORS = {"C": 12.01, "N": 14.01, "O": 16.00, "S": 32.06,
                      "F": 19.00, "Cl": 35.45, "Br": 79.90, "I": 126.90,
                      "P": 30.97, "H": 1.01}


def _estimate_mw(smiles: str) -> float:
    """Crude MW estimate from atom counts in the SMILES string."""
    total = 0.0
    for el, mass in sorted(_SIMPLE_MW_FACTORS.items(), key=lambda x: -len(x[0])):
        count = len(re.findall(r"(?<![A-Za-z])" + el + r"(?![a-z])", smiles))
        total += count * mass
    # implicit hydrogens: rough estimate
    heavy = sum(len(re.findall(r"(?<![A-Za-z])" + el + r"(?![a-z])", smiles))
                for el in _SIMPLE_MW_FACTORS if el != "H")
    total += heavy * 1.5  # ~1.5 H per heavy atom average
    return round(total, 1)


class RuleBasedADMET:
    """Rule-based ADMET estimation without external dependencies.

    Uses SMILES string analysis for approximate molecular weight and
    pattern-matching for PAINS alerts. Accurate descriptor calculation
    (LogP, TPSA, HBD/HBA) requires RDKit via `RDKitADMET`.
    """

    name = "rule-based"

    def predict(self, smiles: str) -> ADMETResult:
        result = ADMETResult(smiles=smiles)
        result.mw_da = _estimate_mw(smiles)
        if result.mw_da > 500:
            result.lipinski_violations += 1
            result.flags.append("MW > 500")

        # PAINS pattern detection
        for name, pattern in _PAINS_PATTERNS:
            if re.search(pattern, smiles):
                result.pains_alerts.append(name)
        if result.pains_alerts:
            result.flags.append(f"PAINS: {', '.join(result.pains_alerts)}")

        return result


class RDKitADMET:
    """Full descriptor calculation using RDKit (requires rdkit extra)."""

    name = "rdkit"

    def __init__(self, pains_check: bool = True):
        self.pains_check = pains_check
        from rdkit import Chem
        from rdkit.Chem import Descriptors, Lipinski, rdMolDescriptors
        self._Chem = Chem
        self._Descriptors = Descriptors
        self._rdMolDescriptors = rdMolDescriptors
        self._Lipinski = Lipinski

    def predict(self, smiles: str) -> ADMETResult:
        mol = self._Chem.MolFromSmiles(smiles)
        if mol is None:
            result = ADMETResult(smiles=smiles)
            result.flags.append("invalid SMILES")
            return result
        result = ADMETResult(smiles=smiles)
        result.mw_da = round(self._Descriptors.MolWt(mol), 1)
        result.logp = round(self._Descriptors.MolLogP(mol), 2)
        result.tpsa = round(self._rdMolDescriptors.CalcTPSA(mol), 1)
        result.hbd = self._Lipinski.NumHDonors(mol)
        result.hba = self._Lipinski.NumHAcceptors(mol)
        result.rotatable_bonds = self._Lipinski.NumRotatableBonds(mol)

        # Lipinski RO5
        violations = 0
        if result.mw_da > 500:
            violations += 1
        if result.logp is not None and result.logp > 5:
            violations += 1
        if result.hbd is not None and result.hbd > 5:
            violations += 1
        if result.hba is not None and result.hba > 10:
            violations += 1
        result.lipinski_violations = violations
        if violations > 1:
            result.flags.append(f"Lipinski violations: {violations}")

        # Veber
        if result.rotatable_bonds is not None and result.rotatable_bonds > 10:
            result.flags.append("rotatable bonds > 10")
        if result.tpsa is not None and result.tpsa > 140:
            result.flags.append("TPSA > 140")

        # PAINS via SMARTS
        if self.pains_check:
            pains_smarts = [
                ("rhodanine", "O=C1SCC(=S)S1"),
                ("cyanoacrylate", "C=C(C#N)C(=O)"),
                ("hydroxyphenylhydrazide", "Nc1ccc(O)cc1C(=O)"),
                ("phenolic_sulfate", "OS(=O)(=O)Oc1ccccc1"),
            ]
            for name, smarts in pains_smarts:
                patt = self._Chem.MolFromSmarts(smarts)
                if patt and mol.HasSubstructMatch(patt):
                    result.pains_alerts.append(name)
            if result.pains_alerts:
                result.flags.append(f"PAINS: {', '.join(result.pains_alerts)}")

        return result


def get_admet_predictor(prefer_rdkit: bool = True) -> ADMETPredictor:
    """Factory: return the best available ADMET predictor."""
    if prefer_rdkit:
        try:
            return RDKitADMET()
        except ImportError:
            pass
    return RuleBasedADMET()
