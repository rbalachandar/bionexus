"""Sequence safety screening — the biologics side of the safety gate.

Small molecules are screened structurally (toxicophore SMARTS on SMILES).
Biologics are sequences: proteins, mRNAs, DNA. There is no SMARTS for a
protein, so the screen is deliberately honest about what it can check:

1. FORMAT — the sequence must be a valid polymer (amino-acid or
   nucleotide alphabet, sane length). Garbage dressed as a sequence is
   refused, not silently waved through.
2. NAME SCREEN — every protocol string is screened against the same
   regulated-agent list as chemistry (DurcTargetRule covers this at
   protocol level; here we also screen per-sequence description/organism
   metadata, because a sample named "botulinum construct" must not hide
   inside an innocuous-looking sequence).
3. LENGTH CEILING — configurable; constructs beyond it require the same
   human review as BSL-2 chemistry. Default 10 kb.

Versioned like the chemistry rules: refusals cite the screen version.
What this screen does NOT claim: it does not predict toxicity or
immunogenicity from sequence — that is Test-phase work for real assays.
"""
from __future__ import annotations

import re

SEQ_SCREEN_VERSION = "seq-screen-v1"

AA_ALPHABET = set("ACDEFGHIKLMNPQRSTVWYBXZUO-")
NT_ALPHABET = set("ACGTUN-")

_RESTRICTED_NAME_FRAGMENTS = [
    "botulinum", "ricin", "abrin", "saxitoxin", "tetrodotoxin",
    "variola", "ebolavirus", "marburg", "yersinia pestis",
    "francisella", "bacillus anthracis", "clos#tridium",
]


def screen_sequence(sequence: str, description: str = "",
                    max_length: int = 10_000) -> list[str]:
    """Returns a list of refusal reasons; empty list = passes."""
    reasons: list[str] = []
    seq = (sequence or "").strip().upper().replace(" ", "")
    if not seq:
        return ["empty sequence"]
    if len(seq) > max_length:
        reasons.append(f"construct length {len(seq)} nt/aa exceeds the "
                       f"{max_length} ceiling — human review required")
    looks_nt = set(seq) <= NT_ALPHABET
    looks_aa = set(seq) <= AA_ALPHABET
    if not (looks_nt or looks_aa):
        bad = sorted(set(seq) - (AA_ALPHABET | NT_ALPHABET))[:5]
        reasons.append("invalid polymer alphabet (unexpected characters: "
                       + ", ".join(bad) + ")")
    blob = f"{description} {seq[:60]}".lower()
    for frag in _RESTRICTED_NAME_FRAGMENTS:
        if re.search(re.escape(frag.replace("#", "")), blob):
            reasons.append(f"names a regulated toxin/organism "
                           f"('{frag}') — dual-use review required")
            break
    return reasons


class SequenceScreenRule:
    """Safety-gate rule for biologic samples: any sample carrying
    metadata['sequence'] is screened before the lab sees it."""

    name = "sequence_screen"

    def check(self, protocol) -> str | None:
        for s in protocol.samples:
            seq = (s.metadata or {}).get("sequence")
            if not seq:
                continue
            reasons = screen_sequence(
                str(seq), str((s.metadata or {}).get("description", "")))
            if reasons:
                return (f"sequence screen ({SEQ_SCREEN_VERSION}) refused "
                        f"sample '{s.sample_id}': " + "; ".join(reasons))
        return None
