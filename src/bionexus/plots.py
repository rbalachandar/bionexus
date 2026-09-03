"""Scientist-facing plots — dependency-free SVG dose-response curves.

`dose_response_svg(points, ...)` renders (conc, response) points plus an
optional fitted curve into a small styled SVG. Used by `labread.PlateResult`,
the HTML report, and `bn serve` — anywhere a curve is the answer.
"""
from __future__ import annotations

from typing import Any, Sequence

DEFAULT_W, DEFAULT_H = 560, 340


def dose_response_svg(
    points: Sequence[tuple[float, float]],
    ic50: float | None = None,
    max_response: float | None = None,
    title: str = "Dose–response",
    conc_unit: str = "µM",
    width: int = DEFAULT_W,
    height: int = DEFAULT_H,
    color: str = "#1f7a86",
) -> str:
    """Render one compound's dose-response as an SVG string.

    points:      (conc_um, response) pairs; responses are plotted as % of the
                 curve maximum (normalized internally if they exceed it).
    ic50:        optional fitted IC50 (µM) — drawn as a dashed drop-line.
    max_response: known maximal response for IC50 placement; else the max of
                 the plotted points is used.
    """
    pts = sorted((float(c), float(v)) for c, v in points if v is not None)
    if not pts:
        return _empty(width, height, title)

    ml, mr, mt, mb = 64, 22, 34, 52
    plot_w, plot_h = width - ml - mr, height - mt - mb

    top = max_response if max_response else max(v for _, v in pts) * 1.15
    c_lo, c_hi = min(c for c, _ in pts), max(c for c, _ in pts)
    span = (c_hi - c_lo) or 1.0

    def X(c: float) -> float:
        return ml + (c - c_lo) / span * plot_w

    def Y(v: float) -> float:
        return mt + (1.0 - max(0.0, min(v, top)) / top) * plot_h

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"'
        f' viewBox="0 0 {width} {height}" font-family="ui-sans-serif,system-ui,sans-serif">',
        f'<rect width="{width}" height="{height}" fill="#faf8f2"/>',
    ]
    # gridlines + y labels
    for gv in range(0, 101, 25):
        y = mt + (1 - gv / 100.0) * plot_h
        parts.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{width-mr}" y2="{y:.1f}"'
                     f' stroke="#e3ded2" stroke-width="1"/>')
        parts.append(f'<text x="{ml-8}" y="{y+4:.1f}" text-anchor="end"'
                     f' font-size="11" fill="#6b6558">{gv}</text>')
    # x labels at data concentrations
    label_step = max(1, len(pts) // 5)
    for i, (c, _) in enumerate(pts):
        if i % label_step:
            continue
        x = X(c)
        parts.append(f'<line x1="{x:.1f}" y1="{mt}" x2="{x:.1f}" y2="{height-mb}"'
                     f' stroke="#e3ded2" stroke-width="1"/>')
        parts.append(f'<text x="{x:.1f}" y="{height-mb+18}" text-anchor="middle"'
                     f' font-size="11" fill="#6b6558">{c:g} {conc_unit}</text>')
    # axes
    parts.append(f'<line x1="{ml}" y1="{mt}" x2="{ml}" y2="{height-mb}"'
                 f' stroke="#8a8272" stroke-width="1.2"/>')
    parts.append(f'<line x1="{ml}" y1="{height-mb}" x2="{width-mr}" y2="{height-mb}"'
                 f' stroke="#8a8272" stroke-width="1.2"/>')
    # curve through points
    line = " ".join(f"{X(c):.1f},{Y(v):.1f}" for c, v in pts)
    parts.append(f'<polyline points="{line}" fill="none" stroke="{color}"'
                 f' stroke-width="2.2" stroke-linejoin="round"/>')
    # measured markers
    for c, v in pts:
        parts.append(f'<circle cx="{X(c):.1f}" cy="{Y(v):.1f}" r="4" fill="{color}"'
                     f' stroke="#fff" stroke-width="1.4"/>')
    # IC50 drop-line
    if ic50 is not None and c_lo <= ic50 <= c_hi:
        x = X(ic50)
        y = Y(top / 2.0)
        parts.append(f'<line x1="{x:.1f}" y1="{mt}" x2="{x:.1f}" y2="{height-mb}"'
                     f' stroke="#a97a1c" stroke-width="1" stroke-dasharray="4 3"/>')
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="#a97a1c"/>')
        parts.append(f'<text x="{x+6:.1f}" y="{mt+16}" font-size="12"'
                     f' fill="#8a6a2c">IC50 {ic50:g} {conc_unit}</text>')
    # labels
    parts.append(f'<text x="{ml}" y="20" font-size="13" fill="#2a2823"'
                 f' font-weight="600">{_esc(title)}</text>')
    parts.append(f'<text x="{(ml+width-mr)/2:.0f}" y="{height-8}" text-anchor="middle"'
                 f' font-size="11.5" fill="#6b6558">concentration ({_esc(conc_unit)})</text>')
    parts.append(f'<text x="14" y="{(mt+height-mb)/2:.0f}" text-anchor="middle"'
                 f' font-size="11.5" fill="#6b6558"'
                 f' transform="rotate(-90 14 {(mt+height-mb)/2:.0f})">% response</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _empty(width: int, height: int, title: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}"'
            f' height="{height}"><rect width="100%" height="100%"'
            f' fill="#faf8f2"/><text x="20" y="30" font-size="13"'
            f' fill="#6b6558">{_esc(title)} — no points to plot</text></svg>')
