"""Campaign launch (P2.2): the server-side twin of the workbench's
Launch-program flow. Builds the campaign cfg from the program doc,
spawns the proef-auto subprocess, and records the relational links."""
from __future__ import annotations

from proef.paths import APPROVALS_FILE

import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

from proef.paths import CAMPAIGN_DIR, ensure_dirs


class LaunchError(Exception):
    pass


def build_cfg(doc: dict) -> dict:
    """Campaign cfg from a program doc (mirrors the workbench form)."""
    metric = doc.get("metric") or "potency"
    unit = doc.get("unit") or ""
    direction = doc.get("direction", "min")
    cmp_ = "<=" if direction == "min" else ">="
    gval = float(doc.get("gate_value", 1.0))
    objective = doc.get("objective") or f"Optimize {metric}"
    cfg: dict = {
        "problem": {
            "objective": objective,
            "constraints": [{
                "name": metric,
                "description": f"{metric} {cmp_} {gval:g} {unit}".strip(),
                "kind": "hard", "limit": gval, "unit": unit}],
            "success_metric": f"{metric} gate decisions consistent "
                              "across replicates"},
        "k": int(doc.get("k", 2)),
        "rounds": int(doc.get("rounds", 2)),
        "autonomy": doc.get("autonomy", "act"),
        "concentrations": ["0.5uM", "2uM", "10uM", "40uM"]}
    for key in ("max_families", "max_variants_per_family"):
        if doc.get(key):
            cfg[key] = int(doc[key])
    if doc.get("budget"):
        cfg["budget"] = dict(doc["budget"])
    candidates = [c.strip() for c in (doc.get("candidates") or "").split(",")
                  if c.strip()]
    if candidates:
        modality = (doc.get("modality") or "").lower()
        assay = "binding" if modality in ("", "small molecule") else "custom"
        cfg["hypotheses"] = [{
            "statement": f"{c} achieves {metric} {cmp_} {gval:g} {unit}".strip(),
            "candidate": c, "assay_type": assay,
            "predicted": f"{metric} {cmp_} {gval:g}",
            "predicted_value": gval, "rationale": ""}
            for c in candidates]
    else:
        cfg["hypothesis_source"] = "agent"
    return cfg


def spawn_campaign(doc: dict, program_name: str) -> str | None:
    """Spawn the campaign subprocess + record registry/spec/links.
    decompose=True runs the plan flow instead: the agent splits the
    objective into a guarded problem tree and executes the leaves
    (each leaf links to the program via PROEF_PROGRAM). Returns the
    campaign eid, or None for decomposed launches."""
    from proef import program as program_cfg
    ensure_dirs()
    if doc.get("decompose"):
        return _spawn_plan(doc, program_name)
    cid = f"cmp-{int(time.time())}-{uuid.uuid4().hex[:4]}"
    cfg = build_cfg(doc)
    cfgpath = CAMPAIGN_DIR / f"{cid}.json"
    cfgpath.write_text(json.dumps(cfg, indent=1))
    logf = CAMPAIGN_DIR / f"{cid}.log"

    env = {**__import__("os").environ, "PROEF_PROGRAM": program_name,
           "PROEF_CAMPAIGN_ID": cid}
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "proef.cli", "campaign", "auto", str(cfgpath),
         "--db", "proef.db", "--inbox", str(APPROVALS_FILE),
         "--yes"],
        stdout=open(logf, "ab", buffering=0), stderr=subprocess.STDOUT,
        cwd=str(Path.cwd()), env=env)

    store = __import__("proef.wizard_store",
                       fromlist=["WizardStore"]).WizardStore()
    objective = cfg["problem"]["objective"]
    store.register_agent(cid, objective, str(logf),
                         autonomy=cfg.get("autonomy", "act"), pid=proc.pid)
    try:
        store.set_campaign_spec(
            cid, objective=objective,
            program_slug=program_cfg._slug(program_name),
            constraints=cfg["problem"]["constraints"],
            success_metric=cfg["problem"].get("success_metric"),
            k=cfg.get("k"), rounds=cfg.get("rounds"),
            autonomy=cfg.get("autonomy", "act"),
            hypothesis_source=("agent" if cfg.get("hypothesis_source")
                               == "agent" else "config"),
            n_candidates=len(cfg.get("hypotheses") or []),
            modality=doc.get("modality") or None)
    except Exception:
        pass
    try:
        program_cfg.link_leaf(program_name, cid, campaign_root=None,
                              question=objective, status="executing")
    except Exception:
        pass
    idx = campaign_index()
    idx[cid] = {"pid": proc.pid, "autonomy": cfg.get("autonomy", "act"),
                "objective": objective, "log": str(logf)}
    save_campaign_index(idx)
    return cid


def _spawn_plan(doc: dict, program_name: str) -> None:
    """Decompose launch: proef campaign plan (agent tree decomposition) runs the
    leaves; PROEF_PROGRAM links every leaf to the program."""
    import os as _os
    cands = ",".join(c.strip() for c in
                     (doc.get("candidates") or "").split(",") if c.strip())
    # autonomy comes from the PROGRAM, never hardcoded here: a gate-mode
    # program must not spawn unattended campaigns (audit fix, Oct 10)
    autonomy = doc.get("autonomy") or "gate"
    cmd = [sys.executable, "-u", "-m", "proef.cli", "campaign", "plan",
           "--objective", doc.get("objective") or "optimize",
           "--model", "anthropic", "--run", "--autonomy", autonomy]
    if cands:
        cmd += ["--candidates", cands]
    import json as _j
    cmd += ["--labs-json", _j.dumps(doc.get("labs")
                                    or [{"instrument":
                                         "proef-virtual-lab"}])]
    logf = CAMPAIGN_DIR / f"plan-{int(time.time())}.log"
    env = {**_os.environ, "PROEF_PROGRAM": program_name,
           "PYTHONPATH": str(Path.cwd() / "src")}
    # a plan runs many leaves in ONE process: no single PROEF_CAMPAIGN_ID
    # fits; each leaf announces its own branch via run_tree -> announce_branch
    env.pop("PROEF_CAMPAIGN_ID", None)
    subprocess.Popen(cmd, stdout=open(logf, "ab", buffering=0),
                     stderr=subprocess.STDOUT, cwd=str(Path.cwd()), env=env)


def save_campaign_index(idx: dict) -> None:
    CAMPAIGN_DIR.mkdir(parents=True, exist_ok=True)
    (CAMPAIGN_DIR / "index.json").write_text(json.dumps(idx, indent=1))


def campaign_index() -> dict:
    path = CAMPAIGN_DIR / "index.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}
    return {}
