"""Approval inbox — the scientist's button, backed by an append-only log.

Autonomy `gate` mode: every lab submission writes a request here and waits for
an operator decision. `bn serve` renders the inbox as a web page with
Approve/Deny buttons; decisions append to the same log. Both sides are
multi-writer-safe (append-only events, folded on read).
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Callable

DEFAULT_INBOX = ".data/approvals.jsonl"


class ApprovalInbox:
    def __init__(self, path: str | Path = DEFAULT_INBOX):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # -- write side (campaigns request, server decides) ----------------------

    def _append(self, event: dict[str, Any]) -> None:
        with self.path.open("a") as f:
            f.write(json.dumps(event) + "\n")

    def request(self, title: str, detail: str = "") -> str:
        aid = f"apr-{uuid.uuid4().hex[:8]}"
        self._append({"event": "request", "id": aid, "title": title,
                      "detail": detail, "ts": time.time()})
        return aid

    def decide(self, approval_id: str, approve: bool, by: str = "operator") -> None:
        self._append({"event": "decision", "id": approval_id,
                      "approve": bool(approve), "by": by, "ts": time.time()})

    # -- read side -------------------------------------------------------------

    def state(self) -> dict[str, dict[str, Any]]:
        """Fold the event log: id -> {title, detail, status, ts}."""
        out: dict[str, dict[str, Any]] = {}
        if not self.path.exists():
            return out
        for line in self.path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("event") == "request":
                out[ev["id"]] = {"title": ev["title"], "detail": ev.get("detail", ""),
                                 "status": "pending", "ts": ev["ts"]}
            elif ev.get("event") == "decision" and ev["id"] in out:
                out[ev["id"]]["status"] = "approved" if ev["approve"] else "denied"
                out[ev["id"]]["decided_by"] = ev.get("by", "operator")
        return out

    def pending(self) -> list[dict[str, Any]]:
        return sorted(({"id": k, **v} for k, v in self.state().items()
                       if v["status"] == "pending"), key=lambda d: d["ts"])

    def status_of(self, approval_id: str) -> str | None:
        rec = self.state().get(approval_id)
        return rec["status"] if rec else None


def web_approver(inbox: ApprovalInbox | str | Path = DEFAULT_INBOX,
                 poll_secs: float = 2.0, timeout_secs: float = 24 * 3600,
                 notify: Callable[[str], None] | None = None
                 ) -> Callable[[str], bool]:
    """Approver callback for `gate` autonomy: request into the inbox, wait for
    the operator's decision in `bn serve`. Denies on timeout."""
    box = inbox if isinstance(inbox, ApprovalInbox) else ApprovalInbox(inbox)
    say = notify or (lambda m: None)

    def approver(title: str) -> bool:
        aid = box.request(title)
        say(f"approval requested: '{title}' ({aid}) — waiting in bn serve")
        deadline = time.time() + timeout_secs
        while time.time() < deadline:
            status = box.status_of(aid)
            if status == "approved":
                say(f"operator APPROVED: {title}")
                return True
            if status == "denied":
                say(f"operator DENIED: {title}")
                return False
            time.sleep(poll_secs)
        say(f"approval timed out: {title}")
        return False

    return approver
