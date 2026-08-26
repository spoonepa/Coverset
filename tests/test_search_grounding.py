"""Tests for the Parallel Search grounding path."""

from __future__ import annotations

import datetime as dt

import pytest
from conftest import (
    EXTRACT_PATH,
    FORECAST_URL,
    PERMIT_URL,
    SEARCH_PATH,
    extract_payload,
    permit_extract_payload,
    permit_search_payload,
    search_payload,
)

from coverset.grounding import (
    DateCoverageError,
    Evidence,
    FactKind,
    GroundingError,
    GroundingUnavailable,
    Location,
    SearchGrounder,
    SourceExcerpt,
)

SHOOT_DATE = dt.date(2026, 3, 17)
CHURCH = Location(
    name="First African Baptist Church", locality="Savannah", region="Georgia"
)


# --------------------------------------------------------------------------
# Track eligibility guard.
#
# Parallel Search must be called at runtime. These assert that at the wire, not
# at the call site, so no refactoring above them can satisfy the requirement on
# paper while bypassing it in practice. If they fail, restore the runtime call --
# do not relax the assertion.
# --------------------------------------------------------------------------


@pytest.mark.req("TRK-001")
def test_grounding_calls_parallel_search_at_runtime(parallel_stub):
    client, recorder = parallel_stub(search=permit_search_payload(), extract=permit_extract_payload())

    SearchGrounder(client).ground(FactKind.PERMIT, CHURCH, SHOOT_DATE)

    assert SEARCH_PATH in recorder.paths()


@pytest.mark.req("TRK-001")
def test_repeated_grounding_is_not_served_from_a_cache(parallel_stub):
    client, recorder = parallel_stub(search=permit_search_payload(), extract=permit_extract_payload())
    grounder = SearchGrounder(client)

    grounder.ground(FactKind.PERMIT, CHURCH, SHOOT_DATE)
    grounder.ground(FactKind.PERMIT, CHURCH, SHOOT_DATE)

    assert len(recorder.of(SEARCH_PATH)) == 2


# --------------------------------------------------------------------------
# Request shape
# --------------------------------------------------------------------------


@pytest.mark.req("GRD-011")
def test_search_request_carries_queries_objective_and_consuming_model(parallel_stub):
    client, recorder = parallel_stub()

    SearchGrounder(client).ground(FactKind.WEATHER, CHURCH, SHOOT_DATE)

    body = recorder.only(SEARCH_PATH).body
    assert 1 <= len(body["search_queries"]) <= 3
    assert all(3 <= len(q.split()) <= 6 for q in body["search_queries"])
    assert "March 17, 2026" in body["objective"]
    assert body["client_model"] == "gemini-2.5-pro"
    assert body["mode"] == "advanced"


@pytest.mark.req("GRD-011")
def test_search_is_geo_targeted_to_the_location_country(parallel_stub):
    client, recorder = parallel_stub()

    SearchGrounder(client).ground(FactKind.WEATHER, CHURCH, SHOOT_DATE)

    assert recorder.only(SEARCH_PATH).settings["location"] == "US"


@pytest.mark.req("GRD-005")
def test_permit_search_restricts_to_authoritative_sources(parallel_stub):
    client, recorder = parallel_stub(search=permit_search_payload(), extract=permit_extract_payload())

    SearchGrounder(client).ground(FactKind.PERMIT, CHURCH, SHOOT_DATE)

    assert recorder.only(SEARCH_PATH).source_policy["include_domains"] == [".gov"]


@pytest.mark.req("GRD-006")
def test_weather_search_drops_sources_older_than_the_forecast_horizon(parallel_stub):
    client, recorder = parallel_stub()

    SearchGrounder(client).ground(FactKind.WEATHER, CHURCH, SHOOT_DATE)

    assert recorder.only(SEARCH_PATH).source_policy["after_date"] == "2026-03-03"


@pytest.mark.req("GRD-005")
def test_per_production_overrides_widen_the_permit_source_policy(parallel_stub):
    client, recorder = parallel_stub(search=permit_search_payload(), extract=permit_extract_payload())

    SearchGrounder(client).ground(
        FactKind.PERMIT, CHURCH, SHOOT_DATE, include_domains=("savannahfilm.org",)
    )

    assert recorder.only(SEARCH_PATH).source_policy["include_domains"] == [
        "savannahfilm.org"
    ]


# --------------------------------------------------------------------------
# Date coverage -- the guard against binding a value from the wrong day
# --------------------------------------------------------------------------


@pytest.mark.req("GRD-003")
def test_weather_evidence_records_which_sources_mention_the_date(parallel_stub):
    client, _ = parallel_stub()

    evidence = SearchGrounder(client).ground(FactKind.WEATHER, CHURCH, SHOOT_DATE)

    assert evidence.covering_urls == (FORECAST_URL,)
    assert [s.url for s in evidence.dated_sources] == [FORECAST_URL]


@pytest.mark.req("GRD-003")
def test_weather_for_the_wrong_day_is_refused_rather_than_bound(parallel_stub):
    # Every source is on-topic, well-formed, and describes March 11 instead of the
    # 17th. This is the failure that motivated the guard: extraction would have
    # succeeded and produced a confident wrong precipitation probability.
    client, _ = parallel_stub(extract=extract_payload(dated=False))

    with pytest.raises(DateCoverageError) as excinfo:
        SearchGrounder(client).ground(FactKind.WEATHER, CHURCH, SHOOT_DATE)

    assert "March 17, 2026" in str(excinfo.value)
    assert "another day" in str(excinfo.value)


@pytest.mark.req("GRD-004")
def test_permit_rules_are_not_required_to_mention_the_shoot_date(parallel_stub):
    # A standing ordinance carries no date at all. Requiring one here would reject
    # the authority and keep only incidental coverage that happens to name the day.
    client, _ = parallel_stub(search=permit_search_payload(), extract=permit_extract_payload())

    evidence = SearchGrounder(client).ground(FactKind.PERMIT, CHURCH, SHOOT_DATE)

    assert evidence.covering_urls == ()
    assert "Historic District" in evidence.primary.full_content


@pytest.mark.req("GRD-003", "TRK-002")
def test_coverage_is_checked_after_escalation_not_before(parallel_stub):
    # The target day's row lives in the part of the page excerpting discarded, so
    # checking coverage on excerpts alone would reject sources that do carry it.
    client, recorder = parallel_stub()

    evidence = SearchGrounder(client).ground(FactKind.WEATHER, CHURCH, SHOOT_DATE)

    assert recorder.of(EXTRACT_PATH), "escalation must run before the coverage check"
    assert evidence.covering_urls  # only discoverable in full content


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------


@pytest.mark.req("GRD-001", "AUD-002")
def test_evidence_carries_every_source_url(parallel_stub):
    client, _ = parallel_stub()

    evidence = SearchGrounder(client).ground(FactKind.WEATHER, CHURCH, SHOOT_DATE)

    assert PERMIT_URL in evidence.source_urls
    assert evidence.search_id.startswith("search_")
    assert evidence.retrieved_at.tzinfo is dt.UTC


@pytest.mark.req("GRD-001", "GRD-002")
def test_evidence_cannot_exist_without_a_source():
    with pytest.raises(GroundingUnavailable):
        Evidence(
            kind=FactKind.WEATHER,
            location=CHURCH,
            date=SHOOT_DATE,
            sources=(),
            search_id="search_x",
            session_id="sess_x",
        )


@pytest.mark.req("GRD-001")
def test_a_source_excerpt_cannot_exist_without_its_url():
    with pytest.raises(ValueError, match="must carry its URL"):
        SourceExcerpt(url="  ", excerpts=("85%",))


# --------------------------------------------------------------------------
# Failure handling -- an ungrounded fact must stop the pipeline, not relax it
# --------------------------------------------------------------------------


@pytest.mark.req("GRD-002")
def test_no_results_raises_rather_than_returning_empty_evidence(parallel_stub):
    client, _ = parallel_stub(search=search_payload(results=[]))

    with pytest.raises(GroundingUnavailable, match="no results"):
        SearchGrounder(client).ground(FactKind.PERMIT, CHURCH, SHOOT_DATE)


@pytest.mark.req("GRD-002")
def test_search_failure_is_reported_with_the_fact_it_was_grounding(parallel_stub):
    client, _ = parallel_stub(search_status=500)

    with pytest.raises(GroundingError) as excinfo:
        SearchGrounder(client).ground(FactKind.PERMIT, CHURCH, SHOOT_DATE)

    assert "permit" in str(excinfo.value)
    assert "Savannah, Georgia" in str(excinfo.value)
    assert "2026-03-17" in str(excinfo.value)


# --------------------------------------------------------------------------
# Extract escalation
# --------------------------------------------------------------------------


@pytest.mark.req("TRK-002")
def test_permit_grounding_escalates_to_the_single_authoritative_page(parallel_stub):
    client, recorder = parallel_stub(search=permit_search_payload(), extract=permit_extract_payload())

    evidence = SearchGrounder(client).ground(FactKind.PERMIT, CHURCH, SHOOT_DATE)

    call = recorder.only(EXTRACT_PATH)
    assert call.body["urls"] == [PERMIT_URL]  # the top-ranked ordinance page
    assert call.settings["full_content"] == {"max_chars_per_result": 12_000}
    assert evidence.escalated is True


@pytest.mark.req("TRK-002")
def test_weather_escalates_several_results_since_any_may_carry_the_day(parallel_stub):
    client, recorder = parallel_stub()

    SearchGrounder(client).ground(FactKind.WEATHER, CHURCH, SHOOT_DATE)

    assert len(recorder.only(EXTRACT_PATH).body["urls"]) == 3


@pytest.mark.req("GRD-007", "AUD-003")
def test_extract_failure_degrades_to_excerpts_and_flags_it(parallel_stub):
    client, recorder = parallel_stub(search=permit_search_payload(), extract_status=500)

    evidence = SearchGrounder(client).ground(FactKind.PERMIT, CHURCH, SHOOT_DATE)

    assert recorder.of(EXTRACT_PATH) != []
    assert evidence.escalated is False
    assert evidence.primary.full_content is None
    assert evidence.primary.excerpts  # still real, sourced text


@pytest.mark.req("GRD-007", "AUD-003")
def test_extract_returning_no_full_content_is_not_reported_as_escalated(parallel_stub):
    client, _ = parallel_stub(search=permit_search_payload(),
                              extract=extract_payload(omit_full_content=True, urls=[PERMIT_URL]))

    evidence = SearchGrounder(client).ground(FactKind.PERMIT, CHURCH, SHOOT_DATE)

    assert evidence.escalated is False


@pytest.mark.req("TRK-002")
def test_source_text_prefers_full_content_over_excerpts(parallel_stub):
    client, _ = parallel_stub(search=permit_search_payload(), extract=permit_extract_payload())

    evidence = SearchGrounder(client).ground(FactKind.PERMIT, CHURCH, SHOOT_DATE)

    assert evidence.primary.text.startswith("# Filming Regulations")


@pytest.mark.req("GRD-007")
def test_sources_that_were_not_escalated_keep_their_excerpts(parallel_stub):
    client, _ = parallel_stub(search=permit_search_payload(), extract=permit_extract_payload())

    evidence = SearchGrounder(client).ground(FactKind.PERMIT, CHURCH, SHOOT_DATE)

    untouched = [s for s in evidence.sources if s.url != PERMIT_URL]
    assert all(s.full_content is None for s in untouched)
    assert all(s.excerpts for s in untouched)


# --------------------------------------------------------------------------
# Session threading
# --------------------------------------------------------------------------


@pytest.mark.req("GRD-008")
def test_session_is_threaded_across_search_and_extract_in_one_replan(parallel_stub):
    client, recorder = parallel_stub()
    grounder = SearchGrounder(client)

    grounder.ground(FactKind.WEATHER, CHURCH, SHOOT_DATE)
    grounder.ground(FactKind.WEATHER, CHURCH, SHOOT_DATE)

    assert grounder.session_id == "sess_grounding_001"
    assert recorder.of(SEARCH_PATH)[0].body.get("session_id") is None
    assert recorder.of(SEARCH_PATH)[1].body["session_id"] == "sess_grounding_001"
    assert all(c.body["session_id"] == "sess_grounding_001" for c in recorder.of(EXTRACT_PATH))
