"""Pick the campaign's model from the environment — a REAL one, or fail loudly.

    PROEF_LLM_BASE_URL   endpoint base, e.g. https://api.anthropic.com or https://host/v1
    PROEF_LLM_MODEL      model name
    PROEF_LLM_TOKEN      API key (read from the environment only, never a flag)
    PROEF_LLM_SESSION_HEADER  optional: name of a header carrying a stable session id, for gateways that
                         require one (e.g. x-opencode-session)
    PROEF_LLM_API        "anthropic" (Messages API, default); "openai" (OpenAI-compatible
                         /chat/completions — OpenRouter, vLLM, Ollama, ...); or "openai-responses"
                         (the /responses API some gateways use for GPT-family models)

There is no silent offline stub here: a campaign whose hypotheses come from a model must be
able to say which model wrote them, so an unconfigured model is an error, not a fake.
"""
from __future__ import annotations

import os


class ModelNotConfigured(RuntimeError):
    pass


def model_status() -> dict:
    """What the workbench shows: is a real model configured, and which?"""
    api = (os.environ.get("PROEF_LLM_API") or "anthropic").lower()
    model = os.environ.get("PROEF_LLM_MODEL")
    base = os.environ.get("PROEF_LLM_BASE_URL")
    key = os.environ.get("PROEF_LLM_TOKEN") or (os.environ.get("ANTHROPIC_AUTH_TOKEN") if api == "anthropic" else None)
    ok = bool(model and key and (base or api == "anthropic"))
    return {"configured": ok, "api": api, "model": model if ok else None}


def model_from_env():
    st = model_status()
    if not st["configured"]:
        raise ModelNotConfigured(
            "no model configured: set PROEF_LLM_MODEL and PROEF_LLM_TOKEN "
            "(and PROEF_LLM_BASE_URL; PROEF_LLM_API=openai or openai-responses for OpenAI-compatible endpoints)")
    base = os.environ.get("PROEF_LLM_BASE_URL")
    key = os.environ.get("PROEF_LLM_TOKEN") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if st["api"] in ("openai", "openai-responses"):
        from proef.adapters.models.openai_compat import OpenAICompatProvider
        return OpenAICompatProvider(model=st["model"], base_url=base, api_key=key,
                                    api="responses" if st["api"] == "openai-responses" else "chat",
                                    session_header=os.environ.get("PROEF_LLM_SESSION_HEADER") or None)
    from proef.adapters.models.anthropic_provider import AnthropicProvider
    return AnthropicProvider(model=st["model"], api_key=key, base_url=base)
