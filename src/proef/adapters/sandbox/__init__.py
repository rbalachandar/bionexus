"""Sandbox adapters — shared provenance vocabulary.

The exec-record shape is the contract's audit surface: every adapter seals
WHAT was attempted, the outcome, and whether it timed out — recorded
BEFORE any raise, so failures are as visible on the chain as successes.
"""
from __future__ import annotations

import hashlib


def exec_decision(sandbox_id: str, command: str, *, exit_code: int = 0,
                  timed_out: bool = False, output: str = "",
                  **extra) -> dict:
    d = {"sandbox_id": sandbox_id,
         "command_sha256": hashlib.sha256(command.encode()).hexdigest()[:16],
         "exit_code": exit_code, "timed_out": bool(timed_out),
         "output_chars": len(output)}
    d.update(extra)
    return d
