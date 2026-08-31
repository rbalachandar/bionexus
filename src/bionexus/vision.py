"""Vision-LLM assay readout — a multimodal model reads simulated plate images.

Closes the loop on device evidence: the imaging lab produces well micrographs;
a vision-capable LLM *looks at them* (no numeric access to the underlying
values) and estimates fluorescence; its estimates are fit to an IC50 and
compared against the analysis pipeline's IC50 and the device ground truth.

This is the evaluation harness for "can a multimodal agent do assay analysis?"

Requires: imaging extra (numpy) + BIONEXUS_LLM_*/ANTHROPIC_* env for the model.
"""
from __future__ import annotations

import base64
import json
import os
import re
import struct
import urllib.request
import zlib
from typing import Any


# ------------------------------------------------------------- PNG encoding

def gray_png(arr: Any) -> bytes:
    """Encode a 2-D uint8-ish numpy array as a minimal grayscale PNG."""
    import numpy as np

    a = np.asarray(arr).astype(np.uint8)
    h, w = a.shape
    raw = b"".join(b"\x00" + a[i].tobytes() for i in range(h))  # filter 0 per row

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)  # grayscale 8-bit
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


# ----------------------------------------------------------- vision reader

class VisionWellReader:
    """Ask a multimodal model to quantify a well micrograph (0-100 intensity).

    The model sees ONLY the image pixels — never the ground truth, never the
    pipeline numbers. Its estimates are then fit like any other readout.
    """

    name = "vision-llm"

    def __init__(self, model: str | None = None, base_url: str | None = None,
                 token: str | None = None):
        self.model = (model or os.environ.get("BIONEXUS_LLM_MODEL")
                      or os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
                      or os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL"))
        self.base_url = (base_url or os.environ.get("BIONEXUS_LLM_BASE_URL")
                         or os.environ.get("ANTHROPIC_BASE_URL", "")).rstrip("/")
        self.token = (token or os.environ.get("BIONEXUS_LLM_TOKEN")
                      or os.environ.get("ANTHROPIC_AUTH_TOKEN") or "")
        if not (self.model and self.base_url and self.token):
            raise RuntimeError("vision readout needs BIONEXUS_LLM_/ANTHROPIC_ env config")

    def estimate_intensity(self, image: Any, well_id: str = "") -> float:
        import numpy as np

        a = (np.asarray(image) - np.asarray(image).min())
        a = (a / (a.max() or 1.0) * 255).astype(np.uint8)
        b64 = base64.standard_b64encode(gray_png(a)).decode()
        body = {
            "model": self.model,
            "max_tokens": 2000,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image",
                     "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                    {"type": "text",
                     "text": "This is a fluorescence micrograph of one wells of a 96-well "
                             "plate. Estimate the overall fluorescence intensity on a 0-100 "
                             'scale. Reply ONLY with JSON: {"value": <number>}'},
                ],
            }],
        }
        req = urllib.request.Request(
            f"{self.base_url}/v1/messages", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.token}",
                     "anthropic-version": "2023-06-01"}, method="POST")
        with urllib.request.urlopen(req, timeout=90) as resp:  # noqa: S310
            data = json.loads(resp.read())
        text = "".join(c.get("text", "") for c in data.get("content", [])
                       if c.get("type") == "text")
        import re
        m = re.search(r"-?\d+(?:\.\d+)?", text)
        if not m:
            raise ValueError(f"no number in vision response: {text[:120]}")
        return float(m.group(0))

    def estimate_series(self, images: list[Any], concentrations: list[str]) -> dict[float, float]:
        """Show the whole dose series side-by-side (one composite image) so the
        model can compare wells RELATIVELY — single-image estimation is
        uncalibrated. Returns {conc_um: estimate}."""
        import numpy as np

        raw = [np.asarray(img).astype(np.float64) for img in images]
        lo = min(a.min() for a in raw)
        hi = max(a.max() for a in raw) or 1.0
        # joint normalization: preserves RELATIVE brightness across wells
        arrs = [((a - lo) / (hi - lo) * 255.0).astype(np.uint8) for a in raw]
        sep = np.full((arrs[0].shape[0], 6), 255, dtype=np.uint8)  # white separators
        strip = arrs[0]
        for a in arrs[1:]:
            strip = np.hstack([strip, sep, a])
        b64 = base64.standard_b64encode(gray_png(strip)).decode()
        conc_list = ", ".join(f"panel {i+1} = {c}" for i, c in enumerate(concentrations))
        body = {
            "model": self.model,
            "max_tokens": 2000,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image",
                     "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                    {"type": "text",
                     "text": "This image shows one fluorescence micrograph per panel, "
                             "separated by thin white lines, for a dose-response series: "
                             f"{conc_list}. All panels share the same imaging settings, so "
                             "compare them RELATIVELY. Estimate each panel's fluorescence "
                             "intensity on a 0-100 scale where 0 = background only and "
                             "100 = a COMPLETELY saturated, uniformly bright field — note "
                             "that even the brightest panel here is far from saturation, so "
                             "its value should be well below 100. "
                             'Reply ONLY with JSON: {"values": [<number>, ...]} '
                             "with one number per panel in order."},
                ],
            }],
        }
        req = urllib.request.Request(
            f"{self.base_url}/v1/messages", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.token}",
                     "anthropic-version": "2023-06-01"}, method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
            data = json.loads(resp.read())
        text = "".join(c.get("text", "") for c in data.get("content", [])
                       if c.get("type") == "text")
        m = re.search(r"\[[^\]]*\]", text, re.S)
        if not m:
            raise ValueError(f"no list in vision response: {text[:150]}")
        values = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", m.group(0))]
        return {float(str(c).replace("uM", "")): v
                for c, v in zip(concentrations, values)}

    def read_dose_response(self, well_images: dict[str, tuple[str, float, Any]],
                           max_response: float = 100.0) -> dict[str, float]:
        """well_images: {well_id: (sample_id, conc_um, image)} -> {sample: {conc: estimate}}"""
        out: dict[str, dict[float, float]] = {}
        for well_id, (sample, conc, image) in well_images.items():
            if sample.startswith("ctrl"):
                continue
            out.setdefault(sample, {})[conc] = self.estimate_intensity(image, well_id)
        return {s: {c: v for c, v in sorted(d.items())} for s, d in out.items()}
