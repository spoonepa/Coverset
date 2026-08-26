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

import re
from dataclasses import dataclass
from typing import Iterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

__all__ = ["Location", "LocationBook", "UnknownLocation"]


class UnknownLocation(KeyError):
    """A record referenced a location that is not on the production's list.

    Same hazard as an unknown cast id: a misspelt reference schedules work at a
    place that does not exist, and nothing downstream notices.
    """


@dataclass(frozen=True, slots=True)
class Location:
    """A shooting location, resolved enough to ground or compute facts about it."""

    name: str
    locality: str
    region: str
    country: str = "US"
    """ISO 3166-1 alpha-2, used to geo-target search results."""

    id: str = ""
    """Stable reference used by scene and work records.

    Derived from the name when not given, which keeps short-form construction
    convenient. `LocationBook` rejects collisions, so two locations whose names
    differ only in punctuation are caught rather than silently merged.
    """

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
        if not self.id:
            slug = re.sub(r"[^a-z0-9]+", "-", self.name.casefold()).strip("-")
            object.__setattr__(self, "id", slug)

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


@dataclass(frozen=True, slots=True)
class LocationBook:
    """Every location on the production, addressable by id."""

    locations: tuple[Location, ...] = ()

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for loc in self.locations:
            if loc.id in seen:
                raise ValueError(
                    f"duplicate location id {loc.id!r}; two locations whose names "
                    f"differ only in punctuation collide when ids are derived"
                )
            seen.add(loc.id)

    def __iter__(self) -> Iterator[Location]:
        return iter(self.locations)

    def __len__(self) -> int:
        return len(self.locations)

    def __getitem__(self, location_id: str) -> Location:
        for loc in self.locations:
            if loc.id == location_id:
                return loc
        raise UnknownLocation(
            f"{location_id!r} is not on the production's locations; known ids: "
            f"{', '.join(sorted(l.id for l in self.locations)) or '(empty)'}"
        )

    def resolve(self, location_ids: tuple[str, ...]) -> tuple[Location, ...]:
        """Turn ids into locations, naming every unknown one at once."""
        known = {loc.id for loc in self.locations}
        if unknown := [i for i in location_ids if i not in known]:
            raise UnknownLocation(
                f"not on the production's locations: {', '.join(sorted(set(unknown)))}; "
                f"known ids: {', '.join(sorted(known)) or '(empty)'}"
            )
        return tuple(self[i] for i in location_ids)
