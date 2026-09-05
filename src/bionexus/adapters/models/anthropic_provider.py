"""Anthropic model provider (T4.1, P3).

Same contract as OpenAICompatProvider: real API when configured, deterministic
offline stub otherwise. Stamps model_version on every result (P5).
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from typing import Any

from bionexus.core.contracts import ToolInvocation, ToolName, ToolResult


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str | None = None, api_key: str | None = None,
                 base_url: str | None = None):
        self.model = (model or os.environ.get("BIONEXUS_LLM_MODEL")
                      or os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
                      or os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL")
                      or "stub-claude")
        self.model_version = self.model
        self.api_key = api_key or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        self.base_url = (base_url or os.environ.get("BIONEXUS_LLM_BASE_URL")
                         or os.environ.get("ANTHROPIC_BASE_URL")
                         or "https://api.anthropic.com").rstrip("/")
        # real-API mode only when a key is present; otherwise offline stub
        self.api_key = self.api_key if self.api_key else None

    def generate(self, invocation: ToolInvocation, prompt: str, system: str | None = None, **kwargs: Any) -> ToolResult:
        if self.api_key is None:
            text = self._stub_generate(prompt, **kwargs)
        else:
            text = self._messages(prompt, system, **kwargs)
        return ToolResult(
            envelope=invocation.envelope.model_copy(),
            invocation_id=invocation.invocation_id,
            status="succeeded",
            output={"text": text},
            model_version=self.model_version,
        )

    def predict(self, invocation: ToolInvocation, kind: ToolName, payload: dict[str, Any]) -> ToolResult:
        return ToolResult(
            envelope=invocation.envelope.model_copy(),
            invocation_id=invocation.invocation_id,
            status="rejected",
            rejection_reason=f"{self.name} does not implement structured prediction '{kind}'",
        )

    def _messages(self, prompt: str, system: str | None, **kwargs: Any) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": kwargs.pop("max_tokens", 4000),
            "messages": [{"role": "user", "content": prompt}],
            **kwargs,
        }
        if system:
            body["system"] = system
        req = urllib.request.Request(
            f"{self.base_url}/v1/messages",
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key or "",
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        data = self._post(req)
        text = "".join(c.get("text", "") for c in data.get("content", [])
                       if c.get("type") == "text")
        if not text:
            raise ValueError("model returned no text content "
                             "(reasoning may have exhausted max_tokens)")
        return text

    def _post(self, req, tries: int = 6):
        import time
        import urllib.error
        for i in range(tries):
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
                    return json.loads(resp.read())
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 500, 502, 503) or i == tries - 1:
                    raise
                time.sleep(10 * (i + 1))
            except Exception:
                if i == tries - 1:
                    raise
                time.sleep(10 * (i + 1))

    def call_with_tools(self, messages: list[dict], tools: list[dict],
                        system: str = "") -> dict:
        """Send a conversation with tool definitions; returns parsed response
        with tool_calls extracted. Used by the agentic loop."""
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 8000,
            "messages": messages,
            "tools": tools,
        }
        if system:
            body["system"] = system
        req = urllib.request.Request(
            f"{self.base_url}/v1/messages",
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key or "",
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        data = self._post(req)
        # Parse content blocks
        text_parts = []
        tool_calls = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "name": block.get("name", ""),
                    "arguments": block.get("input", {}),
                })
        stop = data.get("stop_reason", "")
        return {
            "text": "".join(text_parts),
            "tool_calls": tool_calls if stop == "tool_use" else [],
            "raw": json.dumps(data.get("content", []), default=str)[:4000],
            "stop_reason": stop,
        }

    def _stub_generate(self, prompt: str, n: int = 3, **kwargs: Any) -> str:
        h = hashlib.sha256(("anthropic:" + prompt).encode()).hexdigest()
        proposals = [
            {"smiles": f"N{'C' * (1 + int(h[i:i + 2], 16) % 6)}O", "seed": h[i:i + 8]}
            for i in range(0, 2 * n, 2)
        ]
        return json.dumps(proposals)
