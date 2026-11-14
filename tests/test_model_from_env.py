"""Agent-mode hypotheses come from a REAL model or not at all — never a silent stub."""
import pytest

from proef.adapters.models.from_env import ModelNotConfigured, model_from_env, model_status

KEYS = ("PROEF_LLM_PRESET", "OPENCODE_API_KEY", "PROEF_LLM_SESSION_HEADER", "PROEF_LLM_API", "PROEF_LLM_MODEL", "PROEF_LLM_BASE_URL", "PROEF_LLM_TOKEN", "ANTHROPIC_AUTH_TOKEN")


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)


def test_unconfigured_is_an_error_not_a_stub():
    assert model_status() == {"configured": False, "api": "anthropic", "model": None}
    with pytest.raises(ModelNotConfigured, match="no model configured"):
        model_from_env()


def test_openai_compatible_endpoint_is_supported(monkeypatch):
    monkeypatch.setenv("PROEF_LLM_API", "openai")
    monkeypatch.setenv("PROEF_LLM_MODEL", "some-model")
    monkeypatch.setenv("PROEF_LLM_BASE_URL", "https://host.example/v1")
    monkeypatch.setenv("PROEF_LLM_TOKEN", "k")
    m = model_from_env()
    assert m.name == "openai_compat" and m.base_url == "https://host.example/v1" and m.model == "some-model"
    assert model_status()["configured"] is True and "k" not in str(model_status())   # never echoes the key


def test_anthropic_needs_a_key_too(monkeypatch):
    monkeypatch.setenv("PROEF_LLM_MODEL", "m")
    assert model_status()["configured"] is False
    monkeypatch.setenv("PROEF_LLM_TOKEN", "k")
    assert model_from_env().name == "anthropic"


def test_workbench_refuses_a_candidate_less_launch_without_a_model(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from proef import program as program_cfg
    from proef.api.app import app
    monkeypatch.chdir(tmp_path)
    name = f"No Model {tmp_path.name}"
    program_cfg.save_program_record({"program": name, "custom": True, "objective": "x", "modality": "small molecule",
                                     "metric": "ic50_um", "direction": "min", "gate_value": 10, "unit": "µM",
                                     "mode": "autonomous"})
    with TestClient(app) as c:
        r = c.post(f"/api/v1/programs/{program_cfg._slug(name)}/campaigns", json={"candidates": []})
    assert r.status_code == 409 and r.json()["detail"]["type"] == "model-not-configured"


def test_opencode_go_preset_fills_in_endpoint_header_key_and_api(monkeypatch):
    monkeypatch.setenv("PROEF_LLM_PRESET", "opencode-go")
    monkeypatch.setenv("OPENCODE_API_KEY", "secret-from-shell")
    monkeypatch.setenv("PROEF_LLM_MODEL", "gpt-6-luna")                      # GPT family -> Responses API
    m = model_from_env()
    assert (m.api, m.base_url, m.session_header) == ("responses", "https://opencode.ai/inference/go/openai/v1",
                                                     "x-opencode-session")
    assert m.api_key == "secret-from-shell" and "secret" not in str(model_status())
    monkeypatch.setenv("PROEF_LLM_MODEL", "some-open-model")                  # anything else -> chat completions
    assert model_from_env().api == "chat"


def test_explicit_settings_beat_the_preset(monkeypatch):
    monkeypatch.setenv("PROEF_LLM_PRESET", "opencode-go")
    monkeypatch.setenv("OPENCODE_API_KEY", "k")
    monkeypatch.setenv("PROEF_LLM_MODEL", "gpt-6-luna")
    monkeypatch.setenv("PROEF_LLM_API", "openai")
    monkeypatch.setenv("PROEF_LLM_BASE_URL", "https://elsewhere.example/v1")
    m = model_from_env()
    assert m.api == "chat" and m.base_url == "https://elsewhere.example/v1"


def test_unknown_preset_is_an_error_not_a_guess(monkeypatch):
    monkeypatch.setenv("PROEF_LLM_PRESET", "nope")
    monkeypatch.setenv("PROEF_LLM_MODEL", "m")
    with pytest.raises(ModelNotConfigured, match="unknown PROEF_LLM_PRESET"):
        model_from_env()
    assert model_status()["configured"] is False


def test_a_local_server_needs_no_key_but_a_hosted_one_does(monkeypatch):
    monkeypatch.setenv("PROEF_LLM_API", "openai")
    monkeypatch.setenv("PROEF_LLM_MODEL", "llama3")
    monkeypatch.setenv("PROEF_LLM_BASE_URL", "http://localhost:11434/v1")
    assert model_status()["configured"] is True and model_from_env().api_key is None
    monkeypatch.setenv("PROEF_LLM_BASE_URL", "https://hosted.example/v1")
    assert model_status()["configured"] is False
