"""CV PDF text extraction."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader


def extract_cv_text(pdf_path: str | Path) -> str:
    reader = PdfReader(str(pdf_path))
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        parts.append(text)
    return "\n\n".join(p for p in parts if p.strip())
