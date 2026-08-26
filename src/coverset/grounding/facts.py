"""Typed evidence records for externally-grounded scheduling constraints.

Only facts that genuinely cannot be computed live here. Daylight used to and no
longer does: sunrise and sunset are solar geometry, and `coverset.daylight` derives
them exactly. What remains is weather and permits -- contingent, changing, and with
no closed form, which is what makes them worth retrieving.

Provenance is structural rather than advisory: `Evidence` cannot be constructed
without at least one source URL. Evidence with no source is not weaker evidence, it
is a bug, and it raises rather than reaching the solver unsourced, where it would
silently widen the feasible region.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import StrEnum

from ..locations import Location

__all__ = [
    "DateCoverageError",
    "Evidence",
    "FactKind",
    "GroundingError",
    "GroundingUnavailable",
    "Location",
    "SourceExcerpt",
]


class GroundingError(Exception):
    """Base for failures in the grounding path."""


class GroundingUnavailable(GroundingError):
    """No authoritative source was found for a requested fact.

    Raised rather than returning empty evidence. A constraint the solver never
    learns about is a constraint the board is free to violate, so an ungrounded
    fact must stop the pipeline instead of quietly relaxing it.
    """


class DateCoverageError(GroundingError):
    """Sources were found, but none of them concerns the date that was asked about.

    The dangerous case, and the reason this exception exists separately: the
    retrieved text is on-topic, well-formed, and full of plausible values for some
    *other* day. Extraction would succeed and produce a confident wrong bound.
    """


class FactKind(StrEnum):
    """The fact families that must be retrieved because they cannot be computed."""

    WEATHER = "weather"
    PERMIT = "permit"


@dataclass(frozen=True, slots=True)
class SourceExcerpt:
    """One retrieved source backing a fact.

    `full_content` is populated only when the Extract escalation ran. Its absence
    means the excerpts are all that was retrieved, which callers doing structured
    extraction need to know: reconstructing a rule from fragments is exactly where
    a plausible-but-wrong constraint enters the model unnoticed.
    """

    url: str
    excerpts: tuple[str, ...]
    title: str | None = None
    publish_date: str | None = None
    full_content: str | None = None

    def __post_init__(self) -> None:
        if not self.url.strip():
            raise ValueError("a source excerpt must carry its URL")

    @property
    def text(self) -> str:
        """The best available text for this source, preferring full content."""
        return self.full_content or "\n\n".join(self.excerpts)


@dataclass(frozen=True, slots=True)
class Evidence:
    """Retrieved, sourced material for one fact, ready for typed extraction.

    This is the output of the Search path and the input to Gemini extraction. It is
    deliberately not a constraint: nothing here has been interpreted yet.
    """

    kind: FactKind
    location: Location
    date: dt.date
    sources: tuple[SourceExcerpt, ...]
    search_id: str
    session_id: str
    retrieved_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))
    escalated: bool = False
    """True when Extract retrieved full page contents beyond Search's excerpts."""
    covering_urls: tuple[str, ...] = ()
    """Sources that explicitly mention `date`.

    Empty for facts that are not date-specific, such as a standing permit rule.
    For date-specific facts this is the subset extraction may bind a dated value
    from; the other sources are context only.
    """

    def __post_init__(self) -> None:
        if not self.sources:
            raise GroundingUnavailable(
                f"no source found for {self.kind} at {self.location.place} "
                f"on {self.date.isoformat()}"
            )

    @property
    def primary(self) -> SourceExcerpt:
        """The most relevant source; Search orders results by decreasing relevance."""
        return self.sources[0]

    @property
    def source_urls(self) -> tuple[str, ...]:
        """Every URL backing this fact, for the audit trail on the derived constraint."""
        return tuple(s.url for s in self.sources)

    @property
    def dated_sources(self) -> tuple[SourceExcerpt, ...]:
        """The sources that demonstrably concern `date`."""
        covering = set(self.covering_urls)
        return tuple(s for s in self.sources if s.url in covering)
