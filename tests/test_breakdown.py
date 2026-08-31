"""Breakdown, offline -- folding, gating, resolution and the board, against a known read.

The live Gemini call is exercised by `tests/test_live_breakdown.py`. Here an agent is
injected, so these run with no API key and stay deterministic: they verify the wiring
around the model, not the model. The reading below is the answer key for
`fixtures/corpus/authored/the_ferry_job.txt` -- authored so its breakdown is known by
construction (BRK-011), which is the only way to assert breakdown *correctness* rather
than mere survival.
"""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest

from coverset import breakdown
from coverset.breakdown import RawScene
from coverset.constraints import ConstraintSet
from coverset.locations import Location, LocationBook
from coverset.people import CastMember, Company, Roster
from coverset.scenes import CandidateStatus, IntExt
from coverset.solver import ProductionCalendar, ScheduleProblem, solve
from coverset.work import DayNight

FIXTURE = (
    pathlib.Path(__file__).resolve().parents[1]
    / "fixtures"
    / "corpus"
    / "authored"
    / "the_ferry_job.txt"
)
DOCUMENT = FIXTURE.read_bytes()

# The known reading of THE FERRY JOB: what a correct breakdown returns. Mixed numbering,
# a CONTINUOUS heading with no stated time, a two-place heading, and stunt/vfx/minor
# flags -- the shapes the offline suite has to prove the folding and gating handle.
ANSWER_KEY = (
    RawScene("INT. MAYA'S APARTMENT - NIGHT", ("MAYA", "DEV"), "1", 8, 0.95),
    RawScene(
        "EXT. BROOKLYN BRIDGE PARK - DAY", ("MAYA", "DEV"), "2", 6, 0.92, stunt=True
    ),
    RawScene("INT. WAREHOUSE - CONTINUOUS", ("RUTH",), None, 3, 0.88),
    RawScene(
        "EXT. FERRY TERMINAL / RIVER DOCK - DUSK", ("MAYA",), None, 4, 0.82, vfx=True
    ),
    RawScene("INT. MAYA'S APARTMENT - DAY", ("MAYA", "KID"), "3", 3, 0.70, minors=True),
)


class FakeAgent:
    """A recorded reading, standing in for Gemini exactly as the grounding suite stands
    a fake Parallel client in for the live API."""

    def __init__(self, scenes: tuple[RawScene, ...] = ANSWER_KEY) -> None:
        self._scenes = tuple(scenes)

    def extract(self, document: bytes, *, media: str) -> tuple[RawScene, ...]:
        return self._scenes


ROSTER = Roster(
    (
        CastMember("cast-maya", "A. Idowu", "MAYA"),
        CastMember("cast-dev", "B. Whitfield", "DEV"),
        CastMember("cast-ruth", "C. Okonkwo", "RUTH"),
        CastMember("cast-kid", "D. Alvarez", "KID", is_minor=True),
    )
)

LOCATIONS = LocationBook(
    (
        Location(
            "Maya's Apartment",
            "Brooklyn",
            "NY",
            id="maya-s-apartment",
            latitude=40.700,
            longitude=-73.990,
            timezone="America/New_York",
        ),
        Location(
            "Brooklyn Bridge Park",
            "Brooklyn",
            "NY",
            id="brooklyn-bridge-park",
            latitude=40.7002,
            longitude=-73.9967,
            timezone="America/New_York",
        ),
        Location(
            "Warehouse",
            "Queens",
            "NY",
            id="warehouse",
            latitude=40.742,
            longitude=-73.938,
            timezone="America/New_York",
        ),
        Location(
            "Ferry Terminal",
            "Manhattan",
            "NY",
            id="ferry-terminal",
            latitude=40.701,
            longitude=-74.013,
            timezone="America/New_York",
        ),
    )
)

# The two-place heading resolves to the one unit location the company travels to.
ALIASES = {"FERRY TERMINAL / RIVER DOCK": "ferry-terminal"}


@pytest.fixture(autouse=True)
def _fresh_cache():
    breakdown.clear_cache()
    yield
    breakdown.clear_cache()


def _records():
    return breakdown.parse(DOCUMENT, media="text", agent=FakeAgent())


@pytest.mark.req("BRK-001")
def test_a_screenplay_parses_into_candidate_records():
    records = _records()
    assert len(records) == len(ANSWER_KEY)
    # A parsed record is a proposal. Only a human activates; nothing arrives active.
    assert all(r.status is not CandidateStatus.ACTIVE for r in records)
    assert all(r.slugline for r in records)
    assert all(r.page_eighths > 0 for r in records)


@pytest.mark.req("BRK-001", "BRK-011", "BRK-012")
def test_the_structural_spine_folds_as_expected():
    records = _records()
    assert [(r.int_ext, r.day_night) for r in records] == [
        (IntExt.INT, DayNight.NIGHT),
        (IntExt.EXT, DayNight.DAY),
        (IntExt.INT, DayNight.UNKNOWN),  # CONTINUOUS states no time of day
        (IntExt.EXT, DayNight.DUSK),
        (IntExt.INT, DayNight.DAY),
    ]
    assert records[0].location_ref == "MAYA'S APARTMENT"
    assert records[3].location_ref == "FERRY TERMINAL / RIVER DOCK"


@pytest.mark.req("BRK-014")
def test_scene_numbers_are_verbatim_or_labelled_as_synthesised():
    records = _records()
    # Printed numbers survive verbatim and are not marked synthesised.
    assert (records[0].scene_number, records[0].number_synthesized) == ("1", False)
    assert (records[1].scene_number, records[1].number_synthesized) == ("2", False)
    assert (records[4].scene_number, records[4].number_synthesized) == ("3", False)
    # Unnumbered headings get a number, marked synthesised and visibly not the script's.
    assert records[2].number_synthesized and records[2].scene_number == "S3"
    assert records[3].number_synthesized and records[3].scene_number == "S4"
    numbers = [r.scene_number for r in records]
    assert len(numbers) == len(set(numbers)), (
        "synthesised numbers collided with printed"
    )


@pytest.mark.req("BRK-002")
def test_stunts_minors_and_vfx_are_flagged_as_candidates():
    records = _records()
    assert records[1].flags.stunts and records[1].flags.any_set
    assert records[3].flags.vfx
    assert records[4].flags.minors
    assert records[0].flags.any_set is False


@pytest.mark.req("BRK-003")
def test_low_confidence_records_need_review_and_cannot_be_activated():
    records = _records()
    low = records[4]  # confidence 0.70, below the 0.75 default
    assert low.status is CandidateStatus.NEEDS_REVIEW
    with pytest.raises(breakdown.BreakdownError):
        breakdown.activate(low)
    # A record above threshold activates and becomes schedulable.
    activated = breakdown.activate(records[0])
    assert activated.status is CandidateStatus.ACTIVE


@pytest.mark.req("BRK-003")
def test_the_confidence_threshold_is_overridable():
    lenient = breakdown.parse(DOCUMENT, media="text", agent=FakeAgent(), threshold=0.6)
    assert lenient[4].status is CandidateStatus.CANDIDATE


@pytest.mark.req("BRK-004")
def test_an_empty_roster_leaves_every_cue_unresolved():
    result = breakdown.resolve_cast(_records(), roster=Roster())
    assert result.unresolved
    assert not result.records_ready_for_solver


@pytest.mark.req("BRK-004")
def test_cues_resolve_to_roster_ids_when_the_cast_is_known():
    result = breakdown.resolve_cast(_records(), roster=ROSTER)
    assert result.unresolved == ()
    assert result.records_ready_for_solver == result.records
    assert set(result.records[0].cast_ids) == {"cast-maya", "cast-dev"}


@pytest.mark.req("BRK-004")
def test_a_near_miss_stays_unresolved_rather_than_snapping_to_the_nearest():
    # The SARA/SARAH bug: a roster holding MAYAH must not resolve a MAYA cue to it.
    near = Roster(
        (
            CastMember("cast-mayah", "X", "MAYAH"),
            CastMember("cast-dev", "Y", "DEV"),
            CastMember("cast-ruth", "Z", "RUTH"),
            CastMember("cast-kid", "W", "KID", is_minor=True),
        )
    )
    result = breakdown.resolve_cast(_records(), roster=near)
    assert "MAYA" in result.unresolved
    assert not result.records_ready_for_solver


@pytest.mark.req("BRK-013")
def test_slugline_places_resolve_to_location_ids():
    result = breakdown.resolve_locations(
        _records(), locations=LOCATIONS, aliases=ALIASES
    )
    assert result.unresolved == ()
    assert {r.location_ref for r in result.records} == {
        "maya-s-apartment",
        "brooklyn-bridge-park",
        "warehouse",
        "ferry-terminal",
    }


@pytest.mark.req("BRK-013")
def test_a_two_place_heading_without_an_alias_stays_unresolved():
    result = breakdown.resolve_locations(_records(), locations=LOCATIONS)
    assert "FERRY TERMINAL / RIVER DOCK" in result.unresolved
    assert not result.records_ready_for_solver


@pytest.mark.req("BRK-013")
def test_an_unknown_place_is_reported_not_guessed():
    book = LocationBook((Location("Warehouse", "Queens", "NY", id="warehouse"),))
    result = breakdown.resolve_locations(_records(), locations=book)
    assert "MAYA'S APARTMENT" in result.unresolved


@pytest.mark.req("BRK-013")
def test_an_alias_pointing_off_the_book_is_an_error():
    with pytest.raises(breakdown.BreakdownError):
        breakdown.resolve_locations(
            _records(),
            locations=LOCATIONS,
            aliases={"FERRY TERMINAL / RIVER DOCK": "not-a-real-location"},
        )


@pytest.mark.req("BRK-012")
def test_two_parses_of_one_document_agree():
    first = breakdown.parse(DOCUMENT, media="text", agent=FakeAgent())
    breakdown.clear_cache()
    second = breakdown.parse(DOCUMENT, media="text", agent=FakeAgent())
    assert [r.scene_number for r in first] == [r.scene_number for r in second]
    assert [(r.int_ext, r.day_night) for r in first] == [
        (r.int_ext, r.day_night) for r in second
    ]


@pytest.mark.req("BRK-012")
def test_a_reparse_of_identical_bytes_is_memoised():
    first = breakdown.parse(DOCUMENT, media="text", agent=FakeAgent())
    # A different reading of the same bytes never appears: the content hash pins it.
    second = breakdown.parse(DOCUMENT, media="text", agent=FakeAgent(scenes=()))
    assert first is second


@pytest.mark.req("BRK-001", "BRK-014")
def test_a_margin_scene_number_does_not_break_the_heading():
    # Shooting drafts print the scene number in the margin, so a real read returns it
    # inside the verbatim slugline: "1   INT. ...". The heading must still fold, and the
    # number stays the script's own, not synthesised. Caught by the live tier against
    # real Gemini, pinned here so it cannot regress offline.
    agent = FakeAgent(
        (RawScene("1   INT. MAYA'S APARTMENT - NIGHT", ("MAYA",), "1", 8, 0.95),)
    )
    (record,) = breakdown.parse(DOCUMENT, media="text", agent=agent)
    assert (record.int_ext, record.day_night) == (IntExt.INT, DayNight.NIGHT)
    assert record.location_ref == "MAYA'S APARTMENT"
    assert record.slugline == "INT. MAYA'S APARTMENT - NIGHT"
    assert record.scene_number == "1" and not record.number_synthesized
    assert record.status is CandidateStatus.CANDIDATE


@pytest.mark.req("BRK-001")
def test_unknown_media_is_rejected():
    with pytest.raises(breakdown.BreakdownError):
        breakdown.parse(DOCUMENT, media="docx", agent=FakeAgent())


@pytest.mark.req("BRK-001")
def test_the_breakdown_feeds_a_solvable_board():
    """UC-01 end to end: screenplay -> resolved, activated records -> work -> a board."""
    records = _records()
    located = breakdown.resolve_locations(records, locations=LOCATIONS, aliases=ALIASES)
    casted = breakdown.resolve_cast(located.records_ready_for_solver, roster=ROSTER)
    ready = casted.records_ready_for_solver
    assert ready, (
        "nothing resolved; the board would be built on an incomplete breakdown"
    )

    # Only reviewed, fully-resolved day/night records become work: the solver has no
    # twilight window, so a dusk scene is scheduled by hand, and a CONTINUOUS heading
    # needs its time of day resolved first (DAY-010).
    schedulable = [
        r
        for r in ready
        if r.status is CandidateStatus.CANDIDATE
        and r.day_night in (DayNight.DAY, DayNight.NIGHT)
    ]
    work = tuple(breakdown.activate(r).to_work_item() for r in schedulable)
    assert work

    calendar = ProductionCalendar(
        tuple(dt.date(2026, 9, 14) + dt.timedelta(days=i) for i in range(5))
    )
    problem = ScheduleProblem(
        problem_id="UC-01",
        production_calendar=calendar,
        work_items=work,
        constraints=ConstraintSet(()),
        roster=ROSTER,
        locations=LOCATIONS,
        company=Company(),
    )
    result = solve(problem, seed=0)
    assert result.viable_boards
