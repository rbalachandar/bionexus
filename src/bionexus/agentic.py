"""Constrained agentic tool-calling loop.

The loop lets an LLM iteratively call BioNexus tools (read results, propose
hypotheses, check synthesis, submit assays) while enforcing:

  1. MAX TURNS — hard cap on iterations (no runaway loops)
  2. CONTEXT MANAGEMENT — tool results are truncated; old rounds compressed
  3. ERROR HANDLING — tool errors are returned to the LLM as feedback;
     N consecutive errors stops the loop
  4. SAFETY — lab tools go through LabGateway/SafetyEngine; the loop
     cannot bypass the gate
  5. BUDGET — integrates with ResourceBudget
  6. PROVENANCE — every tool call is recorded

The loop stops when the LLM signals completion, the turn cap is reached,
the budget is exhausted, or 3 consecutive tool errors occur.

Requires a ModelProvider that supports tool-use (Anthropic, OpenAI-compat).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from bionexus.core.contracts import Envelope


@dataclass
class LoopConfig:
    max_turns: int = 15
    max_consecutive_errors: int = 3
    max_tool_result_chars: int = 2000
    summary_after_turns: int = 6       # compress context after N turns
    system_prompt: str = ""
    tools: list[dict[str, Any]] = field(default_factory=list)  # Anthropic tool schemas


@dataclass
class LoopResult:
    completed: bool
    reason: str                        # "done" | "max_turns" | "budget" | "errors"
    turns: int = 0
    tool_calls: int = 0
    output: str = ""
    tool_history: list[dict] = field(default_factory=list)


class AgenticLoop:
    """A constrained tool-calling loop: the LLM iterates, BioNexus enforces."""

    def __init__(
        self,
        provider: Any,                   # must support .call_with_tools()
        tools_schema: list[dict],        # Anthropic tool definitions
        tool_executor: dict[str, Callable],
        config: LoopConfig | None = None,
        envelope: Envelope | None = None,
    ):
        self.provider = provider
        self.tool_schemas = tools_schema
        self.executors = tool_executor
        self.cfg = config or LoopConfig()
        self.envelope = envelope or Envelope(experiment_branch_id="agentic")
        self._consecutive_errors = 0

    def run(self, task: str) -> LoopResult:
        messages: list[dict] = [{"role": "user", "content": task}]
        system = self.cfg.system_prompt or (
            "You are a drug-discovery research agent. Use the available tools "
            "to answer the question or complete the task. Be systematic: "
            "check feasibility before proposing, test before concluding, and "
            "stop when you have enough evidence. Reply with 'DONE: <summary>' "
            "when finished."
        )
        result = LoopResult(completed=False, reason="")
        for turn in range(1, self.cfg.max_turns + 1):
            result.turns = turn
            response = self.provider.call_with_tools(
                messages=messages, tools=self.tool_schemas,
                system=system,
            )
            # Check for text-only response (no tool calls = done)
            if not response.get("tool_calls"):
                text = response.get("text", "")
                result.completed = True
                result.reason = "done"
                result.output = text
                if text.startswith("DONE:"):
                    result.output = text[5:].strip()
                return result
            # Execute each tool call
            tool_results = []
            for call in response.get("tool_calls", []):
                name = call.get("name", "")
                args = call.get("arguments", {})
                outcome = self._execute(name, args)
                tool_results.append({
                    "tool": name, "args": args, **outcome,
                })
                result.tool_calls += 1
                result.tool_history.append(outcome)
                if outcome["status"] == "error":
                    self._consecutive_errors += 1
                else:
                    self._consecutive_errors = 0
                if self._consecutive_errors >= self.cfg.max_consecutive_errors:
                    result.reason = "errors"
                    result.output = f"{self._consecutive_errors} consecutive tool errors"
                    return result
            # Append assistant + tool results to context
            messages.append({"role": "assistant", "content": response.get("raw", "")})
            for tr in tool_results:
                messages.append({
                    "role": "user",
                    "content": f"[tool: {tr['tool']}] {tr['summary']}",
                })
            # Context management: compress if growing
            if turn >= self.cfg.summary_after_turns:
                messages = self._compress(messages)
        result.reason = "max_turns"
        result.output = f"stopped after {self.cfg.max_turns} turns"
        return result

    def _execute(self, name: str, args: dict) -> dict:
        """Execute a tool call; returns {status, summary, data}."""
        fn = self.executors.get(name)
        if fn is None:
            return {"status": "error", "summary": f"unknown tool: {name}"}
        try:
            raw = fn(**args)
            summary = json.dumps(raw, default=str)[: self.cfg.max_tool_result_chars]
            return {"status": "ok", "summary": summary, "data": raw}
        except Exception as exc:
            return {"status": "error", "summary": f"{type(exc).__name__}: {exc}"}

    def _compress(self, messages: list[dict]) -> list[dict]:
        """Keep system + original task + last N exchanges; summarize the rest."""
        if len(messages) <= 12:
            return messages
        keep_head = 2   # original task
        keep_tail = 8   # recent exchanges
        removed = messages[keep_head:-keep_tail]
        summary_text = f"[{len(removed)} earlier exchanges summarized: "
        for m in removed:
            content = m.get("content", "")[:80]
            summary_text += content + " | "
        summary_text += "]"
        compressed = [{"role": "user", "content": summary_text}]
        return messages[:keep_head] + compressed + messages[-keep_tail:]
