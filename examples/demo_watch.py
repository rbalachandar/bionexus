"""Demo: agents notice device output — nobody points at files.

An instrument outbox is watched. Two seconds in, a plate reader "finishes" and
drops its export. The agent notices, reads it, updates the open hypothesis
automatically, and tells the scientist what to do next.

    .venv/bin/python examples/demo_watch.py
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, "src")

from bionexus.watch import AutoAnalysisAgent, DeviceMonitor

INBOX = Path(".data/inbox")


def instrument_finishes_later() -> None:
    """Simulate a plate reader completing a run and exporting its file."""
    time.sleep(2.0)
    INBOX.mkdir(parents=True, exist_ok=True)
    (INBOX / "synergy_run0042.csv").write_text(
        "BioTek Synergy HTX\n\nWell ID,Compound,Conc (uM),RFU\n"
        "A1,ctrl,10,100\nA2,ctrl,10,104\n"
        "A3,C-101,0.5,110\nA4,C-101,2,145\nA5,C-101,10,289\nA6,C-101,40,540\n")
    print("[instrument] run 0042 complete -> synergy_run0042.csv exported")


def main() -> None:
    threading.Thread(target=instrument_finishes_later, daemon=True).start()

    # an open hypothesis awaiting this plate's evidence
    from bionexus.adapters.lab.simulator import SimulatorLab
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.core.hypothesis import (ExperimentDesign, HypothesisTracker,
                                          SuccessCriteria)
    from bionexus.core.interfaces import system_actor
    from bionexus.core.safety import LabGateway, SafetyEngine

    store = SqliteProvenanceStore()
    tracker = HypothesisTracker(store, system_actor("watch-demo"))
    gateway = LabGateway(SimulatorLab(seed=42), SafetyEngine(), store,
                         system_actor("watch-demo"))
    tracker.propose(
        statement="C-101 IC50 <= 20 uM", candidate="C-101", assay_type="binding",
        predicted="IC50 <= 20", predicted_value=20.0,
        criteria=SuccessCriteria(metric="ic50_um", direction="min", threshold=20.0),
        design=ExperimentDesign(assay_type="binding", concentrations=["0.5uM", "2uM", "10uM", "40uM"]),
    )

    print(f"[agent] watching instrument outbox {INBOX}/ ...")
    watch(inbox=INBOX, tracker=tracker, stop_after=1, poll_secs=0.5,
          notify=lambda msg: print(f"[agent] {msg}"),
          gateway=gateway, branch_id="watch-demo")
    print("\n[agent] done — noticed, analyzed, verdict, confirmation submitted.\n[agent] the scientist never touched a file; the loop closes itself.")


from bionexus.watch import watch  # noqa: E402

if __name__ == "__main__":
    main()
