"""Runtime config loaded from .env and settings.json."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
BACKEND = Path(__file__).resolve().parent
TEMPLATES_DIR = BACKEND / "templates"
DATA_DIR = BACKEND / "data"
CONFIG_DIR = BACKEND / "config"
SETTINGS_FILE = CONFIG_DIR / "settings.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)


class LLMConfig(BaseModel):
    provider: str = Field(default="anthropic")
    model_name: str = Field(default="claude-sonnet-4-5")
    base_url: str | None = None
    api_key: str | None = None
    max_tokens: int | None = None


class ModelPricing(BaseModel):
    """Per-model pricing in USD per million tokens."""

    input_per_mtok: float = 0.0
    output_per_mtok: float = 0.0


class TranscriptionConfig(BaseModel):
    """Local speech-to-text settings shared across audio-handling features."""

    provider: str = "faster_whisper"
    model: str = "turbo"
    device: str = "auto"
    compute_type: str = "auto"
    beam_size: int = 5
    max_file_mb: int = 200
    voice_max_mb: int = 10


class AppSettings(BaseModel):
    default_llm: LLMConfig = Field(default_factory=LLMConfig)
    task_llm_configs: dict[str, LLMConfig] = Field(default_factory=dict)
    model_pricing: dict[str, ModelPricing] = Field(default_factory=dict)
    transcription: TranscriptionConfig = Field(default_factory=TranscriptionConfig)
    max_hm_iterations: int = 3
    quality_threshold: float = 8.5
    language: str = "English"
    currency: str = "EUR"
    default_export_folder: str = "~/JobApplications"
    google_sheets_spreadsheet_id: str = ""
    learning_enabled: bool = True
    synthesis_window_n: int = 5
    inline_surface_threshold: int = 3


def _load_settings_file() -> dict[str, Any]:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def load_settings() -> AppSettings:
    """Merge .env defaults into settings.json-backed AppSettings.

    API keys come from env vars, never from settings.json.
    """
    data = _load_settings_file()
    settings = AppSettings.model_validate(data) if data else AppSettings()

    env_provider = os.getenv("LLM_PROVIDER")
    env_model = os.getenv("LLM_MODEL_NAME")
    env_base = os.getenv("LLM_BASE_URL")
    if env_provider:
        settings.default_llm.provider = env_provider
    if env_model:
        settings.default_llm.model_name = env_model
    if env_base:
        settings.default_llm.base_url = env_base

    settings.default_export_folder = os.getenv(
        "DEFAULT_EXPORT_FOLDER", settings.default_export_folder
    )
    if not settings.google_sheets_spreadsheet_id:
        settings.google_sheets_spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")
    return settings


def get_api_key(provider: str) -> str | None:
    """Resolve API key for a provider from environment only."""
    provider = provider.lower()
    if provider == "anthropic":
        return os.getenv("ANTHROPIC_API_KEY") or os.getenv("LLM_API_KEY")
    if provider == "openai":
        return os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    if provider == "ollama":
        return None
    return os.getenv("LLM_API_KEY")


def get_ollama_base_url() -> str:
    return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


def resolved_export_folder() -> Path:
    return Path(os.path.expanduser(load_settings().default_export_folder))


KNOWN_TASKS: list[str] = [
    "candidate_profile",
    "extract_job_and_company_information",
    "alignment_strategy",
    "infer_role",
    "position_candidate",
    "cover_letter_generation",
    "simulate_hiring_manager",
    "refine_cover_letter",
    "qa",
    "interview_briefing",
    "career_advisor_chat",
    "career_advisor_swot",
    "synthesize_learning",
    "ui_translation",
    "transcribe_interview",
    "analyze_interview_performance",
]


def save_settings(settings: AppSettings) -> None:
    """Persist the editable portion of AppSettings to settings.json."""
    payload = settings.model_dump(mode="json", exclude_none=False)
    SETTINGS_FILE.write_text(json.dumps(payload, indent=2))


SETTINGS = load_settings()
