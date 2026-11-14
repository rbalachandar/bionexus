"""Pick the campaign's model from the environment — a REAL one, or fail loudly.

    PROEF_LLM_PRESET     optional shortcut for a known gateway (see PRESETS), e.g. "opencode-go"
    PROEF_LLM_MODEL      model name
    PROEF_LLM_TOKEN      API key (read from the environment only, never a flag)
    PROEF_LLM_BASE_URL   endpoint base, e.g. https://api.anthropic.com or https://host/v1
    PROEF_LLM_API        "anthropic" (Messages API, default); "openai" (OpenAI-compatible
                         /chat/completions — OpenRouter, vLLM, Ollama, ...); or "openai-responses"
                         (the /responses API some gateways use for GPT-family models)
    PROEF_LLM_SESSION_HEADER  optional: header that carries a stable session id, for gateways that
                         require one (e.g. x-opencode-session)

Explicit settings always win over a preset. There is no silent offline stub here: a campaign whose
hypotheses come from a model must be able to say which model wrote them, so an unconfigured model
is an error, not a fake.
"""
from __future__ import annotations

import os

# A preset only fills in what you did not set. `key_env` names the variable that already holds the
# key in your shell, so you do not have to copy it into PROEF_LLM_TOKEN.
PRESETS: dict[str, dict] = {
    "opencode-go": {
        "base_url": "https://opencode.ai/inference/go/openai/v1",
        "session_header": "x-opencode-session",
        "key_env": "OPENCODE_API_KEY",
        # GPT / Grok models are served by the Responses API; the other models by chat completions
        "api_by_model_prefix": {("gpt-", "grok-"): "openai-responses"},
        "api_default": "openai",
    },
}


class ModelNotConfigured(RuntimeError):
    pass


def _resolve() -> dict:
    env = os.environ.get
    preset_name = (env("PROEF_LLM_PRESET") or "").strip().lower()
    preset = PRESETS.get(preset_name, {})
    if preset_name and not preset:
        raise ModelNotConfigured(f"unknown PROEF_LLM_PRESET {preset_name!r}; known: {', '.join(sorted(PRESETS))}")
    model = env("PROEF_LLM_MODEL")
    api = env("PROEF_LLM_API")
    if not api and preset:
        api = preset.get("api_default", "openai")
        for prefixes, name in (preset.get("api_by_model_prefix") or {}).items():
            if model and model.startswith(prefixes):
                api = name
    api = (api or "anthropic").lower()
    key = env("PROEF_LLM_TOKEN") or (env(preset["key_env"]) if preset.get("key_env") else None) \
        or (env("ANTHROPIC_AUTH_TOKEN") if api == "anthropic" else None)
    base = env("PROEF_LLM_BASE_URL") or preset.get("base_url")
    return {"api": api, "model": model, "key": key, "base_url": base,
            "session_header": env("PROEF_LLM_SESSION_HEADER") or preset.get("session_header")}


def _is_local(base_url: str | None) -> bool:
    from urllib.parse import urlparse
    return (urlparse(base_url or "").hostname or "") in ("localhost", "127.0.0.1", "::1")


def model_status() -> dict:
    """What the workbench shows: is a real model configured, and which? Never includes the key."""
    try:
        c = _resolve()
    except ModelNotConfigured:
        return {"configured": False, "api": None, "model": None}
    # a key is required for hosted endpoints; a local server (Ollama, vLLM) needs none
    ok = bool(c["model"] and (c["key"] or _is_local(c["base_url"])) and (c["base_url"] or c["api"] == "anthropic"))
    return {"configured": ok, "api": c["api"], "model": c["model"] if ok else None}


def model_from_env():
    c = _resolve()
    if not model_status()["configured"]:
        raise ModelNotConfigured(
            "no model configured: set PROEF_LLM_MODEL and PROEF_LLM_TOKEN (not needed for a local server), plus PROEF_LLM_BASE_URL "
            "and PROEF_LLM_API=openai or openai-responses for OpenAI-compatible endpoints "
            "(or PROEF_LLM_PRESET=opencode-go with OPENCODE_API_KEY)")
    if c["api"] in ("openai", "openai-responses"):
        from proef.adapters.models.openai_compat import OpenAICompatProvider
        return OpenAICompatProvider(model=c["model"], base_url=c["base_url"], api_key=c["key"],
                                    api="responses" if c["api"] == "openai-responses" else "chat",
                                    session_header=c["session_header"])
    from proef.adapters.models.anthropic_provider import AnthropicProvider
    return AnthropicProvider(model=c["model"], api_key=c["key"], base_url=c["base_url"])
