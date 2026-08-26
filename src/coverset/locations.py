"""Shooting locations.

A location is a domain concept, not a grounding concept: the solver, the daylight
calculation, and the web-grounding path all need one. It lives here so none of them
has to import from another.

Coordinates and timezone are optional because not every use needs them -- permit
grounding works from the civic place name alone -- but they are validated as a set.
A location with a latitude and no timezone is a location whose daylight window is
an hour wrong twice a year, so half-configured coordinates are rejected outright.
"""

from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

__all__ = ["Location"]


@dataclass(frozen=True, slots=True)
class Location:
    """A shooting location, resolved enough to ground or compute facts about it."""

    name: str
    locality: str
    region: str
    country: str = "US"
    """ISO 3166-1 alpha-2, used to geo-target search results."""

    latitude: float | None = None
    longitude: float | None = None
    timezone: str | None = None
    """IANA zone name, e.g. `America/New_York`. Required alongside coordinates."""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("location name must not be empty")
        if not self.locality.strip():
            raise ValueError(f"{self.name}: locality is required to ground facts")
        if len(self.country) != 2 or not self.country.isalpha():
            raise ValueError(
                f"country must be an ISO 3166-1 alpha-2 code, got {self.country!r}"
            )
        object.__setattr__(self, "country", self.country.upper())

        geo = (self.latitude, self.longitude, self.timezone)
        if any(v is not None for v in geo) and not all(v is not None for v in geo):
            raise ValueError(
                f"{self.name}: latitude, longitude and timezone must be set together "
                f"-- coordinates without a timezone give a daylight window that is a "
                f"full hour wrong across a DST boundary"
            )
        if self.latitude is not None:
            if not -90 <= self.latitude <= 90:
                raise ValueError(f"latitude out of range: {self.latitude}")
            if not -180 <= self.longitude <= 180:  # type: ignore[operator]
                raise ValueError(f"longitude out of range: {self.longitude}")
            try:
                ZoneInfo(self.timezone)  # type: ignore[arg-type]
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValueError(
                    f"{self.name}: unknown IANA timezone {self.timezone!r}"
                ) from exc

    @property
    def place(self) -> str:
        """The civic place name, which is what permit sources index on."""
        return f"{self.locality}, {self.region}" if self.region else self.locality

    @property
    def is_locatable(self) -> bool:
        """True when this location can have its daylight window computed."""
        return self.latitude is not None

    @property
    def zone(self) -> ZoneInfo:
        """The location's timezone, honouring DST for whatever date it is applied to."""
        if self.timezone is None:
            raise ValueError(f"{self.name}: no timezone set")
        return ZoneInfo(self.timezone)
