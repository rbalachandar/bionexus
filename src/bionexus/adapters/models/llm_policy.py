"""LLM property/HTS policies — evaluate a real LLM on chemistry tasks.

AnthropicLLMPolicy speaks the Anthropic Messages protocol via stdlib urllib
(configured by env: BIONEXUS_LLM_BASE_URL / BIONEXUS_LLM_TOKEN / BIONEXUS_LLM_MODEL,
falling back to ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN / ANTHROPIC_DEFAULT_*).

LLMs are expensive per call: use `subset` in the harness or evaluate on few
examples. Model version is pinned on every prediction (P5).
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Any


class AnthropicLLMPolicy:
    name = "llm"

    def __init__(self, model: str | None = None, base_url: str | None = None,
                 token: str | None = None, max_examples: int | None = None):
        self.model = (model or os.environ.get("BIONEXUS_LLM_MODEL")
                      or os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
                      or os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL"))
        self.base_url = (base_url or os.environ.get("BIONEXUS_LLM_BASE_URL")
                         or os.environ.get("ANTHROPIC_BASE_URL", "")).rstrip("/")
        self.token = (token or os.environ.get("BIONEXUS_LLM_TOKEN")
                      or os.environ.get("ANTHROPIC_AUTH_TOKEN") or "")
        self.max_examples = max_examples
        if not (self.model and self.base_url and self.token):
            raise RuntimeError(
                "LLM not configured: set BIONEXUS_LLM_BASE_URL/TOKEN/MODEL "
                "(or ANTHROPIC_BASE_URL/AUTH_TOKEN/... model)"
            )

    # -- Policy protocol ------------------------------------------------------

    def fit(self, data: list[tuple[str, float]]) -> None:  # noqa: ARG002
        pass  # zero-shot; few-shot variants would cache exemplars here

    def predict(self, smiles: str) -> float:
        raw = self._complete(
            "You are a computational chemist. Predict the property value. "
            "Reply with ONLY a JSON object: {\"value\": <number>}\n\n"
            f"SMILES: {smiles}"
        )
        return self._parse(raw)

    # -- extras ---------------------------------------------------------------

    def predict_many(self, smiles_list: list[str], task_hint: str) -> list[float]:
        if self.max_examples:
            smiles_list = smiles_list[: self.max_examples]
        return [self.predict(s) for s in smiles_list]

    def _complete(self, prompt: str, max_tokens: int = 200) -> str:
        body = json.dumps({
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            f"{self.base_url}/v1/messages",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=90) as resp:  # noqa: S310
            data = json.loads(resp.read())
        parts = [c.get("text", "") for c in data.get("content", []) if c.get("type") == "text"]
        return "".join(parts)

    @staticmethod
    def _parse(raw: str) -> float:
        m = re.search(r"-?\d+(?:\.\d+)?", raw)
        if not m:
            raise ValueError(f"LLM returned no number: {raw[:120]}")
        return float(m.group(0))


def llm_available() -> bool:
    try:
        AnthropicLLMPolicy()
        return True
    except RuntimeError:
        return False
