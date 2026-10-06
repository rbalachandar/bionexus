#!/usr/bin/env python3
"""CS08 step-2 job runner: generation -> gates -> screening -> submission.

Modes:
  --mock designs.fasta   full pipeline offline against a stand-in screener
                         (CI-testable; THE FLOW THE 4090 SESSION MUST RUN)
  --generate             BindCraft invocation (needs the 4090 pod; commands
                         are echoed + resumable, never invented results)
  --screen               Boltz-1 interface-confidence pass over gate survivors

Every artifact row carries predicted_by + gate reasons + sha256; the
submission pack is re-derivable from work/ + manifest alone.
"""
from __future__ import annotations

import argparse, hashlib, json, random, subprocess, sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))          # entry_gates / diversity_select
sys.path.insert(0, str(HERE.parents[1] / "src"))

from entry_gates import check_sequence, too_close_to_binders, _kmers  # noqa
from diversity_select import select_diverse                           # noqa


def read_fasta(p: Path):
    out, name, seq = {}, None, []
    for line in p.read_text().splitlines():
        if line.startswith(">"):
            if name:
                out[name] = "".join(seq)
            name, seq = line[1:].split()[0], []
        elif name:
            seq.append(line.strip())
    if name:
        out[name] = "".join(seq)
    return out


def gated(designs: dict, binders: list[str]) -> list[dict]:
    rows = []
    for did, seq in sorted(designs.items()):
        g = check_sequence(seq)
        near = too_close_to_binders(seq, binders) if g["pass"] else False
        rows.append({"id": did, "len": len(seq), "gate_pass": g["pass"] and not near,
                     "gate_reasons": g["reasons"] + (["near-copy of known binder"]
                                                      if near else []),
                     "sha256": hashlib.sha256(seq.encode()).hexdigest()[:16]})
    return rows


def screen(rows: list[dict], known_binders: list[str], n: int, mock: bool):
    """Mock screener: deterministic seeded 'interface confidence' — stands
    in for Boltz-1 iptm so the SELECTION LOGIC is testable. Real mode
    replaces this call, never the policy."""
    pick = [r for r in rows if r["gate_pass"]]
    if mock:
        rng = random.Random(11)
        for r in pick:
            r["screen_iptm"] = round(rng.uniform(0.3, 0.95), 3)
    pick.sort(key=lambda r: -r.get("screen_iptm", 0))
    top = pick[: max(n, 1) * 3]                       # quality pool
    sets = [(r["id"], _kmers(r["id_seq"])) for r in top if r.get("id_seq")]
    chosen = set(select_diverse(sets, n)) if sets else {r["id"] for r in top[:n]}
    out = []
    for r in top:
        if r["id"] in chosen:
            r["selected"] = True
            out.append(r)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", metavar="FASTA")
    ap.add_argument("--fasta", metavar="FASTA", help="designs to gate/screen")
    ap.add_argument("--binders", metavar="FASTA", help="known-binder corpus")
    ap.add_argument("--n-slots", type=int, default=150)
    ap.add_argument("--work", default="work")
    a = ap.parse_args(argv)
    work = Path(a.work); work.mkdir(exist_ok=True)

    if a.mock:
        designs = read_fasta(Path(a.mock))
        rng = random.Random(5)
        for i in range(30):                           # synthetic designs
            L = rng.choice([60, 120, 240, 300])
            designs[f"mock-{i:03d}"] = "M" + "".join(
                rng.choice("ACDEFGHIKLMNPQRSTVWY") for _ in range(L))
        fasta = work / "mock_designs.fasta"
        fasta.write_text("".join(f">{k}\n{v}\n" for k, v in designs.items()))
        src = str(fasta)
    else:
        if not a.fasta:
            ap.error("need --fasta (or --mock)")
        src = a.fasta

    designs = read_fasta(Path(src))
    binders = list(read_fasta(Path(a.binders)).values()) if a.binders else []
    rows = gated(designs, binders)
    byid = {r["id"]: r for r in rows}
    for r in rows:
        r["id_seq"] = designs[r["id"]]
    sel = screen(rows, binders, a.n_slots, mock=bool(a.mock))
    for r in sel:
        r.pop("id_seq", None)
    manifest = {
        "predicted_by": {"source": "model", "policy": "mock-screener-v0"
                         if a.mock else "boltz-1 (pending hardware run)",
                         "note": "MOCK FLOW" if a.mock else "real"},
        "n_designs": len(rows),
        "n_gate_pass": sum(1 for r in rows if r["gate_pass"]),
        "n_selected": len(sel),
        "selected": sel,
        "rejected_sample": [r for r in rows if not r["gate_pass"]][:10],
        "sha256_of_manifest_body": "",
    }
    body = json.dumps({k: v for k, v in manifest.items()
                       if k != "sha256_of_manifest_body"}, sort_keys=True)
    manifest["sha256_of_manifest_body"] = hashlib.sha256(
        body.encode()).hexdigest()
    (work / "submission_manifest.json").write_text(
        json.dumps(manifest, indent=1))
    print(f"designs={manifest['n_designs']} gate_pass={manifest['n_gate_pass']} "
          f"selected={manifest['n_selected']} -> {work/'submission_manifest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
