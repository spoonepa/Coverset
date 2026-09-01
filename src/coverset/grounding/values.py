"""Normalized grounded values with source-level provenance."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from coverset.constraints import DerivedFrom

from .facts import DateCoverageError, Evidence, FactKind, GroundingError, SourceExcerpt

__all__ = [
    "GroundedValue",
    "GroundingConflict",
    "ValidatorResult",
    "bind_grounded_value",
    "detect_grounding_conflicts",
]


class GroundingConflict(GroundingError):
    """Two authoritative sources normalize to incompatible values."""


@dataclass(frozen=True, slots=True)
class ValidatorResult:
    """What accepted or rejected a normalized grounded value."""

    family: str
    passed: bool
    reason: str
    validator: str = "coverset.grounding.values"

    def __post_init__(self) -> None:
        if not self.family.strip():
            raise ValueError("validator result must name the fact family")
        if not self.reason.strip():
            raise ValueError("validator result must explain the result")

    def to_json(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "passed": self.passed,
            "reason": self.reason,
            "validator": self.validator,
        }


@dataclass(frozen=True, slots=True)
class GroundedValue:
    """One normalized value and the exact source text that produced it."""

    id: str
    evidence_id: str
    kind: FactKind
    location_id: str
    target_date: dt.date
    normalized_value: dict[str, Any]
    units: str
    source_url: str
    source_quote: str
    source_span: str
    query: str
    retrieval_timestamp: dt.datetime
    provider_response_id: str
    content_hash: str
    derived_from: DerivedFrom
    validator_result: ValidatorResult
    covering_date: bool
    context_source_urls: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for field_name in (
            "id",
            "evidence_id",
            "location_id",
            "source_url",
            "source_quote",
            "source_span",
            "query",
            "provider_response_id",
            "content_hash",
            "units",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"grounded value must set {field_name}")
        if self.retrieval_timestamp.tzinfo is None:
            raise ValueError("grounded value retrieval timestamp must be timezone-aware")

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "evidence_id": self.evidence_id,
            "kind": self.kind.value,
            "location_id": self.location_id,
            "target_date": self.target_date.isoformat(),
            "normalized_value": self.normalized_value,
            "units": self.units,
            "source_url": self.source_url,
            "source_quote": self.source_quote,
            "source_span": self.source_span,
            "query": self.query,
            "retrieval_timestamp": self.retrieval_timestamp.isoformat(),
            "provider_response_id": self.provider_response_id,
            "content_hash": self.content_hash,
            "derived_from": self.derived_from.value,
            "validator_result": self.validator_result.to_json(),
            "covering_date": self.covering_date,
            "context_source_urls": list(self.context_source_urls),
        }


JSONValue = str | int | float | bool | None | dict[str, Any] | list[Any]


def bind_grounded_value(
    evidence: Evidence,
    *,
    value_id: str,
    normalized_value: dict[str, Any],
    units: str,
    source_url: str,
    source_quote: str,
    source_span: str,
    query: str,
    validator_result: ValidatorResult,
    require_date_coverage: bool = True,
) -> GroundedValue:
    """Bind a normalized value to one source span inside an Evidence bundle."""
    source = _source_for(evidence, source_url)
    if source_quote not in source.text:
        raise GroundingError("grounded value quote is not present in its source text")
    covering = source_url in set(evidence.covering_urls)
    if require_date_coverage and not covering:
        raise DateCoverageError(
            evidence.kind,
            evidence.location,
            evidence.date,
            evidence.source_urls,
        )
    return GroundedValue(
        id=value_id,
        evidence_id=evidence.search_id,
        kind=evidence.kind,
        location_id=evidence.location.id,
        target_date=evidence.date,
        normalized_value=_canonical_value(normalized_value),
        units=units,
        source_url=source.url,
        source_quote=source_quote,
        source_span=source_span,
        query=query,
        retrieval_timestamp=evidence.retrieved_at,
        provider_response_id=evidence.search_id,
        content_hash=_content_hash(source),
        derived_from=DerivedFrom.FULL_CONTENT if source.full_content else DerivedFrom.EXCERPT,
        validator_result=validator_result,
        covering_date=covering,
        context_source_urls=tuple(
            url for url in evidence.source_urls if url != source.url and url not in evidence.covering_urls
        ),
    )


def detect_grounding_conflicts(values: tuple[GroundedValue, ...]) -> None:
    """Raise if passed values for the same fact disagree."""
    seen: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for value in values:
        if not value.validator_result.passed:
            continue
        key = (
            value.kind.value,
            value.location_id,
            value.target_date.isoformat(),
            value.units,
        )
        current = seen.setdefault(key, value.normalized_value)
        if _canonical_value(current) != value.normalized_value:
            raise GroundingConflict(
                f"conflicting {value.kind} values for {value.location_id} on "
                f"{value.target_date.isoformat()}: {current!r} vs {value.normalized_value!r}"
            )


def _source_for(evidence: Evidence, source_url: str) -> SourceExcerpt:
    for source in evidence.sources:
        if source.url == source_url:
            return source
    raise GroundingError(f"source URL {source_url!r} is not in evidence {evidence.search_id}")


def _content_hash(source: SourceExcerpt) -> str:
    return hashlib.sha256(source.text.encode("utf-8")).hexdigest()


def _canonical_value(value: dict[str, Any]) -> dict[str, Any]:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
        decoded = json.loads(encoded)
    except (TypeError, json.JSONDecodeError) as exc:
        raise GroundingError("grounded values must be JSON serializable") from exc
    if not isinstance(decoded, dict):
        raise GroundingError("grounded value normalization must produce an object")
    return decoded
