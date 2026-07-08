"""save_settings must never write api_key values to disk."""
import json
import backend.config as config_module
from backend.config import AppSettings, LLMConfig, save_settings


def test_save_settings_strips_api_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "SETTINGS_FILE", tmp_path / "settings.json")
    s = AppSettings(
        default_llm=LLMConfig(provider="anthropic", model_name="m", api_key="sk-secret"),
        task_llm_configs={"qa": LLMConfig(provider="openai", model_name="m2", api_key="sk-other")},
    )
    save_settings(s)
    data = json.loads((tmp_path / "settings.json").read_text())
    assert data["default_llm"]["api_key"] is None
    assert data["task_llm_configs"]["qa"]["api_key"] is None
