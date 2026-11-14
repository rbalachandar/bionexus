"""Wizard provenance chain — manual experiments hash-chain too (P5).

The wizard's lifecycle steps (definition, readiness review, uploaded
results, verdict) are recorded as provenance records on a `wizard/<id>`
branch, so `proef prove wizard/<id>` audits a scientist-defined experiment
exactly like an agent-driven one.
"""
from __future__ import annotations

from proef.adapters.store.sqlite import get_store
from proef.core.contracts import Envelope, EventType
from proef.core.interfaces import record_for, system_actor

ACTOR = system_actor("scientist")


def wizard_branch(eid: str) -> str:
    return f"wizard/{eid}"


def record_wizard_event(eid: str, event: EventType, decision: dict,
                        db_path: str = "proef.db"):
    store = get_store(db_path)
    env = Envelope(experiment_branch_id=wizard_branch(eid))
    return store.append(record_for(env, event, ACTOR, decision=decision))
