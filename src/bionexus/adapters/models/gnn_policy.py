"""GNN property policy (optional deps: torch + rdkit) — a small message-passing
network over the molecular graph. This is the "modern baseline" row: closer to
chemprop-class models than FP+RF, still ~150 lines.

Atom features: element one-hot (C/N/O/S/F/Cl/Br/I/other), degree, formal charge,
aromaticity, hybridization-ish via total Hs. Edge: single/double/triple/aromatic.
3 message-passing steps, mean-pool readout, 2-layer MLP head.
"""
from __future__ import annotations

import math

import torch
import torch.nn as nn

ATOMS = ["C", "N", "O", "S", "F", "Cl", "Br", "I", "P", "B"]
BONDS = [1.0, 2.0, 3.0, 1.5]  # single, double, triple, aromatic
A_DIM = len(ATOMS) + 5
B_DIM = len(BONDS)


def _mol_to_graph(smiles: str):
    from rdkit import Chem

    mol = Chem.MolFromSmiles(smiles)
    if mol is None or mol.GetNumAtoms() == 0:
        return None
    x = torch.zeros(mol.GetNumAtoms(), A_DIM)
    for i, atom in enumerate(mol.GetAtoms()):
        sym = atom.GetSymbol()
        x[i, ATOMS.index(sym) if sym in ATOMS else len(ATOMS)] = 1.0
        x[i, len(ATOMS)] = atom.GetTotalDegree() / 4.0
        x[i, len(ATOMS) + 1] = atom.GetFormalCharge() / 2.0
        x[i, len(ATOMS) + 2] = float(atom.GetIsAromatic())
        x[i, len(ATOMS) + 3] = atom.GetTotalNumHs() / 4.0
        x[i, len(ATOMS) + 4] = atom.IsInRing()
    bonds, edges = [], []
    for b in mol.GetBonds():
        bt = b.GetBondTypeAsDouble()
        oneh = [1.0 if bt == bv else 0.0 for bv in BONDS] + [1.0 - max(  # conjugation fallback
            *[1.0 if bt == bv else 0.0 for bv in BONDS])]
        oneh = oneh[:B_DIM]
        for a, z in ((b.GetBeginAtomIdx(), b.GetEndAtomIdx()), (b.GetEndAtomIdx(), b.GetBeginAtomIdx())):
            edges.append((a, z))
            bonds.append(oneh)
    edge_index = torch.tensor(edges, dtype=torch.long).t().contiguous() if edges else torch.zeros(2, 0, dtype=torch.long)
    edge_attr = torch.tensor(bonds) if bonds else torch.zeros(0, B_DIM)
    return x, edge_index, edge_attr


class _MPNN(nn.Module):
    def __init__(self, hidden: int = 64, layers: int = 3):
        super().__init__()
        self.W_msg = nn.ModuleList([nn.Linear(A_DIM + hidden, hidden) for _ in range(layers)])
        self.W_self = nn.ModuleList([nn.Linear(A_DIM if l == 0 else hidden, hidden)
                                     for l in range(layers)])
        self.bond_net = nn.Sequential(nn.Linear(B_DIM, hidden), nn.ReLU())
        self.head = nn.Sequential(nn.Linear(hidden, hidden), nn.ReLU(), nn.Linear(hidden, 1))

    def forward(self, x, edge_index, edge_attr, batch_idx, n_mols):
        h = x
        for lin_msg, lin_self in zip(self.W_msg, self.W_self):
            h_new = lin_self(h)
            if edge_index.numel():
                src, dst = edge_index
                e = self.bond_net(edge_attr)
                agg = torch.zeros_like(h_new)
                msg = h_new[src] * (1.0 + e)
                agg.index_add_(0, dst, msg)
                h_new = h_new + agg
            h = torch.relu(h_new)
        graph = torch.zeros(n_mols, h.size(1))
        graph.index_add_(0, batch_idx, h)
        counts = torch.zeros(n_mols)
        counts.index_add_(0, batch_idx, torch.ones(h.size(0)))
        graph = graph / counts.clamp(min=1).unsqueeze(1)
        return self.head(graph).squeeze(-1)


class GnnPolicy:
    """Graph neural network policy. `task` inferred in fit like MorganFingerprintRF."""

    name = "gnn-mpnn"

    def __init__(self, epochs: int = 40, lr: float = 1e-3, hidden: int = 64, seed: int = 0):
        self.epochs, self.lr, self.hidden, self.seed = epochs, lr, hidden, seed

    def fit(self, data: list[tuple[str, float]]) -> None:
        torch.manual_seed(self.seed)
        graphs = [_mol_to_graph(s) for s, _ in data]
        keep = [i for i, g in enumerate(graphs) if g is not None]
        self._kept = keep
        y = torch.tensor([data[i][1] for i in keep], dtype=torch.float32)
        self.classification = bool(set(y.tolist()) <= {0.0, 1.0})
        batches = []
        rng = torch.Generator().manual_seed(self.seed)
        perm = torch.randperm(len(keep), generator=rng)
        for start in range(0, len(keep), 64):
            idx = perm[start:start + 64]
            xs, eis, eas, bis = [], [], [], []
            offs, acc = [], 0
            for j in idx.tolist():
                x, ei, ea = graphs[j]
                bis.append(torch.full((x.size(0),), len(offs)))
                offs.append(acc)
                acc += x.size(0)
                xs.append(x)
                eis.append(ei + offs[-1])
                eas.append(ea)
            ei = torch.cat(eis, dim=1) if eis else torch.zeros(2, 0, dtype=torch.long)
            batches.append((
                torch.cat(xs), ei,
                torch.cat(eas) if eas else torch.zeros(0, B_DIM),
                torch.cat(bis), len(offs),
                y[idx],
            ))
        self.model = _MPNN(hidden=self.hidden)
        opt = torch.optim.Adam(self.model.parameters(), lr=self.lr)
        self.loss_fn = nn.BCEWithLogitsLoss() if self.classification else nn.MSELoss()
        self.model.train()
        for _ in range(self.epochs):
            for x, ei, ea, bi, n, yy in batches:
                opt.zero_grad()
                out = self.model(x, ei, ea, bi, n)
                loss = self.loss_fn(out, yy)
                loss.backward()
                opt.step()
        self.model.eval()

    def predict(self, smiles: str) -> float:
        g = _mol_to_graph(smiles)
        if g is None:
            return 0.0
        x, ei, ea = g
        with torch.no_grad():
            out = self.model(x, ei, ea, torch.zeros(x.size(0), dtype=torch.long), 1)
            logit = float(out[0])
        return 1.0 / (1.0 + math.exp(-logit)) if self.classification else logit
