"""Deterministic scorers and statistics — no LLM involved."""

from __future__ import annotations

import json
import math
import re
from statistics import mean, pstdev
from typing import Any

from backend.llm.service import extract_json

# A number as written in prose: 15, 1.5, 1,5, 500.000, 50%. List/heading numbering
# ("1. Leadership", "2) …") is layout, not a claim, and is removed first.
_NUMBERING_RE = re.compile(r"^\s*(?:#+\s*)?\d+[.)]\s", re.MULTILINE)
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
# "€500k", "1,5 Mio.", "2 bn" — magnitude words a CV and a letter use interchangeably.
_SCALED_RE = re.compile(
    r"(\d+(?:[.,]\d+)*)\s*(k|K|m|M|Mio|Mrd|bn|million|Million|thousand|Tsd)\b"
)
_SCALE = {"k": 1e3, "thousand": 1e3, "tsd": 1e3, "m": 1e6, "mio": 1e6, "million": 1e6,
          "mrd": 1e9, "bn": 1e9}


def _value(raw: str) -> float:
    """"500.000" / "500,000" → 500000 (groups of three), "1,5" / "1.5" → 1.5."""
    parts = re.split(r"[.,]", raw)
    if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]):
        return float("".join(parts))
    if len(parts) == 2:
        return float(f"{parts[0]}.{parts[1]}")
    return float("".join(parts))


def _canon(v: float) -> str:
    return f"{v:.6f}".rstrip("0").rstrip(".")


def _numbers(text: str) -> set[str]:
    """Each number in two spellings — its digits and its value — so "500k", "500.000"
    and "500,000" all meet, while list numbering never counts."""
    text = _NUMBERING_RE.sub(" ", text)
    out: set[str] = set()
    for raw in _NUMBER_RE.findall(text):
        out.add(re.sub(r"[.,]", "", raw))
    for raw, unit in _SCALED_RE.findall(text):
        out.add(_canon(_value(raw) * _SCALE[unit.lower()]))
    return out


def _claims(text: str) -> set[str]:
    """The numbers a text states, one entry per number, by value."""
    text = _NUMBERING_RE.sub(" ", text)
    scaled = {m.start(1): _value(m.group(1)) * _SCALE[m.group(2).lower()]
              for m in _SCALED_RE.finditer(text)}
    return {_canon(scaled.get(m.start(), _value(m.group(0)))) for m in _NUMBER_RE.finditer(text)}


def number_grounding(output: str, source: str) -> dict[str, Any]:
    """Numbers in the output that never appear in the input — the cheapest reliable
    signal of an invented fact (team sizes, percentages, years, revenue)."""
    claims = _claims(output)
    known = _numbers(source)
    known |= {_canon(_value(n)) for n in _NUMBER_RE.findall(_NUMBERING_RE.sub(" ", source))}
    ungrounded = sorted(c for c in claims if c not in known and c.replace(".", "") not in known)
    return {"numbers": len(claims), "ungrounded_numbers": ungrounded}


def parse_json(text: str) -> dict | None:
    try:
        out = extract_json(text)
    except (ValueError, json.JSONDecodeError):
        return None
    return out if isinstance(out, dict) else None


def _norm(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v)).strip().lower()


def _leaves(obj: Any, path: str = "") -> set[tuple[str, str]]:
    """(path, value) pairs; list indices are dropped so order does not matter."""
    if isinstance(obj, dict):
        return {leaf for k, v in obj.items() for leaf in _leaves(v, f"{path}.{k}" if path else k)}
    if isinstance(obj, list):
        return {leaf for v in obj for leaf in _leaves(v, f"{path}[]")}
    value = _norm(obj)
    return {(path, value)} if value not in ("", "none", "null") else set()


def _match(a: tuple[str, str], b: tuple[str, str]) -> bool:
    if a[0] != b[0]:
        return False
    x, y = a[1], b[1]
    return x == y or (min(len(x), len(y)) > 3 and (x in y or y in x))


def field_prf(pred: dict, expected: dict) -> dict[str, float]:
    """Field-level precision / recall of a JSON extraction against its label."""
    p, e = _leaves(pred), _leaves(expected)
    precision = sum(any(_match(x, y) for y in e) for x in p) / len(p) if p else 0.0
    recall = sum(any(_match(y, x) for x in p) for y in e) / len(e) if e else 1.0
    return {"precision": round(precision, 3), "recall": round(recall, 3)}


def words(text: str) -> int:
    return len(text.split())


def wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% interval for a win rate; honest at the small n this project has."""
    if n == 0:
        return (0.0, 1.0)
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def mean_ci(xs: list[float], z: float = 1.96) -> tuple[float, float, float] | None:
    """(mean, low, high) with a normal-approximation 95% interval."""
    if not xs:
        return None
    m = mean(xs)
    if len(xs) < 2:
        return (m, m, m)
    half = z * pstdev(xs) * math.sqrt(len(xs) / (len(xs) - 1)) / math.sqrt(len(xs))
    return (m, m - half, m + half)


def verdict(low: float, high: float) -> str:
    if low > 0.5:
        return "switch"
    if high < 0.5:
        return "keep"
    return "inconclusive"
