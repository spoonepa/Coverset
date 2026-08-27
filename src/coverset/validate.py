"""Independent validation of a finished board.

CP-SAT proves that its solution satisfies the model it was handed. It cannot prove
that the model was the production's problem. Every constraint reaches the solver
through a compiler, and a compiler that drops a term, inverts a bound or applies a
window to the wrong subject produces a board the solver will certify as optimal.
That failure is silent, well-formed and expensive (`NNG-003`, `SOL-007`).

So every binding constraint is read twice, by two pieces of code that share nothing
but the record itself:

- `solver.py` turns a `ConstraintRecord` into CP-SAT variables and clauses;
- this module turns the same record into a question about dates and times on a
  finished board, and answers it in plain Python.

**This module must never import `solver` or `ortools`.** That is the whole mechanism.
A validator that reuses the compiler is checking a method against another instance of
itself, which is the mistake `daylight.py` documents: computed daylight is validated
against published almanac tables, not against a second retrieval. A test asserts the
absence of those imports, because this is exactly the property a well-meaning
refactor removes.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from .board import Assignment, ConstraintCheck, ShootDay, ValidationReport
from .clock import elapsed
from .constraints import (
    BlackoutDates,
    ConstraintRecord,
    ConstraintSet,
    DateWindows,
    DaylightBound,
    Family,
    MaximumDailyHours,
    MinimumRest,
    PinnedDay,
    SubjectKind,
)
from .daylight import SunCondition, daylight_window
from .locations import LocationBook
from .people import Engagement, Roster
from .work import WorkItem

__all__ = ["UncheckableConstraint", "validate_board"]


class UncheckableConstraint(Exception):
    """A binding constraint has no independent check, so no board can be trusted.

    Raised rather than skipped. A constraint the validator does not know how to read
    is one that would pass silently, and a report that quietly omits it is worse than
    no report: it certifies a board nobody examined. Adding a constraint shape to the
    compiler without adding it here is meant to fail loudly here.
    """


def _days_of(assignments: tuple[Assignment, ...]) -> tuple[ShootDay, ...]:
    by_date: dict[dt.date, list[Assignment]] = defaultdict(list)
    for a in assignments:
        by_date[a.shoot_day].append(a)
    return tuple(ShootDay(date=d, assignments=tuple(by_date[d])) for d in sorted(by_date))


def validate_board(
    assignments: tuple[Assignment, ...],
    *,
    constraints: ConstraintSet,
    work_items: tuple[WorkItem, ...],
    locations: LocationBook,
    roster: Roster,
) -> ValidationReport:
    """Re-check every binding constraint against `assignments`, from the records alone.

    Returns a report naming each constraint and whether the board satisfies it. Every
    binding constraint is listed in `expected_ids`, so a report that skipped one
    cannot be constructed.

    Raises:
        UncheckableConstraint: a binding constraint has a shape this validator cannot
            evaluate, so the board cannot be certified either way.
    """
    work_by_id = {w.work_id: w for w in work_items}
    placed = {a.work_id: a for a in assignments}
    days = _days_of(assignments)
    checks: list[ConstraintCheck] = []

    def record(r: ConstraintRecord, satisfied: bool, detail: str = "") -> None:
        checks.append(
            ConstraintCheck(
                constraint_id=r.constraint_id,
                family=r.family,
                policy=r.policy,
                satisfied=satisfied,
                detail=detail,
            )
        )

    def work_touching_cast(cast_id: str) -> list[Assignment]:
        return [
            a for a in assignments
            if cast_id in work_by_id[a.work_id].cast_ids
        ]

    for r in constraints.binding:
        expr = r.expression

        # -- date windows and blackouts: cast availability, permits ---------------
        if isinstance(expr, (DateWindows, BlackoutDates)):
            if r.subject.kind is SubjectKind.CAST:
                affected = work_touching_cast(r.subject.ref)
            elif r.subject.kind is SubjectKind.LOCATION:
                affected = [a for a in assignments if a.location_id == r.subject.ref]
            elif r.subject.kind is SubjectKind.WORK:
                affected = [a for a in assignments if a.work_id == r.subject.ref]
            else:
                raise UncheckableConstraint(
                    f"{r.constraint_id}: a {type(expr).__name__} on subject kind "
                    f"{r.subject.kind} has no defined independent check"
                )
            bad = [a for a in affected if not expr.allows(a.shoot_day)]
            record(
                r,
                not bad,
                "" if not bad else
                f"{r.subject} is scheduled outside {expr} on "
                + ", ".join(sorted({a.shoot_day.isoformat() for a in bad})),
            )
            continue

        # -- pinned days: locks, fixed external dates -----------------------------
        if isinstance(expr, PinnedDay):
            if r.subject.kind is not SubjectKind.WORK:
                raise UncheckableConstraint(
                    f"{r.constraint_id}: a pinned day must name the work it pins, "
                    f"got subject kind {r.subject.kind}"
                )
            a = placed.get(r.subject.ref)
            if a is None:
                record(r, False, f"{r.subject.ref} is pinned to {expr.day} but is not on the board")
            else:
                record(
                    r,
                    a.shoot_day == expr.day,
                    "" if a.shoot_day == expr.day else
                    f"{r.subject.ref} sits on {a.shoot_day.isoformat()}, pinned to "
                    f"{expr.day.isoformat()}",
                )
            continue

        # -- daylight: recomputed here, never read off the board ------------------
        if isinstance(expr, DaylightBound):
            problems: list[str] = []
            for a in assignments:
                item = work_by_id[a.work_id]
                if not item.needs_daylight:
                    continue
                if r.subject.kind is SubjectKind.LOCATION and a.location_id != r.subject.ref:
                    continue
                if r.subject.kind is SubjectKind.WORK and a.work_id != r.subject.ref:
                    continue
                loc = locations[a.location_id]
                if not loc.is_locatable:
                    problems.append(
                        f"{a.work_id} needs daylight at {loc.name}, which has no "
                        f"coordinates, so the bound cannot be checked"
                    )
                    continue
                # Recomputed from the assignment's own date. Reusing a window stored
                # at solve time would re-admit the original bug: a sunset correct for
                # some other date (DAY-008).
                window = daylight_window(loc, a.shoot_day)
                if window.condition is not SunCondition.NORMAL:
                    problems.append(
                        f"{a.work_id} needs daylight on {a.shoot_day.isoformat()} at "
                        f"{loc.name}, which is in {window.condition}"
                    )
                    continue
                sunrise, sunset = window.exterior_day_window  # type: ignore[misc]
                if a.planned_call_time < sunrise or a.planned_wrap_time > sunset:
                    problems.append(
                        f"{a.work_id} runs {a.planned_call_time:%H:%M}-"
                        f"{a.planned_wrap_time:%H:%M} on {a.shoot_day.isoformat()}, "
                        f"outside daylight {sunrise:%H:%M}-{sunset:%H:%M} at {loc.name}"
                    )
            record(r, not problems, "; ".join(problems))
            continue

        # -- maximum daily hours: company day length, minor limits ----------------
        if isinstance(expr, MaximumDailyHours):
            problems = []
            for day in days:
                if r.subject.kind is SubjectKind.CAST:
                    on_day = [
                        a for a in day
                        if r.subject.ref in work_by_id[a.work_id].cast_ids
                    ]
                    if not on_day:
                        continue
                    worked = elapsed(
                        min(a.planned_call_time for a in on_day),
                        max(a.planned_wrap_time for a in on_day),
                    )
                elif r.subject.kind is SubjectKind.SCHEDULE:
                    worked = day.length
                else:
                    raise UncheckableConstraint(
                        f"{r.constraint_id}: a daily-hours limit on subject kind "
                        f"{r.subject.kind} has no defined independent check"
                    )
                if worked > dt.timedelta(minutes=expr.minutes):
                    problems.append(
                        f"{day.date.isoformat()} runs {worked.total_seconds() / 3600:.2f}h "
                        f"against a limit of {expr.hours:g}h"
                    )
            record(r, not problems, "; ".join(problems))
            continue

        # -- minimum rest between consecutive shooting days -----------------------
        if isinstance(expr, MinimumRest):
            problems = []
            for earlier, later in zip(days, days[1:], strict=False):
                if r.subject.kind is SubjectKind.CAST:
                    prev = [a for a in earlier if r.subject.ref in work_by_id[a.work_id].cast_ids]
                    nxt = [a for a in later if r.subject.ref in work_by_id[a.work_id].cast_ids]
                    if not prev or not nxt:
                        continue
                    wrap = max(a.planned_wrap_time for a in prev)
                    call = min(a.planned_call_time for a in nxt)
                elif r.subject.kind is SubjectKind.SCHEDULE:
                    wrap, call = earlier.wrap_time, later.call_time
                    if wrap is None or call is None:
                        continue
                else:
                    raise UncheckableConstraint(
                        f"{r.constraint_id}: a rest bound on subject kind "
                        f"{r.subject.kind} has no defined independent check"
                    )
                rest = elapsed(wrap, call).total_seconds() / 3600
                if rest < expr.hours:
                    problems.append(
                        f"{rest:.2f}h between {earlier.date.isoformat()} wrap and "
                        f"{later.date.isoformat()} call, against {expr.hours:g}h"
                    )
            record(r, not problems, "; ".join(problems))
            continue

        raise UncheckableConstraint(
            f"{r.constraint_id}: no independent check exists for a "
            f"{type(expr).__name__} in family {r.family}. Refusing to certify a board "
            f"against a constraint nobody re-read."
        )

    return ValidationReport(
        checks=tuple(checks),
        expected_ids=frozenset(r.constraint_id for r in constraints.binding),
        constraint_snapshot_hash=constraints.snapshot_hash,
    )


def holding_days(
    assignments: tuple[Assignment, ...],
    *,
    work_items: tuple[WorkItem, ...],
    roster: Roster,
) -> dict[str, int]:
    """Held-but-paid days per performer, computed from the board (`CST-004`).

    Reuses `Engagement`, which already owns this arithmetic. Lives here rather than
    in the solver so the reported cost is measured off the finished board rather than
    read back out of the model that produced it.
    """
    work_by_id = {w.work_id: w for w in work_items}
    days_by_cast: dict[str, set[dt.date]] = defaultdict(set)
    for a in assignments:
        for cast_id in work_by_id[a.work_id].cast_ids:
            days_by_cast[cast_id].add(a.shoot_day)
    return {
        cast_id: Engagement(member=roster[cast_id], work_days=tuple(sorted(days))).held_days
        for cast_id, days in days_by_cast.items()
    }
