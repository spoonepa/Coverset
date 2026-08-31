"""Live verification of the breakdown agent against the real Gemini API.

Deselected by default; run with `uv run pytest -m live` and a `GEMINI_API_KEY`.

The twin of `tests/test_live_grounding.py`. The offline suite proves the folding,
gating and resolution around the agent; it cannot prove Gemini actually reads a
screenplay into the shape those tests assume. That is what this does, against the
authored fixture -- a real model call, real bytes, structural invariants pinned rather
than exact readings, because a model's page-eighths estimate is not a fixed fact and a
test that pinned it would fail for the wrong reason.
"""

from __future__ import annotations

import os
import pathlib

import pytest

from coverset import breakdown
from coverset.breakdown import GeminiBreakdown
from coverset.scenes import CandidateStatus
from coverset.work import DayNight

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")),
        reason="GEMINI_API_KEY not set",
    ),
]

FIXTURE = (
    pathlib.Path(__file__).resolve().parents[1]
    / "fixtures" / "corpus" / "authored" / "the_ferry_job.txt"
)


@pytest.fixture(scope="module")
def document() -> bytes:
    return FIXTURE.read_bytes()


@pytest.fixture(autouse=True)
def _fresh_cache():
    breakdown.clear_cache()
    yield
    breakdown.clear_cache()


@pytest.fixture(scope="module")
def records(document):
    return breakdown.parse(document, media="text", agent=GeminiBreakdown())


@pytest.mark.req("BRK-001")
def test_gemini_reads_the_screenplay_into_candidate_records(records):
    assert records, "Gemini returned no scenes for a real screenplay"
    # Extractive and advisory: a real read still arrives as candidates, never active.
    assert all(r.status is not CandidateStatus.ACTIVE for r in records)
    for r in records:
        assert r.slugline.strip(), "a scene came back with no slugline"
        assert r.page_eighths > 0
        assert r.day_night in set(DayNight)


@pytest.mark.req("BRK-001")
def test_the_real_read_holds_the_scene_record_invariants(records):
    numbers = [r.scene_number for r in records]
    assert len(numbers) == len(set(numbers)), "duplicate scene numbers in a real read"
    assert all(r.scene_number.strip() for r in records)


@pytest.mark.req("BRK-012")
def test_a_reparse_is_stable_across_the_stochastic_model(document):
    # The content-hash cache is what makes BRK-012 hold for a model that need not
    # return the same bytes twice: a second parse of one document is the first read.
    first = breakdown.parse(document, media="text", agent=GeminiBreakdown())
    second = breakdown.parse(document, media="text", agent=GeminiBreakdown())
    assert first is second
