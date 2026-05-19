"""Cached LLM translation of short UI / chat strings into the session language.

Substantive deliverables (cover letter, briefing, advice) are generated natively
in the target language via the `{{ language }}` prompt directive. This helper only
covers the hardcoded procedural chat strings, translated once per unique string and
cached to disk so repeat sessions in the same language cost nothing.
"""

from __future__ import annotations

import json
import logging

from backend.config import DATA_DIR
from backend.llm.prompts import load_system_prompt, render_user_prompt
from backend.llm.service import call_llm

log = logging.getLogger("assistant.translate")

_CACHE_FILE = DATA_DIR / "translation_cache.json"

# {language: {source_text: translation}}
_cache: dict[str, dict[str, str]] = {}


def is_english_language(language: str | None) -> bool:
    return (language or "").strip().lower() in ("", "english", "en")


def with_language_directive(prompt: str, language: str) -> str:
    """Append an output-language instruction to an LLM prompt.

    Used to make deliverables (cover letter, briefing, advice) generate natively
    in the session language. Returns the prompt unchanged for English so existing
    behaviour is preserved. Works on either a user or a system prompt.
    """
    if is_english_language(language):
        return prompt
    return (
        f"{prompt}\n\n"
        "--------------------------------------------------\n"
        "OUTPUT LANGUAGE\n\n"
        f"Write your entire response in {language}. Use natural, idiomatic "
        f"{language} with the salutation, sign-off, formatting, and professional "
        "conventions native to that language. Do not include any English "
        "translation or a note about the language.\n"
    )


def _load_cache() -> None:
    if _CACHE_FILE.exists():
        try:
            _cache.update(json.loads(_CACHE_FILE.read_text()))
        except Exception:  # pragma: no cover - corrupt cache is non-fatal
            log.warning("translation cache unreadable — starting empty")


def _persist() -> None:
    try:
        _CACHE_FILE.write_text(json.dumps(_cache, ensure_ascii=False, indent=2))
    except Exception:  # pragma: no cover
        log.warning("could not persist translation cache")


_load_cache()


async def translate_message(text: str, language: str) -> str:
    """Translate `text` into `language`, returning the original on any failure.

    English (or unset) passes straight through. Each unique (language, text) pair
    is translated once and cached on disk.
    """
    if is_english_language(language) or not text or not text.strip():
        return text

    per_lang = _cache.setdefault(language, {})
    cached = per_lang.get(text)
    if cached is not None:
        return cached

    try:
        result = await call_llm(
            task="ui_translation",
            system=load_system_prompt("translate_ui_message"),
            user=render_user_prompt("translate_ui_message", text=text, language=language),
        )
        translated = result.text.strip() or text
    except Exception:
        log.warning("translation failed (language=%s) — using original text", language)
        return text

    per_lang[text] = translated
    _persist()
    return translated
