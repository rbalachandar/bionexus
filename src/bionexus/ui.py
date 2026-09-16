"""Workbench UI primitives — icons and status colors.

Single source for the visual vocabulary defined in docs/UX.md and
docs/BRAND.md. Icons are monoline SVGs in assets/icons/, drawn on the
mark's geometry (ring = progress, gate bar = closed, nexus dot =
evidence). No emoji anywhere in the workbench.
"""
from __future__ import annotations

from functools import lru_cache
from html import escape
from pathlib import Path

ICON_DIR = Path(__file__).resolve().parents[2] / "assets" / "icons"

# docs/BRAND.md — semantic status tokens
COLORS = {
    "ink": "#2a2823",
    "paper": "#f3f1ea",
    "card": "#faf8f2",
    "teal": "#1f7a86",
    "refused": "#a3402f",
    "human-action": "#b07d2b",
    "autonomous": "#1f7a86",
    "fault": "#5b5850",
    "provenance": "#8a867c",
    # semantic aliases (docs/UX.md §8): same ink, different meaning
    "progress": "#1f7a86",
    "confirmed": "#1f7a86",
    "resolved": "#2a2823",
}


@lru_cache(maxsize=None)
def _svg(name: str) -> str:
    path = ICON_DIR / f"{name}.svg"
    if not path.exists():                     # honest empty, never fake art
        return ""
    return path.read_text().replace('stroke="currentColor"',
                                    'stroke=":color:"')


def icon(name: str, size: int = 15, color: str = "ink") -> str:
    """Inline-SVG HTML string, baseline-aligned for use next to text."""
    svg = _svg(name)
    if not svg:
        return ""
    svg = svg.replace(":color:", escape(COLORS.get(color, color)))
    svg = svg.replace("<svg ", f'<svg width="{size}" height="{size}" ')
    return (f'<span style="vertical-align:middle;display:inline-block;'
            f'line-height:0;transform:translateY(-1.5px)">{svg}</span>')


def tagged(name: str, label: str, color: str = "ink",
           size: int = 14) -> str:
    """icon + bold word, the standard status chip pattern."""
    return (f'{icon(name, size, color)} <b style="color:'
            f'{COLORS.get(color, color)}">{escape(label)}</b>')


def small(text: str, color: str | None = None) -> str:
    style = (f'style="color:{COLORS[color]}"' if color else "")
    return f"<small {style}>{text}</small>"
