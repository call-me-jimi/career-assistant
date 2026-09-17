"""The status ladder. derive_status is a pure function over six dates, so it
tests without a database."""

from backend.storage.journeys import STATUSES, derive_status

DAY = 86_400.0


def _journey(**dates) -> dict:
    base = {
        "applied_at": None,
        "on_hold_at": None,
        "rejected_at": None,
        "dropped_at": None,
        "offer_at": None,
    }
    return {**base, **dates}


def _round(scheduled_at: float | None) -> dict:
    return {"interview_id": "i1", "scheduled_at": scheduled_at}


# --- the seven rungs, in order ---------------------------------------------


def test_nothing_set_is_draft():
    assert derive_status(_journey(), []) == "draft"


def test_submission_alone_is_applied():
    assert derive_status(_journey(applied_at=DAY), []) == "applied"


def test_one_interview_date_is_in_progress():
    j = _journey(applied_at=DAY)
    assert derive_status(j, [_round(2 * DAY)]) == "in_progress"


def test_on_hold_date_is_on_hold():
    j = _journey(applied_at=DAY, on_hold_at=3 * DAY)
    assert derive_status(j, [_round(2 * DAY)]) == "on_hold"


def test_dropped_date_is_dropped():
    j = _journey(applied_at=DAY, dropped_at=2 * DAY)
    assert derive_status(j, []) == "dropped"


def test_offer_date_is_offer():
    j = _journey(applied_at=DAY, offer_at=5 * DAY)
    assert derive_status(j, [_round(2 * DAY)]) == "offer"


def test_rejection_date_is_rejected():
    j = _journey(applied_at=DAY, rejected_at=5 * DAY)
    assert derive_status(j, [_round(2 * DAY)]) == "rejected"


# --- precedence -------------------------------------------------------------


def test_rejection_is_terminal_and_outranks_everything():
    j = _journey(
        applied_at=DAY,
        on_hold_at=2 * DAY,
        dropped_at=3 * DAY,
        offer_at=4 * DAY,
        rejected_at=5 * DAY,
    )
    assert derive_status(j, [_round(9 * DAY)]) == "rejected"


def test_offer_outranks_dropped_and_hold():
    j = _journey(applied_at=DAY, on_hold_at=2 * DAY, dropped_at=3 * DAY, offer_at=4 * DAY)
    assert derive_status(j, []) == "offer"


def test_dropped_outranks_hold():
    j = _journey(applied_at=DAY, on_hold_at=2 * DAY, dropped_at=3 * DAY)
    assert derive_status(j, []) == "dropped"


# --- the hold/round judgement call -----------------------------------------


def test_round_dated_after_the_hold_lifts_it():
    """A hold 'might continue at a later time' — a later round says it did."""
    j = _journey(applied_at=DAY, on_hold_at=3 * DAY)
    assert derive_status(j, [_round(2 * DAY), _round(4 * DAY)]) == "in_progress"


def test_round_dated_before_the_hold_leaves_it_on_hold():
    j = _journey(applied_at=DAY, on_hold_at=5 * DAY)
    assert derive_status(j, [_round(2 * DAY), _round(4 * DAY)]) == "on_hold"


def test_round_on_the_same_day_as_the_hold_stays_on_hold():
    j = _journey(applied_at=DAY, on_hold_at=3 * DAY)
    assert derive_status(j, [_round(3 * DAY)]) == "on_hold"


def test_clearing_the_hold_returns_to_in_progress():
    j = _journey(applied_at=DAY, on_hold_at=5 * DAY)
    rounds = [_round(2 * DAY)]
    assert derive_status(j, rounds) == "on_hold"

    j["on_hold_at"] = None
    assert derive_status(j, rounds) == "in_progress"


# --- rounds without dates ---------------------------------------------------


def test_undated_rounds_do_not_make_it_in_progress():
    """A round created by a graph always carries a date, but a hand-added one
    may not — an undated round is not evidence an interview happened."""
    j = _journey(applied_at=DAY)
    assert derive_status(j, [_round(None)]) == "applied"


def test_undated_round_alongside_a_dated_one_is_ignored():
    j = _journey(applied_at=DAY, on_hold_at=5 * DAY)
    assert derive_status(j, [_round(None), _round(2 * DAY)]) == "on_hold"


def test_hold_with_only_undated_rounds_is_on_hold():
    j = _journey(applied_at=DAY, on_hold_at=3 * DAY)
    assert derive_status(j, [_round(None)]) == "on_hold"


# --- interviewed but never marked as applied -------------------------------


def test_interview_without_submission_date_still_reads_in_progress():
    assert derive_status(_journey(), [_round(2 * DAY)]) == "in_progress"


def test_every_returned_status_is_declared():
    cases = [
        (_journey(), []),
        (_journey(applied_at=DAY), []),
        (_journey(applied_at=DAY), [_round(2 * DAY)]),
        (_journey(on_hold_at=DAY), []),
        (_journey(offer_at=DAY), []),
        (_journey(rejected_at=DAY), []),
        (_journey(dropped_at=DAY), []),
    ]
    assert {derive_status(j, rounds) for j, rounds in cases} == set(STATUSES)
