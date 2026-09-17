"""Assay analysis adapters — real instruments, raw files in, results out.

Each adapter parses a standard raw export and produces provenance-ready
results for the Analyze phase:

- ELISA  (`elisa`)  — plate-reader OD files via labread; blank+cutoff
                      serology, endpoint titers from dilution series
- DSF    (`dsf`)    — thermal melt curves (qPCR-style T vs fluorescence);
                      Tm per curve from the derivative peak
- DLS    (`dls`)    — autocorrelation curves; cumulant fit -> hydrodynamic
                      radius (Stokes-Einstein) + polydispersity flag

Dependency policy: pure Python, no numpy/scipy required — these run in
the core install so any lab file can be analyzed anywhere.
"""
