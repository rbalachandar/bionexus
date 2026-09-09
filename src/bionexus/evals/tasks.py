"""The task suite. Add tasks here; the harness scores them."""
from __future__ import annotations

from pathlib import Path

from bionexus.evals.harness import (register, run_offline_campaign,
                                    score_confirmation_coverage,
                                    score_hit_recovery, score_verdict_honesty,
                                    verdict_records)

INBOX = Path(".data/evals/inbox")
COMPOUNDS = [f"E-{i:02d}" for i in range(1, 13)]


@register("hit-recovery",
          "screen 12 compounds, k=6; validated set must match seeded truth")
def _t_hit_recovery():
    threshold, seed = 20.0, 11
    report, lab, recs = run_offline_campaign(COMPOUNDS, threshold, 6, seed, INBOX)
    verdicts = verdict_records(recs)
    truth = {}
    for c, d in verdicts.items():
        run_id = d.get("evidence_run_id")
        if run_id:
            truth[c] = lab.true_ic50_um(run_id, c)
    return score_hit_recovery(verdicts, truth, threshold)


@register("verdict-honesty",
          "threshold set exactly at one compound's TRUE IC50 (the harness "
          "knows it): the agent must abstain on the compound sitting on the bar")
def _t_verdict_honesty():
    # potency is seed-stable per compound, so the harness can place the bar
    # exactly on a true value without peeking into the campaign
    from bionexus.adapters.lab.simulator import SimulatorLab
    seed = 11
    tight = SimulatorLab(seed=seed).true_ic50_um("any", "E-03")
    _, lab, recs = run_offline_campaign(COMPOUNDS, tight, 12, seed, INBOX)
    result = score_verdict_honesty(verdict_records(recs))
    result.notes = (f"bar at E-03's true IC50 ({tight:.2f} uM); "
                    + result.notes)
    return result


@register("confirmation-coverage",
          "every CONFIRMED verdict must carry a recorded agreement check")
def _t_confirmation():
    _, _, recs = run_offline_campaign(COMPOUNDS, 20.0, 6, 42, INBOX)
    return score_confirmation_coverage(verdict_records(recs))
