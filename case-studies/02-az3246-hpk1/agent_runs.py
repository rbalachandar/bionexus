"""CS02 repeated blind agent runs with RAW scores kept.

The original study sealed one agent run's rho but not its per-compound
scores, so no interval could be computed and run-to-run noise was invisible.
This script runs the same blind prompt N times against any OpenAI-compatible
chat endpoint, records every score vector, and reports per-run Spearman rho,
the across-run mean/SD, and a bootstrap 95% interval over compounds for the
run-averaged score.

It first records the two contamination probes for the model used: a 'post-
cutoff' claim only holds for a model that does not know the paper.

    export OPENCODE_API_KEY=...            # never pass keys on the command line
    python case-studies/02-az3246-hpk1/agent_runs.py --model gpt-6-luna --runs 5

Endpoint: --base-url or $PROEF_LLM_BASE_URL (default: OpenCode Go).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
spec = importlib.util.spec_from_file_location("cs02", HERE / "run.py")
cs02 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs02)

from proef import fixtures  # noqa: E402
from proef.benchmark import spearman, spearman_ci  # noqa: E402
from proef.core.contracts import Envelope, ToolInvocation  # noqa: E402


class GoClient:
    """Minimal client for the OpenCode Go endpoints.

    Go asks API clients to (a) identify with their own User-Agent — generic
    HTTP-library agents are refused (Cloudflare 1010) — and (b) send a stable
    `x-opencode-session` per conversation. GPT/Grok models are served by the
    Responses API (`/responses`); the rest by `/chat/completions`.
    """
    UA = "proef-case-study/1.0 (+https://github.com/rbalachandar/proef)"
    RESPONSES_MODELS = ("gpt-", "grok-")

    def __init__(self, model: str, base_url: str, api_key: str):
        import uuid
        self.model, self.base_url, self.api_key = model, base_url.rstrip("/"), api_key
        self.session = f"cs02-{uuid.uuid4()}"
        self.api = ("responses" if model.startswith(self.RESPONSES_MODELS)
                    else "chat")

    def _post(self, path: str, body: dict) -> dict:
        import urllib.request
        req = urllib.request.Request(
            f"{self.base_url}/{path}", data=json.dumps(body).encode(),
            method="POST",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json",
                     "User-Agent": self.UA,
                     "x-opencode-session": self.session})
        import urllib.error
        for attempt in range(6):
            try:
                with urllib.request.urlopen(req, timeout=180) as r:  # noqa: S310
                    return json.loads(r.read())
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 502, 503, 529) or attempt == 5:
                    raise
                wait = float(exc.headers.get("Retry-After") or 0) or 15 * 2 ** attempt
                print(f"   [{exc.code}] backing off {wait:.0f}s", flush=True)
                time.sleep(min(wait, 240))
        raise RuntimeError("unreachable")

    def text(self, prompt: str) -> str:
        if self.api == "responses":
            d = self._post("responses", {"model": self.model, "input": prompt})
            if d.get("output_text"):
                return d["output_text"]
            parts = [c.get("text", "") for o in d.get("output", [])
                     for c in (o.get("content") or [])
                     if c.get("type") in ("output_text", "text")]
            return "".join(parts)
        d = self._post("chat/completions", {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}]})
        return d["choices"][0]["message"]["content"]

    def generate(self, invocation, prompt, system=None, **kw):
        from types import SimpleNamespace
        return SimpleNamespace(output={"text": self.text(prompt)})


DEFAULT_URL = "https://opencode.ai/inference/go/openai/v1"

PROMPT = """You are a medicinal chemistry hypothesis lead. Your team measured a
kinase-inhibitor series (structures below); values are pending.

TARGET: HPK1 (MAP4K1) — an immune-oncology kinase target.

TASK
1. State the binding hypothesis: what scaffold/core and substituent pattern
   drives potency in this series? Name the core explicitly.
2. Identify the SAR direction: which structural features increase potency?
3. Score EVERY compound 0-100 for likelihood of potent inhibition
   (pIC50 > 7).

Reply ONLY with JSON:
{{"hypotheses": [
   {{"family": "core-name", "parent_statement": "...",
     "rationale": "...", "confidence": 0.0-1.0}}],
 "scores": [{{"index": 1, "score": 55}}, ...]}}

SERIES
{smi_list}
"""


def _paper():
    acts = cs02.chembl_json(f"/activity.json?document_chembl_id="
                            f"{cs02.PAPER_DOC}&assay_type=B&limit=1000")
    by = defaultdict(list)
    for a in acts.get("activities", []):
        if a.get("standard_units") == "nM" and a.get("canonical_smiles"):
            try:
                v = float(a["standard_value"])
            except (TypeError, ValueError):
                continue
            if v > 0:
                by[a["canonical_smiles"]].append(-math.log10(v * 1e-9))
    return sorted(({"smiles": s, "pic50": statistics.mean(v)}
                   for s, v in by.items()), key=lambda c: -c["pic50"])


def _ask(agent, prompt):
    inv = ToolInvocation(envelope=Envelope(experiment_branch_id="cs02-runs"),
                         tool="c.fm.generate_molecules")
    return agent.generate(inv, prompt).output["text"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--base-url", default=os.environ.get("PROEF_LLM_BASE_URL",
                                                          DEFAULT_URL))
    ap.add_argument("--key-env", default="OPENCODE_API_KEY")
    ap.add_argument("--probe-only", action="store_true")
    args = ap.parse_args()
    key = os.environ.get(args.key_env)
    if not key:
        sys.exit(f"set ${args.key_env} in the environment (not on the command line)")
    fixtures.materialize(HERE)
    agent = GoClient(args.model, args.base_url, key)
    paper = _paper()
    out = {"model": args.model, "base_url": args.base_url,
           "n_compounds": len(paper), "run_at": time.strftime("%F %T")}

    # contamination probes for THIS model
    inv = ToolInvocation(envelope=Envelope(experiment_branch_id="cs02-runs"),
                         tool="c.kb.search_literature")
    probe = agent.generate(inv, (
        "Do you have specific knowledge of a 2025 Journal of Medicinal "
        "Chemistry paper titled 'Discovery and Optimization of Pyrazine "
        "Carboxamide AZ3246, a Selective HPK1 Inhibitor' (DOI "
        "10.1021/acs.jmedchem.4c02631)? Yes/no, and what do you know about "
        "its compounds?")).output["text"]
    out["paper_probe"] = probe[:600]
    from proef.probes import variant_contamination
    vc = variant_contamination(
        agent, ["az3246", "hpk1", "map4k1", "pyrazine carboxamide",
                "journal of medicinal chemistry"],
        [c["smiles"] for c in paper[:3]])
    out["variant_probe"] = {"verdict": vc["verdict"],
                            "hits": f"{vc['n_mapped_to_paper']}/"
                                    f"{vc['n_variants_probed']}"}
    print(f"[probe] {args.model}: variant probe {out['variant_probe']['verdict']} "
          f"({out['variant_probe']['hits']}); paper probe: {probe[:140]!r}")
    if args.probe_only:
        print(json.dumps(out, indent=1))
        return

    smi_list = "\n".join(f"{i+1}. {c['smiles']}" for i, c in enumerate(paper))
    truth = [c["pic50"] for c in paper]
    runs = []
    for r in range(args.runs):
        raw = _ask(agent, PROMPT.format(smi_list=smi_list))
        try:
            doc = cs02._extract_json(raw)
        except ValueError as exc:
            print(f"[run {r+1}] unparseable: {exc}")
            runs.append({"error": str(exc)})
            continue
        by_i = {int(x["index"]): float(x["score"])
                for x in doc.get("scores", []) if "index" in x}
        scores = [by_i.get(i + 1, 50.0) for i in range(len(paper))]
        missing = sum(1 for i in range(len(paper)) if i + 1 not in by_i)
        rho = spearman(scores, truth)
        runs.append({"scores": scores, "rho": round(rho, 3),
                     "missing_scores": missing,
                     "hypotheses": [h.get("parent_statement", "")[:200]
                                    for h in doc.get("hypotheses", [])]})
        print(f"[run {r+1}/{args.runs}] rho {rho:+.3f} ({missing} missing)")
    ok = [r for r in runs if "scores" in r]
    out["runs"] = runs
    if ok:
        rhos = [r["rho"] for r in ok]
        mean_scores = [statistics.mean(r["scores"][i] for r in ok)
                       for i in range(len(paper))]
        rho_m, lo, hi = spearman_ci(mean_scores, truth)
        out["summary"] = {
            "n_runs": len(ok), "rho_mean_of_runs": round(statistics.mean(rhos), 3),
            "rho_sd_across_runs": round(statistics.pstdev(rhos), 3),
            "rho_run_averaged_scores": round(rho_m, 3),
            "ci95_compound_bootstrap": [round(lo, 3), round(hi, 3)]}
        print(json.dumps(out["summary"]))
    dest = HERE / f"agent_runs_{args.model}.json"
    dest.write_text(json.dumps(out, indent=1))
    print(f"wrote {dest}")


if __name__ == "__main__":
    main()
