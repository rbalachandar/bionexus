"""Pure read-models for the web API (split by screen).

Extracted from the original Streamlit UI; each module is one view family.
Names are re-exported here so `from proef.views import ...` is unchanged.
"""
from __future__ import annotations

from proef.views.counts import (dmta_counts, round_markers, series_view,
                                   verdict_tally)
from proef.views.experiment import experiment_detail
from proef.views.ids import PROVENANCE_DB, resolve_problem, row_status
from proef.views.narrative import narrative_data
from proef.views.pipeline import (_rounds_with_verdicts, _sandbox_summary,
                                     pipeline_cards, pipeline_data)
