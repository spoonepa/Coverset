"""Daylight windows, computed rather than retrieved.

Sunrise, sunset and twilight are a closed-form function of latitude, longitude and
date. They are not web facts; they only resembled web facts because sunrise-sunset
websites exist. Retrieving them meant asking a search engine for a page that happened
to be showing the right date, then asking a language model to read a number off it --
three fallible steps standing in for one exact one.

The argument for computing is not merely that it is exact. It is that the result is
*checkable*: a computed window can be asserted against known invariants and against
published almanac values, whereas a retrieved one can only be compared against
another retrieval. The failure mode goes from undetectable to detectable, which is
the same reason the schedule itself comes from a solver rather than a model.

Implements the NOAA solar position algorithm. Agrees with published almanac tables
to within about a minute, which is well inside the tolerance of a call time.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from enum import StrEnum

from .locations import Location

__all__ = ["ALGORITHM", "DaylightWindow", "SunCondition", "daylight_window"]

ALGORITHM = "NOAA solar position algorithm"
"""Provenance for a computed bound, standing where a source URL stands for a
retrieved one. A daylight constraint traces to this plus the coordinates."""

_SUNRISE_ZENITH = 90.833
"""Standard zenith at sunrise/sunset: 90 degrees plus refraction and solar radius."""
_CIVIL_ZENITH = 96.0
"""Civil twilight: sun 6 degrees below the horizon. The practical end of shootable
ambient light, and the outer edge of post-sunset magic hour."""
_GOLDEN_ZENITH = 84.0
"""Sun 6 degrees above the horizon: the start of golden-hour light quality."""


class SunCondition(StrEnum):
    """Whether the sun actually rises and sets on this date at this latitude."""

    NORMAL = "normal"
    POLAR_DAY = "polar_day"
    POLAR_NIGHT = "polar_night"


@dataclass(frozen=True, slots=True)
class DaylightWindow:
    """The daylight structure of one date at one location, as local wall times.

    Times are timezone-aware and DST-correct for the date in question, which is not
    a detail: a fixed UTC offset puts sunset a full hour late on the far side of a
    DST boundary, and a twenty-day board crosses one routinely.
    """

    location: Location
    date: dt.date
    condition: SunCondition
    solar_noon: dt.datetime
    sunrise: dt.datetime | None
    sunset: dt.datetime | None
    civil_dawn: dt.datetime | None
    civil_dusk: dt.datetime | None
    golden_morning_end: dt.datetime | None
    golden_evening_start: dt.datetime | None
    algorithm: str = ALGORITHM

    def __post_init__(self) -> None:
        if self.condition is not SunCondition.NORMAL:
            return
        # Invariants worth asserting precisely because a wrong-but-plausible time is
        # the failure this module exists to eliminate. If the arithmetic drifts, it
        # should fail here rather than reach the solver looking reasonable.
        ordered = [
            self.civil_dawn,
            self.sunrise,
            self.golden_morning_end,
            self.solar_noon,
            self.golden_evening_start,
            self.sunset,
            self.civil_dusk,
        ]
        if any(t is None for t in ordered):
            raise ValueError(f"incomplete daylight window for {self.date}")
        for earlier, later in zip(ordered, ordered[1:], strict=False):
            if earlier > later:  # type: ignore[operator]
                raise ValueError(
                    f"daylight window for {self.date} is out of order: "
                    f"{earlier:%H:%M} follows {later:%H:%M}"
                )

    @property
    def day_length(self) -> dt.timedelta:
        """Sunrise to sunset."""
        if self.sunrise is None or self.sunset is None:
            return dt.timedelta(days=1) if self.condition is SunCondition.POLAR_DAY else dt.timedelta()
        return self.sunset - self.sunrise

    @property
    def exterior_day_window(self) -> tuple[dt.datetime, dt.datetime] | None:
        """The hard bound on when an exterior DAY scene can be photographed."""
        if self.sunrise is None or self.sunset is None:
            return None
        return (self.sunrise, self.sunset)

    @property
    def golden_hour(self) -> tuple[dt.datetime, dt.datetime] | None:
        """Warm low-angle light before sunset. Short, and worth scheduling around."""
        if self.golden_evening_start is None or self.sunset is None:
            return None
        return (self.golden_evening_start, self.sunset)

    @property
    def magic_hour(self) -> tuple[dt.datetime, dt.datetime] | None:
        """Sunset to civil dusk: shootable ambient light after the sun is down."""
        if self.sunset is None or self.civil_dusk is None:
            return None
        return (self.sunset, self.civil_dusk)


def _julian_day_at_local_noon(date: dt.date, utc_offset_hours: float) -> float:
    year, month = date.year, date.month
    if month <= 2:
        year, month = year - 1, month + 12
    century = year // 100
    gregorian = 2 - century + century // 4
    jd_midnight_utc = (
        int(365.25 * (year + 4716))
        + int(30.6001 * (month + 1))
        + date.day
        + gregorian
        - 1524.5
    )
    return jd_midnight_utc + (12 - utc_offset_hours) / 24


def _solar_geometry(julian_day: float) -> tuple[float, float]:
    """Return (declination degrees, equation of time minutes) for a Julian day."""
    t = (julian_day - 2451545.0) / 36525
    mean_long = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360
    mean_anom = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    eccentricity = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    centre = (
        math.sin(math.radians(mean_anom)) * (1.914602 - t * (0.004817 + 0.000014 * t))
        + math.sin(math.radians(2 * mean_anom)) * (0.019993 - 0.000101 * t)
        + math.sin(math.radians(3 * mean_anom)) * 0.000289
    )
    apparent_long = (
        mean_long
        + centre
        - 0.00569
        - 0.00478 * math.sin(math.radians(125.04 - 1934.136 * t))
    )
    obliquity = (
        23
        + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
        + 0.00256 * math.cos(math.radians(125.04 - 1934.136 * t))
    )
    declination = math.degrees(
        math.asin(math.sin(math.radians(obliquity)) * math.sin(math.radians(apparent_long)))
    )
    var_y = math.tan(math.radians(obliquity / 2)) ** 2
    eq_of_time = 4 * math.degrees(
        var_y * math.sin(2 * math.radians(mean_long))
        - 2 * eccentricity * math.sin(math.radians(mean_anom))
        + 4 * eccentricity * var_y * math.sin(math.radians(mean_anom))
        * math.cos(2 * math.radians(mean_long))
        - 0.5 * var_y * var_y * math.sin(4 * math.radians(mean_long))
        - 1.25 * eccentricity * eccentricity * math.sin(2 * math.radians(mean_anom))
    )
    return declination, eq_of_time


def _hour_angle(latitude: float, declination: float, zenith: float) -> float | None:
    """Half the arc the sun spends above `zenith`, in degrees. None if it never crosses."""
    cos_ha = math.cos(math.radians(zenith)) / (
        math.cos(math.radians(latitude)) * math.cos(math.radians(declination))
    ) - math.tan(math.radians(latitude)) * math.tan(math.radians(declination))
    if not -1 <= cos_ha <= 1:
        return None
    return math.degrees(math.acos(cos_ha))


def daylight_window(location: Location, date: dt.date) -> DaylightWindow:
    """Compute the daylight structure of `date` at `location`.

    Raises:
        ValueError: the location has no coordinates, so its window cannot be
            computed. Grounding it from the web is not an alternative -- geocode it.
    """
    if not location.is_locatable:
        raise ValueError(
            f"{location.name}: daylight requires latitude, longitude and timezone"
        )
    latitude, longitude = location.latitude, location.longitude
    zone = location.zone

    offset = zone.utcoffset(dt.datetime(date.year, date.month, date.day, 12))
    assert offset is not None
    offset_hours = offset.total_seconds() / 3600

    declination, eq_of_time = _solar_geometry(
        _julian_day_at_local_noon(date, offset_hours)
    )
    noon_minutes = 720 - 4 * longitude - eq_of_time + offset_hours * 60  # type: ignore[operator]

    midnight = dt.datetime.combine(date, dt.time())

    def at(minutes: float) -> dt.datetime:
        return (midnight + dt.timedelta(minutes=minutes)).replace(tzinfo=zone)

    def pair(zenith: float) -> tuple[dt.datetime | None, dt.datetime | None]:
        ha = _hour_angle(latitude, declination, zenith)  # type: ignore[arg-type]
        if ha is None:
            return None, None
        return at(noon_minutes - 4 * ha), at(noon_minutes + 4 * ha)

    sunrise, sunset = pair(_SUNRISE_ZENITH)
    civil_dawn, civil_dusk = pair(_CIVIL_ZENITH)
    golden_morning_end, golden_evening_start = pair(_GOLDEN_ZENITH)

    if sunrise is None:
        # The sun never reaches the horizon: either it stays up all day or never rises.
        condition = (
            SunCondition.POLAR_DAY if declination * latitude > 0 else SunCondition.POLAR_NIGHT  # type: ignore[operator]
        )
    else:
        condition = SunCondition.NORMAL

    return DaylightWindow(
        location=location,
        date=date,
        condition=condition,
        solar_noon=at(noon_minutes),
        sunrise=sunrise,
        sunset=sunset,
        civil_dawn=civil_dawn,
        civil_dusk=civil_dusk,
        golden_morning_end=golden_morning_end,
        golden_evening_start=golden_evening_start,
    )
