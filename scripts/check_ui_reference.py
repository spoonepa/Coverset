#!/usr/bin/env python3
"""Lint the UI reference screens against `SPEC.md` vocabularies and computed values.

The v4 screens are an implementation reference, which means a wrong value in them
propagates into whatever gets built from them. The prose checklists that shipped with
those screens tested for strings left over from the previous iteration's bugs -- no
requirement ids, nothing tied to the domain model -- so a stripboard showing a split
day, a `MORNING` time-of-day, and a Savannah sunset 29 minutes off all passed review.

This checks the things a reader cannot eyeball:

- day/night tokens come from the `DayNight` vocabulary and nothing else;
- every daylight claim matches `coverset.daylight` for the date it is labelled with,
  which is the one failure this project keeps rediscovering (a plausible clock time
  bound to the wrong date or the wrong place);
- provenance elements each screen is obliged to show are actually present.

Run from the repo root:  uv run python scripts/check_ui_reference.py
"""

from __future__ import annotations

import datetime as dt
import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from coverset.daylight import daylight_window  # noqa: E402
from coverset.locations import Location  # noqa: E402
from coverset.work import DayNight  # noqa: E402

UI = Path(__file__).resolve().parent.parent / "docs" / "ui-sling"

SAVANNAH = Location(
    name="Savannah Terminal 4",
    locality="Savannah",
    region="GA",
    latitude=32.0809,
    longitude=-81.0912,
    timezone="America/New_York",
)

# Every daylight pair the reference screens assert, with the date each is labelled
# with. Computed rather than transcribed: if a screen is edited to a different time,
# or relabelled to a different date, this stops agreeing.
DAYLIGHT_CLAIMS = [
    ("01-stripboard-dashboard.v4.html", dt.date(2023, 10, 13), "sunset", "18:54"),
    ("01-stripboard-dashboard.v4.html", dt.date(2023, 10, 20), "sunrise", "07:31"),
    ("01-stripboard-dashboard.v4.html", dt.date(2023, 10, 20), "sunset", "18:46"),
    ("04-grounded-facts.v4.html", dt.date(2023, 10, 20), "sunrise", "07:31"),
    ("04-grounded-facts.v4.html", dt.date(2023, 10, 20), "sunset", "18:46"),
    ("06-call-sheet.v4.html", dt.date(2023, 10, 13), "sunrise", "07:26"),
    ("06-call-sheet.v4.html", dt.date(2023, 10, 13), "sunset", "18:54"),
]

# Strings a screen must carry, keyed to the requirement that obliges them. The point
# is not the wording -- it is that dropping the element fails a named requirement
# instead of passing a prose checklist.
REQUIRED = {
    "01-stripboard-dashboard.v4.html": [
        ("OUT-003", r"call \d{2}:\d{2} &rarr; wrap \d{2}:\d{2}", "day-level call/wrap window"),
        ("OUT-003", r"\d{2}:\d{2}&ndash;\d{2}:\d{2}", "per-strip call/wrap window"),
        ("AUD-005", r"CONSTRAINT SNAPSHOT", "constraint snapshot hash"),
        ("DAY-001", r"Not retrieved", "daylight stated as computed"),
    ],
    "03-replan-options.v4.html": [
        ("AUD-006", r"parent v4", "schedule version lineage"),
        ("AUD-005", r"snapshot [0-9a-f]{12}", "snapshot hash per option"),
        ("SOL-004", r"IMMUTABLE", "locked days held immutable"),
    ],
    "04-grounded-facts.v4.html": [
        ("GRD-003", r"Date Coverage &middot; PASSED", "date coverage proven before binding"),
        ("GRD-003", r"REFUSED &mdash; NOT BOUND", "refusal when no source covers the date"),
        ("GRD-007", r"EXCERPT FALLBACK", "excerpt degradation made visible"),
        ("GRD-013", r"Normalised Value", "normalised value with units"),
        ("GRD-013", r"Extraction Mode", "full-content/excerpt flag"),
        ("GRD-014", r"GROUNDING CONFLICT", "conflicting authoritative values"),
        ("DAY-001", r"rejects URL provenance", "daylight refuses URL provenance"),
    ],
    "05-coverage-pickup.v4.html": [
        ("PIK-002", r"Authorisation Trace", "pickup traces to decision and finding"),
        ("REV-001", r"only a human can decide", "finding is advisory"),
        ("PIK-010", r"UPM Approval Required", "cost approval gate"),
    ],
    "06-call-sheet.v4.html": [
        ("OUT-004", r"Turnaround Notes", "turnaround notes"),
        ("OUT-004", r"Permit Notes", "permit notes"),
        ("OUT-004", r"Cast Call Times", "cast calls"),
        ("OUT-004", r"Crew Call", "crew call"),
        ("OUT-006", r"Read-only", "recipients receive read-only"),
    ],
    "07-audit-log.v4.html": [
        ("AUD-005", r"snapshot [0-9a-f]{12}", "snapshot hash on the ledger"),
        ("ACT-009", r"Prior version v4, new version", "board selection records both versions"),
        ("SOL-007", r"re-measured off the finished board", "objective checked against the board"),
    ],
}

# `MORNING`, `LATER`, `EVENING` all appeared as time-of-day values on screens whose
# records feed a solver that only accepts DayNight members.
VALID_DAY_NIGHT = {m.value.upper() for m in DayNight} | {"UNKNOWN"}
BAD_DAY_NIGHT = re.compile(
    r"(?:- |>)(MORNING|LATER|EVENING|AFTERNOON|DUSK/DAWN)(?:<|\b)", re.IGNORECASE
)
SLUGLINE = re.compile(r"\b((?:INT|EXT)\.[^<]{0,60}?-\s*(?:DAY|NIGHT|DAWN|DUSK))", re.IGNORECASE)



def _scene_times(body: str) -> list[tuple[str, str]]:
    """Every (scene number, DAY/NIGHT) pair a screen asserts, however it renders it."""
    body = body[body.index("<body") :]
    body = re.sub(r"<(script|style)\b.*?</\1>", " ", body, flags=re.S)
    lines = [
        html.unescape(line).strip()
        for line in re.sub(r"<[^>]+>", "\n", body).split("\n")
        if line.strip()
    ]
    pairs: list[tuple[str, str]] = []
    for i, line in enumerate(lines):
        if not re.fullmatch(r"\d{2,3}[AB]?", line):
            continue
        # The time of day follows the scene number within a few cells, whether the
        # screen renders it as a pill, a D/N column, or the tail of a slugline.
        for ahead in range(1, 5):
            if i + ahead >= len(lines):
                break
            nxt = lines[i + ahead]
            if nxt.upper() in {"DAY", "NIGHT", "DAWN", "DUSK"}:
                pairs.append((line, nxt.upper()))
                break
            slug = SLUGLINE.search(nxt)
            if slug:
                pairs.append((line, slug.group(1).rsplit("-", 1)[1].strip().upper()))
                break
    return pairs


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def check() -> list[str]:
    problems: list[str] = []

    for name, date, kind, claimed in DAYLIGHT_CLAIMS:
        path = UI / name
        if not path.exists():
            problems.append(f"{name}: missing")
            continue
        window = daylight_window(SAVANNAH, date)
        moment = window.sunrise if kind == "sunrise" else window.sunset
        computed = f"{moment:%H:%M}"
        if computed != claimed:
            problems.append(
                f"{name}: {kind} for {date} is {computed} computed, screen claims {claimed}"
            )
        elif claimed not in _text(path):
            problems.append(f"{name}: {kind} {claimed} for {date} is no longer on the screen")

    for name, rules in REQUIRED.items():
        path = UI / name
        if not path.exists():
            problems.append(f"{name}: missing")
            continue
        body = _text(path)
        for req_id, pattern, what in rules:
            if not re.search(pattern, body):
                problems.append(f"{name}: {req_id} not evidenced -- no {what}")

    for path in sorted(UI.glob("*.v4.html")):
        for match in BAD_DAY_NIGHT.finditer(_text(path)):
            token = match.group(1).upper()
            if token not in VALID_DAY_NIGHT:
                problems.append(
                    f"{path.name}: {token!r} is not a day/night value "
                    f"({', '.join(sorted(VALID_DAY_NIGHT))})"
                )

    # A scene number is a domain reference, and its time of day reaches the screens
    # three ways: as a slugline suffix, as a strip pill, and as the call sheet's D/N
    # column. One scene reading DAY on one screen and NIGHT on another is the same
    # class of defect as the `SARA`/`SARAH` cast id -- each screen reads as correct on
    # its own, and only the pair is wrong. It is also how an exterior day scene ends up
    # scheduled on a night shoot.
    times: dict[str, set[tuple[str, str]]] = {}
    for path in sorted(UI.glob("*.v4.html")):
        for scene, when in _scene_times(_text(path)):
            times.setdefault(scene, set()).add((when, path.name))
    for scene, seen in sorted(times.items()):
        distinct = {when for when, _ in seen}
        if len(distinct) > 1:
            where = "; ".join(f"{f} says {w}" for w, f in sorted(seen))
            problems.append(f"scene {scene} is both {' and '.join(sorted(distinct))} -- {where}")

    counters = {}
    for path in sorted(UI.glob("*.v4.html")):
        for total in re.findall(r"Day \d+ of (\d+)", _text(path)):
            counters.setdefault(total, []).append(path.name)
    if len(counters) > 1:
        detail = "; ".join(f"{n} days: {', '.join(sorted(set(f)))}" for n, f in counters.items())
        problems.append(f"schedule length disagrees across screens -- {detail}")

    return problems


def main() -> int:
    problems = check()
    if problems:
        print(f"UI reference: {len(problems)} problem(s)\n")
        for p in problems:
            print(f"  {p}")
        return 1
    checked = len(DAYLIGHT_CLAIMS) + sum(len(r) for r in REQUIRED.values())
    print(f"UI reference: OK ({checked} assertions across {len(REQUIRED)} screens)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
