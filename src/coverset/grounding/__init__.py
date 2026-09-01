"""Externally-grounded facts: Parallel Search -> sourced evidence -> typed constraints.

Only what cannot be computed is retrieved. Daylight is solar geometry and lives in
`coverset.daylight`; weather and permits are contingent and live here.

Retrieved facts are not context for a chat layer. They become hard bounds on the
solver's feasible region, which is why every piece of evidence carries the URL it
came from, why an ungrounded fact raises instead of defaulting, and why a
date-specific fact must prove its sources mention the date.
"""

from ..locations import Location
from .coverage import covers_date, date_patterns
from .facts import (
    DateCoverageError,
    Evidence,
    FactKind,
    GroundingError,
    GroundingUnavailable,
    SourceExcerpt,
)
from .queries import QueryPlan, SearchMode, plan_for
from .search import SearchGrounder
from .values import (
    GroundedValue,
    GroundingConflict,
    ValidatorResult,
    bind_grounded_value,
    detect_grounding_conflicts,
)

__all__ = [
    "DateCoverageError",
    "Evidence",
    "FactKind",
    "GroundingError",
    "GroundedValue",
    "GroundingConflict",
    "GroundingUnavailable",
    "Location",
    "QueryPlan",
    "SearchGrounder",
    "SearchMode",
    "SourceExcerpt",
    "ValidatorResult",
    "bind_grounded_value",
    "covers_date",
    "date_patterns",
    "detect_grounding_conflicts",
    "plan_for",
]
