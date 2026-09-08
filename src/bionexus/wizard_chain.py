"""Wizard provenance chain — manual experiments hash-chain too (P5).

The wizard's lifecycle steps (definition, readiness review, uploaded
results, verdict) are recorded as provenance records on a `wizard/<id>`
branch, so `bn prove wizard/<id>` audits a scientist-defined experiment
exactly like an agent-driven one.
"""
from __future__ import annotations

from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.core.contracts import Envelope, EventType
from bionexus.core.interfaces import record_for, system_actor

ACTOR = system_actor("scientist")


def wizard_branch(eid: str) -> str:
    return f"wizard/{eid}"


def record_wizard_event(eid: str, event: EventType, decision: dict,
                        db_path: str = "bionexus.db"):
    store = SqliteProvenanceStore(db_path)
    env = Envelope(experiment_branch_id=wizard_branch(eid))
    return store.append(record_for(env, event, ACTOR, decision=decision))
