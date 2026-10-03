"""Execution governance — the parts of the harness the agent cannot reach.

Four structural guarantees, all enforced in gateway code OUTSIDE the agent's
tool surface (the Run-Data-Run critique: prose safety is suggestion; code
safety is physics):

1. AuthorizationMatrix — an explicit three-column rulebook
   (autonomous | human-required | never), evaluated per submission.
   Default columns cover BSL, dual-use text, and recurring (SOP-class)
   protocols; operators extend via a JSON file (BIONEXUS_AUTHZ).
2. HaltSwitch — a kill switch on the filesystem. Engaged by a human
   (`bn halt`), checked by the gateway on EVERY submission, cleared only by
   a human (`bn halt --clear`). The agent has no tool that touches it.
3. SopRegistry — anything flagged `recurring` (run unattended on future
   samples) is treated as a standard operating procedure: it needs
   human sign-off before it runs at all, and the approval is recorded.
   One-off commands can be fast; procedures get review, like code.
4. Every governance decision is a provenance event — the audit answers
   "what did the harness allow, refuse, or escalate, and why", not just
   "runtime error, retried".
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any

from bionexus.adapters.bio.tox_alerts import durc_screen

HALT_FILE = Path(".data/HALT")
HALT_HISTORY = Path(".data/HALT-history.json")
SOPS_FILE = Path(".data/sops.json")
AUTHZ_ENV = "BIONEXUS_AUTHZ"


def execution_governance() -> dict:
    """The governance bundle every gateway needs: kill switch +
    authorization matrix, constructed from current defaults/env config.

    Governance is not optional at ANY surface: an agent that reaches the
    gateway via MCP or the CLI is subject to the same physics as a
    campaign. Any LabGateway built outside `run_campaign` SHOULD pass
    `governance=execution_governance()`."""
    return {"matrix": AuthorizationMatrix(), "halt": HaltSwitch()}


# ------------------------------------------------------------ halt switch

class HaltSwitch:
    """Clearing is recorded too: a halt that leaves no trace once lifted
    would hide exactly the episode an audit needs to see."""

    def __init__(self, path: Path | None = None,
                 history_path: Path | None = None):
        self.path = path or HALT_FILE
        self.history_path = history_path or HALT_HISTORY

    def engaged(self) -> dict | None:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except Exception:
                return {"reason": "manual halt"}
        return None

    def history(self, limit: int = 10) -> list[dict]:
        try:
            h = json.loads(self.history_path.read_text())
            return h[-limit:]
        except Exception:
            return []

    def engage(self, reason: str = "operator halt") -> dict:
        entry = {"reason": reason, "ts": time.time(),
                 "id": f"halt-{uuid.uuid4().hex[:6]}"}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(entry, indent=1))
        return entry

    def clear(self, by: str = "operator") -> bool:
        if not self.path.exists():
            return False
        try:
            entry = json.loads(self.path.read_text())
        except Exception:
            entry = {"reason": "manual halt"}
        entry["cleared_ts"] = time.time()
        entry["cleared_by"] = by
        hist: list = []
        try:
            hist = json.loads(self.history_path.read_text())
        except Exception:
            pass
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.history_path.write_text(
            json.dumps(hist + [entry], indent=1))
        self.path.unlink()
        return True


# -------------------------------------------------------- sop registry

class SopRegistry:
    def __init__(self, path: Path | None = None):
        self.path = path or SOPS_FILE

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except Exception:
            return {}

    @staticmethod
    def sop_id(protocol) -> str:
        basis = "|".join([str(protocol.assay_type),
                          ",".join(sorted(str(s.op) for s in protocol.steps)),
                          protocol.title.split("-")[0]])
        return "sop-" + hashlib.sha1(basis.encode()).hexdigest()[:8]  # noqa: S324

    def propose(self, protocol) -> str:
        sid = self.sop_id(protocol)
        reg = self._load()
        if sid not in reg:
            reg[sid] = {"status": "pending", "objective": protocol.title,
                        "assay": str(protocol.assay_type),
                        "proposed_ts": time.time(),
                        "samples_seen": [s.sample_id
                                         for s in protocol.samples[:5]]}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(reg, indent=1))
        return sid

    def approved(self, sid: str) -> bool:
        return self._load().get(sid, {}).get("status") == "approved"

    def approve(self, sid: str, by: str = "operator") -> bool:
        reg = self._load()
        if sid not in reg:
            return False
        reg[sid].update(status="approved", approved_by=by,
                        approved_ts=time.time())
        self.path.write_text(json.dumps(reg, indent=1))
        return True

    def pending(self) -> list[dict]:
        return [dict(v, id=k) for k, v in self._load().items()
                if v.get("status") == "pending"]


# --------------------------------------------------- authorization matrix

class AuthorizationMatrix:
    """Three columns: autonomous | human | never. Checked in order; first
    match decides. Defaults encode today's sane policy; a JSON file
    (env BIONEXUS_AUTHZ) can add rules: [{"name", "assay", "min_bsl",
    "recurring", "text", "column"}]."""

    def __init__(self, config_path: str | Path | None = None):
        self.extra: list[dict] = []
        path = (config_path or __import__("os").environ.get(AUTHZ_ENV, ""))
        if path and Path(path).exists():
            self.extra = json.loads(Path(path).read_text())
        self.sops = SopRegistry()

    def classify(self, protocol) -> tuple[str, str]:
        """-> (column, reason)."""
        blob = " ".join([protocol.title]
                        + [s.sample_id for s in protocol.samples]
                        + [r.name for r in protocol.reagents])
        max_bsl = max([r.bsl_level for r in protocol.reagents] or [0])
        recurring = bool((protocol.constraints or {}).get("recurring"))
        for rule in self.extra:
            if self._matches(rule, protocol, max_bsl, recurring):
                return rule.get("column", "human"), f"rule '{rule.get('name', '?')}'"
        if durc_screen(blob):
            return ("never",
                    "dual-use content: " + ", ".join(durc_screen(blob))[:80])
        if max_bsl >= 3:
            return "never", f"BSL-{max_bsl} work is outside program scope"
        if max_bsl >= 2:
            return "human", f"BSL-{max_bsl} material requires named approval"
        if recurring:
            sid = self.sops.sop_id(protocol)
            if self.sops.approved(sid):
                return "autonomous", f"SOP {sid} signed off"
            self.sops.propose(protocol)
            return ("human",
                    f"recurring procedure needs SOP sign-off ({sid})")
        return "autonomous", "within standing policy"

    @staticmethod
    def _matches(rule: dict, protocol, max_bsl: int, recurring: bool) -> bool:
        if "assay" in rule and str(protocol.assay_type) != rule["assay"]:
            return False
        if "min_bsl" in rule and max_bsl < rule["min_bsl"]:
            return False
        if "recurring" in rule and bool(recurring) != rule["recurring"]:
            return False
        if "text" in rule and rule["text"].lower() not in json.dumps(
                [protocol.title, [s.sample_id for s in protocol.samples]]
        ).lower():
            return False
        return True
