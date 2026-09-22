"""Recapture docs/screenshots/landing-page.png against invented data.

The landing page shows the state of a real job search, which is not something
a public README should publish. So this seeds a throwaway sqlite file with
plausible journeys, lets the real `journeys_summary()` derive the counters from
their dates, and serves the browser that payload — the numbers in the shot are
computed by the app rather than typed by hand, they just describe a search that
belongs to nobody.

`backend/data/assistant.sqlite` is never opened: `DB_PATH` is only dereferenced
at call time inside `backend/storage/db.py`, so rebinding it first is enough.

Usage — needs the frontend dev server up, but not the backend:

    cd frontend && npm run dev
    uv run python docs/screenshots/seed_demo.py

Re-run it after any landing-page change; the numbers stay put across runs, so
the screenshot only moves when the design does.
"""

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import backend.storage.db as dbmod  # noqa: E402

DEMO_DB = Path(tempfile.gettempdir()) / "career-assistant-demo.sqlite"
DEMO_DB.unlink(missing_ok=True)
dbmod.DB_PATH = DEMO_DB  # before any storage call, so the real DB stays shut

from backend.api.routes import journeys_summary  # noqa: E402
from backend.storage.interviews import create_interview  # noqa: E402
from backend.storage.journeys import create_journey  # noqa: E402

DAY = 86_400.0
NOW = time.time()
OUT = ROOT / "docs" / "screenshots" / "landing-page.png"

# Never rendered on the landing page — the counters are all it shows — but a
# journey wants a company, and invented ones keep real employers out of the repo.
COMPANIES = [
    "Northwind Analytics", "Meridian Labs", "Halcyon Systems", "Verdant Rail",
    "Ashgrove Health", "Pinemark Studio", "Cobalt Freight", "Larkspur Energy",
    "Stillwater Media", "Ironvale Robotics", "Kestrel Insurance", "Brightfold",
    "Quarry & Vane", "Tessellate", "Marlowe Foods", "Osprey Bank",
    "Fernbrook Civic", "Glasshouse Retail", "Dunmore Textiles", "Alder Point",
    "Saltire Mobility", "Ravenna Optics", "Thornbury Press", "Wexford Marine",
]


def ago(days: float) -> float:
    return NOW - days * DAY


async def seed() -> dict:
    """One journey per status, dated so `derive_status()` sorts them itself."""
    await dbmod.init_db()
    names = iter(COMPANIES)

    async def job(**fields) -> str:
        return await create_journey(
            profile_id="p1", company_name=next(names),
            job_title="Head of Data", **fields
        )

    # applied — sent recently, still inside the quiet window
    for d in (2, 5, 9, 14, 21):
        await job(applied_at=ago(d))

    # in_progress — a round on the calendar
    for applied, round_at in ((40, 3), (52, 8), (61, 12)):
        jid = await job(applied_at=ago(applied))
        await create_interview(
            journey_id=jid, profile_id="p1",
            interview_type="screening", scheduled_at=ago(round_at),
        )

    # silent — applied, nothing back, past the threshold
    for d in (35, 42, 55, 63, 78, 95):
        await job(applied_at=ago(d))

    await job(applied_at=ago(50), on_hold_at=ago(20))   # on_hold
    await job(applied_at=ago(70), offer_at=ago(4))      # offer
    await job(applied_at=ago(60), dropped_at=ago(30))   # withdrawn

    for applied, turned_down in ((90, 62), (84, 55), (73, 48),
                                 (66, 40), (58, 33), (47, 26), (38, 15)):
        await job(applied_at=ago(applied), rejected_at=ago(turned_down))

    return await journeys_summary()


summary = asyncio.run(seed())
shown = {k: v for k, v in summary.items() if k not in ("total", "quiet_after_days")}
# The strip claims to be a breakdown. Ship a shot where that is visibly true.
assert sum(shown.values()) == summary["total"], summary
print("summary:", json.dumps(summary))

from playwright.sync_api import sync_playwright  # noqa: E402

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(
        viewport={"width": 1280, "height": 800},
        device_scale_factor=2,
        color_scheme="dark",
    )
    page.route(
        "**/api/journeys/summary",
        lambda route: route.fulfill(
            content_type="application/json", body=json.dumps(summary)
        ),
    )
    # Only read for the pending-suggestion dot; an empty one keeps the nav clean.
    page.route(
        "**/api/profiles",
        lambda route: route.fulfill(
            content_type="application/json",
            body=json.dumps({"profiles": [
                {"profile_id": "p1", "name": "Demo", "pending_suggestion_count": 0}
            ]}),
        ),
    )
    page.goto("http://localhost:3000/", wait_until="networkidle")
    page.wait_for_selector("text=Application overview", timeout=10_000)
    page.wait_for_timeout(600)
    page.screenshot(path=str(OUT), full_page=True)
    browser.close()

DEMO_DB.unlink(missing_ok=True)
print("wrote", OUT.relative_to(ROOT))
