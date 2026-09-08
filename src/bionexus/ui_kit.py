"""UI kit — shared visual primitives for the workbench.

One design language across the overview, wizard, and experiment views:
status chips, relative time, and the BioNexus CSS layer.
"""
from __future__ import annotations

import html as _html
import time

import streamlit as st

_CSS = """
<style>
.chip{display:inline-block;padding:2px 10px;border-radius:999px;
 font-family:ui-monospace,SFMono-Regular,monospace;font-size:12px;
 font-weight:600;letter-spacing:.02em;white-space:nowrap}
.chip.running{background:#e6f4ea;color:#1e7d32}
.chip.completed{background:#e8eef7;color:#33507a}
.chip.interrupted{background:#fdecea;color:#a3392c}
.chip.paused{background:#fef7e0;color:#8a6a2c}
.chip.neutral{background:#efece4;color:#5c5749}
.blocker{border-left:3px solid #a3392c;padding-left:10px}
</style>
"""

_CHIP_CLASS = {
    "running": "running", "completed": "completed", "interrupted": "interrupted",
    "awaiting approval": "paused", "ready with warnings": "paused",
    "blocked": "interrupted", "verdict recorded": "completed",
}


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def chip_html(status: str) -> str:
    cls = _CHIP_CLASS.get(status, "neutral")
    dot = "●" if cls == "running" else "○"
    return (f"<span class='chip {cls}'>{dot} {_html.escape(status)}</span>")


def chip(status: str) -> None:
    st.markdown(chip_html(status), unsafe_allow_html=True)


def ago(ts: float | None) -> str:
    """Relative timestamps: 'just now', '4 min ago', '2 h ago', '3 d ago'."""
    if not ts:
        return "—"
    d = time.time() - ts
    if d < 60:
        return "just now"
    if d < 3600:
        return f"{int(d / 60)} min ago"
    if d < 86400:
        return f"{int(d / 3600)} h ago"
    return f"{int(d / 86400)} d ago"
