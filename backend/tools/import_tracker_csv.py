"""One-off importer for the hand-kept application spreadsheet.

Maps the sheet's columns onto journeys, interview rounds and events:

    Title / Company / Location      -> job_journeys
    Submission                      -> applied_at
    On Hold / Rejection / Offer     -> on_hold_at / rejected_at / offer_at
    Dropped out                     -> dropped_at
    Follow-up Message               -> a follow_up event
    …Interview / Case Study columns -> job_interviews rows, dated
    Events                          -> job_events, one per dated line
    Notes                           -> notes
    Status                          -> discarded; the dates regenerate it

Dry run by default — nothing is written until you pass --commit. Re-running is
safe: rows are matched on company + title, existing values are never
overwritten, and duplicate rounds and events are skipped.

    uv run python -m backend.tools.import_tracker_csv sheet.csv --profile "Head of Data"
    uv run python -m backend.tools.import_tracker_csv sheet.csv --profile "Head of Data" --commit
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.storage.db import init_db
from backend.storage.events import add_event, list_events
from backend.storage.interviews import create_interview, list_interviews
from backend.storage.journeys import (
    create_journey,
    derive_status,
    list_journeys,
    update_journey,
)
from backend.storage.profiles import list_profiles

# Header -> journey field. Headers are matched lowercased with runs of
# non-alphanumerics collapsed to one space, so "Follow-up Message" and
# "follow up message" both land here.
TEXT_COLUMNS = {
    "title": "job_title",
    "job title": "job_title",
    "company": "company_name",
    "location": "location",
    "url": "job_url",
    "job url": "job_url",
    "link": "job_url",
    "notes": "notes",
}

DATE_COLUMNS = {
    "submission": "applied_at",
    "submitted": "applied_at",
    "applied": "applied_at",
    "on hold": "on_hold_at",
    "rejection": "rejected_at",
    "rejected": "rejected_at",
    "offer": "offer_at",
    "dropped": "dropped_at",
    "dropped out": "dropped_at",
    "withdrawn": "dropped_at",
}

# Header -> (interview_type, round label).
ROUND_COLUMNS = {
    "recruiter interview": ("recruiter", ""),
    "screening interview": ("screening", ""),
    "hiring manager interview": ("hiring_manager", ""),
    "technical interview": ("technical", ""),
    "leadership interview": ("leadership", ""),
    "panel interview": ("panel", ""),
    "team interview": ("team_peer", ""),
    "final interview": ("final", ""),
    "final round": ("final", ""),
    "case study": ("case_study", ""),
    "case study presentation": ("case_study", "Presentation"),
}

STATUS_FALLBACK_DATE = {
    "dropped": "dropped_at",
    "dropped out": "dropped_at",
    "withdrawn": "dropped_at",
    "on hold": "on_hold_at",
    "rejected": "rejected_at",
    "offer": "offer_at",
}

_DATE_FORMATS = ("%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%d/%m/%y", "%m/%d/%Y")
_LEADING_DATE = re.compile(r"^\s*(\d{1,2}[./]\d{1,2}[./]\d{2,4})\s*[-–:]?\s*(.*)$")


def normalise(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (header or "").lower()).strip()


def parse_date(raw: str) -> float | None:
    """The sheet is European (dd/mm/yyyy). Noon local, so no timezone can shift
    the day."""
    text = (raw or "").strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            d = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return d.replace(hour=12, minute=0, second=0, microsecond=0).timestamp()
    return None


def parse_events(cell: str) -> tuple[list[tuple[float, str]], list[str]]:
    """Split the Events cell into dated events and leftover prose.

    Lines starting with a date become events. Anything else is returned so the
    caller can fold it into the notes rather than dropping it.
    """
    dated: list[tuple[float, str]] = []
    loose: list[str] = []
    for line in (cell or "").splitlines():
        if not line.strip():
            continue
        match = _LEADING_DATE.match(line)
        when = parse_date(match.group(1)) if match else None
        if match and when is not None and match.group(2).strip():
            dated.append((when, match.group(2).strip()))
        else:
            loose.append(line.strip())
    return dated, loose


@dataclass
class RowPlan:
    title: str
    company: str
    action: str = "create"  # create | merge | skip
    reason: str = ""
    journey_id: str = ""
    fields: dict[str, Any] = field(default_factory=dict)
    rounds: list[tuple[str, str, float]] = field(default_factory=list)
    events: list[tuple[float, str]] = field(default_factory=list)
    inferred: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status: str = ""


def _key(text: str) -> str:
    return (text or "").strip().lower()


def match_journey(
    index: list[dict[str, Any]], company: str, title: str
) -> tuple[dict[str, Any] | None, str]:
    """Find the journey this sheet row is about.

    Titles are hand-typed in the sheet and scraped in the app ("Head of Data
    Science and Analytics" vs "Head of Analytics and Data Science (f/m/d)"), so
    an exact title match almost never fires. When a company has exactly one
    journey, that is the row — matched on company alone and reported, so the
    dry run can be eyeballed. When a company has several, only an exact title
    is trusted; anything else is left to create and flagged.
    """
    same_company = [j for j in index if _key(j["company_name"]) == _key(company)]
    if not same_company:
        return None, ""

    exact = [j for j in same_company if _key(j["job_title"]) == _key(title)]
    if exact:
        return exact[0], "exact"
    if len(same_company) == 1:
        return same_company[0], "company"
    return None, "ambiguous"


def _fmt(ts: float | None) -> str:
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y") if ts else "—"


async def plan_row(
    row: dict[str, str], profile_id: str, index: list[dict[str, Any]] | None = None
) -> RowPlan:
    text: dict[str, Any] = {}
    dates: dict[str, float] = {}
    rounds: list[tuple[str, str, float]] = []
    events: list[tuple[float, str]] = []
    loose_notes: list[str] = []
    status_cell = ""
    follow_ups: list[float] = []

    for header, raw in row.items():
        key = normalise(header)
        value = (raw or "").strip()
        if not key:
            continue

        if key == "status":
            status_cell = normalise(value)
        elif key in TEXT_COLUMNS:
            if value:
                text[TEXT_COLUMNS[key]] = value
        elif key in DATE_COLUMNS:
            when = parse_date(value)
            if when is not None:
                dates[DATE_COLUMNS[key]] = when
        elif key in ROUND_COLUMNS:
            when = parse_date(value)
            if when is not None:
                slug, label = ROUND_COLUMNS[key]
                rounds.append((slug, label, when))
        elif key in ("events", "event log"):
            dated, loose = parse_events(value)
            events.extend(dated)
            loose_notes.extend(loose)
        elif key in ("follow up message", "followup message", "follow up"):
            when = parse_date(value)
            if when is not None:
                follow_ups.append(when)

    title = text.get("job_title", "")
    company = text.get("company_name", "")
    plan = RowPlan(title=title, company=company)

    if not title and not company:
        plan.action = "skip"
        plan.reason = "no title and no company"
        return plan

    for when in follow_ups:
        events.append((when, "Sent a follow-up message."))

    if loose_notes:
        text["notes"] = "\n".join([text.get("notes", ""), *loose_notes]).strip()

    # A sheet row can say "Dropped" or "on hold" without a matching date column.
    # Nothing would regenerate that status, so anchor it to the row's latest
    # known date and report the inference for review.
    target = STATUS_FALLBACK_DATE.get(status_cell)
    if target and target not in dates:
        known = [*dates.values(), *(when for _, _, when in rounds)]
        if known:
            dates[target] = max(known)
            plan.inferred.append(
                f"status {status_cell!r} with no date column -> "
                f"{target} = {_fmt(dates[target])}"
            )

    if index is None:
        index = await list_journeys(profile_id=profile_id, limit=None)
    existing, how = match_journey(index, company, title)

    if how == "ambiguous":
        plan.warnings.append(
            f"{company!r} has several journeys and none match this title — "
            "creating a new one; merge by hand if that is wrong"
        )

    if existing:
        plan.action = "merge"
        plan.journey_id = existing["journey_id"]
        plan.reason = (
            f"matches {existing['journey_id'][:8]} on company alone — "
            f"app calls it {existing['job_title']!r}"
            if how == "company"
            else f"matches existing journey {existing['journey_id'][:8]}"
        )
        # Never overwrite something the app already knows.
        plan.fields = {
            f: v for f, v in {**text, **dates}.items() if not existing.get(f)
        }
        have = {(iv["interview_type"], iv["label"]) for iv in await list_interviews(existing["journey_id"])}
        plan.rounds = [r for r in rounds if (r[0], r[1]) not in have]
        seen = {(e["occurred_at"], e["text"]) for e in await list_events(existing["journey_id"])}
        plan.events = [e for e in events if e not in seen]
        merged = {**existing, **plan.fields}
    else:
        plan.fields = {**text, **dates}
        plan.rounds = rounds
        plan.events = events
        merged = plan.fields

    plan.status = derive_status(
        {k: merged.get(k) for k in
         ("applied_at", "on_hold_at", "rejected_at", "dropped_at", "offer_at")},
        [{"scheduled_at": when} for _, _, when in rounds],
    )
    return plan


async def apply_plan(plan: RowPlan, profile_id: str) -> str:
    if plan.journey_id:
        journey_id = plan.journey_id
        if plan.fields:
            await update_journey(journey_id, **plan.fields)
    else:
        journey_id = await create_journey(profile_id=profile_id, **plan.fields)

    for slug, label, when in plan.rounds:
        await create_interview(
            journey_id=journey_id,
            profile_id=profile_id,
            interview_type=slug,
            label=label,
            scheduled_at=when,
        )
    for when, text in plan.events:
        await add_event(journey_id=journey_id, occurred_at=when, text=text)
    return journey_id


async def resolve_profile(wanted: str) -> str:
    profiles = await list_profiles()
    if not profiles:
        sys.exit("No profiles exist — create one before importing.")
    for p in profiles:
        if p["profile_id"] == wanted or p["profile_id"].startswith(wanted):
            return p["profile_id"]
    matches = [p for p in profiles if p["name"].lower() == wanted.lower()]
    if len(matches) == 1:
        return matches[0]["profile_id"]
    names = ", ".join(f'{p["name"]!r} ({p["profile_id"][:8]})' for p in profiles)
    sys.exit(f"Could not resolve profile {wanted!r}. Available: {names}")


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return [row for row in csv.DictReader(fh)]


async def run(path: Path, wanted_profile: str, commit: bool) -> None:
    await init_db()
    profile_id = await resolve_profile(wanted_profile)

    rows = read_rows(path)
    # Loaded once and kept current, so two sheet rows for the same job do not
    # each create one.
    index = await list_journeys(profile_id=profile_id, limit=None)

    created = merged = skipped = 0
    warnings: list[str] = []

    for row in rows:
        plan = await plan_row(row, profile_id, index)
        if plan.action == "skip":
            skipped += 1
            continue
        if plan.action == "create":
            created += 1
        else:
            merged += 1

        head = f"{plan.action.upper():6} {plan.company or '—'} — {plan.title or '—'}"
        print(f"{head}  [{plan.status}]")
        if plan.reason:
            print(f"       {plan.reason}")
        dated = {k: v for k, v in plan.fields.items() if k.endswith("_at")}
        if dated:
            print("       dates: " + ", ".join(f"{k}={_fmt(v)}" for k, v in dated.items()))
        for slug, label, when in plan.rounds:
            print(f"       round: {slug}{f' ({label})' if label else ''} {_fmt(when)}")
        for when, text in plan.events:
            print(f"       event: {_fmt(when)} {text[:70]}")
        for note in plan.inferred:
            print(f"       inferred: {note}")
        for note in plan.warnings:
            print(f"       WARNING: {note}")
            warnings.append(f"{plan.company} — {plan.title}: {note}")

        if commit:
            journey_id = await apply_plan(plan, profile_id)
            if plan.action == "create":
                index.append(
                    {
                        "journey_id": journey_id,
                        "job_title": plan.title,
                        "company_name": plan.company,
                    }
                )

    print()
    print(f"{len(rows)} row(s) read: {created} to create, {merged} to merge, {skipped} skipped")
    if warnings:
        print(f"{len(warnings)} row(s) need a look — see WARNING above")
    print("COMMITTED." if commit else "Dry run — nothing written. Re-run with --commit.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path, help="the sheet exported as CSV")
    parser.add_argument("--profile", required=True, help="profile id or name to import into")
    parser.add_argument("--commit", action="store_true", help="actually write")
    args = parser.parse_args()

    if not args.csv_path.exists():
        sys.exit(f"No such file: {args.csv_path}")
    asyncio.run(run(args.csv_path, args.profile, args.commit))


if __name__ == "__main__":
    main()
