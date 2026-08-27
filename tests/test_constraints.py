"""Tests for typed constraint records.

The interesting cases are not "does the dataclass hold values". They are the ones
where a constraint would otherwise reach the solver looking perfectly well-formed
while meaning nothing: a daylight bound sourced from a web page, a date window that
lost its windows, a record naming a performer who does not exist.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import pytest

from coverset.actors import Actor, Role
from coverset.constraints import (
    AlgorithmSource,
    BlackoutDates,
    ConstraintError,
    ConstraintRecord,
    ConstraintSet,
    DateWindows,
    DaylightBound,
    DerivedFrom,
    Family,
    GroundedSource,
    HumanSource,
    MaximumDailyHours,
    MinimumRest,
    PinnedDay,
    Policy,
    Subject,
    SubjectKind,
    UnresolvedConstraints,
)
from coverset.people import AvailabilityWindow

AD = Actor("Dana Whitfield", Role.FIRST_AD)
D1 = dt.date(2026, 9, 14)
D2 = dt.date(2026, 9, 15)
WEEK = AvailabilityWindow(D1, dt.date(2026, 9, 20))


def cast_rule(**over) -> ConstraintRecord:
    return dataclasses.replace(
        ConstraintRecord(
            constraint_id="C-1",
            family=Family.CAST,
            policy=Policy.HARD,
            subject=Subject(SubjectKind.CAST, "SARAH"),
            expression=DateWindows((WEEK,)),
            source=HumanSource(AD, "Sarah is out until the 14th", from_fixture=True),
        ),
        **over,
    )


# -- CON-008: daylight provenance is unrepresentable, not merely checked ---------


@pytest.mark.req("CON-008")
def test_daylight_constraint_cannot_carry_a_url_source():
    """A retrieved sunset is not a daylight bound, whatever the record calls itself."""
    with pytest.raises(ConstraintError, match="deterministic algorithm"):
        ConstraintRecord(
            constraint_id="C-SUN",
            family=Family.DAYLIGHT,
            policy=Policy.HARD,
            subject=Subject(SubjectKind.SCHEDULE),
            expression=DaylightBound(),
            source=GroundedSource(
                evidence_id="ev-1",
                source_urls=("https://sunrise-sunset.org/us/savannah-ga",),
            ),
        )


@pytest.mark.req("CON-008")
def test_daylight_constraint_cites_the_algorithm_and_a_version():
    record = ConstraintRecord(
        constraint_id="C-SUN",
        family=Family.DAYLIGHT,
        policy=Policy.HARD,
        subject=Subject(SubjectKind.SCHEDULE),
        expression=DaylightBound(),
        source=AlgorithmSource(),
    )
    assert record.derived_from is DerivedFrom.ALGORITHM
    assert "NOAA" in record.source.describe()
    with pytest.raises(ConstraintError, match="version"):
        AlgorithmSource(version="")


@pytest.mark.req("CON-008")
def test_daylight_family_rejects_a_non_daylight_expression():
    with pytest.raises(ConstraintError, match="DaylightBound"):
        ConstraintRecord(
            constraint_id="C-SUN",
            family=Family.DAYLIGHT,
            policy=Policy.HARD,
            subject=Subject(SubjectKind.SCHEDULE),
            expression=MinimumRest(12),
            source=AlgorithmSource(),
        )


# -- CON-004: a record validates before it can enter a problem ------------------


@pytest.mark.req("CON-004")
def test_a_grounded_constraint_must_carry_at_least_one_url():
    with pytest.raises(ConstraintError, match="source URL"):
        GroundedSource(evidence_id="ev-1", source_urls=())


@pytest.mark.req("CON-004")
def test_an_empty_date_window_is_rejected_rather_than_read_as_unrestricted():
    """A window list that lost its contents would silently widen the feasible region."""
    with pytest.raises(ConstraintError, match="permit every day"):
        DateWindows(())
    with pytest.raises(ConstraintError, match="constrains nothing"):
        BlackoutDates(())


@pytest.mark.req("CON-004")
def test_a_subject_must_be_named_unless_the_constraint_is_schedule_wide():
    with pytest.raises(ConstraintError, match="must name its subject"):
        Subject(SubjectKind.CAST, "")
    with pytest.raises(ConstraintError, match="no specific subject"):
        Subject(SubjectKind.SCHEDULE, "SARAH")


@pytest.mark.req("CON-004")
def test_rest_and_daily_hour_bounds_are_distinct_types():
    """Opposite directions, so a single flag read the wrong way inverts the bound."""
    assert MinimumRest(12).minutes == 720
    assert MaximumDailyHours(12).minutes == 720
    assert "at least" in str(MinimumRest(12))
    assert "at most" in str(MaximumDailyHours(12))
    with pytest.raises(ConstraintError):
        MinimumRest(0)
    with pytest.raises(ConstraintError):
        MaximumDailyHours(25)


@pytest.mark.req("CON-004")
def test_a_human_constraint_records_what_was_actually_stated():
    with pytest.raises(ConstraintError, match="what was actually stated"):
        HumanSource(AD, "   ")
    assert HumanSource(AD, "no Sundays").derived_from is DerivedFrom.HUMAN_INPUT
    assert HumanSource(AD, "no Sundays", from_fixture=True).derived_from is DerivedFrom.FIXTURE


# -- CON-005: unresolved references block the solve -----------------------------


@pytest.mark.req("CON-005")
def test_unknown_references_are_all_reported_together():
    records = ConstraintSet((
        cast_rule(constraint_id="C-1", subject=Subject(SubjectKind.CAST, "SARA")),
        cast_rule(
            constraint_id="C-2",
            family=Family.LOCATION,
            subject=Subject(SubjectKind.LOCATION, "no-such-place"),
        ),
        cast_rule(
            constraint_id="C-3",
            family=Family.LOCK,
            subject=Subject(SubjectKind.WORK, "W-404"),
            expression=PinnedDay(D1),
        ),
    ))
    with pytest.raises(UnresolvedConstraints) as excinfo:
        records.resolve(
            cast_ids=frozenset({"SARAH"}),
            location_ids=frozenset({"studio"}),
            work_ids=frozenset({"W-1"}),
            calendar=(D1, D2),
        )
    assert len(excinfo.value.problems) == 3
    assert {"C-1", "C-2", "C-3"} <= {p.split(":")[0] for p in excinfo.value.problems}


@pytest.mark.req("CON-005")
def test_a_typo_in_a_cast_id_blocks_solving_rather_than_silently_applying_to_nobody():
    """`SARA` for `SARAH` is this project's canonical silent failure."""
    records = ConstraintSet((cast_rule(subject=Subject(SubjectKind.CAST, "SARA")),))
    with pytest.raises(UnresolvedConstraints, match="SARA"):
        records.resolve(
            cast_ids=frozenset({"SARAH"}),
            location_ids=frozenset(),
            work_ids=frozenset(),
        )


@pytest.mark.req("CON-005")
def test_a_window_excluding_every_calendar_day_is_reported():
    far_off = AvailabilityWindow(dt.date(2027, 1, 1), dt.date(2027, 1, 5))
    records = ConstraintSet((cast_rule(expression=DateWindows((far_off,))),))
    with pytest.raises(UnresolvedConstraints, match="excludes every day"):
        records.resolve(
            cast_ids=frozenset({"SARAH"}),
            location_ids=frozenset(),
            work_ids=frozenset(),
            calendar=(D1, D2),
        )


@pytest.mark.req("CON-005")
def test_an_inactive_constraint_is_not_resolved():
    """Deactivated records describe past boards; they must not block a new solve."""
    records = ConstraintSet((cast_rule(subject=Subject(SubjectKind.CAST, "GONE")).deactivate(),))
    records.resolve(
        cast_ids=frozenset({"SARAH"}), location_ids=frozenset(), work_ids=frozenset()
    )


@pytest.mark.req("CON-005")
def test_deactivation_returns_a_new_record_and_leaves_the_original_binding():
    original = cast_rule()
    assert original.binds
    assert not original.deactivate().binds
    assert original.binds, "the record that bound a past board must survive to explain it"


# -- AUD-005: the constraint snapshot hash --------------------------------------


@pytest.mark.req("AUD-005")
def test_the_snapshot_hash_is_stable_across_ordering():
    a = cast_rule(constraint_id="C-A")
    b = cast_rule(constraint_id="C-B", subject=Subject(SubjectKind.CAST, "TOM"))
    assert ConstraintSet((a, b)).snapshot_hash == ConstraintSet((b, a)).snapshot_hash


@pytest.mark.req("AUD-005")
def test_the_snapshot_hash_changes_when_a_bound_changes():
    base = ConstraintSet((cast_rule(),))
    widened = ConstraintSet((
        cast_rule(expression=DateWindows((AvailabilityWindow(D1, dt.date(2026, 9, 30)),))),
    ))
    deactivated = ConstraintSet((cast_rule().deactivate(),))
    assert base.snapshot_hash != widened.snapshot_hash
    assert base.snapshot_hash != deactivated.snapshot_hash


@pytest.mark.req("AUD-005")
def test_a_constraint_set_rejects_duplicate_ids():
    with pytest.raises(ConstraintError, match="duplicate"):
        ConstraintSet((cast_rule(), cast_rule()))


@pytest.mark.req("AUD-005")
def test_binding_excludes_advisory_and_informational_policies():
    hard = cast_rule(constraint_id="C-H", policy=Policy.HARD)
    waivable = cast_rule(constraint_id="C-W", policy=Policy.WAIVABLE_BY_ROLE)
    soft = cast_rule(constraint_id="C-S", policy=Policy.SOFT_PENALTY)
    info = cast_rule(constraint_id="C-I", policy=Policy.INFORMATIONAL)
    records = ConstraintSet((hard, waivable, soft, info))
    assert {r.constraint_id for r in records.binding} == {"C-H", "C-W"}
    assert not Policy.INFORMATIONAL.reaches_solver
