# Quickstart

## Install

```sh
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # core (pydantic only) + test deps
```

Optional extras (all off by default — P1):

```sh
pip install -e ".[models-openai]"     # httpx-based model calls
pip install -e ".[bio-rdkit]"         # RDKit bio tools
pip install -e ".[sandbox-agentenv]"  # AgentENV fork/snapshot sandboxes
```

## Run the reference round (no network, no model server)

```sh
python examples/iteration_loop.py     # or: bn sim
```

This runs one full design round: candidate generation (offline stub) →
hypothesis tournament → safety-checked protocol → virtual wet lab → fork +
safety rejection demo → provenance chain.

## Use a real model (P3: any OpenAI-compatible endpoint)

```sh
export OPENAI_BASE_URL=http://localhost:11434/v1   # ollama, vLLM, llama.cpp, OpenAI…
bn run examples/workflow.yml
```

Set `model.base_url` in the workflow YAML instead of an env var if you prefer.
With no `base_url`, the provider runs in deterministic stub mode — CI never
needs a model server (P8).

## Run a workflow

```sh
bn run examples/workflow.yml   # tournament + assay on the configured lab
bn prove demo-run              # inspect the hash-chained provenance
```

## Write a workflow (boring YAML, no DSL)

See `examples/workflow.yml`. A workflow names a branch, a target, a model, a
lab adapter, a store, and tournament/assay parameters. Anything you can point
at with `module:Class` can be an adapter.

## Next steps

- Adapter authoring: [`docs/ADAPTERS.md`](ADAPTERS.md)
- Safety rules and the LabGateway: [`docs/SAFETY.md`](SAFETY.md)
- Architecture and build plan: [`PLAN.md`](PLAN.md)
