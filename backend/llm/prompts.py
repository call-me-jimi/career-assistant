"""Jinja2 prompt template loading with highest-vN resolver."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound

from backend.config import TEMPLATES_DIR

PROMPTS_DIR = TEMPLATES_DIR / "prompts"
SYSTEM_DIR = TEMPLATES_DIR / "system"

_VERSION_RE = re.compile(r"^(?P<stem>.+)\.v(?P<ver>\d+)\.txt$")

_env = Environment(
    loader=FileSystemLoader([str(PROMPTS_DIR), str(SYSTEM_DIR)]),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)


def _resolve_latest(directory: Path, stem: str) -> Path:
    """Return the path of the highest-vN file matching {stem}.vN.txt."""
    best: tuple[int, Path] | None = None
    for p in directory.glob(f"{stem}.v*.txt"):
        m = _VERSION_RE.match(p.name)
        if not m or m.group("stem") != stem:
            continue
        ver = int(m.group("ver"))
        if best is None or ver > best[0]:
            best = (ver, p)
    if best is None:
        raise TemplateNotFound(stem)
    return best[1]


@lru_cache(maxsize=128)
def latest_prompt_path(stem: str) -> Path:
    return _resolve_latest(PROMPTS_DIR, stem)


@lru_cache(maxsize=128)
def latest_system_path(stem: str) -> Path:
    return _resolve_latest(SYSTEM_DIR, f"{stem}.system")


def render_user_prompt(stem: str, **context) -> str:
    path = latest_prompt_path(stem)
    tmpl = _env.get_template(path.name)
    return tmpl.render(**context)


def load_system_prompt(stem: str) -> str:
    path = latest_system_path(stem)
    return path.read_text()
