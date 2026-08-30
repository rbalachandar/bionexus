"""`bn` CLI — boring on purpose (P1).

    bn run workflow.yml    # execute a workflow against configured adapters
    bn sim                 # run the reference round on the virtual lab
    bn prove <branch_id>   # print the hash-chained provenance for a branch
"""
from __future__ import annotations

import argparse
import json
import sys


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

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001
        print(f"bn: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
