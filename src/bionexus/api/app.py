"""BioNexus web API (P0.5): thin FastAPI layer over the engine.

One uvicorn process serves REST + SSE; the SPA is mounted statically in
production. All state lives in the existing wizard/provenance stores.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import UploadFile
from pydantic import BaseModel

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from bionexus import program as program_cfg
from bionexus import views
from bionexus.adapters.store.sqlite import SqliteProvenanceStore
from bionexus.paths import DATA_DIR
from bionexus.wizard_store import WizardStore

app = FastAPI(title="BioNexus API", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["http://localhost:5173"],
    allow_methods=["*"], allow_headers=["*"])

# ------------------------------------------------------------- SSE broker
_subscribers: set[asyncio.Queue] = set()
_broker: asyncio.Queue = asyncio.Queue()
_watcher_task = None


@app.on_event("startup")
async def _start_watcher():
    global _watcher_task
    from bionexus.api.sse import watcher_loop
    if _watcher_task is None:
        _watcher_task = asyncio.create_task(watcher_loop(_broker))
        asyncio.create_task(_pump())


async def _pump():
    """Move watcher events to every subscriber queue."""
    while True:
        ev = await _broker.get()
        for q in list(_subscribers):
            q.put_nowait(ev)


def get_ws() -> WizardStore:
    return WizardStore()


def publish_workspace(kind: str, payload: dict) -> None:
    """Persist + fan out a workspace-level event (no subprocess needed —
    these originate in this process)."""
    from bionexus.api.sse import record_event
    record_event("workspace", kind, payload)


def get_prov():
    db = Path("bionexus.db")
    if not db.exists():
        return None
    return SqliteProvenanceStore(str(db))


# --------------------------------------------------------------- system
@app.get("/api/system/health")
def health() -> dict:
    return {"ok": True, "wizard_db": views.wizard_db_path().exists(),
            "provenance_db": Path("bionexus.db").exists()}


@app.get("/api/evals")
def evals() -> dict:
    """The product pitch: the last `bn eval` leaderboard, with the honest
    sub-1.0 deductions surfaced (the harness refusing to overcredit its own
    agent). Read-model of the committed artifacts — not a live re-run."""
    from bionexus.evals.harness import leaderboard_payload

    return leaderboard_payload()


@app.get("/api/system/modalities")
def modalities() -> dict:
    from bionexus.modality import PACKS
    return {"packs": [
        {"name": p.name, "production_action": p.production_action,
         "test_assays": list(p.test_assays),
         "safety_rule_names": list(p.safety_rule_names),
         "notes": p.notes}
        for p in PACKS.values()]}


@app.get("/api/halt")
def halt_state() -> dict:
    from bionexus.governance import HaltSwitch
    hs = HaltSwitch()
    halt = hs.engaged()
    return {"halted": halt is not None, "detail": halt,
            "history": hs.history()}


@app.post("/api/halt")
def halt_set(body: dict) -> dict:
    from bionexus.governance import HaltSwitch
    hs = HaltSwitch()
    if body.get("halted"):
        hs.engage(body.get("reason", "operator halt (web)"))
    else:
        hs.clear()
    return halt_state()


@app.get("/api/approvals")
def approvals() -> dict:
    from bionexus.approvals import ApprovalInbox
    inbox = ApprovalInbox(".data/approvals.jsonl")
    st = inbox.state()
    return {"pending": [{"id": k, **v} for k, v in st.items()
                        if v.get("status") == "pending"],
            "decided": [{"id": k, **v} for k, v in st.items()
                        if v.get("status") != "pending"]}


@app.post("/api/approvals/{aid}/decide")
def approval_decide(aid: str, body: dict) -> dict:
    from bionexus.approvals import ApprovalInbox
    inbox = ApprovalInbox(".data/approvals.jsonl")
    inbox.decide(aid, bool(body.get("approve")),
                 by=body.get("by", "operator-web"))
    return approvals()


# ------------------------------------------------------------- programs
@app.get("/api/instruments")
def instruments() -> dict:
    """The catalog + local availability: what the program form may fence."""
    from bionexus.labselect import available_instruments, load_catalog
    return {"catalog_version": load_catalog()["version"],
            "instruments": available_instruments()}


@app.get("/api/programs")
def programs(include_archived: bool = False) -> dict:
    ws = get_ws()
    return views.workspace(ws, include_archived=include_archived)


@app.get("/api/taste")
def taste() -> dict:
    """Taste distillation (advisory): accept-rate deltas by hypothesis
    feature across all campaigns + proposed prompt amendments. Never
    applied — display only."""
    from bionexus.taste import taste_report
    try:
        return taste_report()
    except Exception as exc:  # noqa: BLE001
        return {"n": 0, "accepted": 0, "overall_rate": 0.0,
                "by_feature": {}, "families": {},
                "amendments": [], "error": str(exc)}


@app.get("/api/programs/{slug}")
def program_detail(slug: str) -> dict:
    ws = get_ws()
    ws_view = views.workspace(ws)
    prog = next((p for p in ws_view["programs"] if p["slug"] == slug), None)
    if prog is None:
        raise HTTPException(404, f"program {slug} not found")
    _ensure_brief(prog)   # background: (re)draft when evidence changed
    return prog


_brief_inflight: set[str] = set()


def _brief_evidence_hash(prog: dict) -> str:
    """Stable digest of the evidence a brief was drafted from — a new
    leaf verdict, run, or taste decision invalidates the cached brief."""
    import hashlib
    v = prog.get("verdict") or {}
    parts = [prog["slug"], str(v.get("status")),
             f"{v.get('resolved')}/{v.get('leaves')}"]
    g = v.get("gate")
    if g:
        parts.append(f"gate:{g.get('status')}")
    for t in prog.get("trees") or []:
        for nid, ls in (t.get("leaf_stats") or {}).items():
            parts.append(f"{nid}:{ls.get('hyp', 0)}:{ls.get('ok', 0)}:"
                         f"{ls.get('runs', 0)}")
    # non-tree campaigns count too — completing a launched next-action
    # changes this and triggers an auto-redraft on the next page open
    for l in prog.get("links") or []:
        if l.get("campaign_root"):
            continue  # tree roots are containers
        v = l.get("verdicts") or {}
        parts.append(f"link:{l.get('eid')}:{l.get('runs', 0)}:"
                     f"{v.get('confirmed', 0)}:{v.get('preliminary', 0)}:"
                     f"{v.get('refuted', 0)}:{v.get('inconclusive', 0)}")
    taste = prog.get("taste")
    if taste:
        parts.append(f"taste:{taste.get('n')}:{taste.get('accepted')}")
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def _brief_prompt(prog: dict) -> str:
    v = prog.get("verdict") or {}
    lines = [f"Program: {prog['name']} (id {prog.get('pid')})",
             f"Objective: {prog.get('objective') or prog['gate_summary']}",
             f"Deterministic verdict: {v.get('status')} — {v.get('reason')}"]
    gate = v.get("gate")
    if gate:
        lines.append(f"Gate ({gate.get('metric')}): {gate.get('status')} "
                     f"— leaf: {gate.get('leaf')}")
    lines.append("Already explored in the program's iteration loops "
                 "(do NOT recommend these again in Next):")
    for t in prog["trees"]:
        lines.append(f"Problem tree: {t['objective']}")
        parents = {n["parent"] for n in t["nodes"] if n["parent"]}
        for n in t["nodes"]:
            if n["id"] in parents:
                continue
            st = t["rollup"].get(n["id"], "?")
            ls = (t.get("leaf_stats") or {}).get(n["id"]) or {}
            lines.append(
                f"- [{st}] {n['objective']}"
                f" (tested={ls.get('hyp', 0)}, ok={ls.get('ok', 0)},"
                f" runs={ls.get('runs', 0)})")
    taste = prog.get("taste")
    if taste and taste.get("n"):
        lines.append(f"Decision profile (selection taste learned across "
                     f"the loop): {taste.get('n')} decisions, "
                     f"{taste.get('accepted')} accepted "
                     f"({taste.get('overall_rate', 0):.0%} overall rate); "
                     "Next must build on this taste, not repeat it")
    return (
        "You are writing a short learning brief for a drug-discovery "
        "program lead after several autonomous iteration loops. Use ONLY "
        "the evidence below — do not invent results. Three short "
        "sections, plain text, no markdown headers beyond 'Learned:', "
        "'Blocks:', 'Next:'. Be honest about inconclusive evidence.\n"
        "The program must CONVERGE, not drill: next actions must be "
        "decisive, single-variable experiments that can RESOLVE an "
        "unresolved sub-problem or the stated discrepancy — never "
        "another broad exploration round, and never a refinement of "
        "work that already succeeded. Weigh whether the evidence "
        "already answers the objective.\n"
        "End with EXACTLY ONE of:\n"
        "1. A final line 'CONCLUSION:' followed by 1-2 sentences "
        "stating the program's answer to the objective (used when the "
        "evidence, despite mixed leaves, already supports a defensible "
        "call — favor this over proposing yet more work when the "
        "remaining gaps are assay-level, not decision-relevant).\n"
        "2. A final line 'NEXT:' followed by up to 3 lines, one per "
        "launchable campaign, each formatted exactly: '- <specific, "
        "self-contained objective for a single experiment> [single]' "
        "or '- <objective> [composite]' — tag [single] when one "
        "decisive experiment answers it, [composite] when it hides "
        "sub-questions and needs decomposition into a problem tree. "
        "NEXT: is mandatory.\n\n" + "\n".join(lines))


def _parse_actions(text: str) -> tuple[str, list[dict], str | None]:
    """Split the model draft into (prose, next actions, conclusion).
    Each action: {"objective": str, "tree": bool} — tree=True for
    [composite]-tagged actions that need decomposition."""
    import re
    cm = None
    for cm in re.finditer(r"^CONCLUSION:?\s*(.*)$", text, re.M | re.I):
        pass
    if cm is not None:
        conclusion = cm.group(1).strip()
        if not conclusion:
            after = text[cm.end():].strip()
            conclusion = after.splitlines()[0] if after else ""
        prose = text[:cm.start()].rstrip()
        nx = prose.rfind("NEXT:")
        if nx != -1:
            prose = prose[:nx].rstrip()
        return prose, [], conclusion[:500] or None
    m = None
    for m in re.finditer(r"^NEXT:?\s*$", text, re.M):
        pass
    if m is not None:
        prose = text[:m.start()].strip()
        actions = [_parse_action_line(l)
                   for l in text[m.end():].splitlines()]
        return prose, [a for a in actions if a][:3], None
    # fallback: no NEXT footer — lift actions out of the 'Next:' prose
    # section (split on enumeration markers / sentence boundaries)
    sec = None
    for sec in re.finditer(r"^Next:\s*(.*)$", text, re.M | re.I):
        pass
    if sec is None:
        return text.strip(), [], None
    body = sec.group(1) + "\n" + text[sec.end():]
    chunks = re.split(r"\(\d+\)|\.\s+|\n", body)
    actions = []
    for c in chunks:
        c = re.sub(r"^(?:[-*\u2022]\s*)?", "", c.strip()).strip(" ;:")
        if len(c) > 40:
            actions.append({"objective": c[:280],
                            "tree": "[composite]" in c.lower(),
                            "parsed_from": "prose (no NEXT footer)"})
    return text.strip(), actions[:3], None


def _parse_action_line(line: str) -> dict | None:
    """'- <objective> [single]' / '... [composite]' -> action dict."""
    import re
    line = line.strip()
    if not line:
        return None
    tree = bool(re.search(r"\[composite\]", line, re.I))
    action = re.sub(r"^(?:[-*\u2022]\s*)?(?:\d+[.)]\s*)?", "", line)
    action = re.sub(r"\s*\[(single|composite)\]\s*", " ", action,
                    flags=re.I).strip()
    if len(action) < 15:
        return None
    return {"objective": action[:300], "tree": tree}


def _generate_and_store_brief(prog: dict) -> str:
    """Draft the model program brief and AUDIT it like every other LLM
    actor here: model id + prompt hash travel with the result, so
    'which model said this about which evidence' is answerable from the
    program record (the deterministic verdict remains the source of
    truth; the brief only organizes it)."""
    import hashlib
    from bionexus.adapters.models.anthropic_provider import AnthropicProvider
    from bionexus.core.contracts import Envelope, ToolInvocation
    prompt = _brief_prompt(prog)
    inv = ToolInvocation(envelope=Envelope(experiment_branch_id="plan"),
                         tool="c.fm.generate_molecules")
    prov = AnthropicProvider()
    text = prov.generate(inv, prompt).output["text"].strip()
    prose, actions, conclusion = _parse_actions(text)
    slug = prog["slug"]
    ws = get_ws()
    doc = ws.get_program(slug) or {}
    model = (getattr(prov, "name", None) or "?") + "/" + (
        getattr(prov, "model_version", None)
        or getattr(prov, "model", None) or "?")
    doc["brief"] = {"text": prose, "actions": actions,
                    "conclusion": conclusion,
                    "hash": _brief_evidence_hash(prog),
                    "model": model,
                    "prompt_sha256": hashlib.sha256(
                        prompt.encode()).hexdigest()[:16],
                    "cycle": ((doc.get("brief") or {}).get("cycle") or 0) + 1,
                    "at": __import__("time").time()}
    ws.upsert_program(slug, prog["name"], doc)
    publish_workspace("program_updated", {"slug": slug})
    return prose


@app.post("/api/programs/{slug}/actions/{idx}")
def launch_next_action(slug: str, idx: int, tree: bool = False) -> dict:
    """Launch one of the brief's next-actions, linked to the program
    like any leaf. tree=True decomposes the action into its own
    problem tree (for refinement-type actions); flat otherwise."""
    from bionexus.api.launch import LaunchError, spawn_campaign
    ws = get_ws()
    prog = next((p for p in views.workspace(ws)["programs"]
                 if p["slug"] == slug), None)
    if prog is None:
        raise HTTPException(404, f"program {slug} not found")
    actions = ((prog.get("brief") or {}).get("actions")) or []
    if not 0 <= idx < len(actions):
        raise HTTPException(404, f"action {idx} not found")
    action = actions[idx]
    objective = (action.get("objective") if isinstance(action, dict)
                 else action)
    doc = ws.get_program(slug) or {}
    action_doc = {
        "objective": objective,
        "metric": doc.get("metric") or "potency",
        "unit": doc.get("unit") or "",
        "direction": doc.get("direction", "min"),
        "gate_value": doc.get("gate_value", 1.0),
        "k": doc.get("k", 2), "rounds": doc.get("rounds", 2),
        # a model-drafted objective does NOT inherit self-confirmation by
        # default: autonomous "act" requires the program to state it
        "autonomy": (doc.get("action_autonomy")
                     or doc.get("autonomy") or "gate"),
        "modality": doc.get("modality") or "",
        "candidates": ""}
    # per-action [composite] tag decides; ?tree=true forces either way
    tagged = action.get("tree", False) if isinstance(action, dict) else False
    if tree or tagged:
        action_doc["decompose"] = True
    try:
        eid = spawn_campaign(action_doc, prog["name"])
    except LaunchError as exc:
        raise HTTPException(503, str(exc))
    # decomposed launches return None: the plan subprocess announces
    # its own leaf eids — that is success, not failure
    launched = doc.get("brief", {}).setdefault("launched", {})
    launched[str(idx)] = eid or "tree"
    ws.upsert_program(slug, prog["name"], doc)
    return {"eid": eid, "objective": action_doc["objective"]}


def _ensure_brief(prog: dict) -> None:
    """Fire-and-forget: (re)draft the program brief in the background
    whenever the evidence changed. Cached text keeps serving reads."""
    slug = prog["slug"]
    if slug in _brief_inflight or not prog.get("trees"):
        return
    # termination policy: an escalated program pauses the autonomous
    # loop — no new briefs until a human redrafts (override) or the
    # policy is relaxed
    if (prog.get("policy") or {}).get("status") == "escalated":
        return
    ws = get_ws()
    cached = (ws.get_program(slug) or {}).get("brief") or {}
    if cached.get("hash") == _brief_evidence_hash(prog):
        return
    _brief_inflight.add(slug)

    def _run():
        try:
            _generate_and_store_brief(prog)
        except Exception as exc:
            # Honest backoff: remember the failure against THIS evidence
            # hash (no retry storm on every page open); a redraft button
            # (force=True) overrides the cache and tries again.
            try:
                doc = ws.get_program(slug) or {}
                doc["brief"] = {
                    "text": "", "actions": [], "conclusion": None,
                    "error": f"provider unavailable: {str(exc)[:160]}",
                    "hash": _brief_evidence_hash(prog),
                    "cycle": ((doc.get("brief") or {}).get("cycle") or 0),
                    "at": __import__("time").time()}
                ws.upsert_program(slug, prog["name"], doc)
            except Exception:
                pass
        finally:
            _brief_inflight.discard(slug)

    import threading
    threading.Thread(target=_run, daemon=True,
                     name=f"brief-{slug}").start()


@app.post("/api/programs/{slug}/brief")
def program_brief(slug: str, force: bool = True) -> dict:
    """Redraft the program learning brief now (default: force)."""
    ws = get_ws()
    ws_view = views.workspace(ws)
    prog = next((p for p in ws_view["programs"] if p["slug"] == slug), None)
    if prog is None:
        raise HTTPException(404, f"program {slug} not found")
    if not prog.get("trees"):
        raise HTTPException(409, "program has no problem tree to brief on")
    try:
        return {"narrative": _generate_and_store_brief(prog)}
    except Exception as exc:  # no key / provider down
        raise HTTPException(503, f"model unavailable: {exc}")


class ProgramIn(BaseModel):
    program: str
    objective: str = ""
    modality: str = ""
    metric: str = "ic50"
    unit: str = ""
    direction: str = "min"
    gate_value: float = 20.0
    mode: str = "autonomous"
    autonomy: str = "act"
    k: int = 2
    rounds: int = 2
    candidates: str = ""

    class Config:
        extra = "allow"


@app.post("/api/programs")
def save_program(body: ProgramIn) -> dict:
    from bionexus.core.contracts import Envelope, EventType
    from bionexus.core.interfaces import record_for, system_actor
    doc = body.model_dump()
    doc["custom"] = True          # the web form is the custom-problem form
    slug = program_cfg._slug(doc.get("program"))
    existing = {x["slug"]: x for x in program_cfg.list_programs()}
    prev = existing.get(slug)
    if prev and prev.get("attachments"):
        # same name as an active program: never silently merge — mint a
        # unique id (kappa-selective-binder-2) so both stay distinguishable
        if prev.get("mode") != doc["mode"]:
            raise HTTPException(
                409, f"Execution mode is locked: '{doc['program']}' has "
                f"{len(prev['attachments'])} attached experiment(s).")
        n = 2
        while f"{slug}-{n}" in existing:
            n += 1
        slug = f"{slug}-{n}"
    program_cfg.save(doc)
    program_cfg.save_program_record(doc, slug=slug)
    publish_workspace("program_updated", {"slug": slug})
    return {"slug": slug, "gate_summary": program_cfg.gate_summary(doc)}


@app.delete("/api/programs/{slug}")
def delete_program_route(slug: str, archive: bool = False,
                         purge: bool = False) -> dict:
    """Delete a program. archive=True retires its experiments into the
    Archived section (recoverable). purge=True hard-removes them from
    the workbench registry — the WORM provenance ledger keeps the audit
    trail either way."""
    existing = {p["slug"]: p for p in program_cfg.list_programs()}
    if slug not in existing:
        raise HTTPException(404, f"program {slug} not found")
    ws = get_ws()
    n_touched = 0
    if archive or purge:
        for l in program_cfg.links_for(slug):
            row = ws.get(l["eid"])
            if not row or (row["payload"] or {}).get("archived"):
                continue
            if purge:
                ws.delete_experiment(l["eid"])
            else:
                ws.set_archived(l["eid"], True)
            n_touched += 1
    ok = program_cfg.delete_program(slug)
    if not ok:
        raise HTTPException(404, f"program {slug} not found")
    publish_workspace("program_deleted", {"slug": slug})
    return {"deleted": slug, "archived_experiments": n_touched,
            "purged_experiments": n_touched if purge else 0}


@app.post("/api/programs/{slug}/launch")
def launch_program(slug: str) -> dict:
    existing = {p["slug"]: p for p in program_cfg.list_programs()}
    prow = existing.get(slug)
    if not prow:
        raise HTTPException(404, f"program {slug} not found")
    doc = prow.get("program") or {}
    if doc.get("mode") != "autonomous":
        raise HTTPException(400, "guided programs launch via the wizard")
    from bionexus.api.launch import spawn_campaign
    eid = spawn_campaign(doc, prow["name"])
    if eid:
        publish_workspace("experiment_added", {"eid": eid})
    return {"eid": eid, "decomposed": eid is None}


# ---------------------------------------------------------- experiments
@app.get("/api/experiments")
def experiments() -> dict:
    ws = get_ws()
    return views.workspace(ws)


@app.get("/api/experiments/{eid}")
def experiment_detail_route(eid: str) -> dict:
    detail = views.experiment_detail(eid, get_ws())
    if detail is None:
        raise HTTPException(404, f"experiment {eid} not found")
    return detail


@app.get("/api/experiments/{eid}/pipeline")
def experiment_pipeline(eid: str) -> dict:
    detail = views.experiment_detail(eid, get_ws())
    if detail is None:
        raise HTTPException(404, f"experiment {eid} not found")
    prov = get_prov()
    recs = prov.branch_records(detail["branch"]) \
        if detail["branch"] and prov else []
    return {"cards": views.pipeline_cards(recs) if recs else [],
            "counts": detail["counts"],
            "rounds": detail["rounds"]}


@app.get("/api/experiments/{eid}/record")
def experiment_record(eid: str) -> dict:
    detail = views.experiment_detail(eid, get_ws())
    if detail is None:
        raise HTTPException(404, f"experiment {eid} not found")
    prov = get_prov()
    recs = prov.branch_records(detail["branch"]) \
        if detail["branch"] and prov else []
    logf = Path(detail["agent"]["log_path"]) \
        if detail["agent"].get("log_path") else None
    log_lines = (logf.read_text(errors="replace").splitlines()[-200:]
                 if logf and logf.is_file() else [])
    return views.narrative_data(recs, log_lines)


@app.post("/api/trees/{root_id}/archive")
def archive_tree(root_id: str) -> dict:
    """Retire a problem tree from the workspace: every live leaf
    experiment is archived (kept, provenance intact)."""
    ws = get_ws()
    trees, _ = views.problem_trees()
    tree = next((t for t in trees if t["root_id"] == root_id), None)
    if tree is None:
        raise HTTPException(404, f"tree {root_id} not found")
    leaf_pids = {pid for stats in tree["leaf_stats"].values()
                 for pid in stats.get("pids", [])}
    n = 0
    for row in ws.ongoing() + ws.finished(500):
        pid = (row["payload"].get("agent") or {}).get("problem_id")
        if pid in leaf_pids and not (row["payload"].get("archived")):
            ws.set_archived(row["id"], True)
            n += 1
    publish_workspace("workspace", {"kind": "tree_archived",
                                    "root": root_id, "archived": n})
    return {"root": root_id, "archived_experiments": n}


@app.post("/api/experiments/{eid}/archive")
def archive_experiment(eid: str) -> dict:
    ws = get_ws()
    if not ws.get(eid):
        raise HTTPException(404, f"experiment {eid} not found")
    ws.set_archived(eid, True)
    publish_workspace("workspace", {"kind": "experiment_archived",
                                    "eid": eid})
    return {"eid": eid, "archived": True}


@app.get("/api/experiments/{eid}/evidence/{run_id}.csv")
def experiment_evidence_csv(eid: str, run_id: str):
    """Serve this run's recorded plate file (raw instrument export)."""
    detail = views.experiment_detail(eid, get_ws())
    if detail is None:
        raise HTTPException(404, f"experiment {eid} not found")
    prov = get_prov()
    recs = prov.branch_records(detail["branch"]) \
        if detail["branch"] and prov else []
    data = views.narrative_data(recs, [], data_dir=str(DATA_DIR))
    for curve in data["evidence"]["curves"]:
        if curve["run_id"] == run_id:
            path = Path(curve["path"])
            if path.is_file():
                return FileResponse(path, media_type="text/csv",
                                    filename=f"{run_id}.csv")
    raise HTTPException(404, f"no recorded plate file for run {run_id}")


@app.post("/api/experiments/{eid}/rereview")
def experiment_rereview(eid: str) -> dict:
    """Re-run the deterministic reviewer on the branch and append a
    fresh review_report (the latest one wins on the page). Honest
    re-audit: findings are re-derived from recorded evidence."""
    detail = views.experiment_detail(eid, get_ws())
    if detail is None:
        raise HTTPException(404, f"experiment {eid} not found")
    if not detail["branch"] or not Path("bionexus.db").exists():
        raise HTTPException(409, "no provenance branch to review")
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.core.contracts import Envelope, EventType
    from bionexus.core.interfaces import record_for, system_actor
    from bionexus.reviewer import review_campaign
    prov = SqliteProvenanceStore("bionexus.db")
    recs = prov.branch_records(detail["branch"])
    review = review_campaign(recs)
    prov.append(record_for(
        Envelope(experiment_branch_id=detail["branch"]),
        EventType.stage_transition, system_actor("reviewer"),
        decision={"kind": "review_report", "review": review["review"],
                  "critical": review["critical"],
                  "warnings": review["warnings"],
                  "verdicts_reviewed": review["verdicts_reviewed"],
                  "findings": review["findings"],
                  "rerun": True}))
    return {"critical": review["critical"],
            "warnings": review["warnings"],
            "verdicts_reviewed": review["verdicts_reviewed"],
            "findings": review["findings"]}


@app.get("/api/experiments/{eid}/trace")
def experiment_trace(eid: str, lines: int = 30) -> dict:
    detail = views.experiment_detail(eid, get_ws())
    if detail is None:
        raise HTTPException(404, f"experiment {eid} not found")
    logf = Path(detail["agent"]["log_path"]) \
        if detail["agent"].get("log_path") else None
    if not logf or not logf.is_file():
        return {"lines": [], "truncated": False}
    all_lines = logf.read_text(errors="replace").splitlines()
    tail = all_lines[-lines:]
    return {"lines": tail, "truncated": len(all_lines) > lines}


# ---------------------------------------------------------------- wizard
@app.post("/api/wizard/sessions")
def wizard_create(body: dict) -> dict:
    from bionexus.api import wizard_sessions
    return wizard_sessions.create_session(
        body.get("question", ""), body.get("target", "user-target"),
        body.get("claim", "causal_modification"),
        program=body.get("program"))


@app.get("/api/wizard/sessions/{sid}")
def wizard_get(sid: str) -> dict:
    from bionexus.api import wizard_sessions
    try:
        return wizard_sessions.get_session(sid)
    except KeyError as e:
        raise HTTPException(404, str(e))


@app.post("/api/wizard/sessions/{sid}/design")
def wizard_design(sid: str, body: dict) -> dict:
    from bionexus.api import wizard_sessions
    try:
        return wizard_sessions.design(
            sid, body.get("site"), int(body.get("half_life", 120)),
            bool(body.get("edited_frac")), bool(body.get("mimetic")),
            body.get("controls") or [], body.get("mechanism", ""),
            body.get("refutation", ""), body.get("citation", ""))
    except KeyError as e:
        raise HTTPException(404, str(e))


@app.post("/api/wizard/sessions/{sid}/execute")
def wizard_execute(sid: str) -> dict:
    from bionexus.api import wizard_sessions
    try:
        return wizard_sessions.execute(sid)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.post("/api/wizard/sessions/{sid}/upload")
async def wizard_upload(sid: str, file: "UploadFile") -> dict:
    from bionexus.api import wizard_sessions
    try:
        return wizard_sessions.upload(sid, file.filename,
                                      await file.read())
    except KeyError as e:
        raise HTTPException(404, str(e))


@app.post("/api/wizard/sessions/{sid}/analyze")
def wizard_analyze(sid: str, body: dict) -> dict:
    from bionexus.api import wizard_sessions
    try:
        return wizard_sessions.analyze(sid, body.get("selected") or [])
    except KeyError as e:
        raise HTTPException(404, str(e))


# ------------------------------------------------------------------ SSE
@app.get("/api/events")
async def events(
        request: Request,
        topics: str = "workspace") -> StreamingResponse:
    """Server-sent events. topics: comma-separated
    (campaign:<eid>, workspace). Replays missed events when a
    Last-Event-ID header is present. The approvals queue is
    polled (refetch), not streamed — no approvals topic is emitted."""
    from bionexus.api.sse import replay_events
    wanted = {t.strip() for t in topics.split(",") if t.strip()}
    last_id = 0
    lid = request.headers.get("Last-Event-ID")
    if lid and lid.isdigit():
        last_id = int(lid)
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.add(q)

    async def gen():
        try:
            for ev in replay_events(last_id, wanted):
                yield (f"id: {ev['id']}\nevent: {ev['kind']}\n"
                       f"data: {json.dumps(ev['payload'])}\n\n")
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    if ev["topic"] not in wanted:
                        continue
                    yield (f"id: {ev['id']}\nevent: {ev['kind']}\n"
                           f"data: {json.dumps(ev['payload'])}\n\n")
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            _subscribers.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# -------------------------------------------------- static SPA (prod)
_web_dist = Path(__file__).resolve().parents[3] / "web" / "dist"
if _web_dist.exists():                                    # pragma: no cover
    from fastapi.staticfiles import StaticFiles
    app.mount("/assets", StaticFiles(directory=str(_web_dist / "assets")),
              name="spa-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        """BrowserRouter deep links: real files serve, everything else
        (non-API client routes like /experiments/<eid>) gets the SPA shell.
        Registered last — concrete /api routes above always win."""
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(404, "no such endpoint")
        candidate = (_web_dist / full_path).resolve()
        if (full_path and candidate.is_file()
                and candidate.is_relative_to(_web_dist.resolve())):
            return FileResponse(candidate)
        return FileResponse(_web_dist / "index.html")
