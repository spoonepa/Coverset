"""Elapsed time between two instants.

One function, because getting it wrong is silent and this project already paid for
one hour-shaped bug (`PROJECT_BRIEF.md`, daylight across a DST boundary).

Python defines subtraction between two aware datetimes that carry the *same* tzinfo
object as naive: "the common tzinfo attribute is ignored and the result is a
timedelta". Every time on a board carries the same `Location.zone`, so `wrap - call`
returns the wall-clock difference, not the elapsed one. On the night the clocks go
back, a call at 17:53 EDT and a wrap at 05:53 EST subtract to twelve hours and really
ran thirteen.

That is not a cross-check the two-readings arrangement could have caught. The
compiled model and the independent validator both subtracted the same way and agreed
with each other, which is exactly the failure `CLAUDE.md` warns about: cross-checks
catch disagreement, never a shared misconception. So the fix is one definition both
sides call, not a second opinion.

`DAY-009` is the requirement: times are timezone-aware and DST-correct for the date
in question. Wall-clock arithmetic is neither.
"""

from __future__ import annotations

import datetime as dt

__all__ = ["advance", "elapsed"]


def elapsed(start: dt.datetime, end: dt.datetime) -> dt.timedelta:
    """Real time from `start` to `end`, as a crew on the clock would count it.

    Both instants are normalised to UTC first, so the answer does not depend on
    whether they happen to share a tzinfo object.
    """
    return end.astimezone(dt.timezone.utc) - start.astimezone(dt.timezone.utc)


def advance(when: dt.datetime, by: dt.timedelta) -> dt.datetime:
    """`when` plus `by` of real elapsed time, back in `when`'s own timezone.

    The inverse of `elapsed`, and needed for the same reason: adding a timedelta to
    an aware datetime moves the *wall clock*, so a twelve-hour scene starting at
    17:53 the night the clocks go back would be recorded as wrapping at 05:53 -- an
    hour before the twelve hours are up.
    """
    zone = when.tzinfo
    return (when.astimezone(dt.timezone.utc) + by).astimezone(zone)
