"""Stripboard output, and why each strip sits where it does.

Two things an AD needs from a board, and they are the same artifact seen twice:

- **What is the plan** — days, ordered work, scenes, locations, day/night, cast, and
  the call and wrap windows those imply (`OUT-003`).
- **Why is this the plan** — for any strip, the active constraints that bounded where
  it could go and the objective terms that decided where it went (`AUD-001`).

The second is not a nicety. A board an AD cannot interrogate is one they have to
either accept on faith or throw away, and a scheduling tool that cannot say *why*
loses the argument with a producer who wants Tuesday.

Nothing here re-derives a bound. Both views read the same `ConstraintRecord`s the
solver was given and the same `Board` it produced, so the explanation cannot drift
from the schedule it explains.
"""

from __future__ import annotations

import datetime as dt

from .board import Board
from .constraints import (
    BlackoutDates,
    ConstraintRecord,
    ConstraintSet,
    DateWindows,
    DaylightBound,
    MaximumDailyHours,
    MinimumRest,
    PinnedDay,
    SubjectKind,
)
from .locations import LocationBook
from .people import Roster
from .work import WorkItem

__all__ = ["explain_assignment", "stripboard"]


def _cast_names(roster: Roster, cast_ids: tuple[str, ...]) -> str:
    if not cast_ids:
        return "—"
    return ", ".join(roster[c].character for c in sorted(cast_ids))


def stripboard(
    board: Board,
    *,
    work_items: tuple[WorkItem, ...],
    locations: LocationBook,
    roster: Roster,
) -> str:
    """Render the board as a stripboard an AD can read (`OUT-003`).

    Days in order, work in shooting order within the day, and the call/wrap window
    each strip implies. Characters rather than cast ids, because the ids exist to be
    unambiguous to the machine and the names exist to be unambiguous to a person.
    """
    work_by_id = {w.work_id: w for w in work_items}
    lines: list[str] = [
        f"STRIPBOARD  {board.schedule_version_id}",
        f"  {board.shoot_day_count} shoot day(s), {len(board.assignments)} strip(s)"
        f"  ·  {board.solver_status}  ·  cost {board.cost_bracket}",
        f"  weights: {board.objective_weights or 'unrecorded'}",
        f"  constraints: {board.constraint_snapshot_hash[:12]}  ·  {board.solver_parameters}",
        "",
    ]
    for day in board.days:
        call, wrap = day.call_time, day.wrap_time
        assert call is not None and wrap is not None  # a ShootDay on a board is non-empty
        lines.append(
            f"{day.date:%a %d %b %Y}   call {call:%H:%M}  wrap {wrap:%H:%M}  "
            f"({day.length.total_seconds() / 3600:.1f}h)"
            + (f"  ·  {day.company_moves} move(s)" if day.company_moves else "")
        )
        for a in day:
            item = work_by_id[a.work_id]
            lines.append(
                f"   {a.sequence + 1}. sc {item.scene_id:<6} "
                f"{str(item.day_night).upper():<5} "
                f"{locations[a.location_id].name:<26} "
                f"{a.planned_call_time:%H:%M}-{a.planned_wrap_time:%H:%M} "
                f"{item.estimated_duration_minutes:>4}m  "
                f"cast: {_cast_names(roster, item.cast_ids)}"
                + ("  [daylight]" if item.needs_daylight else "")
                + (f"  [{item.flags}]" if item.flags.any_set else "")
            )
        lines.append("")

    lines.append("COST")
    lines.extend(f"   {line}" for line in board.objective_breakdown.lines())
    if not board.is_proven_optimal:
        # Without this an AD reads two options as meaningfully different when the
        # solver may simply not have looked long enough to tell them apart.
        lines.append(
            f"   NOT PROVEN OPTIMAL — may be up to {board.optimality_gap:.1%} worse "
            f"than the best possible board"
        )
    lines.append(f"   validation: {board.validation_result.summary()}")
    return "\n".join(lines)


def _bounds(record: ConstraintRecord, item: WorkItem, day: dt.date) -> str | None:
    """How this record bore on this item, in the AD's terms, or None if it did not."""
    expr = record.expression
    subject = record.subject

    def about_this_item() -> bool:
        if subject.kind is SubjectKind.SCHEDULE:
            return True
        if subject.kind is SubjectKind.CAST:
            return subject.ref in item.cast_ids
        if subject.kind is SubjectKind.LOCATION:
            return subject.ref == item.location_id
        if subject.kind is SubjectKind.WORK:
            return subject.ref == item.work_id
        return False

    if not about_this_item():
        return None
    if isinstance(expr, (DateWindows, BlackoutDates)):
        verdict = "allows" if expr.allows(day) else "FORBIDS"
        return f"{verdict} {day.isoformat()} — {subject} {expr}"
    if isinstance(expr, PinnedDay):
        return f"pins to {expr.day.isoformat()}"
    if isinstance(expr, DaylightBound):
        if not item.needs_daylight:
            return None
        return f"bounds the strip inside the computed daylight window ({expr.algorithm})"
    if isinstance(expr, MaximumDailyHours):
        return f"caps the day at {expr.hours:g}h for {subject}"
    if isinstance(expr, MinimumRest):
        return f"requires {expr.hours:g}h between wrap and next call for {subject}"
    return None


def explain_assignment(
    board: Board,
    work_id: str,
    *,
    constraints: ConstraintSet,
    work_items: tuple[WorkItem, ...],
) -> str:
    """Trace one strip back to the constraints and objective terms that decided it.

    Every line names an active record by id, so the answer to "why is this on
    Tuesday" is a list of things someone can go and change, not a rationalisation
    produced after the fact (`AUD-001`).
    """
    work_by_id = {w.work_id: w for w in work_items}
    if work_id not in work_by_id:
        raise KeyError(f"{work_id} is not in this problem")
    item = work_by_id[work_id]
    day = board.day_of(work_id)
    assignment = next(a for a in board.assignments if a.work_id == work_id)

    lines = [
        f"{work_id} (scene {item.scene_id}) is on {day:%a %d %b %Y} at "
        f"{assignment.location_id}, {assignment.planned_call_time:%H:%M}–"
        f"{assignment.planned_wrap_time:%H:%M}.",
        "",
        "Bounded by:",
    ]
    bounding = [
        (r, why)
        for r in constraints.active
        if (why := _bounds(r, item, day)) is not None
    ]
    if bounding:
        lines.extend(f"   {r.constraint_id} [{r.policy}] {why}" for r, why in bounding)
    else:
        lines.append("   nothing — no active constraint bears on this strip")

    lines += [
        "",
        "Chosen among the remaining days by these objective terms:",
        f"   company moves      weight in {board.objective_weights or 'unrecorded weights'}",
        f"   cast holding days  {item.cast_ids and ', '.join(sorted(item.cast_ids)) or '—'}",
        f"   overtime exposure  strip runs {item.estimated_duration_minutes}m",
        "",
        f"Board totals: " + " · ".join(board.objective_breakdown.lines()),
        f"Solved under {board.solver_parameters}; validated against constraint "
        f"snapshot {board.constraint_snapshot_hash[:12]}.",
    ]
    return "\n".join(lines)
