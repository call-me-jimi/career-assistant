"""Best-effort full-page screenshot of a job posting.

Job pages are frequently taken offline once a role is filled. We render the
live page with a headless Chromium and store a PNG so the original posting
stays viewable after the URL dies. Capture is best-effort: any failure returns
None and the calling flow continues with the already-persisted job text.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from backend.config import DATA_DIR

log = logging.getLogger("assistant.screenshot")

SCREENSHOT_DIR = DATA_DIR / "screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

# Hard ceiling so a slow/hanging page never stalls the collect_job node.
_TIMEOUT_S = 25.0
_NAV_TIMEOUT_MS = 20_000
_VIEWPORT = {"width": 1280, "height": 1024}


async def _render(url: str, dest: Path) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport=_VIEWPORT)
            await page.goto(url, wait_until="networkidle", timeout=_NAV_TIMEOUT_MS)
            await page.screenshot(path=str(dest), full_page=True)
        finally:
            await browser.close()


async def capture_screenshot(url: str, *, name_hint: str = "") -> str | None:
    """Render ``url`` to a PNG under SCREENSHOT_DIR.

    Returns the filename (relative to SCREENSHOT_DIR) on success, or None on any
    failure. Never raises — job collection must survive a capture failure.
    """
    prefix = "".join(c for c in name_hint if c.isalnum())[:40] or "job"
    filename = f"{prefix}_{uuid.uuid4().hex}.png"
    dest = SCREENSHOT_DIR / filename
    try:
        await asyncio.wait_for(_render(url, dest), timeout=_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 — best-effort, log and move on
        log.warning("screenshot capture failed for %s: %s", url, exc)
        dest.unlink(missing_ok=True)
        return None
    log.info("captured screenshot for %s -> %s", url, filename)
    return filename
