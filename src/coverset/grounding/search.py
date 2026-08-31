"""The runtime grounding path: Parallel Search -> sourced evidence.

    location + date -> Parallel Search -> source URL + excerpt
                    -> Gemini extraction -> validated typed constraint
                    -> CP-SAT bound

This module owns the first arrow. It returns `Evidence`, never a constraint:
nothing here interprets what was retrieved.

TRACK REQUIREMENT -- do not refactor around this.
    Parallel Search is called at runtime, on every grounding request. This is a
    hard eligibility requirement, not a performance tradeoff, and it is the reason
    there is no cache, no precomputed fact table, and no offline fallback in this
    module. `tests/test_search_grounding.py` asserts the wire call to `/v1/search`
    for exactly this reason; if that test starts failing, the fix is to restore the
    runtime call, not to relax the test.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, cast

from parallel import APIError, Parallel  # type: ignore[import-not-found]
from parallel.types import (  # type: ignore[import-not-found]
    ExtractResponse,
    SearchResult,
)

from ..locations import Location
from .coverage import covers_date
from .facts import (
    DateCoverageError,
    Evidence,
    FactKind,
    GroundingError,
    GroundingUnavailable,
    SourceExcerpt,
)
from .queries import QueryPlan, plan_for

__all__ = ["SearchGrounder"]

CLIENT_MODEL = "gemini-2.5-pro"
"""Declared to Parallel so excerpt compression is tuned for the consuming model.

Coverset's extraction step is Gemini; telling Search that lets it size and shape
excerpts for that context rather than for a generic caller.
"""


class SearchGrounder:
    """Grounds scheduling facts against the live web via Parallel.

    One grounder per replan. Parallel threads a `session_id` across Search and
    Extract calls belonging to the same task and uses it to improve contextual
    relevance, so a grounder that outlives a single replan would be pooling
    unrelated context and degrading results.
    """

    def __init__(
        self, client: Parallel | None = None, *, session_id: str | None = None
    ) -> None:
        self._client = client if client is not None else Parallel()
        self._session_id = session_id

    @property
    def session_id(self) -> str | None:
        """The Parallel session shared by this replan's Search and Extract calls."""
        return self._session_id

    def ground(
        self, kind: FactKind, location: Location, date: dt.date, **overrides: Any
    ) -> Evidence:
        """Retrieve sourced evidence for one fact. Always hits the network.

        Raises:
            GroundingUnavailable: no source was found at all.
            DateCoverageError: sources were found, but for a date-specific fact none
                of them mentions the requested date. Proceeding would let extraction
                bind a plausible value belonging to some other day.
            GroundingError: the Search or Extract call itself failed.
        """
        plan = plan_for(kind, location, date, **overrides)
        result = self._search(plan, kind, location, date)

        sources = tuple(
            SourceExcerpt(
                url=r.url,
                excerpts=tuple(r.excerpts),
                title=r.title,
                publish_date=r.publish_date,
            )
            for r in result.results
        )
        if not sources:
            raise GroundingUnavailable(
                f"Parallel Search returned no results for {kind} at "
                f"{location.place} on {date.isoformat()} "
                f"(search_id={result.search_id})"
            )

        self._session_id = result.session_id

        # Escalate before checking coverage: the target day's row is usually in the
        # part of the page that excerpt compression discarded, so full content is
        # what turns an apparently date-blind source into a usable one.
        escalated = False
        if plan.escalate:
            sources, escalated = self._escalate(plan, sources)

        covering = tuple(s.url for s in sources if covers_date(s.text, date))
        if plan.requires_date_coverage and not covering:
            raise DateCoverageError(
                f"{len(sources)} source(s) found for {kind} at {location.place}, but "
                f"none explicitly mentions {date:%B %-d, %Y}"
                f"{' even after full-content retrieval' if escalated else ''}. "
                f"Refusing to bind a value that may belong to another day. "
                f"Sources: {', '.join(s.url for s in sources[:3])}"
            )

        return Evidence(
            kind=kind,
            location=location,
            date=date,
            sources=sources,
            search_id=result.search_id,
            session_id=result.session_id,
            retrieved_at=dt.datetime.now(dt.UTC),
            escalated=escalated,
            covering_urls=covering,
        )

    def _search(
        self, plan: QueryPlan, kind: FactKind, location: Location, date: dt.date
    ) -> SearchResult:
        settings: dict[str, Any] = {
            "max_results": plan.max_results,
            "location": location.country,
        }
        if source_policy := _source_policy(plan):
            settings["source_policy"] = source_policy

        kwargs: dict[str, Any] = {
            "search_queries": list(plan.queries),
            "objective": plan.objective,
            "mode": plan.mode,
            "max_chars_total": plan.max_chars_total,
            "client_model": CLIENT_MODEL,
            "advanced_settings": settings,
        }
        if self._session_id:
            kwargs["session_id"] = self._session_id

        try:
            return cast(SearchResult, cast(Any, self._client).search(**kwargs))
        except APIError as exc:
            raise GroundingError(
                f"Parallel Search failed grounding {kind} for {location.place} "
                f"on {date.isoformat()}: {exc}"
            ) from exc

    def _escalate(
        self, plan: QueryPlan, sources: tuple[SourceExcerpt, ...]
    ) -> tuple[tuple[SourceExcerpt, ...], bool]:
        """Retrieve the top-ranked pages in full via Extract.

        Escalation failure is not fatal. The excerpts are still real, sourced text,
        and evidence is returned with `escalated=False` so the extraction step can
        see it is working from fragments and lower its confidence accordingly.
        """
        targets = sources[: plan.escalate_top_n]
        kwargs: dict[str, Any] = {
            "urls": [s.url for s in targets],
            "objective": plan.objective,
            "search_queries": list(plan.queries),
            "max_chars_total": plan.max_chars_total,
            "client_model": CLIENT_MODEL,
            "advanced_settings": {
                "full_content": {"max_chars_per_result": plan.max_chars_total}
            },
        }
        if self._session_id:
            kwargs["session_id"] = self._session_id

        try:
            response = cast(ExtractResponse, cast(Any, self._client).extract(**kwargs))
        except APIError:
            return sources, False

        full_by_url = {r.url: r for r in response.results if r.full_content}
        if not full_by_url:
            return sources, False

        enriched = tuple(
            SourceExcerpt(
                url=s.url,
                excerpts=tuple(full.excerpts) or s.excerpts,
                title=full.title or s.title,
                publish_date=full.publish_date or s.publish_date,
                full_content=full.full_content,
            )
            if (full := full_by_url.get(s.url)) is not None
            else s
            for s in sources
        )
        return enriched, True


def _source_policy(plan: QueryPlan) -> dict[str, Any]:
    """Build the Search source policy, omitting it entirely when unconstrained."""
    policy: dict[str, Any] = {}
    if plan.include_domains:
        policy["include_domains"] = list(plan.include_domains)
    if plan.exclude_domains:
        policy["exclude_domains"] = list(plan.exclude_domains)
    if plan.after_date:
        policy["after_date"] = plan.after_date
    return policy
