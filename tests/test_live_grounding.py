"""Live verification against the real Parallel API.

Deselected by default; run with `uv run pytest -m live` and a `PARALLEL_API_KEY`.

These exist because the offline suite cannot prove the world agrees with it. Its
fixtures encode what the API was *assumed* to return, and every finding recorded in
the brief came from a live run contradicting one of those assumptions. Offline tests
verify wiring; these verify reality.

Assertions are structural rather than exact -- the live web changes, and a test that
pins a precipitation percentage would fail for the wrong reason. What is pinned is
what must hold for the grounding contract to mean anything.
"""

from __future__ import annotations

import datetime as dt
import os

import pytest

from coverset.grounding import FactKind, SearchGrounder
from coverset.locations import Location

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("PARALLEL_API_KEY"),
        reason="PARALLEL_API_KEY not set",
    ),
]

CHURCH = Location(
    name="First African Baptist Church",
    locality="Savannah",
    region="Georgia",
    latitude=32.0809,
    longitude=-81.0912,
    timezone="America/New_York",
)
NEAR_DATE = dt.date.today() + dt.timedelta(days=6)
"""Inside any real forecast horizon, so a forecast for it genuinely exists."""


@pytest.fixture(scope="module")
def grounder():
    return SearchGrounder()


@pytest.fixture(scope="module")
def weather(grounder):
    return grounder.ground(FactKind.WEATHER, CHURCH, NEAR_DATE)


@pytest.fixture(scope="module")
def permit(grounder):
    return grounder.ground(FactKind.PERMIT, CHURCH, NEAR_DATE)


@pytest.mark.req("TRK-001", "GRD-011")
def test_the_live_search_api_accepts_our_request_shape(weather):
    # A 4xx on any parameter would surface here rather than in production.
    assert weather.search_id.startswith("search_")
    assert weather.session_id


@pytest.mark.req("GRD-001", "AUD-002")
def test_live_evidence_carries_real_source_urls(weather):
    assert weather.sources
    assert all(s.url.startswith("http") for s in weather.sources)
    assert weather.source_urls


@pytest.mark.req("GRD-003")
def test_a_real_forecast_inside_the_horizon_covers_the_target_date(weather):
    # The defect that motivated the guard: live Search returned the right site
    # showing the wrong day. At least one source must genuinely name the date.
    assert weather.covering_urls, (
        f"no live source explicitly mentioned {NEAR_DATE:%B %-d, %Y}; "
        f"sources: {weather.source_urls}"
    )
    assert all(s.text for s in weather.dated_sources)


@pytest.mark.req("TRK-002")
def test_live_extract_returns_full_page_contents(weather):
    assert weather.escalated is True
    assert any(s.full_content for s in weather.sources)


@pytest.mark.req("GRD-006")
def test_live_weather_sources_are_within_the_forecast_horizon(weather):
    horizon = NEAR_DATE - dt.timedelta(days=14)
    dated = [s.publish_date for s in weather.sources if s.publish_date]
    assert dated, "no live weather source reported a publish date"
    assert all(dt.date.fromisoformat(d) >= horizon for d in dated)


@pytest.mark.req("GRD-005")
def test_live_permit_search_reaches_authoritative_sources(permit):
    assert permit.sources
    assert all(".gov" in s.url for s in permit.sources), permit.source_urls


@pytest.mark.req("GRD-004")
def test_a_real_permit_page_grounds_without_naming_the_shoot_date(permit):
    # A standing ordinance carries no date. This must not be rejected.
    assert permit.covering_urls == ()
    assert permit.escalated is True
    assert any(s.full_content for s in permit.sources)


@pytest.mark.req("GRD-008")
def test_the_session_is_shared_across_live_calls(grounder, weather, permit):
    assert grounder.session_id
    assert permit.session_id
