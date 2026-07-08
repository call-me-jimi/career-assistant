"""KNOWN_TASKS must exactly match the task names used in backend code."""
import re
from pathlib import Path
from backend.config import KNOWN_TASKS


def test_known_tasks_matches_code():
    backend_root = Path(__file__).resolve().parents[1]
    used: set[str] = set()
    for p in backend_root.rglob("*.py"):
        if "tests" in p.parts:
            continue
        used |= set(re.findall(r'task="([a-z_]+)"', p.read_text()))
    assert used == set(KNOWN_TASKS), (
        f"missing from KNOWN_TASKS: {used - set(KNOWN_TASKS)}; "
        f"stale in KNOWN_TASKS: {set(KNOWN_TASKS) - used}"
    )
