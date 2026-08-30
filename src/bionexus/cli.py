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


def cmd_auto(args: argparse.Namespace) -> int:
    import json
    from bionexus.autoloop import CampaignConfig, run_campaign
    from bionexus.adapters.lab.simulator import SimulatorLab
    from bionexus.adapters.store.sqlite import SqliteProvenanceStore
    from bionexus.core.hypothesis import Constraint, ProblemStatement

    cfg_doc = json.loads(Path(args.config).read_text())
    problem = ProblemStatement(
        objective=cfg_doc["problem"]["objective"],
        context=cfg_doc["problem"].get("context", ""),
        constraints=[Constraint(**c) for c in cfg_doc["problem"].get("constraints", [])],
        success_metric=cfg_doc["problem"].get("success_metric"))
    cfg = CampaignConfig(
        problem=problem, hypotheses=cfg_doc["hypotheses"],
        score_fn=lambda h: float(cfg_doc.get("scores", {}).get(h.candidate, 0.5)),
        k=cfg_doc.get("k", 2), autonomy=cfg_doc.get("autonomy", "act"),
        inbox=cfg_doc.get("inbox", ".data/inbox"))
    lab = SimulatorLab(seed=cfg_doc.get("seed", 42))
    report = run_campaign(cfg, lab, SqliteProvenanceStore())
    print(json.dumps({"problem": report.problem_id, "selected": report.selected,
                      "verdicts": report.verdicts}, indent=1))
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
    read.set_defaults(func=cmd_read)

    watch_p = sub.add_parser("watch", help="watch an instrument outbox; agent notices results automatically")
    watch_p.add_argument("inbox")
    watch_p.add_argument("--poll", type=float, default=1.0)
    watch_p.set_defaults(func=cmd_watch)

    auto = sub.add_parser("auto", help="start the whole campaign flow from a config")
    auto.add_argument("config")
    auto.set_defaults(func=cmd_auto)

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
