"""Tests for scene records, schedulable work, and fixture import.

Two boundaries carry most of the weight here. A record a model is not sure about
must not become work the board commits a crew day to, and a scene naming a performer
or a place that does not exist must not reach the solver, because both failures are
silent: the board looks complete and schedules nobody at nowhere.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from coverset.fixtures import FixtureError, load_scenes
from coverset.locations import Location, LocationBook
from coverset.people import CastMember, Roster
from coverset.scenes import (
    MINUTES_PER_EIGHTH,
    CandidateStatus,
    IntExt,
    NotSchedulable,
    SceneRecord,
)
from coverset.work import DayNight, WorkFlags, WorkItem, WorkKind

CHURCH = Location("First African Baptist Church", "Savannah", "Georgia")
CEMETERY = Location("Bonaventure Cemetery", "Savannah", "Georgia")
PLACES = LocationBook((CHURCH, CEMETERY))
ROSTER = Roster((
    CastMember("SARAH", "S. Idowu", "Ruth"),
    CastMember("MARCUS", "D. Whitfield", "Elias"),
))


def scene(**over) -> SceneRecord:
    return dataclasses.replace(SceneRecord(
        scene_id="12", scene_number="12", slugline="EXT. CHURCH STEPS - DAY",
        int_ext=IntExt.EXT, day_night=DayNight.DAY, location_ref=CHURCH.id,
        page_eighths=6, cast_ids=("SARAH", "MARCUS"), source_page_range="14-15",
        status=CandidateStatus.ACTIVE,
    ), **over)


def fixture(**over) -> dict:
    return {
        "scene_id": "12", "scene_number": "12", "slugline": "EXT. STEPS - DAY",
        "int_ext": "ext", "day_night": "day", "location_ref": CHURCH.id,
        "page_eighths": 6, "cast_ids": ["SARAH"], "status": "active",
    } | over


def load(*raw, **kw):
    return load_scenes(list(raw), roster=ROSTER, locations=PLACES, **kw)


# --------------------------------------------------------------------------
# SCN-001 -- the record
# --------------------------------------------------------------------------


@pytest.mark.req("SCN-001")
def test_a_scene_record_carries_the_screenplay_facts_and_its_source():
    s = scene()

    assert (s.scene_number, s.int_ext, s.day_night) == ("12", IntExt.EXT, DayNight.DAY)
    assert s.location_ref == "first-african-baptist-church"
    assert s.source_page_range == "14-15"


@pytest.mark.req("SCN-001")
def test_a_scene_number_need_not_be_numeric():
    # "12A" is ordinary in a revised screenplay.
    assert scene(scene_number="12A").scene_number == "12A"


@pytest.mark.req("SCN-001")
@pytest.mark.parametrize(
    ("over", "match"),
    [
        ({"scene_id": " "}, "needs a stable id"),
        ({"scene_number": ""}, "scene number is required"),
        ({"location_ref": ""}, "must name where it plays"),
        ({"page_eighths": 0}, "page eighths must be positive"),
        ({"page_eighths": -3}, "page eighths must be positive"),
        ({"confidence": 1.4}, "confidence out of range"),
    ],
)
def test_an_unusable_record_is_refused_at_construction(over, match):
    with pytest.raises(ValueError, match=match):
        scene(**over)


@pytest.mark.req("SCN-001")
@pytest.mark.parametrize(
    ("int_ext", "day_night", "expected"),
    [
        (IntExt.EXT, DayNight.DAY, True),
        (IntExt.INT_EXT, DayNight.DAY, True),
        (IntExt.INT, DayNight.DAY, False),      # a stage interior needs no sun
        (IntExt.EXT, DayNight.NIGHT, False),
        (IntExt.EXT, DayNight.DUSK, False),
    ],
)
def test_only_exterior_day_scenes_need_the_sun_up(int_ext, day_night, expected):
    assert scene(int_ext=int_ext, day_night=day_night).needs_daylight is expected


@pytest.mark.req("SCN-001")
def test_shooting_time_follows_the_declared_page_rate():
    # One page is eight eighths and roughly an hour, so six eighths is 45 minutes.
    assert scene(page_eighths=6).estimated_minutes == 45
    assert scene(page_eighths=8).estimated_minutes == round(8 * MINUTES_PER_EIGHTH)


@pytest.mark.req("SCN-001")
def test_a_very_short_scene_still_takes_a_minute():
    assert scene(page_eighths=1).estimated_minutes >= 1


# --------------------------------------------------------------------------
# SCN-003 -- becoming schedulable work
# --------------------------------------------------------------------------


@pytest.mark.req("SCN-003")
def test_an_active_record_converts_to_work():
    w = scene().to_work_item()

    assert isinstance(w, WorkItem)
    assert (w.kind, w.scene_id, w.location_id) == (WorkKind.SCENE, "12", CHURCH.id)
    assert w.estimated_duration_minutes == 45
    assert w.cast_ids == ("SARAH", "MARCUS")
    assert w.source_record_id == "12"


@pytest.mark.req("SCN-003")
@pytest.mark.parametrize(
    "status",
    [CandidateStatus.CANDIDATE, CandidateStatus.NEEDS_REVIEW, CandidateStatus.REJECTED],
)
def test_a_record_that_is_not_active_cannot_become_work(status):
    # A candidate scene reaching the solver is a crew day committed on a model's
    # unreviewed say-so.
    with pytest.raises(NotSchedulable, match="only an accepted record"):
        scene(status=status).to_work_item()


@pytest.mark.req("SCN-003")
def test_work_cannot_be_made_from_an_unresolved_day_night():
    # Work that could be day or night carries no daylight bound at all, so it would
    # be scheduled as though unconstrained.
    with pytest.raises(NotSchedulable, match="day/night is unresolved"):
        scene(day_night=DayNight.UNKNOWN).to_work_item()


@pytest.mark.req("SCN-003")
def test_the_same_refusal_holds_at_the_work_item_itself():
    with pytest.raises(ValueError, match="day/night is unknown"):
        WorkItem("W-1", WorkKind.SCENE, "1", "loc", DayNight.UNKNOWN, 30)


@pytest.mark.req("SCN-003")
def test_flags_survive_the_conversion():
    w = scene(flags=WorkFlags(stunts=True, minors=True)).to_work_item()

    assert (w.flags.stunts, w.flags.minors, w.flags.vfx) == (True, True, False)
    assert str(w.flags) == "stunts, minors"


@pytest.mark.req("SCN-003")
def test_an_explicit_duration_overrides_the_page_estimate():
    # A page of stunt work is not a page of dialogue.
    assert scene(page_eighths=6).to_work_item(minutes=180).estimated_duration_minutes == 180


# --------------------------------------------------------------------------
# SCN-002 -- fixture import
# --------------------------------------------------------------------------


@pytest.mark.req("SCN-002")
def test_a_valid_fixture_loads():
    scenes = load(fixture(), fixture(scene_id="13", location_ref=CEMETERY.id))

    assert [s.scene_id for s in scenes] == ["12", "13"]
    assert scenes[0].status is CandidateStatus.ACTIVE


@pytest.mark.req("SCN-002")
def test_records_default_to_candidate_when_no_status_is_given():
    raw = fixture()
    del raw["status"]

    assert load(raw)[0].status is CandidateStatus.CANDIDATE


@pytest.mark.req("SCN-002")
def test_json_text_and_parsed_data_are_both_accepted():
    assert load_scenes(json.dumps([fixture()]), roster=ROSTER, locations=PLACES)[0].scene_id == "12"


@pytest.mark.req("SCN-002")
def test_missing_required_fields_are_named():
    raw = fixture()
    del raw["day_night"], raw["page_eighths"]

    with pytest.raises(FixtureError) as e:
        load(raw)
    assert "missing required field(s) day_night, page_eighths" in str(e.value)


@pytest.mark.req("SCN-002")
@pytest.mark.parametrize(
    ("field", "bad"), [("int_ext", "interior"), ("day_night", "nite"), ("status", "maybe")]
)
def test_an_invalid_enum_value_is_reported_with_the_legal_ones(field, bad):
    with pytest.raises(FixtureError) as e:
        load(fixture(**{field: bad}))

    assert f"{field} {bad!r} is not one of" in str(e.value)


@pytest.mark.req("SCN-002")
@pytest.mark.parametrize("bad", [0, -2, "six", 1.5, True])
def test_page_eighths_must_be_a_positive_integer(bad):
    with pytest.raises(FixtureError, match="page_eighths must be a positive integer"):
        load(fixture(page_eighths=bad))


@pytest.mark.req("SCN-002")
def test_a_duplicate_scene_id_is_reported():
    with pytest.raises(FixtureError, match="duplicate scene_id"):
        load(fixture(), fixture(slugline="different scene"))


@pytest.mark.req("SCN-002")
def test_malformed_json_is_reported_as_such():
    with pytest.raises(FixtureError, match="not valid JSON"):
        load_scenes("{not json", roster=ROSTER, locations=PLACES)


@pytest.mark.req("SCN-002")
def test_every_problem_in_a_file_is_reported_at_once():
    # An AD correcting a breakdown wants the whole list, not one error per run.
    with pytest.raises(FixtureError) as e:
        load(
            fixture(int_ext="interior"),
            fixture(scene_id="13", page_eighths=0),
            fixture(scene_id="14", location_ref="nowhere"),
        )

    assert len(e.value.problems) == 3


@pytest.mark.req("SCN-002")
def test_independent_problems_in_one_scene_do_not_mask_each_other():
    # A bad enum must not hide a bad page count, or fixing the file takes one run
    # per mistake.
    with pytest.raises(FixtureError) as e:
        load(fixture(int_ext="interior", day_night="nite", page_eighths=0,
                     cast_ids=["SARA"], location_ref="nowhere"))

    assert len(e.value.problems) == 5


# --------------------------------------------------------------------------
# CST-009 -- cross-references checked before anything is solved
# --------------------------------------------------------------------------


@pytest.mark.req("CST-009")
def test_a_scene_naming_someone_off_the_roster_is_rejected():
    with pytest.raises(FixtureError, match="cast not on the roster: SARA"):
        load(fixture(cast_ids=["SARAH", "SARA"]))


@pytest.mark.req("CST-009")
def test_every_unknown_cast_id_in_a_scene_is_named():
    with pytest.raises(FixtureError) as e:
        load(fixture(cast_ids=["SARA", "MARCEL"]))

    assert "MARCEL, SARA" in str(e.value)


@pytest.mark.req("CST-009")
def test_a_scene_naming_a_location_the_production_does_not_have_is_rejected():
    with pytest.raises(FixtureError, match="location 'nowhere' is not on"):
        load(fixture(location_ref="nowhere"))


@pytest.mark.req("CST-009")
def test_resolved_cast_and_location_reach_the_work_item():
    s = load(fixture(cast_ids=["SARAH", "MARCUS"]))[0]
    w = s.to_work_item()

    assert ROSTER.resolve(w.cast_ids) == (ROSTER["SARAH"], ROSTER["MARCUS"])
    assert PLACES[w.location_id] is CHURCH


# --------------------------------------------------------------------------
# The location book scene records resolve against
# --------------------------------------------------------------------------


@pytest.mark.req("SCN-002")
def test_a_location_derives_a_stable_id_from_its_name():
    assert CHURCH.id == "first-african-baptist-church"


@pytest.mark.req("SCN-002")
def test_an_explicit_location_id_is_kept():
    assert Location("The Church", "Savannah", "Georgia", id="church-01").id == "church-01"


@pytest.mark.req("SCN-002")
def test_locations_whose_names_differ_only_in_punctuation_collide_loudly():
    # Derived ids can coincide. Silently merging two locations would schedule work
    # at the wrong one, so the book refuses to hold both.
    with pytest.raises(ValueError, match="duplicate location id"):
        LocationBook((CHURCH, Location("First African Baptist Church!", "Savannah", "Georgia")))


@pytest.mark.req("SCN-002")
def test_every_unknown_location_is_named_at_once():
    from coverset.locations import UnknownLocation

    with pytest.raises(UnknownLocation) as e:
        PLACES.resolve(("nowhere", CHURCH.id, "elsewhere"))

    assert "elsewhere, nowhere" in str(e.value)
