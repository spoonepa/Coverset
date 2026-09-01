from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.live


@pytest.mark.req("TRK-003", "MON-001", "MON-003", "MON-004")
def test_live_parallel_monitor_contract_is_opt_in():
    if os.getenv("COVERSET_ENABLE_LIVE_MONITOR_TEST") != "1":
        pytest.skip(
            "set COVERSET_ENABLE_LIVE_MONITOR_TEST=1 to create/check a live monitor"
        )
    if not os.getenv("PARALLEL_API_KEY"):
        pytest.skip("PARALLEL_API_KEY is required for live Parallel Monitor checks")

    import parallel  # type: ignore[import-not-found]

    client = parallel.Client()
    assert hasattr(client, "monitor")


@pytest.mark.req("WEA-001", "WEA-002", "GRD-010")
def test_live_weather_completion_contract_is_opt_in():
    if os.getenv("COVERSET_ENABLE_LIVE_WEATHER_TEST") != "1":
        pytest.skip(
            "set COVERSET_ENABLE_LIVE_WEATHER_TEST=1 to run live weather grounding"
        )
    if not os.getenv("PARALLEL_API_KEY"):
        pytest.skip("PARALLEL_API_KEY is required for live weather grounding")

    from coverset.grounding import FactKind, SearchGrounder
    from coverset.locations import Location

    location = Location(
        "Brooklyn Bridge Park",
        "Brooklyn",
        "NY",
        id="brooklyn-bridge-park",
        latitude=40.7002,
        longitude=-73.9967,
        timezone="America/New_York",
    )
    evidence = SearchGrounder().ground(
        FactKind.WEATHER, location, __import__("datetime").date.today()
    )
    assert evidence.source_urls
