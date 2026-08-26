"""Per-fact-kind search plans.

Search quality is not uniform across fact families, so neither are the requests.
Both remaining families escalate to Extract, for the same reason from opposite
directions: a forecast page's excerpt keeps the current-conditions headline and
drops the per-day table, while an ordinance page's excerpt keeps the prose and
drops the table of permitted hours. In both cases the operative value is the part
compression throws away.

They differ in date binding. A forecast is *about* a specific day and must prove it
mentions that day. A permit rule is a standing rule with no date at all, so demanding
date coverage there would reject the very ordinances the schedule depends on.

Query shape follows the Parallel Search API's guidance: 2-3 concise keyword queries
of 3-6 words each, paired with a self-contained natural-language objective that
carries the intent the keywords cannot.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal

from ..locations import Location
from .facts import FactKind

__all__ = ["QueryPlan", "SearchMode", "plan_for"]

SearchMode = Literal["turbo", "fast", "basic", "advanced"]


@dataclass(frozen=True, slots=True)
class QueryPlan:
    """A fully-specified Search request for one fact, before it is issued."""

    queries: tuple[str, ...]
    objective: str
    mode: SearchMode = "advanced"
    max_results: int = 5
    max_chars_total: int = 6_000
    include_domains: tuple[str, ...] = ()
    exclude_domains: tuple[str, ...] = ()
    after_date: dt.date | None = None
    """Drops sources published before this date. Used where staleness is silent."""
    escalate_top_n: int = 0
    """How many ranked results to pull full contents for. 0 disables escalation."""
    requires_date_coverage: bool = False
    """Whether evidence must explicitly mention the target date to be usable."""

    def __post_init__(self) -> None:
        if not self.queries:
            raise ValueError("a search plan needs at least one query")
        if not self.objective.strip():
            raise ValueError("a search plan needs an objective")

    @property
    def escalate(self) -> bool:
        return self.escalate_top_n > 0


def _weather_plan(location: Location, date: dt.date) -> QueryPlan:
    """Forecast outlook informing exterior risk and replan triggers.

    Escalates several results rather than one. The target day's row may appear on
    any of the returned forecast pages, and which one carries it is not something
    relevance ranking predicts -- the top hit is usually whichever page is most
    about the *place*.

    Staleness compounds the problem: a cached forecast page reads as confident and
    current while describing weather already superseded. `after_date` drops sources
    older than the forecast horizon rather than merely ranking them lower.
    """
    return QueryPlan(
        queries=(
            f"weather forecast {location.place}",
            f"{location.locality} rain forecast {date:%B %-d}",
            f"{location.locality} extended forecast outlook",
        ),
        objective=(
            f"Find the weather forecast for {location.place} on "
            f"{date:%A, %B %-d, %Y}, specifically the precipitation probability, wind "
            f"and temperature for that particular day, to assess the risk to exterior "
            f"scenes scheduled then."
        ),
        mode="advanced",
        max_results=6,
        max_chars_total=12_000,
        after_date=date - dt.timedelta(days=14),
        escalate_top_n=3,
        requires_date_coverage=True,
    )


def _permit_plan(location: Location, date: dt.date) -> QueryPlan:
    """Municipal filming rules: allowed dates, restricted hours, blackout dates.

    Search reliably locates the right ordinance page, but the operative restriction
    is typically a table several headings deep, and excerpt fragments are precisely
    where a plausible-but-wrong permit rule enters the constraint set unnoticed.

    Date coverage is deliberately not required. A filming ordinance is a standing
    rule -- "no filming in the Historic District after 10pm" carries no date at all
    -- so demanding the shoot date appear on the page would reject the authority
    itself and keep only incidental news coverage that happens to mention the day.

    Results default to `.gov` on the assumption that the ordinance is the authority.
    Jurisdictions publishing through a film commission off `.gov` need this widened
    per production -- see `plan_for(..., include_domains=...)`.
    """
    return QueryPlan(
        queries=(
            f"{location.locality} film permit requirements",
            f"{location.locality} filming restricted hours ordinance",
            f"{location.locality} film office blackout dates",
        ),
        objective=(
            f"Find the municipal filming permit rules governing "
            f"{location.name} in {location.place}: which dates filming is permitted, "
            f"any restricted or prohibited hours, and any blackout dates that would "
            f"make the location unavailable on {date:%B %-d, %Y}."
        ),
        mode="advanced",
        max_results=5,
        max_chars_total=12_000,
        include_domains=(".gov",),
        escalate_top_n=1,
        requires_date_coverage=False,
    )


_PLANNERS: dict[FactKind, Callable[[Location, dt.date], QueryPlan]] = {
    FactKind.WEATHER: _weather_plan,
    FactKind.PERMIT: _permit_plan,
}


def plan_for(kind: FactKind, location: Location, date: dt.date, **overrides: object) -> QueryPlan:
    """Build the Search plan for one fact, with optional per-production overrides.

    Overrides exist because source policy is jurisdictional, not universal: the
    `.gov` default for permits is right for most US municipalities and wrong for
    some. Everything else is derived from the fact kind.
    """
    planner = _PLANNERS.get(kind)
    if planner is None:  # pragma: no cover - guarded by the enum
        raise ValueError(f"no search plan defined for fact kind {kind!r}")
    plan = planner(location, date)
    return replace(plan, **overrides) if overrides else plan  # type: ignore[arg-type]
