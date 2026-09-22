"""Virtual Lab Simulator — deterministic, seeded assay outcomes (P4, P8).

Implements LabAdapter. Same contract as any hardware adapter; CI runs this.
Outcome model: per-assay baseline response modulated by a seeded per-sample
factor + gaussian noise, so workflows are reproducible given a seed.
"""
from __future__ import annotations

import hashlib
import random
from typing import Any

from bionexus.core.contracts import (
    AssayResult,
    Envelope,
    InstrumentInfo,
    Measurement,
    MeasurementFlag,
    ProtocolSubmission,
    RunStatus,
)

# assay -> (max_response, unit, noise_std)
ASSAY_PROFILE: dict[str, tuple[float, str, float]] = {
    "binding": (100.0, "percent_inhibition", 4.0),
    "enzymatic": (100.0, "percent_inhibition", 5.0),
    "cytotoxicity": (100.0, "percent_viability_loss", 6.0),
    "counterscreen": (100.0, "percent_interference", 3.0),
    "adme": (70.0, "permeability_score", 9.0),
    "plate_reader": (60.0, "od450", 0.15),
    # materials characterization (simulated property curves)
    "tensile": (250.0, "MPa", 12.0),
    "dsc": (145.0, "degC", 3.0),
    "dls": (120.0, "nm", 8.0),
    "ftir": (97.0, "pct_transmittance", 1.5),
    "xrd": (68.0, "pct_crystallinity", 4.0),
    "density": (7.8, "g_per_cm3", 0.15),
    # biologics
    "elisa": (850.0, "ng_per_mL", 40.0),
    "dsf": (62.0, "degC", 1.2),
    "immunogenicity": (35.0, "pct_response", 4.0),
    "aggregation": (8.0, "pct_aggregate", 0.8),
    "thermal_stability": (71.0, "degC", 1.0),
    # cell therapy
    "potency": (88.0, "pct_potency", 5.0),
    "sterility": (99.0, "pct_sterile", 0.5),
    "phenotype_stability": (92.0, "pct_phenotype", 2.5),
    # mRNA
    "expression": (74.0, "pct_expression", 4.5),
    "stability": (80.0, "pct_intact", 3.0),
    # agrochemical
    "organism_dose_response": (100.0, "pct_mortality", 5.0),
    "phytotoxicity": (100.0, "pct_injury", 5.0),
    "custom": (50.0, "signal", 10.0),
}

DOSE_RESPONSE_ASSAYS = {"binding", "enzymatic", "cytotoxicity", "counterscreen"}


def parse_concentration_um(conc: str | None, default_um: float = 10.0) -> float:
    """Parse '10uM'/'500nM'/None -> micromolar."""
    if not conc:
        return default_um
    c = conc.strip().lower()
    if c.endswith("nm"):
        return float(c[:-2]) / 1000.0
    if c.endswith("um"):
        return float(c[:-2])
    if c.endswith("mm"):
        return float(c[:-2]) * 1000.0
    try:
        return float(c)
    except ValueError:
        return default_um


class SimulatorLab:
    """Virtual lab with realistic assay semantics (P4/P8):

    - Dose–response: repeated sample_ids at increasing concentrations produce a
      Hill curve; `ic50_um` is reported in derived_metrics.
    - Replicates: repeated (sample_id, concentration) pairs are independent
      draws; median is the reported value.
    - Counterscreens: 'counterscreen' assay flags assay-interference artifacts
      (PAINS-like): a seeded fraction of compounds shows false signal.
    """

    name = "simulator"
    version = "sim-v1"

    def __init__(self, seed: int = 7, instruments: dict[str, Any] | None = None,
                 replicates: int = 3, interference_rate: float = 0.25):
        self.seed = seed
        self.replicates = replicates
        self.interference_rate = interference_rate
        self._runs: dict[str, ProtocolSubmission] = {}
        self._capabilities = instruments or {
            "assays": ["binding", "enzymatic", "cytotoxicity", "counterscreen", "adme"],
            "throughput": {"plates_per_day": 20},
            "bsl_max": 2,
        }

    def list_capabilities(self) -> dict[str, Any]:
        return dict(self._capabilities)

    def submit_protocol(self, protocol: ProtocolSubmission) -> str:
        # deterministic run ids (seed + call order): downstream noise seeds
        # derive from run ids, so evals and case studies stay reproducible
        self._seq = getattr(self, "_seq", 0) + 1
        run_id = f"sim-{self.seed}-{self._seq:03d}"
        self._runs[run_id] = protocol
        return run_id

    def get_status(self, run_id: str) -> str:
        return "done" if run_id in self._runs else "failed"

    # -- per-compound ground truth (seeded, stable across runs) ----------------

    def _compound_key(self, protocol_id: str, sample_id: str) -> int:
        # potency is a COMPOUND property, not a run property: key on the
        # seed + sample only, so the same compound has the same ground truth
        # across primary and confirmation runs (protocol_id kept in the
        # signature for call-site stability)
        material = f"{self.seed}:{sample_id}".encode()
        return int(hashlib.sha256(material).hexdigest()[:8], 16)

    def true_ic50_um(self, protocol_id: str, sample_id: str) -> float:
        """Seeded true potency for a compound (stable across runs)."""
        key = self._compound_key(protocol_id, sample_id)
        return 0.5 + (key % 1000) / 1000.0 * 49.5  # 0.5 – 50 uM

    def is_interferer(self, protocol_id: str, sample_id: str) -> bool:
        key = self._compound_key(protocol_id, sample_id)
        return (key % 100) < self.interference_rate * 100

    def set_property_gate(self, metric: str, direction: str,
                          threshold: float) -> None:
        """When the campaign's gate is a property metric (potency, Tm,
        expression...), simulate candidate true values that STRADDLE the
        gate — roughly half pass, half fail — instead of arbitrary
        dose-response numbers. Dose-independent readout."""
        self._property_gate = {"metric": metric, "direction": direction,
                               "threshold": float(threshold)}

    def _property_true_value(self, protocol_id: str, sample_id: str) -> float:
        # seeded by CANDIDATE only: a construct's true property value is
        # fixed — replicate/confirmation runs sample noise around it
        key = self._compound_key("property-truth", sample_id)
        gate = self._property_gate["threshold"]
        # spread candidates across 0.55x–1.45x of the gate, seeded/stable
        factor = 0.55 + (key % 1000) / 1000.0 * 0.9
        return gate * factor

    def fetch_results(self, run_id: str) -> AssayResult:
        protocol = self._runs[run_id]
        assay = protocol.assay_type.value
        max_resp, unit, noise = ASSAY_PROFILE.get(assay, ASSAY_PROFILE["custom"])
        gate = getattr(self, "_property_gate", None)
        property_mode = bool(gate and gate["metric"] not in
                             ("ic50_um", "value"))
        measurements: list[Measurement] = []
        controls_passed = True

        # group wells: (sample_id, concentration) -> replicate draws
        for sample in protocol.samples:
            is_control = sample.kind.value == "buffer" or sample.sample_id.startswith("ctrl")
            conc = parse_concentration_um(sample.concentration)
            ic50 = self.true_ic50_um(run_id, sample.sample_id)
            draws = []
            for rep in range(1, self.replicates + 1):
                rng = random.Random(self._compound_key(run_id + f"r{rep}", sample.sample_id + str(conc)))
                if property_mode and not is_control:
                    # property readout: dose-independent true value per
                    # candidate, stable across replicates + noise
                    true_v = self._property_true_value(run_id, sample.sample_id)
                    value = true_v + rng.gauss(0, noise)
                else:
                    value = self._response(assay, max_resp, conc, ic50, sample.sample_id, run_id)
                    value += rng.gauss(0, noise)
                draws.append(value)
            value = sorted(draws)[len(draws) // 2]  # median of replicates
            flags: list[MeasurementFlag] = []
            if is_control:
                value = 0.0 if assay != "plate_reader" else value
                flags.append(MeasurementFlag.control)
                if assay == "counterscreen" and value > 20:
                    controls_passed = False
            derived: dict[str, float] = {}
            if not is_control:
                derived["conc_um"] = conc
            if assay in DOSE_RESPONSE_ASSAYS and not is_control:
                derived["ic50_um"] = round(ic50, 3)
            measurements.append(
                Measurement(
                    sample_id=sample.sample_id,
                    well=f"{sample.sample_id[:4]}-{conc:g}uM",
                    assay_type=assay,
                    value=round(value, 3),
                    unit=unit,
                    uncertainty=round(noise, 3),
                    replicate=self.replicates,
                    derived_metrics=derived,
                    flags=flags,
                )
            )
        return AssayResult(
            envelope=Envelope(experiment_branch_id="simulator"),
            protocol_id=protocol.protocol_id,
            instrument=InstrumentInfo(adapter=self.name, instrument_id=f"{self.name}-01"),
            status=RunStatus.completed,
            measurements=measurements,
            qc={"controls_passed": controls_passed},
        )

    def _response(self, assay: str, max_resp: float, conc: float, ic50: float,
                  sample_id: str, run_id: str) -> float:
        """Hill curve (n=1): response = max / (1 + IC50/C). Counterscreen is not
        dose-dependent: interferers (PAINS-like) show high artifact signal."""
        if assay == "counterscreen":
            return max_resp * 0.9 if self.is_interferer(run_id, sample_id) else max_resp * 0.02
        return max_resp / (1.0 + ic50 / max(conc, 1e-6))

    def cancel(self, run_id: str) -> None:
        self._runs.pop(run_id, None)
