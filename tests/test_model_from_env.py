"""Agent-mode hypotheses come from a REAL model or not at all — never a silent stub."""
import pytest

from proef.adapters.models.from_env import ModelNotConfigured, model_from_env, model_status

KEYS = ("PROEF_LLM_API", "PROEF_LLM_MODEL", "PROEF_LLM_BASE_URL", "PROEF_LLM_TOKEN", "ANTHROPIC_AUTH_TOKEN")


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)


def test_unconfigured_is_an_error_not_a_stub():
    assert model_status() == {"configured": False, "api": "anthropic", "model": None}
    with pytest.raises(ModelNotConfigured, match="PROEF_LLM_MODEL"):
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
