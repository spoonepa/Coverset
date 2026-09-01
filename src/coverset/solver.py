"""CP-SAT scheduling.

No language model emits a schedule. Work items, typed constraints and declared
weights go in; a proven, independently validated board comes out, or an irreducible
explanation of why none exists.

What the solver is and is not trusted for:

- It is trusted to find an optimal solution *to the model it was given*.
- It is not trusted to have been given the right model. Every board it returns is
  re-checked by `validate.py`, which shares no code with the compiler here, and a
  board that fails that check is never constructed (`SOL-007`).
- It is not trusted to report infeasibility minimally. CP-SAT returns a *sufficient*
  set of assumptions, not a minimal one, so `SOL-003`'s irreducibility is established
  by a deletion filter that re-proves the conflict without each member in turn.

Two deliberate simplifications, stated rather than hidden:

- **A shoot day is a day shoot or a night shoot, never both.** Split days are
  post-MVP (SPEC section 3), and mixing them makes the day's timeline a piecewise
  function of the daylight window rather than a sum of durations.
- **Turnaround is compiled conservatively** from per-day anchor bounds, then checked
  exactly on the finished board. Over-tightening loses a board and says so; the exact
  check is what guarantees no board escapes with a real violation.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from fractions import Fraction

from ortools.sat.python import cp_model

from .board import (
    Assignment,
    Board,
    ObjectiveBreakdown,
    SolverStatus,
)
from .clock import advance, elapsed
from .constraints import (
    AlgorithmSource,
    BlackoutDates,
    ConstraintRecord,
    ConstraintSet,
    DateWindows,
    DaylightBound,
    Family,
    MaximumDailyHours,
    MinimumRest,
    PinnedDay,
    Policy,
    Subject,
    SubjectKind,
)
from .daylight import SunCondition, daylight_window
from .locations import Location, LocationBook
from .people import Company, Roster
from .validate import holding_days, validate_board
from .work import DayNight, WorkItem

__all__ = [
    "DECLARED_WEIGHTS",
    "ConflictSet",
    "ObjectiveWeights",
    "SYNTHETIC_DAYLIGHT_ID",
    "ProductionCalendar",
    "ScheduleProblem",
    "SolveResult",
    "SolverError",
    "UndeclaredWeight",
    "solve",
]

COMPANY_MOVE_MINUTES = 60
"""Shooting time a unit move consumes. A move is not only an objective term -- it
eats the day, which is why it appears in the day-length constraint as well."""

MINUTES_PER_DAY = 24 * 60

DEFAULT_CALL_HOUR = 7
"""Local call time for a day shoot with no daylight-bound work to anchor it."""

SYNTHETIC_COMPANY_DAY_ID = "SYN-COMPANY-DAY"
"""Id of the day-length record the solver adds when the production states a maximum
day and the constraint set does not. Named like `SYN-DAYLIGHT` and for the same
reason: an AD reading a conflict should be able to tell a stated bound from an
implied one."""

SYNTHETIC_DAYLIGHT_ID = "SYN-DAYLIGHT"
"""Id of the daylight record the solver adds when exterior day work exists and
nothing in the constraint set mentions daylight. Distinctive on purpose: an AD
reading a conflict should be able to tell a stated bound from an implied one."""

MODEL_VERSION = "cpsat-mvp0-2"
"""Bumped when the compilation changes. Two boards are comparable only under one
model version, one weight set and one constraint snapshot."""


class SolverError(Exception):
    """The problem could not be compiled or solved."""


class UndeclaredWeight(SolverError):
    """An objective term has no declared weight.

    Raised rather than defaulted. A term silently weighted zero is a cost the board
    is free to run up without anyone seeing it in the breakdown.
    """


@dataclass(frozen=True, slots=True)
class ObjectiveWeights:
    """Declared weights for the objective (`SOL-005`, SPEC section 4.1).

    No defaults. The ratio between a company move and a holding day is a production
    judgement, and inventing one here would put a number nobody agreed to in front of
    an AD as though it were a fact.
    """

    company_move: float
    cast_holding_day: float
    overtime_hour: float
    standard_day_hours: float = 10.0
    """Hours after which a day accrues overtime exposure. Not the hard cap -- that is
    `Company.maximum_day_hours`, which is a feasibility bound."""

    def __post_init__(self) -> None:
        for name in ("company_move", "cast_holding_day", "overtime_hour"):
            value = getattr(self, name)
            if value is None:
                raise UndeclaredWeight(f"{name} has no declared weight")
            if value < 0:
                raise UndeclaredWeight(
                    f"{name} weight must not be negative, got {value}; a negative "
                    f"weight pays the production to do the thing"
                )
        if not 0 < self.standard_day_hours <= 24:
            raise SolverError(
                f"standard day must fall in (0, 24]h, got {self.standard_day_hours}"
            )

    def integer_coefficients(self) -> tuple[int, int, int]:
        """Objective coefficients as exact integers: (move, holding day, overtime minute).

        CP-SAT optimises over integers. Scaling by a common denominator keeps the
        declared ratio exact rather than rounding it -- a rounded weight quietly
        changes which board wins, and the change is invisible in the breakdown.
        """
        move = Fraction(self.company_move).limit_denominator(10_000)
        hold = Fraction(self.cast_holding_day).limit_denominator(10_000)
        per_minute = Fraction(self.overtime_hour).limit_denominator(10_000) / 60
        scale = math.lcm(move.denominator, hold.denominator, per_minute.denominator)
        coefficients = (move * scale, hold * scale, per_minute * scale)
        if any(value.denominator != 1 for value in coefficients):
            raise SolverError("objective weights did not scale to integers")
        move_coeff, hold_coeff, overtime_coeff = coefficients
        return (move_coeff.numerator, hold_coeff.numerator, overtime_coeff.numerator)

    def __str__(self) -> str:
        return (
            f"move={self.company_move:g} holding_day={self.cast_holding_day:g} "
            f"overtime_hour={self.overtime_hour:g} standard_day={self.standard_day_hours:g}h"
        )


DECLARED_WEIGHTS = ObjectiveWeights(
    company_move=3.0,
    cast_holding_day=1.0,
    overtime_hour=0.5,
)
"""The production's declared weights, from SPEC section 4.1.

Holding days are the numeraire: one company move is worth three, one overtime hour
half of one.
"""


@dataclass(frozen=True, slots=True)
class ProductionCalendar:
    """The days available to shoot on, in order."""

    days: tuple[dt.date, ...]

    def __post_init__(self) -> None:
        if not self.days:
            raise SolverError("a production calendar needs at least one shooting day")
        ordered = tuple(sorted(set(self.days)))
        if len(ordered) != len(self.days):
            raise SolverError("the production calendar repeats a date")
        object.__setattr__(self, "days", ordered)

    def __iter__(self) -> Iterator[dt.date]:
        return iter(self.days)

    def __len__(self) -> int:
        return len(self.days)

    def index_of(self, day: dt.date) -> int:
        return self.days.index(day)


@dataclass(frozen=True, slots=True)
class ScheduleProblem:
    """Everything needed to solve, and nothing that depends on having solved."""

    problem_id: str
    production_calendar: ProductionCalendar
    work_items: tuple[WorkItem, ...]
    constraints: ConstraintSet
    roster: Roster
    locations: LocationBook
    company: Company = Company()
    weights: ObjectiveWeights = DECLARED_WEIGHTS
    created_at: dt.datetime | None = None

    def __post_init__(self) -> None:
        if not self.work_items:
            raise SolverError(f"{self.problem_id}: nothing to schedule")
        seen: set[str] = set()
        problems: list[str] = []
        for w in self.work_items:
            if w.work_id in seen:
                problems.append(f"duplicate work id {w.work_id}")
            seen.add(w.work_id)
            if w.location_id not in {loc.id for loc in self.locations}:
                problems.append(
                    f"{w.work_id}: location {w.location_id!r} is not on the "
                    f"production's locations"
                )
            unknown = sorted(set(w.cast_ids) - {m.id for m in self.roster})
            if unknown:
                problems.append(
                    f"{w.work_id}: cast not on the roster: {', '.join(unknown)}"
                )
            if w.day_night in (DayNight.DAWN, DayNight.DUSK):
                # Twilight is a short, hard window -- civil dawn to sunrise, or golden
                # hour to civil dusk -- and the model has no representation for it. It
                # would otherwise be scheduled as ordinary day work at a 07:00 call,
                # which is not a dawn scene; it is a dawn scene shot in daylight. Same
                # reasoning as `WorkItem` refusing `UNKNOWN`: work with no bound gets
                # scheduled as though unconstrained (DAY-010).
                problems.append(
                    f"{w.work_id}: {w.day_night} work has no twilight window in the "
                    f"model and would be scheduled as an ordinary day call. Schedule "
                    f"it by hand, or reclassify it as day or night work"
                )
        if problems:
            raise SolverError(
                f"{self.problem_id}: {len(problems)} problem(s) before solving:\n  "
                + "\n  ".join(problems)
            )
        # Daylight binds because the sun does, not because a record asked it to --
        # but a bound that appears in no constraint set is one nobody can trace,
        # validate or waive, and it would not reach the snapshot hash the board is
        # audited against. So it is made explicit rather than applied invisibly.
        #
        # Only when the set mentions daylight nowhere. A record someone deliberately
        # deactivated is a decision, and re-adding it would overrule them.
        needs_sun = any(w.needs_daylight for w in self.work_items)
        mentions_daylight = any(r.family is Family.DAYLIGHT for r in self.constraints)
        if needs_sun and not mentions_daylight:
            synthesised = ConstraintRecord(
                constraint_id=SYNTHETIC_DAYLIGHT_ID,
                family=Family.DAYLIGHT,
                policy=Policy.HARD,
                subject=Subject(SubjectKind.SCHEDULE),
                expression=DaylightBound(),
                source=AlgorithmSource(),
                created_by="coverset.solver (synthesised: exterior day work with no "
                "daylight constraint stated)",
                validated_against="coverset.daylight",
            )
            object.__setattr__(
                self,
                "constraints",
                ConstraintSet(self.constraints.records + (synthesised,)),
            )

        # The company's maximum day was compiled straight from `Company` and bound
        # nothing else: no record, so no assumption literal, nothing in the snapshot
        # hash, and no second reading. A board an hour over the company day passed
        # validation cleanly, two productions with different maximum days hashed
        # identically, and a schedule impossible only because of the twelve-hour day
        # was reported as structurally impossible -- offering an AD nothing to
        # negotiate when authorising a fourteen-hour day would have fixed it.
        #
        # Same test as daylight above: only when the set states no schedule-wide
        # limit of its own, so a deactivated record stays a decision.
        states_day_length = any(
            isinstance(r.expression, MaximumDailyHours)
            and r.subject.kind is SubjectKind.SCHEDULE
            for r in self.constraints
        )
        if not states_day_length:
            company_day = ConstraintRecord(
                constraint_id=SYNTHETIC_COMPANY_DAY_ID,
                family=Family.TURNAROUND,
                policy=Policy.HARD,
                subject=Subject(SubjectKind.SCHEDULE),
                expression=MaximumDailyHours(hours=self.company.maximum_day_hours),
                # Derived from the production's own parameters and re-derived on every
                # solve, which is what algorithmic provenance means here: nothing to
                # monitor, nothing retrieved.
                source=AlgorithmSource(
                    name="coverset.people.Company", version="company-day-1"
                ),
                created_by="coverset.solver (synthesised: the production's maximum "
                "day, with no day-length constraint stated)",
                validated_against="coverset.validate",
            )
            object.__setattr__(
                self,
                "constraints",
                ConstraintSet(self.constraints.records + (company_day,)),
            )

        # CON-005: unresolved constraint references block the solve rather than
        # being skipped. A constraint that fails to apply is not a no-op.
        self.constraints.resolve(
            cast_ids=frozenset(m.id for m in self.roster),
            location_ids=frozenset(loc.id for loc in self.locations),
            work_ids=frozenset(w.work_id for w in self.work_items),
            calendar=self.production_calendar.days,
        )

    @property
    def constraint_snapshot_hash(self) -> str:
        return self.constraints.snapshot_hash


@dataclass(frozen=True, slots=True)
class ConflictSet:
    """Why no schedule exists, reduced until nothing in it is redundant (`SOL-003`).

    Two kinds of cause, kept apart because they call for different actions:

    - `constraint_ids` name active records. Relaxing any one of them makes the
      conflict go away, which is a thing a production can go and negotiate.
    - `structural_causes` name properties of the problem itself -- a scene longer
      than any day, day and night work with only one day to put them on. No
      constraint relaxation helps; the breakdown or the calendar has to change.

    A conflict set that names neither is unconstructible. An empty set reported as
    irreducible tells a First AD that no schedule exists and offers nothing to
    change, which is worse than saying nothing: it looks like an answer.
    """

    constraint_ids: tuple[str, ...] = ()
    structural_causes: tuple[str, ...] = ()
    irreducible: bool = False
    detail: str = ""

    def __post_init__(self) -> None:
        # Deduplicated: `_structural_diagnosis` names a cause once per offending item,
        # so a three-scene problem repeated the same cause three times and `__len__`
        # reported a conflict larger than it was.
        object.__setattr__(
            self, "constraint_ids", tuple(sorted(set(self.constraint_ids)))
        )
        object.__setattr__(
            self, "structural_causes", tuple(sorted(set(self.structural_causes)))
        )
        if not self.constraint_ids and not self.structural_causes:
            raise SolverError(
                "a conflict set that names nothing explains nothing; if the problem is "
                "infeasible, say which constraint or which structural property makes "
                "it so"
            )
        if self.irreducible and not self.constraint_ids:
            raise SolverError(
                "irreducibility is a claim about relaxable constraints, and this "
                "conflict names none"
            )

    def __len__(self) -> int:
        return len(self.constraint_ids) + len(self.structural_causes)

    def __str__(self) -> str:
        parts = []
        if self.constraint_ids:
            proof = "irreducible" if self.irreducible else "NOT PROVEN irreducible"
            parts.append(f"{', '.join(self.constraint_ids)} ({proof})")
        if self.structural_causes:
            parts.append(f"structural: {', '.join(self.structural_causes)}")
        return " | ".join(parts)


@dataclass(frozen=True, slots=True)
class SolveResult:
    """What a solve produced. A board, or an explanation, never a plausible guess."""

    status: SolverStatus
    viable_boards: tuple[Board, ...] = ()
    conflict_set: ConflictSet | None = None
    diagnostics: tuple[str, ...] = ()

    @property
    def board(self) -> Board:
        """The single best board, when there is one."""
        if not self.viable_boards:
            raise SolverError(
                f"no viable board: status {self.status}"
                + (f"; conflict {self.conflict_set}" if self.conflict_set else "")
            )
        return self.viable_boards[0]


# -- compilation ---------------------------------------------------------------


def _daylight_minutes(loc: Location, day: dt.date) -> int | None:
    """Shootable sun-up minutes, or None where the bound cannot apply."""
    if not loc.is_locatable:
        return None
    window = daylight_window(loc, day)
    if window.condition is not SunCondition.NORMAL:
        return 0 if window.condition is SunCondition.POLAR_NIGHT else 24 * 60
    return round(window.day_length.total_seconds() / 60)


def _epoch(days: tuple[dt.date, ...]) -> dt.datetime:
    """The instant the model counts absolute minutes from.

    A day ahead of the first shooting date so that a local midnight east of UTC still
    lands after it, which keeps every time variable non-negative.
    """
    return dt.datetime.combine(
        days[0] - dt.timedelta(days=1), dt.time(), tzinfo=dt.timezone.utc
    )


def _abs_minutes(when: dt.datetime, epoch: dt.datetime) -> int:
    """`when` as whole minutes after `epoch` -- an instant, not a clock face."""
    return round(elapsed(epoch, when).total_seconds() / 60)


def _call_time(
    loc: Location, day: dt.date, *, is_night: bool, needs_sun: bool
) -> dt.datetime:
    """When the unit calls at `loc` on `day`. One definition, both readings.

    The model and the emitted timeline used to derive this separately and could
    disagree: at a locatable location with no sunset -- polar day or polar night --
    the model assumed an 18:00 night call while the timeline fell through to 07:00.
    An eleven-hour gap, surfaced as a turnaround miscompile that was really two
    fallbacks differing. Deriving it once makes that disagreement unrepresentable
    rather than something a drift check has to notice.
    """
    if not loc.is_locatable:
        # Coordinates and timezone are set together on `Location`, so this is also a
        # location with no timezone: every call time derived from it would be an hour
        # wrong across a DST boundary. Refused at compile rather than at emit, so the
        # solver does not spend a search proving a board that cannot be written down.
        raise SolverError(
            f"{loc.name} has no coordinates or timezone, so a call time on "
            f"{day.isoformat()} would be an hour wrong across a DST boundary. "
            f"Geocode the location."
        )
    window = daylight_window(loc, day)
    if is_night:
        return window.sunset if window.sunset is not None else _local(day, 18, 0, loc)
    if needs_sun and window.sunrise is not None:
        return window.sunrise
    return _local(day, DEFAULT_CALL_HOUR, 0, loc)


def _sunset_abs(loc: Location, day: dt.date, epoch: dt.datetime) -> int | None:
    """Sunset as absolute minutes, or None where no sunset bounds the day.

    `None` covers a location with no coordinates and polar day, neither of which is a
    sunset the schedule can be held to. Polar night returns the day's own start, which
    forbids daylight work outright rather than pretending a window exists.
    """
    if not loc.is_locatable:
        return None
    window = daylight_window(loc, day)
    if window.condition is SunCondition.POLAR_DAY:
        return None
    if window.condition is SunCondition.POLAR_NIGHT or window.sunset is None:
        return _abs_minutes(_local(day, 0, 0, loc), epoch)
    return _abs_minutes(window.sunset, epoch)


def _anchor_abs(
    loc: Location, day: dt.date, epoch: dt.datetime
) -> tuple[int, int, int]:
    """Absolute call minutes for a (night, sunrise, plain) shoot at `loc` on `day`."""
    return (
        _abs_minutes(_call_time(loc, day, is_night=True, needs_sun=False), epoch),
        _abs_minutes(_call_time(loc, day, is_night=False, needs_sun=True), epoch),
        _abs_minutes(_call_time(loc, day, is_night=False, needs_sun=False), epoch),
    )


def _forbidden(record: ConstraintRecord, item: WorkItem, day: dt.date) -> bool:
    """Whether this record forbids placing `item` on `day`. Pure lookup, no solver."""
    expr = record.expression
    if isinstance(expr, (DateWindows, BlackoutDates)):
        if record.subject.kind is SubjectKind.CAST:
            if record.subject.ref not in item.cast_ids:
                return False
        elif record.subject.kind is SubjectKind.LOCATION:
            if record.subject.ref != item.location_id:
                return False
        elif record.subject.kind is SubjectKind.WORK:
            if record.subject.ref != item.work_id:
                return False
        else:
            return False
        return not expr.allows(day)
    if isinstance(expr, PinnedDay) and record.subject.kind is SubjectKind.WORK:
        if record.subject.ref == item.work_id:
            return day != expr.day
    return False


@dataclass
class _Compiled:
    """The CP-SAT model plus the handles needed to read a solution back out."""

    model: cp_model.CpModel
    place: dict[tuple[int, int], cp_model.IntVar]
    used: dict[tuple[str, int], cp_model.IntVar]
    starts: dict[tuple[str, int], cp_model.IntVar]
    ends: dict[tuple[str, int], cp_model.IntVar]
    call_abs: dict[int, cp_model.IntVar]
    wrap_abs: dict[int, cp_model.IntVar]
    is_night: dict[int, cp_model.IntVar]
    day_minutes: dict[int, cp_model.IntVar]
    overtime: dict[int, cp_model.IntVar]
    held: dict[str, cp_model.IntVar]
    moves: cp_model.IntVar
    assumptions: dict[str, cp_model.IntVar]


def _compile(
    problem: ScheduleProblem, *, only: frozenset[str] | None = None
) -> _Compiled:
    """Turn the problem into a CP-SAT model.

    `only` restricts which binding constraints are enforced, used by the conflict
    shrink. Each enforced record is pinned to its own assumption literal so an
    infeasible solve can name the records responsible.
    """
    m = cp_model.CpModel()
    days = problem.production_calendar.days
    items = problem.work_items
    binding = [
        r
        for r in problem.constraints.binding
        if only is None or r.constraint_id in only
    ]

    place = {
        (i, d): m.new_bool_var(f"place_{items[i].work_id}_{days[d]}")
        for i in range(len(items))
        for d in range(len(days))
    }
    for i in range(len(items)):
        m.add_exactly_one(place[i, d] for d in range(len(days)))

    assumptions: dict[str, cp_model.IntVar] = {}
    for r in binding:
        assumptions[r.constraint_id] = m.new_bool_var(f"assume_{r.constraint_id}")

    # -- per-record hard bounds -------------------------------------------------
    for r in binding:
        lit = assumptions[r.constraint_id]
        expr = r.expression
        if isinstance(expr, (DateWindows, BlackoutDates, PinnedDay)):
            for i, item in enumerate(items):
                for d, day in enumerate(days):
                    if _forbidden(r, item, day):
                        m.add(place[i, d] == 0).only_enforce_if(lit)
                if isinstance(expr, PinnedDay) and r.subject.ref == item.work_id:
                    if expr.day in days:
                        m.add(place[i, days.index(expr.day)] == 1).only_enforce_if(lit)

    # -- locations in use -------------------------------------------------------
    location_ids = sorted({w.location_id for w in items})
    used: dict[tuple[str, int], cp_model.IntVar] = {}
    for loc_id in location_ids:
        at_loc = [i for i, w in enumerate(items) if w.location_id == loc_id]
        for d in range(len(days)):
            u = m.new_bool_var(f"used_{loc_id}_{days[d]}")
            used[loc_id, d] = u
            for i in at_loc:
                m.add_implication(place[i, d], u)
            m.add(u <= sum(place[i, d] for i in at_loc))

    day_used: dict[int, cp_model.IntVar] = {}
    for d in range(len(days)):
        du = m.new_bool_var(f"day_used_{days[d]}")
        day_used[d] = du
        for i in range(len(items)):
            m.add_implication(place[i, d], du)
        m.add(du <= sum(place[i, d] for i in range(len(items))))

    # -- where each day begins and where it wraps -------------------------------
    #
    # A company move is a relocation of the unit, so counting it needs to know where
    # the unit *is*, not merely which places a day touched. Sharing some location
    # with the previous day is not continuity: wrapping at the studio and calling at
    # the park is a move whether or not the park was also used yesterday. Modelling
    # the first and last location of each day is what makes the count match the board.
    starts: dict[tuple[str, int], cp_model.IntVar] = {}
    ends: dict[tuple[str, int], cp_model.IntVar] = {}
    within_moves: dict[int, cp_model.IntVar] = {}
    for d in range(len(days)):
        locations_today = sum(used[loc_id, d] for loc_id in location_ids)
        wm = m.new_int_var(0, len(location_ids), f"within_moves_{days[d]}")
        m.add_max_equality(wm, [locations_today - 1, 0])
        within_moves[d] = wm

        single = m.new_bool_var(f"single_location_{days[d]}")
        m.add(locations_today == 1).only_enforce_if(single)
        m.add(locations_today != 1).only_enforce_if(single.Not())

        for loc_id in location_ids:
            s = m.new_bool_var(f"starts_{loc_id}_{days[d]}")
            e = m.new_bool_var(f"ends_{loc_id}_{days[d]}")
            starts[loc_id, d], ends[loc_id, d] = s, e
            m.add(s <= used[loc_id, d])
            m.add(e <= used[loc_id, d])
            # A day touching two or more locations cannot both begin and end at the
            # same one without doubling back, which would be a further move.
            m.add(s + e <= 1 + single)
        m.add(sum(starts[loc_id, d] for loc_id in location_ids) == day_used[d])
        m.add(sum(ends[loc_id, d] for loc_id in location_ids) == day_used[d])

    # Where the unit sits at the end of day d, carried forward across gap days: a
    # day off does not move the trucks.
    end_base: dict[tuple[str, int], cp_model.IntVar] = {}
    for loc_id in location_ids:
        for d in range(len(days)):
            b = m.new_bool_var(f"end_base_{loc_id}_{days[d]}")
            end_base[loc_id, d] = b
            m.add(b == ends[loc_id, d]).only_enforce_if(day_used[d])
            if d:
                m.add(b == end_base[loc_id, d - 1]).only_enforce_if(day_used[d].Not())
            else:
                m.add(b == 0).only_enforce_if(day_used[d].Not())

    started: dict[int, cp_model.IntVar] = {}
    for d in range(len(days)):
        s = m.new_bool_var(f"started_{days[d]}")
        started[d] = s
        if d:
            m.add(s >= started[d - 1])
            m.add(s <= started[d - 1] + day_used[d])
        else:
            m.add(s <= day_used[d])
        m.add(s >= day_used[d])

    # Every counter here is pinned in *both* directions. A one-sided bound that the
    # objective happens to close is exact only at proven optimality: stop the search
    # early and the counter sits slack above the truth, `solve` compares it against
    # the count measured off the board, and a perfectly valid `FEASIBLE` board is
    # thrown away with a diagnostic blaming a miscompile that is not there. The
    # cross-check is only a second reading if the first one is exact at every status.
    overnight: list[cp_model.IntVar] = []
    for d in range(1, len(days)):
        continues = m.new_bool_var(f"continues_{days[d]}")
        links = []
        for loc_id in location_ids:
            link = m.new_bool_var(f"link_{loc_id}_{days[d]}")
            m.add(link <= end_base[loc_id, d - 1])
            m.add(link <= starts[loc_id, d])
            m.add(link >= end_base[loc_id, d - 1] + starts[loc_id, d] - 1)
            links.append(link)
        m.add_max_equality(continues, links)
        # The unit moved overnight exactly when the day is worked, the production has
        # already started, and today does not call where yesterday wrapped.
        move_overnight = m.new_bool_var(f"overnight_move_{days[d]}")
        m.add(move_overnight >= day_used[d] + started[d - 1] - continues - 1)
        m.add(move_overnight <= day_used[d])
        m.add(move_overnight <= started[d - 1])
        m.add(move_overnight <= 1 - continues)
        overnight.append(move_overnight)

    moves = m.new_int_var(0, len(location_ids) * len(days), "company_moves")
    m.add(moves == sum(within_moves.values()) + sum(overnight))

    # -- day shape: day-or-night, length, overtime, call and wrap ---------------
    is_night: dict[int, cp_model.IntVar] = {}
    needs_sun: dict[int, cp_model.IntVar] = {}
    day_minutes: dict[int, cp_model.IntVar] = {}
    overtime: dict[int, cp_model.IntVar] = {}
    call_abs: dict[int, cp_model.IntVar] = {}
    wrap_abs: dict[int, cp_model.IntVar] = {}
    sun_loc: dict[tuple[str, int], cp_model.IntVar] = {}
    sun_prefix: dict[int, cp_model.IntVar] = {}
    has_non_sun: dict[int, cp_model.IntVar] = {
        d: m.new_bool_var(f"has_non_sun_{day}") for d, day in enumerate(days)
    }
    standard = round(problem.weights.standard_day_hours * 60)
    total_minutes = sum(w.estimated_duration_minutes for w in items)
    # The most a day could hold if every bound were relaxed. Variable domains are
    # sized from this rather than from the company day, which is now relaxable: a
    # domain that quietly re-imposes a bound the conflict shrink just switched off
    # would make the shrink report the wrong constraint as load-bearing.
    day_ceiling = total_minutes + len(location_ids) * COMPANY_MOVE_MINUTES
    daylight_items = [i for i, w in enumerate(items) if w.needs_daylight]
    # Offsets in *calendar* days from the first shooting day. A production calendar
    # skips dark days, weekends and holds, so the index of a day in the calendar is
    # not how far away it is. Using the index puts every clock time on the wrong date
    # the moment a day is missed, and prices a hold across a dark day as though the
    # dark day did not exist.
    offsets = [(day - days[0]).days for day in days]
    # Clock variables count absolute minutes from `epoch`, not minutes past a local
    # midnight. Durations are real minutes, so the coordinate has to be a real
    # instant: on a day spanning a DST transition, wall-clock coordinates make the
    # day an hour longer or shorter than the model believes, and `worked <= max_day`
    # and the turnaround bound are both then enforced against a clock nobody is on.
    epoch = _epoch(days)
    horizon = (offsets[-1] + 3) * MINUTES_PER_DAY

    for d, day in enumerate(days):
        night = m.new_bool_var(f"night_{day}")
        is_night[d] = night
        for i, item in enumerate(items):
            # A shoot day is a day shoot or a night shoot. Split days are post-MVP.
            if item.day_night is DayNight.NIGHT:
                m.add_implication(place[i, d], night)
            else:
                m.add_implication(place[i, d], night.Not())

        sun = m.new_bool_var(f"needs_sun_{day}")
        needs_sun[d] = sun
        for i in daylight_items:
            m.add_implication(place[i, d], sun)
        if daylight_items:
            m.add(sun <= sum(place[i, d] for i in daylight_items))
        else:
            m.add(sun == 0)

        # Which locations hold daylight work today. The day is emitted with these
        # first, so everything that must happen before sunset is a prefix of the day
        # rather than scattered through it.
        for loc_id in location_ids:
            here = [i for i in daylight_items if items[i].location_id == loc_id]
            sl = m.new_bool_var(f"sun_location_{loc_id}_{days[d]}")
            sun_loc[loc_id, d] = sl
            if here:
                for i in here:
                    m.add_implication(place[i, d], sl)
                m.add(sl <= sum(place[i, d] for i in here))
            else:
                m.add(sl == 0)

            # A day needing the sun must begin at a location that needs it, and --
            # when there is anywhere else to finish -- must not end at one, so the
            # sun-bound work really is the front of the day.
            m.add(starts[loc_id, d] <= sl).only_enforce_if(sun)
            m.add(ends[loc_id, d] + sl + has_non_sun[d] <= 2).only_enforce_if(sun)

        non_sun = []
        for loc_id in location_ids:
            ns = m.new_bool_var(f"non_sun_{loc_id}_{days[d]}")
            m.add(ns <= used[loc_id, d])
            m.add(ns <= 1 - sun_loc[loc_id, d])
            m.add(ns >= used[loc_id, d] - sun_loc[loc_id, d])
            non_sun.append(ns)
        m.add(has_non_sun[d] <= sum(non_sun))
        for ns in non_sun:
            m.add_implication(ns, has_non_sun[d])

        # Minutes from call until the last sun-bound location wraps: every item at a
        # sun location, plus the moves between them.
        prefix_terms = []
        for i, item in enumerate(items):
            y = m.new_bool_var(f"in_sun_prefix_{item.work_id}_{days[d]}")
            m.add(y <= place[i, d])
            m.add(y <= sun_loc[item.location_id, d])
            m.add(y >= place[i, d] + sun_loc[item.location_id, d] - 1)
            prefix_terms.append(items[i].estimated_duration_minutes * y)
        sun_hops = m.new_int_var(0, len(location_ids), f"sun_moves_{days[d]}")
        m.add_max_equality(
            sun_hops,
            [sum(sun_loc[location_id, d] for location_id in location_ids) - 1, 0],
        )
        prefix = m.new_int_var(
            0,
            total_minutes + len(location_ids) * COMPANY_MOVE_MINUTES,
            f"sun_prefix_{days[d]}",
        )
        m.add(prefix == sum(prefix_terms) + COMPANY_MOVE_MINUTES * sun_hops)
        sun_prefix[d] = prefix

        worked = m.new_int_var(
            0,
            total_minutes + len(location_ids) * COMPANY_MOVE_MINUTES,
            f"minutes_{day}",
        )
        m.add(
            worked
            == sum(
                items[i].estimated_duration_minutes * place[i, d]
                for i in range(len(items))
            )
            + COMPANY_MOVE_MINUTES * within_moves[d]
        )
        day_minutes[d] = worked
        # The company's day is no longer capped here: it arrives as `SYN-COMPANY-DAY`
        # (or as whatever the production stated) and compiles through the
        # record-driven branch below like every other bound, which is what lets the
        # conflict shrink name it and the validator re-read it.
        #
        # What stays is the calendar day itself. Twenty-four hours is not a policy
        # anybody can authorise their way past, so it is the one day-length bound that
        # belongs in the model unconditionally -- and it is what keeps a twenty-five
        # hour scene reported as structurally impossible rather than blamed on a
        # company day that could be relaxed to no effect.
        m.add(worked <= MINUTES_PER_DAY)

        ot = m.new_int_var(0, day_ceiling, f"overtime_{day}")
        m.add_max_equality(ot, [worked - standard, 0])
        overtime[d] = ot

        # Call and wrap as absolute minutes, so a bound between one day's wrap and
        # the next day's call is expressible. Without these, turnaround could only be
        # approximated as a day-length cap, which says nothing about a night wrap
        # running into a sunrise call.
        call = m.new_int_var(0, horizon, f"call_{day}")
        wrap = m.new_int_var(0, horizon, f"wrap_{day}")
        call_abs[d], wrap_abs[d] = call, wrap
        m.add(wrap == call + worked)
        for loc_id in location_ids:
            at_night, at_sunrise, plain = _anchor_abs(
                problem.locations[loc_id], day, epoch
            )
            here = starts[loc_id, d]
            m.add(call == at_night).only_enforce_if([here, night])
            m.add(call == at_sunrise).only_enforce_if([here, night.Not(), sun])
            m.add(call == plain).only_enforce_if([here, night.Not(), sun.Not()])

    # -- cast engagement spans --------------------------------------------------
    held: dict[str, cp_model.IntVar] = {}
    works: dict[tuple[str, int], cp_model.IntVar] = {}
    n = len(days)
    for member in problem.roster:
        theirs = [i for i, w in enumerate(items) if member.id in w.cast_ids]
        if not theirs:
            continue
        for d in range(n):
            w = m.new_bool_var(f"works_{member.id}_{days[d]}")
            works[member.id, d] = w
            for i in theirs:
                m.add_implication(place[i, d], w)
            m.add(w <= sum(place[i, d] for i in theirs))
        any_work = m.new_bool_var(f"engaged_{member.id}")
        span = [works[member.id, d] for d in range(n)]
        m.add(sum(span) >= 1).only_enforce_if(any_work)
        m.add(sum(span) == 0).only_enforce_if(any_work.Not())
        # Spans measured in calendar days: a performer retained across a dark day is
        # paid for it, which is what `Engagement.held_days` counts off the board.
        #
        # Channelled through a per-day term rather than bounded from one side, for the
        # reason given at the move counters: `first <= offset` alone lets the span run
        # wider than the performer's actual engagement in any solution short of proven
        # optimal, which prices a holding day nobody is owed. A day they do not work
        # contributes the identity of the bound it feeds -- the last offset to a
        # minimum, the first to a maximum -- so it cannot widen the span.
        first = m.new_int_var(0, offsets[-1], f"first_{member.id}")
        last = m.new_int_var(0, offsets[-1], f"last_{member.id}")
        first_terms, last_terms = [], []
        for d in range(n):
            worked = works[member.id, d]
            lo = m.new_int_var(0, offsets[-1], f"first_term_{member.id}_{days[d]}")
            m.add(lo == offsets[d]).only_enforce_if(worked)
            m.add(lo == offsets[-1]).only_enforce_if(worked.Not())
            first_terms.append(lo)
            hi = m.new_int_var(0, offsets[-1], f"last_term_{member.id}_{days[d]}")
            m.add(hi == offsets[d]).only_enforce_if(worked)
            m.add(hi == 0).only_enforce_if(worked.Not())
            last_terms.append(hi)
        m.add_min_equality(first, first_terms)
        m.add_max_equality(last, last_terms)
        h = m.new_int_var(0, offsets[-1] + 1, f"held_{member.id}")
        m.add(h == last - first + 1 - sum(span)).only_enforce_if(any_work)
        m.add(h == 0).only_enforce_if(any_work.Not())
        held[member.id] = h

    # -- record-driven bounds: daylight, daily hours, rest ----------------------
    for r in binding:
        lit = assumptions[r.constraint_id]
        expr = r.expression

        if isinstance(expr, DaylightBound):
            # Gated on the record. Daylight is physics, but a bound that binds
            # without a record behind it appears in no snapshot and no validation
            # report, so nobody can trace or waive it. `ScheduleProblem` synthesises
            # a record when work needs the sun and the set is silent.
            in_scope = [
                i
                for i in daylight_items
                if (
                    r.subject.kind is not SubjectKind.WORK
                    or r.subject.ref == items[i].work_id
                )
                and (
                    r.subject.kind is not SubjectKind.LOCATION
                    or r.subject.ref == items[i].location_id
                )
            ]
            if not in_scope:
                continue
            # Bounding the *aggregate* daylight load said nothing about when in the
            # day that load happens. The timeline lays locations out in sequence, so
            # an exterior scene behind a long interior one can wrap after sunset while
            # the aggregate still fits -- caught by the validator, but only after the
            # fact. Bounding the day's own wrap against each used location's sunset is
            # true whatever order the day is emitted in.
            for d, day in enumerate(days):
                for loc_id in location_ids:
                    sunset = _sunset_abs(problem.locations[loc_id], day, epoch)
                    if sunset is None:
                        continue
                    m.add(call_abs[d] + sun_prefix[d] <= sunset).only_enforce_if(
                        [lit, sun_loc[loc_id, d]]
                    )
            for i in in_scope:
                loc = problem.locations[items[i].location_id]
                for d, day in enumerate(days):
                    available = _daylight_minutes(loc, day)
                    if (
                        available is not None
                        and available < items[i].estimated_duration_minutes
                    ):
                        m.add(place[i, d] == 0).only_enforce_if(lit)

        elif isinstance(expr, MaximumDailyHours):
            for d in range(len(days)):
                if r.subject.kind is SubjectKind.SCHEDULE:
                    m.add(day_minutes[d] <= expr.minutes).only_enforce_if(lit)
                elif r.subject.kind is SubjectKind.CAST:
                    # Elapsed time on set, not the sum of scene durations. A performer
                    # waiting through a company move is still at work, and a minor's
                    # limit is a limit on the day they are held through, not on the
                    # minutes the camera rolls. The validator measures call-to-wrap, so
                    # the model bounds the day that contains it -- conservative, and
                    # conservative in the direction that cannot ship a bad board.
                    worker = works.get((r.subject.ref, d))
                    if worker is not None:
                        m.add(day_minutes[d] <= expr.minutes).only_enforce_if(
                            [lit, worker]
                        )

        elif isinstance(expr, MinimumRest):
            # Exact: wrap of one day to call of the next, in absolute minutes. The
            # old compilation bounded day *length* only, which permits a night wrap
            # at 00:06 followed by a 06:36 sunrise call -- caught by the validator,
            # but only after the fact, and reported as though the model had been
            # miscompiled rather than never having expressed the bound.
            for d in range(len(days) - 1):
                if (days[d + 1] - days[d]).days != 1:
                    continue  # a clear day already exceeds any rest this models
                guards = [lit, day_used[d], day_used[d + 1]]
                if r.subject.kind is SubjectKind.CAST:
                    pair = [
                        works.get((r.subject.ref, d)),
                        works.get((r.subject.ref, d + 1)),
                    ]
                    if any(v is None for v in pair):
                        continue
                    guards.extend(v for v in pair if v is not None)
                m.add(call_abs[d + 1] - wrap_abs[d] >= expr.minutes).only_enforce_if(
                    guards
                )

    move_coeff, hold_coeff, ot_coeff = problem.weights.integer_coefficients()
    m.minimize(
        move_coeff * moves
        + hold_coeff * sum(held.values())
        + ot_coeff * sum(overtime.values())
    )
    return _Compiled(
        model=m,
        place=place,
        used=used,
        starts=starts,
        ends=ends,
        call_abs=call_abs,
        wrap_abs=wrap_abs,
        is_night=is_night,
        day_minutes=day_minutes,
        overtime=overtime,
        held=held,
        moves=moves,
        assumptions=assumptions,
    )


# -- reading a solution back out -----------------------------------------------


def _local(day: dt.date, hour: int, minute: int, loc: Location) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(hour, minute)).replace(tzinfo=loc.zone)


def _order_day(
    items_today: list[WorkItem], start_location: str, end_location: str
) -> list[WorkItem]:
    """Order a day's work to begin and end where the model decided it would.

    The model counts a move between where one day wraps and where the next calls, so
    the board has to actually realise that first and last location. If the ordering
    were free to pick its own, the count the model minimised and the moves the board
    contains would be different numbers, and the objective would be optimising
    something nobody is driving to.

    Within a location, daylight work goes first: the day is anchored at sunrise, and
    work that needs the sun cannot wait behind work that does not.
    """
    groups: dict[str, list[WorkItem]] = {}
    for w in items_today:
        groups.setdefault(w.location_id, []).append(w)

    # Sun-bound locations lead. The model bounds the daylight prefix on exactly this
    # assumption, so the emitted day has to honour it or the bound is about a day
    # nobody is shooting.
    def sun_first(loc_id: str) -> tuple[int, str]:
        return (0 if any(w.needs_daylight for w in groups[loc_id]) else 1, loc_id)

    middle = sorted(
        (loc for loc in groups if loc not in (start_location, end_location)),
        key=sun_first,
    )
    order = [start_location] + middle
    if end_location != start_location:
        order.append(end_location)
    if set(order) != set(groups):
        raise SolverError(
            f"day ordering {order} does not cover the locations actually used "
            f"({sorted(groups)}); the model and the board disagree about the day"
        )

    out: list[WorkItem] = []
    for loc_id in order:
        out.extend(
            sorted(groups[loc_id], key=lambda w: (not w.needs_daylight, w.work_id))
        )
    return out


def _timeline(
    problem: ScheduleProblem,
    day: dt.date,
    items_today: list[WorkItem],
    start_location: str,
    end_location: str,
) -> list[Assignment]:
    """Lay a day's work out in wall-clock time, anchored to the sun where required."""
    ordered = _order_day(items_today, start_location, end_location)
    first = problem.locations[ordered[0].location_id]
    is_night = any(w.day_night is DayNight.NIGHT for w in ordered)
    needs_sun = any(w.needs_daylight for w in ordered)
    clock = _call_time(first, day, is_night=is_night, needs_sun=needs_sun)

    assignments: list[Assignment] = []
    current_location: str | None = None
    for seq, item in enumerate(ordered):
        # `advance`, not `+=`: adding a timedelta to an aware datetime moves the wall
        # clock, so a twelve-hour night the clocks go back inside would be written
        # down as wrapping an hour before the twelve hours were up.
        if current_location is not None and item.location_id != current_location:
            clock = advance(clock, dt.timedelta(minutes=COMPANY_MOVE_MINUTES))
        current_location = item.location_id
        call = clock
        clock = advance(clock, item.duration)
        assignments.append(
            Assignment(
                work_id=item.work_id,
                shoot_day=day,
                sequence=seq,
                location_id=item.location_id,
                planned_call_time=call,
                planned_wrap_time=clock,
            )
        )
    return assignments


def _measure_moves(assignments: tuple[Assignment, ...]) -> int:
    """Count company moves on a finished board, by the same definition the model used.

    Measured rather than read back from the solver. A number the model reports about
    itself proves nothing about the board; this is the second reading that makes the
    objective breakdown auditable.
    """
    by_day: dict[dt.date, list[Assignment]] = {}
    for a in assignments:
        by_day.setdefault(a.shoot_day, []).append(a)

    total = 0
    previous_end: str | None = None
    for day in sorted(by_day):
        todays = sorted(by_day[day], key=lambda a: a.sequence)
        runs: list[str] = []
        for a in todays:
            if not runs or runs[-1] != a.location_id:
                runs.append(a.location_id)
        total += len(runs) - 1
        # Where the unit wrapped versus where it now calls. Asking only whether the
        # two days *share* a location counts a park-studio day followed by a park day
        # as continuous, when the trucks plainly moved from the studio back to the
        # park overnight.
        if previous_end is not None and runs[0] != previous_end:
            total += 1
        previous_end = runs[-1]
    return total


def _measure_overtime_minutes(
    assignments: tuple[Assignment, ...], weights: ObjectiveWeights
) -> int:
    """Overtime measured off the board, in whole minutes.

    Minutes rather than hours because this is compared against the model\'s own
    integer term, and a float comparison would report a disagreement that is really
    a rounding difference -- or, worse, miss a real one inside the tolerance.
    """
    standard = round(weights.standard_day_hours * 60)
    by_day: dict[dt.date, list[Assignment]] = {}
    for a in assignments:
        by_day.setdefault(a.shoot_day, []).append(a)
    total = 0
    for todays in by_day.values():
        length = elapsed(
            min(a.planned_call_time for a in todays),
            max(a.planned_wrap_time for a in todays),
        )
        total += max(0, round(length.total_seconds() / 60) - standard)
    return total


def _timeline_drift(
    assignments: tuple[Assignment, ...],
    compiled: _Compiled,
    solver: cp_model.CpSolver,
    problem: ScheduleProblem,
) -> list[str]:
    """Where the model's call/wrap differs from the board's, if anywhere."""
    days = problem.production_calendar.days
    epoch = _epoch(days)
    by_day: dict[dt.date, list[Assignment]] = {}
    for a in assignments:
        by_day.setdefault(a.shoot_day, []).append(a)

    problems: list[str] = []
    for d, day in enumerate(days):
        todays = by_day.get(day)
        if not todays:
            continue
        zone = problem.locations[min(todays, key=lambda a: a.sequence).location_id].zone
        for label, model_var, actual in (
            ("call", compiled.call_abs[d], min(a.planned_call_time for a in todays)),
            ("wrap", compiled.wrap_abs[d], max(a.planned_wrap_time for a in todays)),
        ):
            # Both sides are instants, so this compares moments rather than clock
            # faces -- the whole reason the model counts from `epoch`.
            expected = (
                epoch + dt.timedelta(minutes=solver.value(model_var))
            ).astimezone(zone)
            if abs(elapsed(expected, actual).total_seconds()) > 60:
                problems.append(
                    f"{day.isoformat()} {label}: model says {expected:%d %H:%M}, "
                    f"board says {actual:%d %H:%M}"
                )
    return problems


def _relative_gap(objective: float, bound: float) -> float:
    """How far a board may be from optimal, as a fraction (`SOL-013`).

    The denominator is floored at 1 so a board that costs nothing -- no moves, no
    holding days, which a small fixture reaches easily -- reports a gap rather than
    dividing by zero. Clamped at zero because a bound very slightly above the
    objective is floating-point noise, not a board that beat the proven optimum.
    """
    return max(0.0, (objective - bound) / max(1.0, abs(objective)))


def _extract(problem: ScheduleProblem, compiled: _Compiled, solver: cp_model.CpSolver):
    """Turn solver values into assignments, day by day."""
    days = problem.production_calendar.days
    items = problem.work_items
    assignments: list[Assignment] = []
    for d, day in enumerate(days):
        today = [
            items[i] for i in range(len(items)) if solver.value(compiled.place[i, d])
        ]
        if not today:
            continue
        here = {w.location_id for w in today}
        chosen = [loc for loc in here if solver.value(compiled.starts[loc, d])]
        wrapping = [loc for loc in here if solver.value(compiled.ends[loc, d])]
        if len(chosen) != 1 or len(wrapping) != 1:
            raise SolverError(
                f"{day}: the model chose {len(chosen)} start and {len(wrapping)} end "
                f"location(s) for a day that used {sorted(here)}"
            )
        assignments.extend(_timeline(problem, day, today, chosen[0], wrapping[0]))
    return tuple(assignments)


# -- conflict analysis ----------------------------------------------------------


def _infeasible_with(problem: ScheduleProblem, ids: Iterable[str]) -> bool:
    compiled = _compile(problem, only=frozenset(ids))
    compiled.model.clear_assumptions()
    for lit in compiled.assumptions.values():
        compiled.model.add_assumption(lit)
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    solver.parameters.random_seed = 0
    return solver.solve(compiled.model) == cp_model.INFEASIBLE


def _structural_diagnosis(problem: ScheduleProblem) -> tuple[list[str], list[str]]:
    """Name the problem properties that make it unschedulable before any constraint.

    Runs every check rather than stopping at the first, for the same reason
    `Roster.resolve` names every unknown cast id at once: someone repairing a
    breakdown wants the list, not one error per run.

    Returns:
        (cause ids, human-readable detail lines).
    """
    days = problem.production_calendar.days
    items = problem.work_items
    # A *structural* cause is one no relaxation can remove, so the day here is the
    # physical one, not the company's. The company day is `SYN-COMPANY-DAY` now and
    # is nameable as a constraint; blaming structure for it would send an AD away
    # with nothing to negotiate when authorising a longer day is exactly the fix.
    max_day = MINUTES_PER_DAY
    causes: list[str] = []
    detail: list[str] = []

    too_long = [w for w in items if w.estimated_duration_minutes > max_day]
    if too_long:
        causes.append("STRUCT-DAY-LENGTH")
        detail.extend(
            f"{w.work_id} runs {w.estimated_duration_minutes}m, longer than the "
            f"{max_day // 60}h a calendar day has, so no day can hold it"
            for w in too_long
        )

    for w in items:
        if not w.needs_daylight:
            continue
        loc = problem.locations[w.location_id]
        windows = [m for d in days if (m := _daylight_minutes(loc, d)) is not None]
        if windows and w.estimated_duration_minutes > max(windows):
            causes.append("STRUCT-DAYLIGHT-WINDOW")
            detail.append(
                f"{w.work_id} needs {w.estimated_duration_minutes}m of daylight at "
                f"{loc.name}, and the longest window on the calendar is {max(windows)}m"
            )

    night = [w for w in items if w.day_night is DayNight.NIGHT]
    daytime = [w for w in items if w.day_night is not DayNight.NIGHT]
    needed = sum(
        -(-sum(w.estimated_duration_minutes for w in group) // max_day)
        for group in (night, daytime)
        if group
    )
    if needed > len(days):
        causes.append("STRUCT-DAY-NIGHT-SPLIT")
        detail.append(
            f"{len(daytime)} day and {len(night)} night work item(s) need at least "
            f"{needed} calendar day(s) once day and night are kept apart, and the "
            f"calendar has {len(days)}. A shoot day is a day shoot or a night shoot; "
            f"split days are post-MVP"
        )

    total = sum(w.estimated_duration_minutes for w in items)
    if total > len(days) * max_day:
        causes.append("STRUCT-TOTAL-CAPACITY")
        detail.append(
            f"{total}m of work will not fit {len(days)} day(s) of at most "
            f"{max_day}m each"
        )

    if not causes:
        causes.append("STRUCT-UNDIAGNOSED")
        detail.append(
            "the problem is infeasible with every relaxable constraint switched off, "
            "but no structural check identified why. This is a gap in the diagnosis, "
            "not a schedule -- please report the fixture"
        )
    return causes, detail


def _conflict_set(problem: ScheduleProblem, core: list[str]) -> ConflictSet:
    """Reduce a sufficient core to an irreducible one (`SOL-003`).

    CP-SAT returns assumptions sufficient to prove infeasibility, not a minimal set.
    A deletion filter re-proves the conflict without each member in turn; whatever
    survives is load-bearing, which is precisely the promise the requirement makes.

    This is not belt-and-braces. On the two-performer conflict fixture CP-SAT returns
    a core of three, including a location window that has nothing to do with the
    conflict; the filter reduces it to the two availability records that actually
    collide. Handing an AD a third constraint to go and renegotiate, when relaxing it
    would change nothing, is exactly the kind of confident wrong answer this codebase
    keeps having to design against.
    """
    current = list(core)
    changed = True
    while changed:
        changed = False
        for candidate in list(current):
            trial = [c for c in current if c != candidate]
            # No `if trial` guard: the empty set is exactly the case worth testing.
            # Skipping it is how a structurally infeasible problem came to be blamed
            # on whichever relaxable constraint happened to be in the core.
            if _infeasible_with(problem, trial):
                current = trial
                changed = True
    irreducible = all(
        not _infeasible_with(problem, [c for c in current if c != drop])
        for drop in current
    )
    if not current:
        # Every constraint dropped out, so none of them is the reason.
        causes, detail = _structural_diagnosis(problem)
        return ConflictSet(
            structural_causes=tuple(causes),
            irreducible=False,
            detail="; ".join(detail),
        )
    return ConflictSet(
        constraint_ids=tuple(current),
        irreducible=irreducible,
        detail=(
            f"reduced from {len(core)} sufficient to {len(current)} load-bearing "
            f"constraint(s)"
        ),
    )


# -- the entry point ------------------------------------------------------------


def solve(
    problem: ScheduleProblem, *, seed: int = 0, budget: float = 120.0
) -> SolveResult:
    """Schedule `problem`, or explain irreducibly why it cannot be scheduled.

    A board is returned only when the solver proved a solution *and* an independent
    reading of every binding constraint agrees the board satisfies it. The two must
    also agree on what the board costs; a disagreement means the model and the board
    are not the same object, and no board is returned.

    Args:
        seed: fixes the solver's tie-breaking. Boards are deterministic per seed, and
            two seeds give different, equally optimal boards -- so the seed is
            recorded on the board rather than left implicit.
        budget: CP-SAT *deterministic* time, not wall clock. A wall-clock cutoff makes
            the board depend on how fast the machine was that day, which quietly
            undoes the reason the seed is recorded at all: "reproduce the board we
            approved on Tuesday" has to mean something. A deterministic budget cuts
            off at the same point in the search on every machine.
    """
    compiled = _compile(problem)
    compiled.model.clear_assumptions()
    for lit in compiled.assumptions.values():
        compiled.model.add_assumption(lit)

    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    solver.parameters.random_seed = seed
    solver.parameters.max_deterministic_time = budget
    raw = solver.solve(compiled.model)
    parameters = f"seed={seed} workers=1 budget={budget:g}det model={MODEL_VERSION}"

    if raw == cp_model.INFEASIBLE:
        index_to_id = {lit.index: cid for cid, lit in compiled.assumptions.items()}
        core = [
            index_to_id[i]
            for i in solver.sufficient_assumptions_for_infeasibility()
            if i in index_to_id
        ]
        if not _infeasible_with(problem, []):
            conflict = _conflict_set(problem, core)
        else:
            # Infeasible with every relaxable constraint switched off. Whatever CP-SAT
            # put in the core is incidental, and naming it would send someone to
            # renegotiate a bound whose relaxation changes nothing.
            causes, detail = _structural_diagnosis(problem)
            conflict = ConflictSet(
                structural_causes=tuple(causes),
                irreducible=False,
                detail="; ".join(detail),
            )
        return SolveResult(
            status=SolverStatus.INFEASIBLE,
            conflict_set=conflict,
            diagnostics=(
                f"no schedule exists under "
                f"{len(problem.constraints.binding)} binding constraint(s)",
            ),
        )

    if raw not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # UNKNOWN is not a weak yes. Nothing was proven, so nothing is returned.
        return SolveResult(
            status=SolverStatus.UNKNOWN,
            diagnostics=(
                f"solver returned {solver.status_name(raw)} within a deterministic "
                f"budget of {budget:g}; no solution was proven and none is reported",
            ),
        )

    assignments = _extract(problem, compiled, solver)

    report = validate_board(
        assignments,
        constraints=problem.constraints,
        work_items=problem.work_items,
        locations=problem.locations,
        roster=problem.roster,
    )
    if not report.passed:
        # The solver proved optimality of a model that does not match the production's
        # constraints. That is the miscompile this whole arrangement exists to catch.
        return SolveResult(
            status=SolverStatus.ERROR,
            diagnostics=(
                "the board the solver proved optimal violates its own constraints, so "
                "the compiled model and the constraint records are not the same "
                "problem -- either a constraint is miscompiled, or one is compiled too "
                "weakly to prevent what it forbids: " + report.summary(),
            ),
        )

    # The model now decides call and wrap too, and `_timeline` derives them again
    # from the anchors. Two readings that must agree; if `_anchor_abs` and the
    # timeline ever drift apart, the turnaround bound would be enforced against times
    # the board does not actually contain.
    if drift := _timeline_drift(assignments, compiled, solver, problem):
        return SolveResult(
            status=SolverStatus.ERROR,
            diagnostics=(
                "the model and the board disagree about when days start or end, so a "
                "turnaround bound was enforced against times the board does not "
                "contain: " + "; ".join(drift),
            ),
        )

    # Every term the objective minimises is read a second time off the finished
    # board. Overtime used to be the exception -- compiled, minimised, then reported
    # from a measurement nothing compared against -- so a miscompile of it would have
    # produced a board proven optimal against a cost it did not have, which is exactly
    # what the other two comparisons exist to prevent (`NNG-003`).
    measured_overtime_minutes = _measure_overtime_minutes(assignments, problem.weights)
    readings = (
        ("company moves", solver.value(compiled.moves), _measure_moves(assignments)),
        (
            "holding days",
            sum(solver.value(h) for h in compiled.held.values()),
            sum(
                holding_days(
                    assignments, work_items=problem.work_items, roster=problem.roster
                ).values()
            ),
        ),
        (
            "overtime minutes",
            sum(solver.value(o) for o in compiled.overtime.values()),
            measured_overtime_minutes,
        ),
    )
    if disagreed := [r for r in readings if r[1] != r[2]]:
        return SolveResult(
            status=SolverStatus.ERROR,
            diagnostics=(
                "the model and the board disagree about what the board costs ("
                + "; ".join(
                    f"{label}: model {model}, board {measured}"
                    for label, model, measured in disagreed
                )
                + "). The objective optimised something other than the board produced.",
            ),
        )
    measured_moves = readings[0][2]
    measured_holding = readings[1][2]

    breakdown = ObjectiveBreakdown(
        company_moves=measured_moves,
        holding_days=measured_holding,
        # The number that was cross-checked, not a second call that could drift from
        # it. Reporting a figure the guard above never saw would put the guard's
        # reassurance behind a value it did not check.
        overtime_hours=round(measured_overtime_minutes / 60, 6),
    )
    status = SolverStatus.OPTIMAL if raw == cp_model.OPTIMAL else SolverStatus.FEASIBLE
    objective, bound = solver.objective_value, solver.best_objective_bound
    gap = 0.0 if status is SolverStatus.OPTIMAL else _relative_gap(objective, bound)
    board = Board(
        board_id=f"{problem.problem_id}-b1",
        schedule_version_id=f"{problem.problem_id}-v1",
        assignments=assignments,
        objective_breakdown=breakdown,
        constraint_snapshot_hash=problem.constraint_snapshot_hash,
        solver_status=status,
        solver_objective_value=objective,
        validation_result=report,
        solver_best_bound=bound,
        optimality_gap=gap,
        solver_parameters=parameters,
        objective_weights=str(problem.weights),
    )
    return SolveResult(status=status, viable_boards=(board,))
