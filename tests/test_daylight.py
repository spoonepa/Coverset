"""Tests for the computed daylight path.

The reference values below were read from published almanac tables (timeanddate.com
and sunrise-sunset.org for Savannah, GA) and are checked in deliberately. The point
of computing daylight rather than retrieving it is that the result becomes
*checkable* against known-good values; these are those values.
"""

from __future__ import annotations

import datetime as dt

import pytest

from coverset.daylight import SunCondition, daylight_window
from coverset.locations import Location

SAVANNAH = Location(
    name="First African Baptist Church",
    locality="Savannah",
    region="Georgia",
    latitude=32.0809,
    longitude=-81.0912,
    timezone="America/New_York",
)
SVALBARD = Location(
    name="Longyearbyen",
    locality="Longyearbyen",
    region="Svalbard",
    country="NO",
    latitude=78.2232,
    longitude=15.6469,
    timezone="Arctic/Longyearbyen",
)

TOLERANCE_MINUTES = 2


def _minutes_apart(when: dt.datetime, hh: int, mm: int) -> float:
    return abs((when.hour * 60 + when.minute) - (hh * 60 + mm))


# --------------------------------------------------------------------------
# Agreement with published tables
# --------------------------------------------------------------------------


@pytest.mark.req("DAY-001", "DAY-002")
@pytest.mark.parametrize(
    ("date", "sunrise", "sunset", "source"),
    [
        (dt.date(2026, 9, 1), (6, 59), (19, 48), "timeanddate.com/sun/usa/savannah?month=9"),
        (dt.date(2026, 8, 26), (6, 56), (19, 55), "timeanddate.com/sun/usa/savannah"),
        (dt.date(2026, 8, 1), (6, 38), (20, 22), "sunrise-sunset.org/us/savannah-ga"),
    ],
)
def test_computed_times_agree_with_published_almanacs(date, sunrise, sunset, source):
    window = daylight_window(SAVANNAH, date)

    assert _minutes_apart(window.sunrise, *sunrise) <= TOLERANCE_MINUTES, source
    assert _minutes_apart(window.sunset, *sunset) <= TOLERANCE_MINUTES, source


# --------------------------------------------------------------------------
# Daylight Saving Time -- the failure that reintroduces "plausible but wrong"
# --------------------------------------------------------------------------


@pytest.mark.req("DAY-003")
def test_sunset_follows_the_dst_transition():
    before = daylight_window(SAVANNAH, dt.date(2026, 10, 31))
    after = daylight_window(SAVANNAH, dt.date(2026, 11, 1))

    assert before.sunset.tzname() == "EDT"
    assert after.sunset.tzname() == "EST"
    # Wall-clock sunset jumps back roughly an hour; true day length barely moves.
    assert 55 <= (before.sunset.hour * 60 + before.sunset.minute) - (
        after.sunset.hour * 60 + after.sunset.minute
    ) <= 65
    assert abs(before.day_length - after.day_length) < dt.timedelta(minutes=5)


@pytest.mark.req("DAY-003")
def test_times_are_timezone_aware():
    window = daylight_window(SAVANNAH, dt.date(2026, 9, 1))

    assert all(
        t.tzinfo is not None
        for t in (window.sunrise, window.sunset, window.civil_dusk, window.solar_noon)
    )


# --------------------------------------------------------------------------
# Invariants -- these fail loudly rather than producing a plausible wrong bound
# --------------------------------------------------------------------------


@pytest.mark.req("DAY-004")
def test_window_is_chronologically_ordered():
    w = daylight_window(SAVANNAH, dt.date(2026, 9, 1))

    assert (
        w.civil_dawn < w.sunrise < w.golden_morning_end
        < w.solar_noon
        < w.golden_evening_start < w.sunset < w.civil_dusk
    )


@pytest.mark.req("DAY-004")
def test_day_length_shortens_from_summer_towards_winter():
    lengths = [
        daylight_window(SAVANNAH, d).day_length
        for d in (dt.date(2026, 6, 21), dt.date(2026, 9, 1), dt.date(2026, 12, 21))
    ]

    assert lengths == sorted(lengths, reverse=True)


@pytest.mark.req("DAY-001")
def test_magic_hour_runs_from_sunset_to_civil_dusk():
    w = daylight_window(SAVANNAH, dt.date(2026, 9, 1))

    start, end = w.magic_hour
    assert (start, end) == (w.sunset, w.civil_dusk)
    assert dt.timedelta(minutes=15) < end - start < dt.timedelta(minutes=45)


@pytest.mark.req("DAY-001")
def test_golden_hour_precedes_sunset():
    w = daylight_window(SAVANNAH, dt.date(2026, 9, 1))

    start, end = w.golden_hour
    assert start < end == w.sunset


@pytest.mark.req("DAY-001")
def test_exterior_day_window_is_sunrise_to_sunset():
    w = daylight_window(SAVANNAH, dt.date(2026, 9, 1))

    assert w.exterior_day_window == (w.sunrise, w.sunset)


# --------------------------------------------------------------------------
# Latitudes where the sun does not rise or set
# --------------------------------------------------------------------------


@pytest.mark.req("DAY-005")
def test_arctic_summer_is_reported_as_polar_day():
    w = daylight_window(SVALBARD, dt.date(2026, 6, 21))

    assert w.condition is SunCondition.POLAR_DAY
    assert w.exterior_day_window is None
    assert w.day_length == dt.timedelta(days=1)


@pytest.mark.req("DAY-005")
def test_arctic_winter_is_reported_as_polar_night():
    w = daylight_window(SVALBARD, dt.date(2026, 12, 21))

    assert w.condition is SunCondition.POLAR_NIGHT
    assert w.exterior_day_window is None
    assert w.day_length == dt.timedelta()


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------


@pytest.mark.req("DAY-006")
def test_a_location_without_coordinates_cannot_be_computed():
    plain = Location(name="Church", locality="Savannah", region="Georgia")

    with pytest.raises(ValueError, match="requires latitude"):
        daylight_window(plain, dt.date(2026, 9, 1))


@pytest.mark.req("DAY-006")
def test_coordinates_without_a_timezone_are_rejected():
    with pytest.raises(ValueError, match="must be set together"):
        Location(name="Church", locality="Savannah", region="Georgia", latitude=32.08)


@pytest.mark.req("DAY-006")
def test_an_unknown_timezone_is_rejected():
    with pytest.raises(ValueError, match="unknown IANA timezone"):
        Location(
            name="Church", locality="Savannah", region="Georgia",
            latitude=32.08, longitude=-81.09, timezone="Mars/Olympus",
        )


@pytest.mark.req("AUD-002", "DAY-001")
def test_a_computed_window_names_its_algorithm_as_provenance():
    w = daylight_window(SAVANNAH, dt.date(2026, 9, 1))

    assert "NOAA" in w.algorithm
