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

## The scientist path (no code)

```sh
bn connect scan /path/to/reader_share   # what instrument is this?
bn read results.csv --csv out.csv --html report.html   # analyze an export
make api            # the web app: workspace, launches, live agents (:8000)
#   → "Analyze data": upload an instrument export (optional plate layout),
#     confirm the interpretation (controls, normalization, gate), run,
#     review — calls with CIs, abstentions and refusals kept honest,
#     provenance + report/CSV export; a reviewed analysis can hand off to
#     a guided campaign.
bn templates                            # campaign presets
bn campaign auto --template dose-response-screen --field compounds=C1,C2,C3 \
        --autonomy gate                 # pause at each submission for your click
bn campaign auto campaign.json --dose-design adaptive  # Bayesian sequential dosing
bn diary <branch> --html diary.html     # the campaign as a lab notebook
```

### Campaign commands (`bn campaign <sub>`)

Use **`bn campaign auto`** (or the workbench's Launch button) — it is the one entry
point for a real campaign. The other subcommands are narrower:

| Command | Use it when |
|---|---|
| `bn campaign auto` | start a campaign from a template or config (this is the default path) |
| `bn campaign plan` | decompose a compound objective into a guarded problem tree first |
| `bn campaign sweep` | fan one problem across candidate shards in parallel |
| `bn campaign select` | preview which experiments would run (picks + every refusal), submitting nothing |
| `bn campaign run <workflow.yml>` | run a hand-written workflow file |
| `bn watch <inbox>` | let the agent notice instrument exports as they land |
| `bn demo` | first-run tour on the virtual lab (simulated) |
| `bn campaign reproduce` | replay a recorded experiment and diff the verdicts |
| `bn campaign materials` | materials formulation sweeps |

## Verify the claims

```sh
bn eval                               # epistemics tier: verdict honesty,
                                      # confirmation, falsifiability, adaptive design
bn eval --suite models                # baselines on MoleculeNet vs random floor
bn prove <branch> --eln out.csv       # ELN-ready audit export
bn anchor && bn anchor --verify       # Merkle root: externally checkable
```

## Run the reference round (no network, no model server)

```sh
python examples/demo_full_flow.py     # one file exercising every layer
bn demo                               # the guided first run
```

This runs one full design round: candidate generation (offline stub) →
hypothesis tournament → safety-checked protocol → virtual wet lab → fork +
safety rejection demo → provenance chain.

## Use a real model (P3: any OpenAI-compatible endpoint)

```sh
export OPENAI_BASE_URL=http://localhost:11434/v1   # ollama, vLLM, llama.cpp, OpenAI…
bn campaign run examples/workflow.yml
```

Set `model.base_url` in the workflow YAML instead of an env var if you prefer.
With no `base_url`, the provider runs in deterministic stub mode — CI never
needs a model server (P8).

## Run a workflow

```sh
bn campaign run examples/workflow.yml   # tournament + assay on the configured lab
bn prove demo-run              # inspect the hash-chained provenance
```

## Write a workflow (boring YAML, no DSL)

See `examples/workflow.yml`. A workflow names a branch, a target, a model, a
lab adapter, a store, and tournament/assay parameters. Anything you can point
at with `module:Class` can be an adapter.

## Next steps

- Adapter authoring: [`docs/ADAPTERS.md`](ADAPTERS.md)
- Safety and security — full mechanism table, rules, trust boundaries: [`docs/safety-and-security.md`](safety-and-security.md)
- Architecture and build plan: [`PLAN.md`](PLAN.md)
