"""Live check of the fact pipeline: computed daylight + grounded weather and permits.

The test suite runs offline against a mock transport, which proves the wiring but
not that the API agrees with it. This hits Parallel for real.

    export PARALLEL_API_KEY=...        # or put it in .env
    uv run python scripts/smoke_grounding.py

Daylight is computed and needs no network. Weather and permits are retrieved, and
weather must prove its sources actually mention the shoot date -- if it cannot, it
raises rather than binding a plausible value from some other day.
"""

from __future__ import annotations

import datetime as dt
import os
import sys

from coverset.daylight import daylight_window
from coverset.grounding import DateCoverageError, FactKind, GroundingError, SearchGrounder
from coverset.locations import Location

try:  # local-dev convenience only; deployed runtimes get real environment variables
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

LOCATION = Location(
    name="First African Baptist Church",
    locality="Savannah",
    region="Georgia",
    latitude=32.0809,
    longitude=-81.0912,
    timezone="America/New_York",
)
SHOOT_DATE = dt.date.today() + dt.timedelta(days=6)
RULE = "=" * 78


def _format_window(window: tuple[dt.datetime, dt.datetime] | None) -> str:
    if window is None:
        return "unavailable"
    start, end = window
    return f"{start:%H:%M} - {end:%H:%M}"


def show_daylight() -> None:
    print(f"\n{RULE}\nDAYLIGHT  (computed -- no network)\n{RULE}")
    w = daylight_window(LOCATION, SHOOT_DATE)
    print(f"  provenance : {w.algorithm} @ {LOCATION.latitude}, {LOCATION.longitude}")
    print(f"  condition  : {w.condition}")
    print(f"  sunrise    : {w.sunrise:%H:%M %Z}")
    print(f"  solar noon : {w.solar_noon:%H:%M %Z}")
    print(f"  sunset     : {w.sunset:%H:%M %Z}")
    print(f"  golden hr  : {_format_window(w.golden_hour)}")
    print(f"  magic hr   : {_format_window(w.magic_hour)}")
    print(f"  day length : {w.day_length}")
    print(f"\n  -> exterior DAY scenes bounded to {w.sunrise:%H:%M}-{w.sunset:%H:%M}")


def show_grounded(grounder: SearchGrounder, kind: FactKind) -> bool:
    print(f"\n{RULE}\n{kind.value.upper()}  (grounded via Parallel Search)\n{RULE}")
    try:
        ev = grounder.ground(kind, LOCATION, SHOOT_DATE)
    except DateCoverageError as exc:
        print(f"  REFUSED: {exc}")
        return False
    except GroundingError as exc:
        print(f"  FAILED: {exc}")
        return False

    print(f"  search_id  : {ev.search_id}")
    print(f"  escalated  : {ev.escalated}   sources: {len(ev.sources)}")
    print(f"  mentions {SHOOT_DATE:%b %-d}: {len(ev.covering_urls)} of {len(ev.sources)}")
    for s in ev.sources[:3]:
        mark = "*" if s.url in ev.covering_urls else " "
        print(f"\n  {mark} {s.url}")
        print(f"      {(s.title or '(untitled)')[:66]}  published={s.publish_date or 'unknown'}")
        body = " ".join(s.text.split())
        print(f"      {body[:280]}{'...' if len(body) > 280 else ''}")
    if ev.covering_urls:
        print(f"\n  (* = explicitly mentions {SHOOT_DATE:%B %-d}; only these may bind a dated value)")
    return True


def main() -> int:
    if load_dotenv is not None:
        load_dotenv()

    print(f"\n{LOCATION.name} -- {LOCATION.place}    shoot date {SHOOT_DATE:%A, %B %-d, %Y}")
    show_daylight()

    if not os.environ.get("PARALLEL_API_KEY"):
        print("\nPARALLEL_API_KEY is not set -- skipping the grounded facts.", file=sys.stderr)
        return 2

    grounder = SearchGrounder()
    results = [show_grounded(grounder, kind) for kind in FactKind]

    print(f"\n{RULE}")
    print(f"daylight computed; {sum(results)}/{len(results)} grounded fact kinds retrieved.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
