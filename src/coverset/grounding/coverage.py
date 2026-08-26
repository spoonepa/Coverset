"""Does this retrieved text actually concern the date we asked about?

The question sounds trivial and is not. Forecast and almanac pages are one URL per
*place*, with the date as a query parameter or a page default, so search relevance
reliably returns the right site showing the wrong day. The excerpt that comes back
is maximally on-topic and contains precisely the number that must not be used, and
because a wrong forecast is still well-formed, nothing downstream detects it.

So a date-specific fact has to prove its evidence mentions the date before that
evidence is allowed to become a solver bound.

Weekday labels are deliberately *not* accepted as proof. "Tuesday" is unambiguous
inside a seven-day forecast and silently wrong outside one, and a shooting schedule
routinely reaches further out than that. Requiring an explicit date costs some
otherwise-good sources and removes an entire class of silent misbinding.
"""

from __future__ import annotations

import datetime as dt
import re

__all__ = ["covers_date", "date_patterns"]

_MONTHS = {
    1: r"Jan(?:uary|\.)?", 2: r"Feb(?:ruary|\.)?", 3: r"Mar(?:ch|\.)?",
    4: r"Apr(?:il|\.)?", 5: r"May", 6: r"Jun(?:e|\.)?",
    7: r"Jul(?:y|\.)?", 8: r"Aug(?:ust|\.)?", 9: r"Sep(?:t(?:ember)?|\.)?",
    10: r"Oct(?:ober|\.)?", 11: r"Nov(?:ember|\.)?", 12: r"Dec(?:ember|\.)?",
}
_ORDINAL = r"(?:st|nd|rd|th)?"


def date_patterns(date: dt.date) -> tuple[re.Pattern[str], ...]:
    """Every written form of `date` that counts as an explicit reference to it."""
    month, day, year = _MONTHS[date.month], date.day, date.year
    return tuple(
        re.compile(p, re.IGNORECASE)
        for p in (
            rf"{month}\s+0?{day}{_ORDINAL}\b",          # September 1 / Sep 1st
            rf"\b0?{day}{_ORDINAL}\s+{month}\b",        # 1 September
            rf"\b{year}-{date.month:02d}-{date.day:02d}\b",   # 2026-09-01
            rf"\b0?{date.month}[/-]0?{day}(?:[/-]{year})?\b",  # 9/1 or 09/01/2026
        )
    )


def covers_date(text: str, date: dt.date) -> bool:
    """True when `text` explicitly refers to `date` in any common written form."""
    return any(p.search(text) for p in date_patterns(date))
