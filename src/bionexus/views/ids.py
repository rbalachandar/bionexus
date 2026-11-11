"""Id conventions and registry helpers shared by every read-model."""
from __future__ import annotations

import os
import re
from pathlib import Path

from bionexus.paths import DATA_DIR


PROVENANCE_DB = "bionexus.db"


# --------------------------------------------------------------- row status
def row_status(e: dict) -> str:
    """Registry status for log-less runs (tree leaves), log/pid-derived
    status for launched campaigns. Port of webview._row_status."""
    ag = e["payload"].get("agent") or {}
    if not ag:
        return e["status"].replace("_", " ")
    log = ag.get("log") or ""
    logf = Path(log)
    if log and logf.is_file() and "CAMPAIGN COMPLETE" in logf.read_text(
            errors="replace"):
        return "completed"
    pid = ag.get("pid")
    if pid:
        try:
            os.kill(pid, 0)
            return "running"
        except OSError:
            return "interrupted"
    return e["status"]


# ------------------------------------------------------- problem id helpers
def leaf_pid(root_id: str, leaf_id: str) -> str:
    """The ONE campaign pid convention for a leaf of a problem tree:
    problem/<root>-<leaf> (a single-node tree is <root>-<root>)."""
    return f"{root_id}-{leaf_id}"


def resolve_problem(meta: dict, logf: Path) -> str | None:
    """Latest prob-* id for a campaign: explicit metadata wins; else the
    log is searched (problem-registration lines first, then any
    CAMPAIGN COMPLETE-style token). Port of Overview._resolve_problem."""
    problem_id = meta.get("problem_id")
    if logf and str(logf) != "." and Path(logf).is_file():
        txt = Path(logf).read_text(errors="replace")
        m = re.findall(r"problem (prob-\w+):", txt) \
            or re.findall(r"\b(prob-[0-9a-f]+)\b", txt)
        latest = m[-1] if m else None
        if latest and latest != problem_id:
            problem_id = latest
    return problem_id


def wizard_db_path() -> Path:
    """The registry DB path, honoring BIONEXUS_DATA_DIR."""
    return DATA_DIR / "wizard.db"
