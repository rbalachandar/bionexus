"""Instrument output blocks — device-aware rendering of lab results.

Each renderer claims an instrument export and returns an HTML block for the
diary. Dispatch is by (assay, file content) so a plate reader CSV, a
microscope image, a robot protocol log, or a genomics QC table each render
as what they are.

Device authors extend this without touching the diary: call
`register_output_renderer(predicate, renderer)` from an adapter (P4).
"""
from __future__ import annotations

import base64
import csv
import json
from collections.abc import Callable
from html import escape as _esc
from pathlib import Path

Renderer = Callable[[Path, dict], str | None]
# renderer(file_path, ctx) -> html or None to pass. ctx: {assay, instrument,
# run_id, candidate}

_RENDERERS: list[tuple[Callable[[Path, dict], bool], Renderer]] = []


def register_output_renderer(predicate: Callable[[Path, dict], bool],
                             renderer: Renderer) -> None:
    """Adapter extension point: claim files your device produces."""
    _RENDERERS.append((predicate, renderer))


# ----------------------------------------------------------------- helpers

def _block(kind: str, title: str, body: str) -> str:
    return (f"<div class='entry runout'><div class='k'>{_esc(kind)}</div>"
            f"<div class='title'>{title}</div>{body}</div>")


def _table(rows: list[dict], cols: list[str] | None = None,
           max_rows: int = 12) -> str:
    if not rows:
        return ""
    cols = cols or [c for c in rows[0] if c]
    head = "".join(f"<th>{_esc(c)}</th>" for c in cols)
    body = ""
    for r in rows[:max_rows]:
        body += "<tr>" + "".join(
            f"<td class='mono'>{_esc(str(r.get(c, '')))[:40]}</td>" for c in cols) + "</tr>"
    more = (f"<div class='sub'>… {len(rows) - max_rows} more rows</div>"
            if len(rows) > max_rows else "")
    return (f"<table class='grid'>{head}{body}</table>{more}")


# -------------------------------------------------------------- renderers

def _is_image(f: Path, ctx: dict) -> bool:
    return f.suffix.lower() in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".gif")


def _render_image(f: Path, ctx: dict) -> str:
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png",
            "gif": "gif", "tif": "tiff", "tiff": "tiff"}[f.suffix[1:].lower()]
    b64 = base64.b64encode(f.read_bytes()).decode()
    cand = ctx.get("candidate") or ""
    cap = (f"field image — {cand}" if cand else "field image")
    return _block("instrument output", cap,
                  f"<img src='data:image/{mime};base64,{b64}' "
                  f"style='max-width:380px;border-radius:6px' "
                  f"alt='{_esc(cap)}'>")


def _is_dose_response(f: Path, ctx: dict) -> bool:
    if f.suffix.lower() not in (".csv", ".tsv", ".xlsx"):
        return False
    try:
        rows = _read_rows(f)
        hdr = [c.lower() for c in rows[0]] if rows else []
        return any("conc" in c for c in hdr) and any(
            k in c for c in hdr for k in ("rfu", "value", "response", "abs"))
    except Exception:
        return False


def _render_dose_response(f: Path, ctx: dict) -> str:
    from bionexus.labread import read_plate
    from bionexus.plots import dose_response_svg
    result = read_plate(str(f))
    cand = ctx.get("candidate") or ""
    comp = (result.analysis["compounds"].get(cand)
            or next(iter(result.analysis["compounds"].values()), {}))
    ic50 = comp.get("ic50_um")
    pts = [(r["conc_um"], r["value"]) for r in result.records
           if r.get("sample") == cand and not r.get("control")]
    svg = ""
    if pts:
        svg = dose_response_svg(pts, ic50=ic50,
                                title=f"{cand or 'sample'} — {ctx.get('run_id', '')}",
                                width=380, height=220)
    bits = [f"fit IC50 <b>{ic50:.3f} µM</b>" if ic50 else "fit failed"]
    if result.z_prime is not None:
        bits.append(f"Z&#8242; = {result.z_prime:.3f} "
                    f"({'accept' if result.z_prime >= 0.5 else 'marginal'})")
    bits.append(f"{len(result.records)} wells")
    rows_txt = "".join(f"<span class='pt'>{c:g} µM: {v:.1f} RFU</span>"
                       for c, v in pts)
    return _block("instrument output", " · ".join(bits),
                  f"{svg}<div class='pts'>{rows_txt}</div>")


def _read_rows(f: Path) -> list[dict]:
    sep = "\t" if f.suffix.lower() == ".tsv" else ","
    with f.open() as fh:
        return list(csv.DictReader(fh, delimiter=sep))


def _is_robot_log(f: Path, ctx: dict) -> bool:
    if f.suffix.lower() == ".json":
        try:
            d = json.loads(f.read_text())
            return isinstance(d, (list, dict)) and (
                "steps" in d or "ops" in d
                or (isinstance(d, list) and d and isinstance(d[0], dict)
                    and any(k in d[0] for k in ("op", "step", "action"))))
        except Exception:
            return False
    return False


def _render_robot(f: Path, ctx: dict) -> str:
    d = json.loads(f.read_text())
    steps = d.get("steps", d.get("ops", d)) if isinstance(d, dict) else d
    rows = steps if isinstance(steps, list) else []
    body = _table(rows, max_rows=15)
    meta = []
    if isinstance(d, dict):
        for k in ("protocol", "robot", "deck", "duration_s"):
            if d.get(k):
                meta.append(f"{k}: {_esc(str(d[k]))}")
    head = " · ".join(meta) or f"{len(rows)} steps executed"
    return _block("instrument output", head, body)


def _render_generic_table(f: Path, ctx: dict) -> str:
    """Genomics/QC CSVs and anything else tabular: show the data honestly."""
    try:
        rows = _read_rows(f)
    except Exception as exc:
        return _block("instrument output", "unrenderable export",
                      _esc(str(exc))[:120])
    head = f"{len(rows)} rows · {ctx.get('assay') or 'assay'} output"
    return _block("instrument output", head,
                  _table(rows, max_rows=10))


# ------------------------------------------------------- default registry

register_output_renderer(_is_image, _render_image)
register_output_renderer(_is_robot_log, _render_robot)
register_output_renderer(_is_dose_response, _render_dose_response)
register_output_renderer(_render_generic_table, _render_generic_table)


def dispatch_output(f: Path, ctx: dict) -> str:
    """Pick the first renderer that claims this file; degrade gracefully."""
    if not f.exists():
        return _block("instrument output", "pending",
                      "the instrument has not dropped its export yet")
    for pred, renderer in _RENDERERS:
        try:
            if pred(f, ctx):
                out = renderer(f, ctx)
                if out:
                    return out
        except Exception as exc:  # cosmetics must never kill the diary
            return _block("instrument output", "render failed",
                          _esc(str(exc))[:120])
    return _block("instrument output", "unrecognized format",
                  _esc(f.name))
