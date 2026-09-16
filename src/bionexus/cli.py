"""`bn` CLI — boring on purpose (P1).

    bn run workflow.yml    # execute a workflow against configured adapters
    bn sim                 # run the reference round on the virtual lab
    bn prove <branch_id>   # print the hash-chained provenance for a branch
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load_workflow(path: str) -> dict:
    import yaml  # optional extra; kept out of core deps

    with open(path) as f:
        return yaml.safe_load(f)


def _build_default_registry(cfg: dict):
    from bionexus.adapters.lab.simulator import SimulatorLab
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.adapters.models.openai_compat import OpenAICompatProvider
    from bionexus.core.registry import Registry

    registry = Registry()
    model_cfg = cfg.get("model", {})
    provider = OpenAICompatProvider(
        model=model_cfg.get("name", "stub-1"),
        base_url=model_cfg.get("base_url"),
    )
    registry.register_model(provider, default=True)
    lab_cfg = cfg.get("lab", {})
    lab = (
        SimulatorLab(seed=lab_cfg.get("seed", 7))
        if lab_cfg.get("adapter", "simulator") == "simulator"
        else _load_adapter(lab_cfg["adapter"], lab_cfg.get("options", {}))
    )
    store = SqliteProvenanceStore(cfg.get("store", {}).get("path", "bionexus.db"))
    return registry, lab, store


def _load_adapter(path: str, options: dict):
    from bionexus.core.registry import import_string

    cls = import_string(path)
    return cls(**options)


def cmd_run(args: argparse.Namespace) -> int:
    cfg = _load_workflow(args.workflow)
    registry, lab, store = _build_default_registry(cfg)
    from bionexus.core.contracts import Actor, Envelope, ToolInvocation
    from bionexus.core.safety import LabGateway, SafetyEngine
    from bionexus.core.workflow import HypothesisTournament, TournamentConfig

    actor = Actor(kind="service", id="bn-cli")
    branch = cfg.get("branch", "run-1")
    envelope = Envelope(experiment_branch_id=branch)
    safety = SafetyEngine()  # operator rules may be extended via cfg["safety"]
    gateway = LabGateway(lab, safety, store, actor)

    tcfg = cfg.get("tournament", {})
    tournament = HypothesisTournament(
        registry.model,
        TournamentConfig(
            population=tcfg.get("population", 8),
            survivors=tcfg.get("survivors", 3),
            waves=tcfg.get("waves", 2),
        ),
    )
    inv = ToolInvocation(envelope=envelope, tool="c.fm.generate_molecules", args={})
    target = cfg.get("target", "target-1")
    gen = registry.model.generate(inv, f"generate candidates for {target}", n=tcfg.get("population", 8))
    candidates = json.loads(gen.output["text"])
    ranked = tournament.run(
        branch,
        seed_context={"target": target},
        generate_fn=lambda ctx: candidates,
        score_fn=lambda p: int(p.get("smiles", "").count("C")) * 0.1,
    )
    print(f"[bn] survivors: {[c['smiles'] for c in ranked]}")

    if cfg.get("assay", {}).get("enabled", True):
        from bionexus.core.contracts import (
            ProtocolOp,
            ProtocolStep,
            ProtocolSubmission,
            ReagentSpec,
            SampleKind,
            SampleSpec,
        )
        top = ranked[0]["smiles"]
        protocol = ProtocolSubmission(
            envelope=envelope,
            title=f"assay {top}",
            assay_type=cfg["assay"].get("type", "binding"),
            steps=[ProtocolStep(seq=1, op=ProtocolOp.dispense, params={"volume_ul": 50})],
            samples=[SampleSpec(sample_id=top, kind=SampleKind.compound)],
            reagents=[ReagentSpec(name="buffer-A", amount="10 mL", bsl_level=1)],
        )
        run_id, rejection = gateway.submit(protocol)
        if rejection:
            print(f"[bn] safety rejected: {rejection}")
            return 1
        result = gateway.results(envelope, run_id)
        print(f"[bn] run {run_id}: {result.measurements[0].value} {result.measurements[0].unit}")
    print(f"[bn] provenance: bn prove {branch}")
    return 0


def cmd_sim(args: argparse.Namespace) -> int:
    import examples.iteration_loop as example

    example.main()
    return 0


def cmd_prove(args: argparse.Namespace) -> int:
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore

    store = SqliteProvenanceStore(args.db)
    records = store.branch_records(args.branch)
    if not records:
        print(f"no records for branch '{args.branch}' in {args.db}")
        return 1
    prev_ok = True
    prev_hash = None
    for r in records:
        ok = r.prev_record_hash == prev_hash
        prev_ok &= ok
        prev_hash = r.record_hash
        print(f"{r.envelope.created_at:>14.0f}  {r.event_type.value:<18} "
              f"hash={r.record_hash[:12]}… prev={'genesis' if not r.prev_record_hash else r.prev_record_hash[:12] + '…'} "
              f"[{'ok' if ok else 'BROKEN'}]")
    print(f"chain intact: {prev_ok} ({len(records)} records)")
    if args.html:
        from bionexus.report import write_report

        path = write_report(records, args.html)
        print(f"report: {path}")
    if getattr(args, "eln", None):
        from bionexus.eln import export_eln

        p = export_eln(records, args.eln,
                       args.eln + ".json" if getattr(args, "eln_json", True)
                       else None)
        print(f"ELN export: {p} (+ .json sidecar)")
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    from bionexus.mcp_server import serve

    serve()
    return 0


def cmd_new_adapter(args: argparse.Namespace) -> int:
    from bionexus.scaffold import main as scaffold_main

    return scaffold_main([args.kind, args.name, "--dir", args.dir]
                         + (["--cap", args.cap] if args.cap else []))


def cmd_skills(args: argparse.Namespace) -> int:
    from bionexus.skills import discover_skills, install_skills, recommend_for_role

    if args.command == "list":
        found = discover_skills()
        if not found:
            print("no skills discovered")
            return 0
        for name, info in sorted(found.items()):
            desc = (info["description"] or "-")[:80]
            print(f"{name:28} v{info['version'] or '-':<6} [{info['source']}] {desc}")
        return 0
    if args.command == "role":
        recs = recommend_for_role(args.role, auto_install=args.install)
        print(f"role '{args.role}': {len(recs)} skill(s) available")
        for r in recs:
            print(f"  {r['path']}  v{r['version'] or '-'}")
        return 0
    if args.command == "install":
        installed = install_skills(args.names, args.dest)
        for pth in installed:
            print(f"installed: {pth}")
        return 0
    return 2


def cmd_read(args: argparse.Namespace) -> int:
    from pathlib import Path

    from bionexus.labread import read_plate

    result = read_plate(args.path, max_response=args.max_response)
    print(result)
    if args.csv:
        print(f"csv: {result.to_csv(args.csv)}")
    if args.html:
        Path(args.html).write_text(
            "<!DOCTYPE html><meta charset='utf-8'><title>BioNexus read</title>"
            f"<h1>{result.source}</h1><pre>{result}</pre>")
        print(f"report: {args.html}")
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    from bionexus.watch import watch

    watch(inbox=args.inbox, poll_secs=args.poll)
    return 0


def _campaign_from_doc(cfg_doc: dict) -> "CampaignConfig":
    from bionexus.autoloop import CampaignConfig
    from bionexus.core.hypothesis import Constraint, ProblemStatement

    problem = ProblemStatement(
        objective=cfg_doc["problem"]["objective"],
        context=cfg_doc["problem"].get("context", ""),
        constraints=[Constraint(**c) for c in cfg_doc["problem"].get("constraints", [])],
        success_metric=cfg_doc["problem"].get("success_metric"))
    return CampaignConfig(
        problem=problem, hypotheses=cfg_doc.get("hypotheses") or None,
        hypothesis_source=cfg_doc.get("hypothesis_source", "config"),
        model=cfg_doc.get("_model"),
        k=cfg_doc.get("k", 2), autonomy=cfg_doc.get("autonomy", "act"),
        inbox=cfg_doc.get("inbox", ".data/inbox"),
        concentrations=tuple(cfg_doc.get("concentrations",
                                         ["0.5uM", "2uM", "10uM", "40uM"])),
        max_families=cfg_doc.get("max_families", 3),
        max_variants_per_family=cfg_doc.get("max_variants_per_family", 3),
        dose_design=cfg_doc.get("dose_design", "fixed"))


def cmd_auto(args: argparse.Namespace) -> int:
    import json
    from bionexus.autoloop import run_campaign
    from bionexus.adapters.lab.simulator import SimulatorLab
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore

    if args.template:
        from bionexus.templates import build_campaign, fill, load_template
        fields = dict(f.split("=", 1) for f in (args.field or []))
        cfg_doc = build_campaign(fill(load_template(args.template), fields,
                                      prompt_missing=not getattr(args, "yes", False)))
    elif args.config:
        raw = Path(args.config).read_text()
        try:
            import yaml
            cfg_doc = yaml.safe_load(raw)
        except ImportError:
            cfg_doc = json.loads(raw)
    else:
        print("bn auto: pass a config file or --template NAME", file=sys.stderr)
        return 2
    if args.autonomy:
        cfg_doc["autonomy"] = args.autonomy
    if cfg_doc.get("hypothesis_source") == "agent" and not cfg_doc.get("model"):
        try:
            from bionexus.adapters.models.anthropic_provider import \
                AnthropicProvider
            cfg_doc["_model"] = AnthropicProvider()
        except Exception as exc:
            print(f"agent hypothesis source needs a model: {exc}",
                  file=sys.stderr)
            return 2
    if getattr(args, "dose_design", None):
        cfg_doc["dose_design"] = args.dose_design
    cfg = _campaign_from_doc(cfg_doc)
    approver = None
    if cfg.autonomy == "gate":
        from bionexus.approvals import web_approver
        approver = web_approver(inbox=args.inbox or ".data/approvals.jsonl",
                                notify=lambda m: print(f"[campaign] {m}"))
    lab = SimulatorLab(seed=cfg_doc.get("seed", 42))

    import time as _time
    def _ts_notify(msg: str) -> None:
        print(f"[{_time.strftime('%H:%M:%S')}] {msg}", flush=True)
    report = run_campaign(cfg, lab, SqliteProvenanceStore(args.db),
                          approver=approver, notify=_ts_notify)
    print(json.dumps({"problem": report.problem_id, "selected": report.selected,
                      "verdicts": report.verdicts}, indent=1))
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    import time as _t
    from bionexus.evals import tasks as _tasks          # registers suite
    from bionexus.evals.harness import TASKS, PASS_THRESHOLD

    suites = None
    if getattr(args, "all", False) or args.task:
        suites = None
    elif getattr(args, "suite", None):
        suites = {s.strip() for s in args.suite.split(",")}
    else:
        suites = {"epistemics"}
    results = []
    for task in TASKS:
        if args.task and args.task != task.task_id:
            continue
        if suites and task.suite not in suites:
            continue
        t0 = _t.time()
        try:
            r = task.run()
        except Exception as exc:
            from bionexus.evals.harness import TaskResult
            r = TaskResult(task.task_id, task.description, 0.0, False,
                           notes=f"ERROR: {exc}")
        r.metrics["duration_s"] = round(_t.time() - t0, 1)
        results.append(r)
        skipped = r.notes.startswith("SKIPPED")
        mark = "⏭ " if skipped else ("✅" if r.passed else "❌")
        print(f"{mark} {r.task_id:24s} "
              f"{'—' if skipped else f'score={r.score:.3f}'}  "
              f"({r.metrics.get('duration_s')}s)  {r.notes}")

    if not results:
        print("no tasks matched", file=sys.stderr)
        return 2
    scored = [r for r in results if not r.notes.startswith("SKIPPED")]
    overall = sum(r.score for r in scored) / len(scored) if scored else 0.0
    all_pass = all(r.passed for r in scored)
    print(f"\n{'PASS' if all_pass else 'FAIL'} — {len(results)} tasks, "
          f"mean score {overall:.3f} (pass bar {PASS_THRESHOLD})")

    import json as _json
    from pathlib import Path as _P
    out = _P("evals/leaderboard.md")
    out.parent.mkdir(exist_ok=True)
    by_suite: dict[str, list] = {}
    for task, r in zip([t for t in TASKS if t.task_id in
                        {x.task_id for x in results}], results):
        by_suite.setdefault(task.suite, []).append(r)
    sections = ""
    for suite, rs in by_suite.items():
        rows = "\n".join(
            f"| {r.task_id} | {r.score:.3f} | "
            f"{'⏭' if r.notes.startswith('SKIPPED') else ('✅' if r.passed else '❌')} | "
            f"{r.metrics.get('duration_s', '—')}s | {r.notes} |" for r in rs)
        sections += (f"\n### {suite} — mean "
                     f"{sum(x.score for x in rs) / len(rs):.3f}\n\n"
                     f"| task | score | pass | time | notes |\n"
                     f"|---|---|---|---|---|\n{rows}\n")
    out.write_text(
        f"# BioNexus eval leaderboard\n\n"
        f"Run {_t.strftime('%Y-%m-%d %H:%M')} · mean **{overall:.3f}** · "
        f"{'all pass' if all_pass else 'FAILING'}\n{sections}")
    _P("evals/results.json").write_text(_json.dumps(
        [{"task": r.task_id, "score": r.score, "passed": r.passed,
          "metrics": r.metrics, "notes": r.notes} for r in results], indent=1))
    return 0 if all_pass else 1


def cmd_anchor(args: argparse.Namespace) -> int:
    from bionexus.anchor import anchor as make_anchor, verify

    if args.verify:
        res = verify(args.db, args.root)
        ok = res["match"]
        print(f"current root: {res['current_root'][:16]}…  "
              f"anchored: {(res['anchored_root'] or '—')[:16]}…  "
              f"records: {res['records']}  -> {'MATCH' if ok else 'MISMATCH'}")
        return 0 if ok else 1
    entry = make_anchor(args.db, publish_cmd=args.publish_cmd)
    print(f"anchored {entry['records']} records -> root "
          f"{entry['merkle_root'][:16]}…")
    if "published" in entry:
        print("published" if entry["published"]
              else f"publish FAILED: {entry.get('publish_error', '')}")
    return 0


def cmd_fixtures(args: argparse.Namespace) -> int:
    from bionexus import fixtures
    study = args.study
    if args.command == "verify":
        ok, problems = fixtures.verify(study)
        for p in problems:
            print(p)
        print(f"{study}: {'all fixtures intact' if ok else 'DRIFT DETECTED'}")
        return 0 if ok else 1
    if args.command == "materialize":
        n = fixtures.materialize(study)
        print(f"restored {n} cache file(s)")
        return 0
    print("freeze is dev-only; use bionexus.fixtures.freeze(study, sources)",
          file=sys.stderr)
    return 2


def cmd_reproduce(args: argparse.Namespace) -> int:
    from bionexus.reproduce import reproduce
    res = reproduce(args.branch, db_path=args.db)
    status = res["status"]
    icon = {"match": "✅", "differs": "⚠️", "not-reproducible": "⏭",
            "error": "❌"}.get(status, "•")
    print(f"{icon} {status}", end="")
    if status in ("match", "differs"):
        print(f" — {res['matched']}/{res['recorded_verdicts']} verdicts "
              f"reproduced identically")
        for d in res["diffs"]:
            print(f"   Δ {d['candidate']}: recorded={d['recorded']} "
                  f"replayed={d['replayed']}")
        print(f"   env: {res['environment'].get('lab')} "
              f"seed={res['environment'].get('lab_seed')} "
              f"conc={res['environment'].get('concentrations')}")
    else:
        print(f" — {res.get('reason', '')}")
    return 0 if status == "match" else 1


def cmd_plan(args: argparse.Namespace) -> int:
    from bionexus.problem_tree import (ProblemTree, TreeLimits,
                                       decompose_with_agent, run_tree)

    limits = TreeLimits(max_children=args.max_children,
                        max_depth=args.max_depth, max_nodes=args.max_nodes)
    model = None
    if args.model == "anthropic":
        from bionexus.adapters.models.anthropic_provider import \
            AnthropicProvider
        model = AnthropicProvider()
        tree = decompose_with_agent(model, args.objective,
                                    context=args.context or "",
                                    limits=limits, say=print)
    else:
        tree = ProblemTree.create(args.objective, limits=limits,
                                  metric=None, gate=None)
    tree.run_budget = args.run_budget
    print(tree.render())
    print("run allocation:", tree.allocation())
    if not args.run:
        print("(dry plan — add --run to execute the leaves)")
        return 0
    from bionexus.adapters.lab.simulator import SimulatorLab
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    cands = [{"sample_id": x.strip()} for x in args.candidates.split(",")
             if x.strip()]
    if not cands:
        print("--run needs --candidates", file=sys.stderr)
        return 2
    summary = run_tree(tree, lambda: SimulatorLab(seed=args.seed),
                       SqliteProvenanceStore(args.db), candidates=cands,
                       model=model, autonomy=args.autonomy, notify=print)
    print("root status:", summary[tree.root.id])
    return 0


def cmd_halt(args: argparse.Namespace) -> int:
    from bionexus.governance import HaltSwitch
    hs = HaltSwitch(path=args.path)
    if args.clear:
        print("halt cleared" if hs.clear() else "no halt was engaged")
        return 0
    if args.engage:
        entry = hs.engage(args.reason)
        print(f"HALT ENGAGED ({entry['id']}): {entry['reason']}")
        print("all submissions refused until `bn halt --clear` by an operator")
        return 0
    state = hs.engaged()
    print(f"HALTED: {state}" if state else "not halted")
    return 1 if state else 0


def cmd_sop(args: argparse.Namespace) -> int:
    from bionexus.governance import SopRegistry
    reg = SopRegistry()
    if args.command == "list":
        pend = reg.pending()
        for p in pend:
            print(f"pending {p['id']}: {p['objective'][:50]} "
                  f"(assay {p['assay']})")
        if not pend:
            print("no SOPs awaiting sign-off")
        return 0
    if args.command == "approve":
        ok = reg.approve(args.sop_id, by=args.by)
        print(f"approved {args.sop_id} — recurring runs of this procedure "
              "are now authorized" if ok else f"unknown SOP {args.sop_id}")
        return 0 if ok else 1
    return 2


def cmd_templates(args: argparse.Namespace) -> int:
    from bionexus.templates import list_templates, load_template

    if args.name:
        doc = load_template(args.name)
        print(json.dumps(doc, indent=2) if False else json.dumps(doc, indent=2))
        return 0
    for t in list_templates():
        print(f"{t['name']:26} {t['description']}")
    return 0


def cmd_connect(args: argparse.Namespace) -> int:
    from bionexus.connect import format_scan, probe_robot, scan_share

    if args.command == "scan":
        print(format_scan(scan_share(args.path)))
        return 0
    if args.command == "describe":
        from bionexus.core.device_card import save_operator_tags, to_agent_text, \
            builtin_card, load_card
        print(f"Interview: what should an agent know to operate "
              f"'{args.device}' safely? Enter notes one per line; "
              f"empty line finishes.")
        notes = []
        prompts = [
            "What does it measure / adjust?",
            "Any physical quirks not in the manual?",
            "Safety limits an agent must respect?",
            "Anything else (free notes)?",
        ]
        for p in prompts:
            line = input(f"  {p} > ").strip()
            if line:
                notes.append(line)
        base = builtin_card(args.device, args.device, {}) if args.builtin else None
        card = save_operator_tags(args.device, notes, base=base)
        card = load_card(args.device, base=card) or card
        print("\nReference file:\n")
        print(to_agent_text(card))
        return 0
    if args.command == "card":
        from bionexus.core.device_card import load_card, to_agent_text, \
            builtin_card
        base = builtin_card(args.device, args.device, {}) if args.builtin else None
        card = load_card(args.device, base=base)
        if not card:
            print(f"no card for '{args.device}' — run "
                  f"`bn connect describe {args.device}` first")
            return 1
        print(to_agent_text(card))
        return 0
    if args.command == "robot":
        info = probe_robot(args.ip)
        if info.get("reachable"):
            print(f"robot found: {info['name']} (API {info['api_version']})")
            print(f"  setup: {info['usage']}")
        else:
            print(f"no robot at {info['base_url']}: {info.get('error')}")
        return 0 if info.get("reachable") else 1
    return 2


def cmd_diary(args: argparse.Namespace) -> int:
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.diary import write_diary

    store = SqliteProvenanceStore(args.db)
    records = store.branch_records(args.branch)
    if not records:
        print(f"no records for branch '{args.branch}' in {args.db}")
        return 1
    path = write_diary(records, args.branch, args.html)
    print(f"diary: {path}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from bionexus.serve import serve

    serve(port=args.port, inbox=args.inbox, db_path=args.db)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bn", description="BioNexus CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="run a workflow YAML")
    run.add_argument("workflow")
    run.set_defaults(func=cmd_run)

    sim = sub.add_parser("sim", help="reference round on the virtual lab")
    sim.set_defaults(func=cmd_sim)

    prove = sub.add_parser("prove", help="print provenance chain for a branch")
    prove.add_argument("branch")
    prove.add_argument("--db", default="bionexus.db")
    prove.add_argument("--html", metavar="PATH",
                       help="also write a self-contained HTML report")
    prove.add_argument("--eln", help="export branch as ELN CSV (+ .json sidecar)")
    prove.set_defaults(func=cmd_prove)

    mcp = sub.add_parser("mcp", help="serve BioNexus tools over MCP (stdio)")
    mcp.set_defaults(func=cmd_mcp)

    new_adapter = sub.add_parser("new-adapter", help="scaffold a tested adapter")
    new_adapter.add_argument("kind", choices=["lab", "tool"])
    new_adapter.add_argument("name")
    new_adapter.add_argument("--dir", default="adapters-contrib")
    new_adapter.add_argument("--cap", default=None)
    new_adapter.set_defaults(func=cmd_new_adapter)

    read = sub.add_parser("read", help="auto-read an instrument/lab result file")
    read.add_argument("path")
    read.add_argument("--max-response", type=float, default=None,
                      help="known maximal assay response (enables IC50 vs fixed max)")
    read.add_argument("--html", default=None, help="write an HTML summary")
    read.add_argument("--csv", default=None, help="export standardized records to CSV")
    read.set_defaults(func=cmd_read)

    conn = sub.add_parser("connect", help="find your instruments: scan a share or probe a robot")
    conns = conn.add_subparsers(dest="command", required=True)
    cscan = conns.add_parser("scan", help="detect instruments writing files into a folder")
    cscan.add_argument("path")
    crob = conns.add_parser("robot", help="probe an Opentrons robot (IP or URL)")
    crob.add_argument("ip")
    cdesc = conns.add_parser("describe",
                             help="interview the operator; produce an agent reference file for a device")
    cdesc.add_argument("device")
    cdesc.add_argument("--builtin", action="store_true",
                       help="seed with the built-in capability card")
    ccard = conns.add_parser("card", help="print the agent reference file for a device")
    ccard.add_argument("device")
    ccard.add_argument("--builtin", action="store_true")
    conn.set_defaults(func=cmd_connect)

    diary = sub.add_parser("diary", help="render provenance as a lab-notebook narrative")
    diary.add_argument("branch")
    diary.add_argument("--db", default="bionexus.db")
    diary.add_argument("--html", default="diary.html")
    diary.set_defaults(func=cmd_diary)

    srv = sub.add_parser("serve", help="scientist cockpit: approval inbox + campaign dashboard")
    srv.add_argument("--port", type=int, default=8080)
    srv.add_argument("--inbox", default=".data/approvals.jsonl")
    srv.add_argument("--db", default=None, help="provenance DB to show recent events from")
    srv.set_defaults(func=cmd_serve)

    watch_p = sub.add_parser("watch", help="watch an instrument outbox; agent notices results automatically")
    watch_p.add_argument("inbox")
    watch_p.add_argument("--poll", type=float, default=1.0)
    watch_p.set_defaults(func=cmd_watch)

    auto = sub.add_parser("auto", help="start the whole campaign flow (config or --template)")
    auto.add_argument("--dose-design", choices=("fixed", "adaptive"),
                      help="adaptive = Bayesian sequential dosing (3 wells/compound)")
    auto.add_argument("config", nargs="?", default=None)
    auto.add_argument("--template", default=None, help="preset template name (see: bn templates)")
    auto.add_argument("--field", action="append", metavar="KEY=VALUE",
                      help="template field, e.g. --field compounds=C1,C2")
    auto.add_argument("--autonomy", choices=["observe", "gate", "act"], default=None)
    auto.add_argument("--yes", action="store_true",
                      help="never prompt for template fields; fail instead")
    auto.add_argument("--db", default="bionexus.db",
                      help="provenance DB (shown by bn serve)")
    auto.add_argument("--inbox", default=None,
                      help="approval inbox file for gate mode (default .data/approvals.jsonl)")
    auto.set_defaults(func=cmd_auto)

    fx = sub.add_parser("fixtures", help="case-study data fixtures: verify / materialize")
    fxsub = fx.add_subparsers(dest="command", required=True)
    for name in ("verify", "materialize"):
        sp = fxsub.add_parser(name)
        sp.add_argument("study")
    fx.set_defaults(func=cmd_fixtures)
    anc = sub.add_parser("anchor", help="Merkle-root the provenance store; "
                         "publish the root for external tamper-evidence")
    anc.add_argument("--db", default="bionexus.db")
    anc.add_argument("--verify", action="store_true",
                     help="recompute and compare against the latest anchor")
    anc.add_argument("--root", help="explicit root to verify against")
    anc.add_argument("--publish-cmd",
                     help="shell command receiving the anchor JSON on stdin "
                          "(e.g. 'gh gist create - && …', 'git commit …')")
    ht = sub.add_parser("halt", help="operator stop-condition outside the "
                        "agent's reach: engage/status/clear")
    ht.add_argument("--engage", action="store_true")
    ht.add_argument("--clear", action="store_true")
    ht.add_argument("--reason", default="operator halt")
    ht.add_argument("--path", default=None,
                    help="halt file path (default .data/HALT)")
    ht.set_defaults(func=cmd_halt)
    so = sub.add_parser("sop", help="sign off agent-proposed recurring "
                        "procedures (SOPs) before they run unattended")
    sosub = so.add_subparsers(dest="command", required=True)
    sosub.add_parser("list")
    ap = sosub.add_parser("approve")
    ap.add_argument("sop_id")
    ap.add_argument("--by", default="operator")
    so.set_defaults(func=cmd_sop)
    pl = sub.add_parser("plan", help="decompose a compound objective into a "
                        "guarded problem tree (dry plan, or --run the leaves)")
    pl.add_argument("--objective", required=True)
    pl.add_argument("--context", default="")
    pl.add_argument("--model", choices=("anthropic", "none"), default="none",
                    help="anthropic = LLM-assisted decomposition (env-configured)")
    pl.add_argument("--max-children", type=int, default=4)
    pl.add_argument("--max-depth", type=int, default=2)
    pl.add_argument("--max-nodes", type=int, default=12)
    pl.add_argument("--run-budget", type=int, default=20,
                    help="total lab runs the whole tree may spend")
    pl.add_argument("--run", action="store_true")
    pl.add_argument("--candidates", default="", help="comma list for leaf hypotheses")
    pl.add_argument("--seed", type=int, default=7)
    pl.add_argument("--db", default="bionexus.db")
    pl.add_argument("--autonomy", choices=("act", "gate", "observe"), default="act")
    pl.set_defaults(func=cmd_plan)
    rep = sub.add_parser("reproduce",
                         help="replay a recorded experiment; diff verdicts")
    rep.add_argument("branch")
    rep.add_argument("--db", default="bionexus.db")
    rep.set_defaults(func=cmd_reproduce)
    ev = sub.add_parser("eval", help="run the eval suite (tasks, scores, leaderboard)")
    ev.add_argument("--task", help="run a single task by id")
    ev.add_argument("--suite", help="comma list: epistemics,models,reproductions "
                                    "(default: epistemics)")
    ev.add_argument("--all", action="store_true", help="every suite")
    anc.set_defaults(func=cmd_anchor)
    ev.set_defaults(func=cmd_eval)
    templates = sub.add_parser("templates", help="list campaign templates")
    templates.add_argument("name", nargs="?", default=None)
    templates.set_defaults(func=cmd_templates)

    sk = sub.add_parser("skills", help="discover/install scientific agent skills")
    sksub = sk.add_subparsers(dest="command", required=True)
    sksub.add_parser("list", help="list discovered skills")
    role = sksub.add_parser("role", help="skills recommended for an agent role")
    role.add_argument("role", choices=["design-agent", "target-agent",
                                       "assay-planning-agent", "analysis-agent",
                                       "trial-agent"])
    role.add_argument("--install", action="store_true",
                      help="auto-install missing recommended skills")
    inst = sksub.add_parser("install", help="install skills from scientific-agent-skills")
    inst.add_argument("names", nargs="+")
    inst.add_argument("--dest", default=".agents/skills")
    sk.set_defaults(func=cmd_skills)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001
        print(f"bn: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
