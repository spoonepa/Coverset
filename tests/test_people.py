"""Tests for cast and crew.

Cast are constraint family 1 and were, until this module existed, a tuple of bare
strings on a coverage item. The tests below mostly exist to hold two things: that a
misspelled cast id is caught rather than silently scheduling nobody, and that the
cost of holding a performer between their first and last day is visible, since that
is what the objective is meant to minimise.
"""

from __future__ import annotations

import datetime as dt

import pytest

from coverset.people import (
    DEFAULT_MINOR_MAX_WORK_HOURS,
    AvailabilityWindow,
    CastMember,
    Company,
    Engagement,
    Roster,
    UnknownCastMember,
)

FIRST_TWO_WEEKS = AvailabilityWindow(dt.date(2026, 3, 2), dt.date(2026, 3, 13))

SARAH = CastMember(
    id="SARAH", name="S. Idowu", character="Ruth",
    availability=(FIRST_TWO_WEEKS,), contracted_days=12,
)
MARCUS = CastMember(id="MARCUS", name="D. Whitfield", character="Elias")
TOBY = CastMember(id="TOBY", name="K. Brennan", character="Sam", is_minor=True)
ROSTER = Roster((SARAH, MARCUS, TOBY))


# --------------------------------------------------------------------------
# Typed entities, not names
# --------------------------------------------------------------------------


@pytest.mark.req("CST-001")
def test_a_cast_member_carries_performer_character_and_contract():
    assert SARAH.name == "S. Idowu"
    assert SARAH.character == "Ruth"
    assert SARAH.contracted_days == 12
    assert str(SARAH) == "S. Idowu as Ruth"


@pytest.mark.req("CST-002")
def test_an_unknown_cast_id_is_rejected_not_silently_scheduled():
    # "SARA" and "SARAH" are indistinguishable to a scheduler and differ by one
    # person. Left unchecked, the board calls nobody and never notices.
    with pytest.raises(UnknownCastMember, match="SARA"):
        ROSTER.resolve(("SARAH", "SARA"))


@pytest.mark.req("CST-002")
def test_every_unknown_id_is_reported_at_once():
    with pytest.raises(UnknownCastMember) as excinfo:
        ROSTER.resolve(("SARAH", "SARA", "MARCEL"))

    message = str(excinfo.value)
    assert "SARA" in message and "MARCEL" in message   # not just the first
    assert "SARAH" in message                          # known ids, to fix the typo


@pytest.mark.req("CST-002")
def test_resolving_known_ids_returns_the_performers():
    assert ROSTER.resolve(("SARAH", "MARCUS")) == (SARAH, MARCUS)


@pytest.mark.req("CST-002")
def test_a_roster_cannot_hold_the_same_id_twice():
    with pytest.raises(ValueError, match="duplicate cast id"):
        Roster((SARAH, SARAH))


# --------------------------------------------------------------------------
# Availability
# --------------------------------------------------------------------------


@pytest.mark.req("CST-003")
def test_a_performer_with_no_stated_availability_is_available_throughout():
    assert MARCUS.is_available_on(dt.date(2026, 3, 2))
    assert MARCUS.is_available_on(dt.date(2026, 12, 25))


@pytest.mark.req("CST-003")
@pytest.mark.parametrize(
    ("day", "available"),
    [
        (dt.date(2026, 3, 1), False),   # day before the window
        (dt.date(2026, 3, 2), True),    # inclusive start
        (dt.date(2026, 3, 13), True),   # inclusive end
        (dt.date(2026, 3, 14), False),  # day after
    ],
)
def test_availability_windows_are_inclusive_of_both_ends(day, available):
    assert SARAH.is_available_on(day) is available


@pytest.mark.req("CST-003")
def test_days_outside_every_window_are_reported():
    days = (dt.date(2026, 3, 10), dt.date(2026, 3, 20), dt.date(2026, 3, 21))

    assert SARAH.unavailable_among(days) == (dt.date(2026, 3, 20), dt.date(2026, 3, 21))


@pytest.mark.req("CST-003")
def test_a_window_cannot_end_before_it_starts():
    with pytest.raises(ValueError, match="ends before it starts"):
        AvailabilityWindow(dt.date(2026, 3, 13), dt.date(2026, 3, 2))


# --------------------------------------------------------------------------
# Holding days -- the cost the objective exists to minimise
# --------------------------------------------------------------------------


@pytest.mark.req("CST-004")
def test_a_performer_held_between_work_days_accrues_holding_days():
    # Three days of work scattered across ten days of engagement. The seven idle
    # days are paid, which is why scattering one actor's scenes is expensive even
    # when the number of days worked does not change.
    engagement = Engagement(SARAH, (dt.date(2026, 3, 3), dt.date(2026, 3, 4), dt.date(2026, 3, 12)))

    assert engagement.worked_days == 3
    assert engagement.span_days == 10
    assert engagement.held_days == 7


@pytest.mark.req("CST-004")
def test_consecutive_work_days_accrue_no_holding():
    engagement = Engagement(SARAH, (dt.date(2026, 3, 3), dt.date(2026, 3, 4), dt.date(2026, 3, 5)))

    assert engagement.held_days == 0


@pytest.mark.req("CST-004")
def test_a_performer_never_scheduled_costs_no_engagement_days():
    engagement = Engagement(MARCUS, ())

    assert (engagement.worked_days, engagement.span_days, engagement.held_days) == (0, 0, 0)


@pytest.mark.req("CST-004")
def test_duplicate_work_days_are_counted_once():
    day = dt.date(2026, 3, 3)

    assert Engagement(MARCUS, (day, day)).worked_days == 1


# --------------------------------------------------------------------------
# Contract economics
# --------------------------------------------------------------------------


@pytest.mark.req("CST-005")
def test_billable_days_fall_back_to_the_contracted_guarantee():
    # Two days of work against a twelve-day guarantee still bills twelve.
    engagement = Engagement(SARAH, (dt.date(2026, 3, 3), dt.date(2026, 3, 4)))

    assert engagement.billable_days == 12
    assert engagement.contract_overrun == 0


@pytest.mark.req("CST-005")
def test_an_engagement_longer_than_the_contract_is_new_money():
    # This is the brief's "burns 1 of Sarah's 12 contracted days" made checkable:
    # a thirteen-day span against a twelve-day guarantee costs one more day.
    engagement = Engagement(SARAH, (dt.date(2026, 3, 2), dt.date(2026, 3, 14)))

    assert engagement.span_days == 13
    assert engagement.billable_days == 13
    assert engagement.contract_overrun == 1


@pytest.mark.req("CST-005")
def test_an_uncontracted_performer_bills_their_engagement():
    engagement = Engagement(MARCUS, (dt.date(2026, 3, 3), dt.date(2026, 3, 5)))

    assert engagement.billable_days == 3
    assert engagement.contract_overrun == 0


@pytest.mark.req("CST-003", "CST-005")
def test_work_scheduled_outside_availability_is_reported_by_the_engagement():
    engagement = Engagement(SARAH, (dt.date(2026, 3, 10), dt.date(2026, 3, 20)))

    assert engagement.violates_availability == (dt.date(2026, 3, 20),)


@pytest.mark.req("CST-001")
def test_a_contracted_day_count_must_be_positive():
    with pytest.raises(ValueError, match="contracted days must be positive"):
        CastMember(id="X", name="N. One", character="Extra", contracted_days=0)


# --------------------------------------------------------------------------
# Minors and turnaround
# --------------------------------------------------------------------------


@pytest.mark.req("CST-006")
def test_a_minor_carries_a_restricted_working_day():
    assert TOBY.is_minor
    assert TOBY.max_work_hours_per_day == DEFAULT_MINOR_MAX_WORK_HOURS


@pytest.mark.req("CST-006")
def test_an_explicit_limit_for_a_minor_is_not_overridden():
    strict = CastMember(id="Y", name="A. Small", character="Child", is_minor=True,
                        max_work_hours_per_day=4.0)

    assert strict.max_work_hours_per_day == 4.0


@pytest.mark.req("CST-006")
def test_an_adult_has_no_default_daily_limit():
    assert MARCUS.max_work_hours_per_day is None


@pytest.mark.req("CST-007")
def test_cast_turnaround_defaults_longer_than_crew():
    # Cast rest minimums are typically longer than crew. Both are norms, not law.
    assert SARAH.minimum_turnaround_hours > Company().minimum_turnaround_hours


@pytest.mark.req("CST-007")
@pytest.mark.parametrize(
    ("wrap_hour", "call_hour", "satisfied"),
    [(22, 8, True), (22, 7, False), (23, 9, True), (23, 8, False)],
)
def test_crew_turnaround_measures_rest_between_wrap_and_next_call(
    wrap_hour, call_hour, satisfied
):
    company = Company(minimum_turnaround_hours=10.0)
    wrap = dt.datetime(2026, 3, 3, wrap_hour, 0)
    call = dt.datetime(2026, 3, 4, call_hour, 0)

    assert company.turnaround_satisfied(wrap, call) is satisfied
