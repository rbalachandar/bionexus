"""RDKit-backed bio tools (optional extra: pip install bionexus[bio-rdkit]).

Implemented lazily so the module imports cleanly without rdkit installed.
"""
from __future__ import annotations

from typing import Any

from bionexus.core.contracts import ToolInvocation, ToolName, ToolResult


class MoleculeDescriptors:
    """Compute basic descriptors for SMILES payloads (capability: fm_predict_property
    for local, deterministic chemistry — no model server needed)."""

    name = "rdkit_descriptors"
    capabilities = (ToolName.fm_predict_property,)

    def invoke(self, invocation: ToolInvocation) -> ToolResult:
        try:
            from rdkit import Chem
            from rdkit.Chem import Descriptors, Lipinski
        except ImportError:
            return ToolResult(
                envelope=invocation.envelope.model_copy(),
                invocation_id=invocation.invocation_id,
                status="rejected",
                rejection_reason="rdkit not installed (pip install bionexus[bio-rdkit])",
            )
        smiles_list = invocation.args.get("smiles", [])
        out = []
        for smi in smiles_list:
            mol = Chem.MolFromSmiles(smi)
            if mol is None:
                out.append({"smiles": smi, "valid": False})
                continue
            out.append(
                {
                    "smiles": smi,
                    "valid": True,
                    "mol_wt": round(Descriptors.MolWt(mol), 2),
                    "logp": round(Descriptors.MolLogP(mol), 2),
                    "hbd": Lipinski.NumHDonors(mol),
                    "hba": Lipinski.NumHAcceptors(mol),
                }
            )
        return ToolResult(
            envelope=invocation.envelope.model_copy(),
            invocation_id=invocation.invocation_id,
            status="succeeded",
            output={"descriptors": out},
        )
