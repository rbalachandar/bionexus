"""Analysis profiles — domain interpretation behind the generic lifecycle.

Each profile owns parsing, preview, QC, and result interpretation for ONE
kind of experimental data. The generic lifecycle (experiment_analysis)
dispatches to exactly the profile the scientist selected; nothing here
leaks into shared contracts.
"""
from proef.analysis_profiles import plate_assay  # noqa: F401
