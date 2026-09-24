"""Hand-checked reference answers for extraction tasks, one JSON file per trace.

They live under backend/data/ (git-ignored) because they are built from your real
CV and job ads. Two shapes:

  {"kind": "fields", "expected": {...}}   JSON tasks — scored by field precision/recall
  {"kind": "facts",  "facts": ["..."]}    prose tasks — scored by how many facts the output states
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.config import DATA_DIR
from backend.eval import store
from backend.eval.scorers import parse_json

LABEL_DIR = DATA_DIR / "eval" / "labels"


def label_path(trace_id: int) -> Path:
    return LABEL_DIR / f"{trace_id}.json"


def load_label(trace_id: int) -> dict[str, Any] | None:
    path = label_path(trace_id)
    if not path.exists():
        return None
    label = json.loads(path.read_text())
    # A facts label nobody has filled in yet scores nothing.
    if label.get("kind") == "facts" and not label.get("facts"):
        return None
    return label


async def init_labels(set_name: str) -> list[Path]:
    """Write a draft label per case, seeded from the traced output, for you to correct.

    A JSON output becomes the expected fields as-is — fix what is wrong, delete what
    should not be there. A prose output gets an empty fact list and the output beside
    it for reference; write the facts a correct answer must state.
    """
    s = await store.get_set(set_name)
    if not s:
        raise ValueError(f"No eval set named {set_name!r}")
    LABEL_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for case in await store.load_cases(s["trace_ids"]):
        path = label_path(case["trace_id"])
        if path.exists():
            continue
        parsed = parse_json(case["response_text"] or "")
        if parsed is not None:
            label: dict[str, Any] = {"kind": "fields", "expected": parsed}
        else:
            label = {"kind": "facts", "facts": [],
                     "reference_output": case["response_text"]}
        path.write_text(json.dumps(label, indent=2, ensure_ascii=False))
        written.append(path)
    return written
