"""Lab awareness — agents notice device outputs instead of being pointed at them.

Three pieces:

1. `DeviceMonitor`  — watches an instrument "outbox"/inbox directory (the
   universal convention: every real instrument exports a file when a run
   completes) and emits `LabEvent`s as files appear.
2. `AutoAnalysisAgent` — consumes those events: reads the result
   (read_plate), updates any hypotheses whose candidate was measured,
   records diary entries into provenance, and queues decisions for the
   scientist. Humans never shuttle files.
3. `bn watch <inbox>` — runs the loop.

The same event interface later maps 1:1 to real push sources (instrument
webhooks, queue depth on the LabGateway, device SDKs) — inbox watching is the
lowest-common-denominator that works with every existing instrument.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator


@dataclass
class LabEvent:
    kind: str                 # "plate_ready" | "file_seen"
    source: str               # device/file path
    path: Path | None = None
    detail: str = ""
    seen_at: float = field(default_factory=time.time)


class DeviceMonitor:
    """Watch a directory instruments write into; yield events for new files."""

    def __init__(self, inbox: str | Path, poll_secs: float = 1.0,
                 patterns: tuple[str, ...] = ("*.csv", "*.tsv", "*.xlsx", "*.npy")):
        self.inbox = Path(inbox)
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.poll_secs = poll_secs
        self.patterns = patterns
        self._seen: set[Path] = set()

    def poll(self) -> list[LabEvent]:
        events = []
        for pattern in self.patterns:
            for f in self.inbox.glob(pattern):
                if f in self._seen:
                    continue
                self._seen.add(f)
                kind = "plate_ready" if f.suffix.lower() in (".csv", ".tsv", ".xlsx") else "file_seen"
                events.append(LabEvent(kind=kind, source=self.inbox.name, path=f,
                                       detail=f"instrument output appeared: {f.name}"))
        return events

    def events(self, stop_after: int | None = None, once: bool = False) -> Iterator[LabEvent]:
        """Blocking generator. `stop_after` bounds total events (for demos/tests)."""
        count = 0
        while True:
            for ev in self.poll():
                yield ev
                count += 1
                if stop_after is not None and count >= stop_after:
                    return
            if once:
                return
            time.sleep(self.poll_secs)


class AutoAnalysisAgent:
    """Reacts to lab events: reads results, updates hypotheses, records decisions.

    `notify` is how the scientist hears about it (console, MCP message, chat...).
    """

    def __init__(self, store: Any = None, tracker: Any = None,
                 notify: Callable[[str], None] | None = None,
                 max_response: float | None = None):
        self.store = store
        self.tracker = tracker
        self.notify = notify or (lambda msg: print(f"[agent] {msg}"))
        self.max_response = max_response

    def handle(self, event: LabEvent) -> dict[str, Any] | None:
        if event.kind != "plate_ready" or event.path is None:
            return None
        from bionexus.labread import read_plate

        self.notify(f"noticed device output: {event.path.name} — reading it")
        result = read_plate(event.path, max_response=self.max_response)
        self.notify(f"analyzed: {len(result.analysis['compounds'])} compound(s), "
                    f"Z'={result.z_prime}")

        # auto-update hypotheses whose candidate appears in this plate
        verdicts = []
        if self.tracker:
            for hyp in self.tracker.hypotheses.values():
                match = result.analysis["compounds"].get(hyp.candidate)
                if match and hyp.status in ("proposed", "designed", "tested") and match["ic50_um"]:
                    # attach evidence directly (measurement already fitted)
                    hyp.observed_value = match["ic50_um"]
                    if hyp.criteria:
                        hyp.status = ("validated" if hyp.criteria.met(match["ic50_um"])
                                      else "invalidated")
                    verdicts.append((hyp.hypothesis_id, hyp.candidate, hyp.status,
                                     match["ic50_um"]))
                    self.notify(f"hypothesis {hyp.hypothesis_id} ({hyp.candidate}): "
                                f"{hyp.status.upper()} — IC50 {match['ic50_um']} uM "
                                f"vs threshold {hyp.criteria.threshold if hyp.criteria else '?'}")
        # scientist-facing diary line
        best = sorted(((c, r["ic50_um"]) for c, r in result.analysis["compounds"].items()
                       if r["ic50_um"]), key=lambda t: t[1])
        if best:
            self.notify(f"recommendation: best binder so far is {best[0][0]} "
                        f"(IC50 {best[0][1]} uM) — next: confirm with orthogonal assay")
        summary = {"compounds": len(result.analysis["compounds"]),
                   "z_prime": result.z_prime, "verdicts": verdicts}
        return summary


def watch(inbox: str | Path, store: Any = None, tracker: Any = None,
          stop_after: int | None = None, poll_secs: float = 1.0,
          notify: Callable[[str], None] | None = None) -> None:
    monitor = DeviceMonitor(inbox, poll_secs=poll_secs)
    agent = AutoAnalysisAgent(store=store, tracker=tracker, notify=notify)
    for event in monitor.events(stop_after=stop_after):
        agent.handle(event)
