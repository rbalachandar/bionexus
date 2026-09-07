"""Campaign templates — scientist-callable presets.

`bn templates` lists them; `bn auto --template dose-response-screen
--field compounds=C1,C2,C3` fills the template (prompts for missing required
fields), turns the compound list into a hypothesis portfolio, and runs the
campaign. Users never see JSON unless they want to.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TEMPLATE_DIR = Path(__file__).parent / "templates"
USER_TEMPLATE_DIR = Path(".data/templates")   # drop your own .json here


def list_templates() -> list[dict[str, str]]:
    out = []
    seen = set()
    for d in (TEMPLATE_DIR, USER_TEMPLATE_DIR):
        if not d.exists():
            continue
        for f in sorted(d.glob("*.json")):
            doc = json.loads(f.read_text())
            name = doc["template"]
            if name in seen:
                continue
            seen.add(name)
            out.append({"name": name,
                        "description": doc.get("description", ""),
                        "source": "user" if d == USER_TEMPLATE_DIR else "built-in"})
    return out


def load_template(name: str) -> dict[str, Any]:
    for d in (USER_TEMPLATE_DIR, TEMPLATE_DIR):   # user overrides built-in
        path = d / f"{name}.json"
        if path.exists():
            return json.loads(path.read_text())
    raise FileNotFoundError(
        f"unknown template '{name}' — available: "
        + ", ".join(t["name"] for t in list_templates()))


def save_user_template(name: str, description: str, problem: dict[str, Any],
                       assay: dict[str, Any]) -> Path:
    """Persist a reusable template under .data/templates/<name>.json."""
    from bionexus.paths import ensure_dirs
    ensure_dirs()
    safe = "".join(c for c in name.lower() if c.isalnum() or c in "-_")
    path = USER_TEMPLATE_DIR / f"{safe}.json"
    path.write_text(json.dumps({
        "template": safe,
        "description": description,
        "problem": problem,
        "hypotheses": [],
        "hypothesis_source": "config",
        "autonomy": "gate",
        "assay": assay,
        "fields": {
            "compounds": {"prompt": "Compounds (comma-separated)",
                          "required": True},
            "threshold": {"prompt": "Potency threshold (uM)",
                          "default": 20},
        },
    }, indent=1))
    return path


def fill(template: dict[str, Any], fields: dict[str, str],
         prompt_missing: bool = True) -> dict[str, Any]:
    """Interpolate {placeholders} from fields; prompt (or error) on missing
    required fields. Returns the rendered template doc."""
    values = dict(fields)
    for key, spec in template.get("fields", {}).items():
        if key in values:
            continue
        if spec.get("default") is not None:
            values[key] = str(spec["default"])
        elif prompt_missing:
            values[key] = input(f"{spec['prompt']}: ").strip()
        elif spec.get("required"):
            raise ValueError(f"missing required field '{key}' ({spec['prompt']})")

    def sub(obj: Any) -> Any:
        if isinstance(obj, str):
            for k, v in values.items():
                obj = obj.replace("{" + k + "}", v)
            return obj
        if isinstance(obj, list):
            return [sub(x) for x in obj]
        if isinstance(obj, dict):
            return {k: sub(v) for k, v in obj.items()}
        return obj

    rendered = sub({k: v for k, v in template.items() if k != "fields"})
    rendered["_values"] = values
    return rendered


def build_campaign(rendered: dict[str, Any]) -> dict[str, Any]:
    """Turn a filled template into a campaign config (the `bn auto` JSON):
    compounds become one hypothesis each with the template's potency criteria."""
    compounds = [c.strip() for c in
                 rendered.get("_values", {}).get("compounds", "").split(",") if c.strip()]
    threshold = float(rendered.get("_values", {}).get("threshold", 20) or 20)
    assay = rendered.get("assay", {})
    concs = assay.get("concentrations", ["0.5uM", "2uM", "10uM", "40uM"])
    hypotheses = [
        {"statement": f"{c} binds with IC50 <= {threshold:g} uM",
         "candidate": c, "assay_type": assay.get("type", "binding"),
         "predicted": f"IC50 <= {threshold:g}", "predicted_value": threshold,
         "rationale": "template: dose-response screen"}
        for c in compounds
    ]
    return {
        "problem": rendered["problem"],
        "hypotheses": hypotheses,
        "k": int(rendered.get("_values", {}).get("k", 2) or 2),
        "autonomy": rendered.get("autonomy", "gate"),
        "concentrations": concs,
    }
