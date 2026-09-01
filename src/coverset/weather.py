"""Weather risk facts and production policy mapping."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .constraints import (
    BlackoutDates,
    ConstraintRecord,
    Family,
    GroundedSource,
    Policy,
    Subject,
    SubjectKind,
)
from .grounding import (
    Evidence,
    FactKind,
    GroundingError,
    ValidatorResult,
    bind_grounded_value,
)
from .grounding.values import GroundedValue

__all__ = [
    "ConfidenceTier",
    "ForecastClassification",
    "ForecastRisk",
    "WeatherPolicy",
    "forecast_risk_from_evidence",
    "policy_for_weather_risk",
    "weather_constraint_from_risk",
]


class ForecastClassification(StrEnum):
    FORECAST = "forecast"
    CLIMATOLOGY = "climatology"


class ConfidenceTier(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class ForecastRisk:
    """A normalized weather value that may or may not become a constraint."""

    id: str
    location_id: str
    issued_at: dt.datetime
    valid_for_date: dt.date
    horizon_days: int
    condition: str
    probability: float
    intensity: str
    source_url: str
    confidence_tier: ConfidenceTier
    classification: ForecastClassification
    grounded_value: GroundedValue

    def __post_init__(self) -> None:
        if self.issued_at.tzinfo is None:
            raise ValueError("weather risk issued_at must be timezone-aware")
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError(f"weather probability must be in [0, 1], got {self.probability}")
        if not self.condition.strip():
            raise ValueError("weather risk must name the condition")
        if not self.source_url.strip():
            raise ValueError("weather risk must cite its source URL")

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "location_id": self.location_id,
            "issued_at": self.issued_at.isoformat(),
            "valid_for_date": self.valid_for_date.isoformat(),
            "horizon_days": self.horizon_days,
            "condition": self.condition,
            "probability": self.probability,
            "intensity": self.intensity,
            "source_url": self.source_url,
            "confidence_tier": self.confidence_tier.value,
            "classification": self.classification.value,
            "grounded_value": self.grounded_value.to_json(),
        }


@dataclass(frozen=True, slots=True)
class WeatherPolicy:
    """How a production maps weather risk into schedule policy."""

    hard_probability: float = 0.75
    soft_probability: float = 0.35
    waivable_probability: float = 0.6
    allow_climatology_constraints: bool = False

    def __post_init__(self) -> None:
        for label, value in (
            ("hard_probability", self.hard_probability),
            ("soft_probability", self.soft_probability),
            ("waivable_probability", self.waivable_probability),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{label} must be in [0, 1], got {value}")
        if self.soft_probability > self.waivable_probability:
            raise ValueError("soft probability threshold cannot exceed waivable threshold")
        if self.waivable_probability > self.hard_probability:
            raise ValueError("waivable probability threshold cannot exceed hard threshold")


def forecast_risk_from_evidence(
    evidence: Evidence,
    *,
    risk_id: str,
    condition: str,
    probability: float,
    intensity: str = "unknown",
    issued_at: dt.datetime | None = None,
    source_url: str | None = None,
    source_quote: str | None = None,
    source_span: str = "source text",
    query: str = "weather forecast",
    near_term_days: int = 14,
) -> ForecastRisk:
    """Normalize sourced weather evidence into a forecast/climatology risk."""
    if evidence.kind is not FactKind.WEATHER:
        raise GroundingError(f"expected weather evidence, got {evidence.kind}")
    issued = issued_at or evidence.retrieved_at
    horizon_days = (evidence.date - issued.date()).days
    classification = (
        ForecastClassification.FORECAST
        if 0 <= horizon_days <= near_term_days
        else ForecastClassification.CLIMATOLOGY
    )
    tier = _confidence_tier(classification, probability, horizon_days, near_term_days)
    source = source_url or (evidence.covering_urls[0] if evidence.covering_urls else evidence.primary.url)
    quote = source_quote or _quote_for_source(evidence, source)
    value = bind_grounded_value(
        evidence,
        value_id=risk_id,
        normalized_value={
            "condition": condition,
            "probability": probability,
            "intensity": intensity,
            "classification": classification.value,
            "horizon_days": horizon_days,
        },
        units="probability_0_1",
        source_url=source,
        source_quote=quote,
        source_span=source_span,
        query=query,
        validator_result=ValidatorResult(
            family="weather",
            passed=True,
            reason="probability in range and source covers target date",
            validator="coverset.weather.forecast_risk_from_evidence",
        ),
        require_date_coverage=True,
    )
    return ForecastRisk(
        id=risk_id,
        location_id=evidence.location.id,
        issued_at=issued,
        valid_for_date=evidence.date,
        horizon_days=horizon_days,
        condition=condition,
        probability=probability,
        intensity=intensity,
        source_url=source,
        confidence_tier=tier,
        classification=classification,
        grounded_value=value,
    )


def policy_for_weather_risk(risk: ForecastRisk, policy: WeatherPolicy) -> Policy:
    if (
        risk.classification is ForecastClassification.CLIMATOLOGY
        and not policy.allow_climatology_constraints
    ):
        return Policy.INFORMATIONAL
    if risk.probability >= policy.hard_probability:
        return Policy.HARD
    if risk.probability >= policy.waivable_probability:
        return Policy.WAIVABLE_BY_ROLE
    if risk.probability >= policy.soft_probability:
        return Policy.SOFT_PENALTY
    return Policy.INFORMATIONAL


def weather_constraint_from_risk(
    risk: ForecastRisk,
    *,
    policy: WeatherPolicy = WeatherPolicy(),
    constraint_id: str | None = None,
    active: bool = True,
) -> ConstraintRecord:
    mapped = policy_for_weather_risk(risk, policy)
    return ConstraintRecord(
        constraint_id=constraint_id or f"WEA-{risk.id}",
        family=Family.WEATHER,
        policy=mapped,
        subject=Subject(SubjectKind.LOCATION, risk.location_id),
        expression=BlackoutDates((risk.valid_for_date,)),
        source=GroundedSource(
            evidence_id=risk.grounded_value.evidence_id,
            source_urls=(risk.source_url,),
            grounded_value_id=risk.grounded_value.id,
        ),
        created_by="coverset.weather",
        validated_against="coverset.weather.WeatherPolicy",
        active=active and mapped is not Policy.INFORMATIONAL,
        activated_at=dt.datetime.now(dt.UTC) if active and mapped is not Policy.INFORMATIONAL else None,
    )


def _confidence_tier(
    classification: ForecastClassification,
    probability: float,
    horizon_days: int,
    near_term_days: int,
) -> ConfidenceTier:
    if classification is ForecastClassification.CLIMATOLOGY:
        return ConfidenceTier.LOW
    if horizon_days <= min(3, near_term_days) and probability >= 0.5:
        return ConfidenceTier.HIGH
    if horizon_days <= near_term_days:
        return ConfidenceTier.MEDIUM
    return ConfidenceTier.LOW


def _quote_for_source(evidence: Evidence, source_url: str) -> str:
    for source in evidence.sources:
        if source.url == source_url:
            if source.full_content:
                return source.full_content[:200]
            if source.excerpts:
                return source.excerpts[0]
    raise GroundingError(f"source {source_url!r} is not part of weather evidence")
