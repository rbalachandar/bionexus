"""Computed story figures — the claims on the Story page, drawn from code.

Every figure regenerates deterministically from shipped modules
(adaptive.DoseDesigner, labread.fit_ic50_ci, plots.dose_response_svg) and
caches to assets/fig/. Same math as the eval tasks, so the site and the
suite can never disagree.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

FIG_DIR = Path("assets/fig")

INK, TEAL, CORAL, DIM, GRID = "#2a2823", "#1f7a86", "#d94f30", "#8a8272", "#e3ded2"
RMAX, SIGMA, GATE = 500.0, 15.0, 20.0
TRUES = [10 ** random.Random(11).uniform(math.log10(0.3), math.log10(150))
         for _ in range(60)]


def _chart(series, xlab, ylab, title, w=560, h=340, ymax=1.0, xfmt="{:g}"):
    ml, mb, mt = 58, 44, 34
    pw, ph = w - ml - 24, h - mt - 40
    xmax = max(s[1][-1] for s in series) or 1

    def X(x): return ml + x / xmax * pw
    def Y(y): return mt + (1 - y / ymax) * ph
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}"'
         f' width="{w}" height="{h}"'
         f' font-family="ui-sans-serif,system-ui,sans-serif">',
         f'<rect width="{w}" height="{h}" fill="#faf8f2"/>',
         f'<text x="{ml}" y="20" font-size="13" font-weight="700"'
         f' fill="{INK}">{title}</text>']
    for gv in (0, .25, .5, .75, 1.0):
        y = Y(gv * ymax)
        s.append(f'<line x1="{ml}" y1="{y:.0f}" x2="{w-24}" y2="{y:.0f}"'
                 f' stroke="{GRID}"/>')
        s.append(f'<text x="{ml-6}" y="{y+4:.0f}" text-anchor="end"'
                 f' font-size="10.5" fill="{DIM}">{gv * ymax:.0%}</text>')
    for name, xs, ys, color in series:
        pts = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in zip(xs, ys))
        s.append(f'<polyline points="{pts}" fill="none" stroke="{color}"'
                 f' stroke-width="2.6"/>')
        for x, y in zip(xs, ys):
            s.append(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="3"'
                     f' fill="{color}"/>')
    step = max(1, len(series[0][1]) // 5)
    for i in range(0, len(series[0][1]), step):
        x = series[0][1][i]
        s.append(f'<text x="{X(x):.0f}" y="{h-mb+18}" text-anchor="middle"'
                 f' font-size="10.5" fill="{DIM}">{xfmt.format(x)}</text>')
    s.append(f'<text x="{w/2}" y="{h-6}" text-anchor="middle" font-size="11"'
             f' fill="{DIM}">{xlab}</text>')
    s.append(f'<text x="14" y="{h/2}" font-size="11" fill="{DIM}"'
             f' transform="rotate(-90 14 {h/2})" text-anchor="middle">'
             f'{ylab}</text>')
    lx, ly = ml + 8, mt + 8
    for name, _, _, color in series:
        s.append(f'<rect x="{lx}" y="{ly-8}" width="10" height="10"'
                 f' fill="{color}"/>')
        s.append(f'<text x="{lx+15}" y="{ly}" font-size="11" fill="{INK}">'
                 f'{name}</text>')
        ly += 16
    s.append("</svg>")
    return "\n".join(s)


def _decidable(est, ci, gate=GATE):
    return 1 if (ci[0] > gate and ci[1] > gate) or (ci[0] < gate and ci[1] < gate) else 0


def recovery_curve_svg() -> str:
    """Decision confidence vs assay wells: adaptive vs fixed vs random."""
    from bionexus.adaptive import DoseDesigner
    conf_a, conf_f, conf_r = [0] * 7, [0] * 7, [0] * 7
    for idx, t in enumerate(TRUES):
        d = DoseDesigner(rmax=RMAX, sigma=SIGMA)
        nr = DoseDesigner(rmax=RMAX, sigma=SIGMA)
        for w in range(6):
            noise = random.Random(1000 + idx * 10 + w).gauss(0, SIGMA)
            c = d.next_dose()
            if c is not None:
                d.observe(c, max(0.0, RMAX / (1 + t / c) + noise))
            est, ci = d.estimate()
            conf_a[w + 1] += _decidable(est, ci)
            fixed_c = (0.5, 2, 10, 40)[min(w, 3)]
            nr.observe(fixed_c, max(0.0, RMAX / (1 + t / fixed_c) + noise))
            est, ci = nr.estimate()
            conf_f[w + 1] += _decidable(est, ci)
        dd = DoseDesigner(rmax=RMAX, sigma=SIGMA,
                          doses=(0.25, 0.5, 1, 2, 5, 10, 20, 40, 80))
        rr = random.Random(idx)
        for w in range(6):
            c = (0.5, 2, 10, 40, 80, 1)[w]
            dd.observe(c, max(0.0, RMAX / (1 + t / c) + rr.gauss(0, SIGMA)))
            est, ci = dd.estimate()
            conf_r[w + 1] += _decidable(est, ci)
    n = len(TRUES)
    return _chart([("adaptive (Bayesian)", list(range(1, 7)),
                    [c / n for c in conf_a], TEAL),
                   ("fixed 4-point series", list(range(1, 7)),
                    [c / n for c in conf_f], INK),
                   ("random doses", list(range(1, 7)),
                    [c / n for c in conf_r], CORAL)],
                  "assay wells spent", "confident decisions",
                  "Decision confidence vs assay budget — 60 simulated compounds,"
                  " gate at 20 µM")


def abstention_rate_svg() -> str:
    """Abstention (inconclusive) rate vs distance from the gate."""
    from bionexus.adaptive import DoseDesigner
    from bionexus.core.hypothesis import SuccessCriteria
    crit = SuccessCriteria(metric="ic50_um", threshold=GATE)
    bins: list[list[float]] = [[] for _ in range(5)]
    for idx, t in enumerate(TRUES):
        b = min(4, int(abs(math.log10(t / GATE)) / 0.3))
        flips = 0
        for nv in range(3):
            d = DoseDesigner(rmax=RMAX, sigma=SIGMA)
            for c in (0.5, 2, 10, 40):
                d.observe(c, max(0.0, RMAX / (1 + t / c)
                                 + random.Random(idx * 7 + nv * 100 + c)
                                 .gauss(0, SIGMA)))
            est, ci = d.estimate()
            if crit.classify(est, tuple(ci)) == "inconclusive":
                flips += 1
        bins[b].append(flips / 3)
    xs = [0.05, 0.35, 0.65, 0.95, 1.25]
    ys = [sum(b) / len(b) if b else 0.0 for b in bins]
    return _chart([("abstention rate", xs, ys, TEAL)],
                  "distance from gate  |log₁₀(true IC50 / gate)|",
                  "verdicts abstained",
                  "Honesty by design: abstention rate vs distance from the gate")


def evidence_panel_svg() -> str:
    """Three dose-response curves with CI bands: hit / narrow margin / miss."""
    from bionexus.labread import fit_ic50_ci
    from bionexus.plots import dose_response_svg
    combo = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1092 250"'
             ' width="100%"><rect width="1092" height="250" fill="#faf8f2"/>')
    for i, (t, lab) in enumerate([(2.4, "clear hit"), (18.9, "narrow margin"),
                                  (47.3, "clear miss")]):
        rr = random.Random(i)
        pts = [(c, max(0.0, RMAX / (1 + t / c) + rr.gauss(0, SIGMA)))
               for c in (0.5, 2, 10, 40)]
        f = fit_ic50_ci(pts, None)
        svg = dose_response_svg(
            pts, ic50=f["ic50"], ci=(f["ci_low"], f["ci_high"]),
            title=f"{lab}: fit {f['ic50']:.1f} µM"
                  f" (CI {f['ci_low']:.1f}–{f['ci_high']:.1f})",
            width=360, height=230)
        inner = svg[svg.index(">") + 1:svg.rindex("</svg>")]
        combo += (f'<g transform="translate({i*364},8)">'
                  f'{inner.replace(chr(34)+"360"+chr(34), chr(34)+"360"+chr(34))}'
                  f'</g>')
    return combo + "</svg>"


def run_evidence_svg(items: list[dict]) -> str:
    """REAL evidence panels: one per recorded plate file, fitted from the
    actual readings — never synthetic. `items` = [{"path", "label",
    "verdict"}]. Returns "" when nothing is plottable (honest empty)."""
    from bionexus.labread import read_plate, fit_ic50_ci
    from bionexus.plots import dose_response_svg
    panels = []
    for it in items:
        try:
            pr = read_plate(it["path"])
        except Exception:
            continue
        pts = sorted({(r["conc_um"], r["value"]) for r in pr.records
                      if not r.get("control") and r.get("conc_um")})
        if len(pts) < 3:
            continue
        try:
            f = fit_ic50_ci(pts, None)
        except Exception:
            continue
        label = it.get("label") or Path(it["path"]).stem
        title = (f"{label}: fit {f['ic50']:.1f} "
                 f"{pr.response_unit or 'µM'}"
                 f" (CI {f['ci_low']:.1f}\u2013{f['ci_high']:.1f})")
        verdict = it.get("verdict")
        if verdict in ("validated", "confirmed"):
            title += " \u00b7 pass"
        elif verdict == "inconclusive":
            title += " \u00b7 abstain"
        elif verdict in ("refuted", "invalidated"):
            title += " \u00b7 fail"
        svg = dose_response_svg(
            pts, ic50=f["ic50"], ci=(f["ci_low"], f["ci_high"]),
            title=title, width=360, height=230)
        inner = svg[svg.index(">") + 1:svg.rindex("</svg>")]
        panels.append(inner)
    if not panels:
        return ""
    width = max(360, len(panels) * 364)
    combo = (f'<svg xmlns="http://www.w3.org/2000/svg" '
             f'viewBox="0 0 {width} 250" width="100%">'
             f'<rect width="{width}" height="250" fill="#faf8f2"/>')
    for i, inner in enumerate(panels):
        combo += (f'<g transform="translate({i * 364},8)">{inner}</g>')
    return combo + "</svg>"


def get(name: str) -> str:
    """Cached figure: 'recovery' | 'stability' | 'evidence'."""
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    path = FIG_DIR / f"{name}.svg"
    if path.exists():
        return path.read_text()
    svg = {"recovery": recovery_curve_svg, "stability": abstention_rate_svg,
           "evidence": evidence_panel_svg}[name]()
    path.write_text(svg)
    return svg
