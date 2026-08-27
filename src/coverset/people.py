"""Cast and crew.

The people a schedule is built around. They do not operate Coverset -- they receive
call sheets from it -- but they are what most of the constraint set is *about*:
availability windows, contracted day minimums, holding-day cost, turnaround between
wrap and next call, and restricted hours for minors.

Modelled as typed entities rather than names on a coverage item, for the same reason
the decider on a review became an `Actor`: a bare string cannot be checked. "SARAH"
and "SARA" are indistinguishable to a scheduler and differ by one person, and the
failure is silent -- the board simply schedules someone who does not exist and never
notices the real performer was never called.

Legal note: the turnaround and minor-hours defaults below are illustrative
production norms, not legal or union authority. Real SAG-AFTRA, IATSE and DGA rules
and jurisdiction-specific child labour limits belong in pluggable constraint
libraries (CST-008), which the brief places after the hackathon.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Iterator

from .clock import elapsed

__all__ = [
    "DEFAULT_CAST_TURNAROUND_HOURS",
    "DEFAULT_CREW_TURNAROUND_HOURS",
    "DEFAULT_MINOR_MAX_WORK_HOURS",
    "AvailabilityWindow",
    "CastMember",
    "Company",
    "Engagement",
    "Roster",
    "UnknownCastMember",
]

DEFAULT_CAST_TURNAROUND_HOURS = 12.0
DEFAULT_CREW_TURNAROUND_HOURS = 10.0
DEFAULT_MINOR_MAX_WORK_HOURS = 8.0
"""Illustrative norms. Actual limits vary by union agreement, jurisdiction and age."""


class UnknownCastMember(KeyError):
    """A coverage item named someone who is not on the roster.

    Almost always a typo, and one worth catching loudly: a misspelled cast ID
    schedules a person who does not exist while the real performer is never called.
    """


@dataclass(frozen=True, slots=True)
class AvailabilityWindow:
    """A date range during which a performer can be scheduled. Inclusive of both ends."""

    start: dt.date
    end: dt.date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"availability window ends before it starts: {self}")

    def __str__(self) -> str:
        return f"{self.start.isoformat()}..{self.end.isoformat()}"

    def covers(self, day: dt.date) -> bool:
        return self.start <= day <= self.end

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


@dataclass(frozen=True, slots=True)
class CastMember:
    """A performer, and the contractual shape of their engagement."""

    id: str
    name: str
    character: str
    availability: tuple[AvailabilityWindow, ...] = ()
    """Empty means unrestricted -- available for the whole shoot."""
    contracted_days: int | None = None
    """Guaranteed paid days. Paid whether worked or held."""
    is_minor: bool = False
    minimum_turnaround_hours: float = DEFAULT_CAST_TURNAROUND_HOURS
    max_work_hours_per_day: float | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("a cast member needs an id")
        if self.contracted_days is not None and self.contracted_days <= 0:
            raise ValueError(f"{self.id}: contracted days must be positive")
        if self.is_minor and self.max_work_hours_per_day is None:
            object.__setattr__(self, "max_work_hours_per_day", DEFAULT_MINOR_MAX_WORK_HOURS)

    def __str__(self) -> str:
        return f"{self.name} as {self.character}"

    def is_available_on(self, day: dt.date) -> bool:
        """True when the performer may be scheduled on `day`."""
        if not self.availability:
            return True
        return any(w.covers(day) for w in self.availability)

    def unavailable_among(self, days: tuple[dt.date, ...]) -> tuple[dt.date, ...]:
        """Which of `days` fall outside every availability window."""
        return tuple(d for d in days if not self.is_available_on(d))


@dataclass(frozen=True, slots=True)
class Roster:
    """Every performer on the production, addressable by id."""

    members: tuple[CastMember, ...] = ()

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for m in self.members:
            if m.id in seen:
                raise ValueError(f"duplicate cast id on the roster: {m.id}")
            seen.add(m.id)

    def __iter__(self) -> Iterator[CastMember]:
        return iter(self.members)

    def __len__(self) -> int:
        return len(self.members)

    def __getitem__(self, cast_id: str) -> CastMember:
        for m in self.members:
            if m.id == cast_id:
                return m
        raise UnknownCastMember(
            f"{cast_id!r} is not on the roster; known ids: "
            f"{', '.join(sorted(m.id for m in self.members)) or '(empty)'}"
        )

    def resolve(self, cast_ids: tuple[str, ...]) -> tuple[CastMember, ...]:
        """Turn ids into performers, naming every unknown one at once.

        Reports all failures together rather than the first: an AD fixing a
        breakdown wants the full list of typos, not one per run.
        """
        known = {m.id for m in self.members}
        if unknown := [c for c in cast_ids if c not in known]:
            raise UnknownCastMember(
                f"not on the roster: {', '.join(sorted(unknown))}; known ids: "
                f"{', '.join(sorted(known)) or '(empty)'}"
            )
        return tuple(self[c] for c in cast_ids)

    def available_on(self, day: dt.date) -> tuple[CastMember, ...]:
        return tuple(m for m in self.members if m.is_available_on(day))


@dataclass(frozen=True, slots=True)
class Engagement:
    """What a performer is owed for a given set of work days.

    A performer held between their first and last day is paid for the gap, which is
    why scattering one actor's scenes across the board is expensive even when the
    number of days worked is unchanged. This is the cost the objective minimises and
    the one the brief surfaces as *"burns 1 of Sarah's 12 contracted days"*.

    Simplified against real contracts, which distinguish daily from weekly players
    and allow drop/pickup. See CST-008.
    """

    member: CastMember
    work_days: tuple[dt.date, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "work_days", tuple(sorted(set(self.work_days))))

    @property
    def worked_days(self) -> int:
        return len(self.work_days)

    @property
    def span_days(self) -> int:
        """First call to final wrap, inclusive. Zero if never scheduled."""
        if not self.work_days:
            return 0
        return (self.work_days[-1] - self.work_days[0]).days + 1

    @property
    def held_days(self) -> int:
        """Days retained but not working. Paid, and pure waste."""
        return max(0, self.span_days - self.worked_days)

    @property
    def billable_days(self) -> int:
        """What the production pays: the engagement, or the contract, whichever is more."""
        return max(self.member.contracted_days or 0, self.span_days)

    @property
    def contract_overrun(self) -> int:
        """Days beyond the guarantee. Each one is new money."""
        if self.member.contracted_days is None:
            return 0
        return max(0, self.span_days - self.member.contracted_days)

    @property
    def violates_availability(self) -> tuple[dt.date, ...]:
        """Scheduled days falling outside every stated availability window."""
        return self.member.unavailable_among(self.work_days)


@dataclass(frozen=True, slots=True)
class Company:
    """The crew as a scheduling unit.

    Crew are scheduled collectively -- one call, one wrap -- so turnaround and day
    length are company-wide rather than per-person. Individual crew members are not
    modelled: nothing in the schedule varies by which grip is working.
    """

    minimum_turnaround_hours: float = DEFAULT_CREW_TURNAROUND_HOURS
    maximum_day_hours: float = 12.0

    def turnaround_satisfied(self, wrap: dt.datetime, next_call: dt.datetime) -> bool:
        """Whether the rest between wrap and the next call meets the minimum.

        Elapsed time, not the difference of two clock faces: a wrap at 23:00 and a
        call at 11:00 across the spring forward is eleven hours of rest, and the
        performer is an hour short in exactly the way this method exists to prevent.
        """
        rest = elapsed(wrap, next_call).total_seconds() / 3600
        return rest >= self.minimum_turnaround_hours
