from __future__ import annotations

import datetime as dt

import pytest

from coverset.constraint_translation import translate_plain_english_constraints
from coverset.constraints import Policy
from coverset.grounding import (
    DateCoverageError,
    Evidence,
    FactKind,
    SourceExcerpt,
    ValidatorResult,
)
from coverset.grounding.values import (
    GroundingConflict,
    bind_grounded_value,
    detect_grounding_conflicts,
)
from coverset.locations import Location
from coverset.schedule_diff import build_schedule_diff, render_schedule_diff_text
from coverset.weather import (
    ForecastClassification,
    WeatherPolicy,
    forecast_risk_from_evidence,
    policy_for_weather_risk,
    weather_constraint_from_risk,
)


def _evidence(
    *,
    kind: FactKind = FactKind.WEATHER,
    target_date: dt.date = dt.date(2026, 9, 14),
    covering: bool = True,
    full_content: str | None = None,
) -> Evidence:
    quote = "September 14, 2026: precipitation probability 85%."
    sources = (
        SourceExcerpt(
            url="https://weather.example.gov/forecast",
            excerpts=(quote,),
            full_content=full_content,
        ),
        SourceExcerpt(
            url="https://weather.example.com/context",
            excerpts=("General seasonal context.",),
        ),
    )
    return Evidence(
        kind=kind,
        location=Location(
            "Pier 13",
            "Brooklyn",
            "NY",
            id="pier-13",
            latitude=40.7,
            longitude=-73.9,
            timezone="America/New_York",
        ),
        date=target_date,
        sources=sources,
        search_id="search-weather-1",
        session_id="session-weather-1",
        retrieved_at=dt.datetime(2026, 9, 10, 12, tzinfo=dt.UTC),
        escalated=full_content is not None,
        covering_urls=("https://weather.example.gov/forecast",) if covering else (),
    )


@pytest.mark.req("CON-001", "CON-009")
def test_plain_english_constraints_translate_to_inactive_typed_candidates():
    candidates = translate_plain_english_constraints(
        "prod1",
        "Cast MAYA available from 2026-09-14 to 2026-09-16. "
        "Location pier-13 closed on 2026-09-15.",
        created_by="R. Okonkwo",
    )

    assert len(candidates) == 2
    assert all(candidate.requires_human_acceptance for candidate in candidates)
    assert candidates[0].constraint_payload["family"] == "cast"
    assert candidates[0].constraint_payload["expression_type"] == "date_windows"
    assert candidates[0].constraint_payload["active"] is False
    assert candidates[1].constraint_payload["expression_type"] == "blackout_dates"


@pytest.mark.req("GRD-012", "GRD-013", "GRD-014", "GRD-015", "CON-003", "AUD-003")
def test_grounded_values_record_exact_quote_date_coverage_and_conflicts():
    evidence = _evidence(full_content="# Forecast\nSeptember 14, 2026: precipitation probability 85%.")
    value = bind_grounded_value(
        evidence,
        value_id="gval-1",
        normalized_value={"probability": 0.85},
        units="probability_0_1",
        source_url="https://weather.example.gov/forecast",
        source_quote="September 14, 2026: precipitation probability 85%.",
        source_span="line 2",
        query="weather forecast",
        validator_result=ValidatorResult(
            family="weather",
            passed=True,
            reason="probability in range",
        ),
    )

    assert value.source_quote in value.to_json()["source_quote"]
    assert value.covering_date is True
    assert value.derived_from.value == "full_content"
    assert value.context_source_urls == ("https://weather.example.com/context",)

    conflicting = bind_grounded_value(
        evidence,
        value_id="gval-2",
        normalized_value={"probability": 0.1},
        units="probability_0_1",
        source_url="https://weather.example.gov/forecast",
        source_quote="September 14, 2026: precipitation probability 85%.",
        source_span="line 2",
        query="weather forecast",
        validator_result=ValidatorResult(
            family="weather",
            passed=True,
            reason="probability in range",
        ),
    )
    with pytest.raises(GroundingConflict):
        detect_grounding_conflicts((value, conflicting))

    with pytest.raises(DateCoverageError):
        bind_grounded_value(
            _evidence(covering=False),
            value_id="gval-3",
            normalized_value={"probability": 0.85},
            units="probability_0_1",
            source_url="https://weather.example.gov/forecast",
            source_quote="September 14, 2026: precipitation probability 85%.",
            source_span="line 2",
            query="weather forecast",
            validator_result=ValidatorResult(
                family="weather",
                passed=True,
                reason="probability in range",
            ),
        )


@pytest.mark.req("WEA-001", "WEA-002", "WEA-003", "WEA-005", "CON-006", "GRD-010")
def test_weather_forecast_policy_maps_grounded_risk_to_constraint():
    evidence = _evidence()
    risk = forecast_risk_from_evidence(
        evidence,
        risk_id="rain-1",
        condition="rain",
        probability=0.85,
        issued_at=dt.datetime(2026, 9, 10, 8, tzinfo=dt.UTC),
        source_quote="September 14, 2026: precipitation probability 85%.",
    )

    assert risk.classification is ForecastClassification.FORECAST
    assert policy_for_weather_risk(risk, WeatherPolicy()) is Policy.HARD
    constraint = weather_constraint_from_risk(risk)
    assert constraint.active is True
    assert constraint.policy is Policy.HARD
    assert getattr(constraint.source, "grounded_value_id", "") == "rain-1"

    climatology = forecast_risk_from_evidence(
        _evidence(target_date=dt.date(2027, 9, 14)),
        risk_id="rain-climo",
        condition="rain",
        probability=0.9,
        issued_at=dt.datetime(2026, 9, 10, 8, tzinfo=dt.UTC),
        source_quote="September 14, 2026: precipitation probability 85%.",
    )
    assert climatology.classification is ForecastClassification.CLIMATOLOGY
    assert policy_for_weather_risk(climatology, WeatherPolicy()) is Policy.INFORMATIONAL


@pytest.mark.req("OUT-002", "OUT-005", "PIK-007", "MON-002")
def test_schedule_diff_reports_production_disruption_terms():
    base = {
        "days": [{"date": "2026-09-14"}],
        "strips": [
            {
                "work_id": "scene-1",
                "scene_id": "1",
                "shoot_day": "2026-09-14",
                "sequence": 0,
                "planned_call_time": "2026-09-14T08:00:00-04:00",
                "planned_wrap_time": "2026-09-14T10:00:00-04:00",
                "kind": "scene",
            }
        ],
        "objective_breakdown": {"company_moves": 0, "holding_days": 0, "overtime_hours": 0},
    }
    revised = {
        "days": [{"date": "2026-09-14"}, {"date": "2026-09-15"}],
        "strips": [
            {
                "work_id": "scene-1",
                "scene_id": "1",
                "shoot_day": "2026-09-15",
                "sequence": 1,
                "planned_call_time": "2026-09-15T08:00:00-04:00",
                "planned_wrap_time": "2026-09-15T10:00:00-04:00",
                "kind": "scene",
            },
            {
                "work_id": "pickup-1",
                "scene_id": "1",
                "shoot_day": "2026-09-14",
                "sequence": 0,
                "planned_call_time": "2026-09-14T10:00:00-04:00",
                "planned_wrap_time": "2026-09-14T11:00:00-04:00",
                "kind": "pickup",
            },
        ],
        "objective_breakdown": {"company_moves": 1, "holding_days": 2, "overtime_hours": 1.5},
    }

    diff = build_schedule_diff(
        base_board_id="board-a",
        revised_board_id="board-b",
        base=base,
        revised=revised,
    )

    assert diff.added_days == ("2026-09-15",)
    assert diff.added_pickups == ("pickup-1",)
    assert diff.company_move_delta == 1
    assert diff.cast_holding_delta == 2
    assert diff.overtime_delta_hours == 1.5
    assert "upm_or_line_producer_cost_approval" in diff.required_approvals
    assert "pickup-1" in render_schedule_diff_text(diff)
