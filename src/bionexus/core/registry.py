"""Plugin discovery + typed tool registry (P2).

Adapters register via entry points (see pyproject.toml) or directly in code.
The registry matches requested ToolNames to implementations with declared
capabilities.
"""
from __future__ import annotations

import importlib
from typing import Any

from bionexus.core.contracts import ToolInvocation, ToolName, ToolResult


class Registry:
    """Holds BioTool implementations keyed by declared capability."""

    def __init__(self) -> None:
        self._tools: dict[ToolName, list[Any]] = {}
        self._model_providers: dict[str, Any] = {}
        self._default_provider: str | None = None

    # ---- tools

    def register_tool(self, tool: Any) -> None:
        for cap in tool.capabilities:
            self._tools.setdefault(ToolName(cap), []).append(tool)

    def resolve(self, tool: ToolName) -> Any:
        tools = self._tools.get(ToolName(tool))
        if not tools:
            raise LookupError(f"no tool registered for capability '{tool}'")
        return tools[0]

    def invoke(self, invocation: ToolInvocation) -> ToolResult:
        tool = self.resolve(invocation.tool)
        return tool.invoke(invocation)

    # ---- model providers

    def register_model(self, provider: Any, default: bool = False) -> None:
        self._model_providers[provider.name] = provider
        if default or self._default_provider is None:
            self._default_provider = provider.name

    @property
    def model(self) -> Any:
        if self._default_provider is None:
            raise LookupError("no model provider registered")
        return self._model_providers[self._default_provider]

    # ---- entry-point discovery

    def load_entry_points(self, group_prefix: str = "bionexus") -> int:
        """Discover installed adapters. Returns count loaded. Optional deps
        that aren't installed are skipped, never fatal."""
        try:
            from importlib.metadata import entry_points
        except ImportError:  # pragma: no cover
            return 0
        eps = entry_points()
        loaded = 0
        groups = [
            (ep, f"{group_prefix}.models")
            if hasattr(eps, "select")
            else (ep, ep.group)
            for ep in []
        ]  # placeholder; real dispatch below
        if hasattr(eps, "select"):  # py3.10+
            for group, setter in (
                (f"{group_prefix}.models", self._ep_model),
                (f"{group_prefix}.labs", self._ep_tool),
                (f"{group_prefix}.tools", self._ep_tool),
            ):
                for ep in eps.select(group=group):
                    try:
                        setter(ep)
                        loaded += 1
                    except Exception:
                        continue  # optional dep missing — skip, never fatal
        return loaded

    def _ep_model(self, ep: Any) -> None:
        cls = ep.load()
        self.register_model(cls())

    def _ep_tool(self, ep: Any) -> None:
        cls = ep.load()
        self.register_tool(cls())


def import_string(path: str) -> Any:
    """Resolve 'module:attr' or 'module.attr' to an object."""
    mod_path, _, attr = path.partition(":")
    if not attr:
        mod_path, _, attr = path.rpartition(".")
    module = importlib.import_module(mod_path)
    return getattr(module, attr)
