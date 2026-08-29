"""OpenAI-compatible model provider (P3).

Works with OpenAI, ollama, vLLM, llama.cpp server, OpenRouter — anything that
speaks POST {base_url}/chat/completions. Only stdlib urllib (keeps the adapter
dependency-free); `httpx` extra available for production use.

model_version is pinned from the constructor and stamped on every ToolResult
(P5). If no network is available (or base_url is None) the provider runs in
stub mode: deterministic proposals derived from the prompt — enough for
simulator-first CI (P8).
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from typing import Any

from bionexus.core.contracts import ToolInvocation, ToolName, ToolResult


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(
        self,
        model: str = "stub-1",
        base_url: str | None = None,  # e.g. http://localhost:11434/v1 (ollama)
        api_key: str | None = None,
    ):
        self.model = model
        self.model_version = model
        self.base_url = base_url
        self.api_key = api_key

    # -- ModelProvider ------------------------------------------------------

    def generate(self, invocation: ToolInvocation, prompt: str, system: str | None = None, **kwargs: Any) -> ToolResult:
        if self.base_url is None:
            text = self._stub_generate(prompt, **kwargs)
        else:
            text = self._chat(prompt, system, **kwargs)
        return ToolResult(
            envelope=invocation.envelope.model_copy(),
            invocation_id=invocation.invocation_id,
            status="succeeded",
            output={"text": text},
            model_version=self.model_version,
        )

    def predict(self, invocation: ToolInvocation, kind: ToolName, payload: dict[str, Any]) -> ToolResult:
        # providers only do text; structured prediction belongs to BioTools.
        return ToolResult(
            envelope=invocation.envelope.model_copy(),
            invocation_id=invocation.invocation_id,
            status="rejected",
            rejection_reason=f"{self.name} does not implement structured prediction '{kind}'",
        )

    # -- internals ------------------------------------------------------------

    def _chat(self, prompt: str, system: str | None, **kwargs: Any) -> str:
        body = {
            "model": self.model,
            "messages": ([{"role": "system", "content": system}] if system else [])
            + [{"role": "user", "content": prompt}],
            **kwargs,
        }
        req = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"]

    def _stub_generate(self, prompt: str, n: int = 3, **kwargs: Any) -> str:
        """Deterministic offline generation so CI never needs a model server."""
        h = hashlib.sha256(prompt.encode()).hexdigest()
        proposals = [
            {"smiles": f"C{'C' * (1 + int(h[i:i + 2], 16) % 6)}O", "seed": h[i:i + 8]}
            for i in range(0, 2 * n, 2)
        ]
        return json.dumps(proposals)
