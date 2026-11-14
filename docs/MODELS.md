# Language models in Proef

By default **no language model is involved**: give a campaign its candidates and selection, lab runs, curve
fits, the verdict rule, confirmation and review are all code. A model is an optional extra, and it can do
exactly two jobs in a campaign. It never decides a verdict.

## What a model can do

| Job | When it runs | Providers | What is recorded |
|---|---|---|---|
| **Propose hypotheses** | a campaign with `"hypothesis_source": "agent"` (or launched with no candidates) | any | the model on every hypothesis (`predicted_by`), plus the prompt and response, sealed as a `tool_invocation` |
| **Review the verdicts** | automatically, when a model took part in the campaign | any | `review_report_llm`: model, prompt hash, advisory flags (flags only, schema-enforced) |

Both are shown in the workbench: the campaign header reads `LLM · <model> wrote N hypotheses · reviewed`
(or `no LLM`), and each hypothesis names its model. This is read from the ledger, not from current settings.

Other features that use a model have their own transport and speak the **Anthropic Messages API only** today:
the LLM acquisition policy (`AnthropicLLMPolicy`, used by the benchmarks) and the vision readout
(`proef.vision`). The optional advisory toxicity pass (`PROEF_ADVISORY_LLM=1`) uses whatever provider you
configured below.

## Configure a provider

Everything comes from the environment. The key is never a command-line flag.

| Variable | Meaning |
|---|---|
| `PROEF_LLM_MODEL` | model name |
| `PROEF_LLM_TOKEN` | API key (not needed for a local server) |
| `PROEF_LLM_BASE_URL` | endpoint base, e.g. `https://api.anthropic.com` or `https://host/v1` |
| `PROEF_LLM_API` | `anthropic` (default, Messages API) · `openai` (`/chat/completions`) · `openai-responses` (`/responses`) |
| `PROEF_LLM_SESSION_HEADER` | optional header carrying a stable session id, for gateways that require one |
| `PROEF_LLM_PRESET` | shortcut for a known gateway; explicit settings above always win |

The old `BIONEXUS_LLM_*` names still work.

```sh
# Anthropic
export PROEF_LLM_MODEL=<model> PROEF_LLM_TOKEN=<key>

# Any OpenAI-compatible endpoint (OpenRouter, vLLM, a hosted gateway, ...)
export PROEF_LLM_API=openai PROEF_LLM_BASE_URL=https://host/v1 PROEF_LLM_MODEL=<model> PROEF_LLM_TOKEN=<key>

# A local server — no key
export PROEF_LLM_API=openai PROEF_LLM_BASE_URL=http://localhost:11434/v1 PROEF_LLM_MODEL=llama3

# OpenCode Go: one preset, and your key stays in OPENCODE_API_KEY
export PROEF_LLM_PRESET=opencode-go PROEF_LLM_MODEL=gpt-6-luna
```

**The `opencode-go` preset** fills in the endpoint, the `x-opencode-session` header and the key variable, and
picks the right API for the model: GPT and Grok models are served by the Responses API, the others by chat
completions. The provider also sends its own `User-Agent` (some gateways refuse generic HTTP-library agents)
and backs off on `429` and `5xx`.

There is **no offline stub**. With no usable model, a candidate-less launch is refused:

```
agent hypothesis source needs a model: no model configured: set PROEF_LLM_MODEL and PROEF_LLM_TOKEN ...
```

and the workbench returns the same message as a `409` instead of starting a campaign that cannot work.

## Run it

[`examples/campaign_llm.json`](../examples/campaign_llm.json) has no candidates; the model proposes them:

```sh
export PROEF_LLM_PRESET=opencode-go PROEF_LLM_MODEL=gpt-6-luna
proef campaign auto examples/campaign_llm.json --yes
```

A real run (the lab is **simulated**, so the numbers say nothing about real EGFR chemistry):

```
family 'reversible_hinge_atp' (confidence 0.82): Gefitinib-like 4-anilinoquinazolines bind wild-type EGFR ...
family 'c797_covalent_atp' (confidence 0.72): Cys797-directed acrylamide inhibitors bind the EGFR ATP pocket ...
citation check: 10.1016/S0092-8674(02)00942-6=invalid, 10.1158/2159-8290.CD-14-0337=verified
WARNING: 1 fabricated/unresolvable citation(s) penalized in portfolio scoring
agent proposed 4 variant hypotheses
round 1: testing ['COV-C797-OSI-01', 'REVQ-GEF-01'] (2 candidates remain)
[agent] hypothesis ... (REVQ-GEF-01): VALIDATED (preliminary — pending orthogonal confirmation) — IC50 7.079 uM ...
[agent] gate honesty: COV-C797-OSI-01 methods agree but a borderline CI straddles threshold 20.0 -> inconclusive
```

In the workbench, launch a campaign from a program and leave **Candidates** empty (the server needs the
variables above in its environment).

## What keeps a model honest

- **Verdicts are not the model's.** Its hypotheses are judged by the same fixed rule, against criteria
  registered before any data, with the same interval and abstention logic as everyone else's.
- **Output is validated.** The reply must be schema-valid JSON, within operator limits (`max_families`,
  `max_variants_per_family`), or it is rejected.
- **Citations are checked.** DOIs the model cites are resolved. In the run above, one was unresolvable and
  was flagged and penalised in scoring, not trusted.
- **Everything is on the record.** Model, prompt, response and prompt hash are sealed in the hash-chained
  ledger, so a result can be traced back to what the model was asked and what it said.
- **No silent fallback.** Unconfigured means an error, never a canned answer.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `403 Forbidden` | the gateway refuses generic HTTP-library User-Agents; use the provider in this repo (it sends its own) |
| `400 MissingSessionID` | the gateway needs a session header: set `PROEF_LLM_SESSION_HEADER`, or use a preset |
| a GPT-family model is rejected on `/chat/completions` | some gateways (OpenCode Go does) serve GPT and Grok models only through `/responses`: use `PROEF_LLM_API=openai-responses`, or the preset, which chooses per model |
| `no model configured` | one of `PROEF_LLM_MODEL` / `PROEF_LLM_TOKEN` / `PROEF_LLM_BASE_URL` is missing |
| header says `no LLM` on a campaign you expected to use a model | the campaign had candidates, so the model was never asked, or the server was started before the variables were set |
