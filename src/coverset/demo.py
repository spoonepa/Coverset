"""UC-00 -- a board from structured fixtures, end to end.

Every part of this path was built and unit-tested before anything ran it together.
That is the gap this module closes: `load_scenes`, `load_constraints`, `solve`,
`validate_board` and `stripboard` each had tests, and no single thing composed them,
so MVP-0 read 47/47 while no use case was deliverable. A capability nothing exercises
end to end is a claim, not a capability.

What is a fixture here and what is not:

- **Scenes and constraints are data**, loaded from JSON and validated on the way in.
  That is what UC-00 means by structured fixtures -- the breakdown and the bounds are
  the things a production would hand over, and they are the things that must survive
  import without being trusted.
- **The production is code**: roster, locations, calendar, company. These are the
  setup the fixtures refer to rather than fixture content themselves, and typing them
  here keeps the demo honest about `Location` ids, which are derived from names unless
  stated. Two of this project's bugs were an untyped string where an entity belonged.

Run it:

    uv run python -m coverset.demo

It exits non-zero if no board is returned, and prints the conflict set rather than a
plausible-looking partial answer.
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys

from .fixtures import load_constraints, load_scenes
from .locations import Location, LocationBook
from .people import CastMember, Company, Roster
from .scenes import SceneRecord
from .solver import ProductionCalendar, ScheduleProblem, SolveResult, solve
from .stripboard import explain_assignment, stripboard
from .work import WorkItem

__all__ = [
    "CALENDAR",
    "COMPANY",
    "FIXTURES",
    "LOCATIONS",
    "ROSTER",
    "build_problem",
    "main",
    "render",
]

FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "uc00"

# Ids are stated rather than derived. `Location` slugs its name when no id is given,
# and "St. Ann's Church" slugs to `st-ann-s-church` -- which would not match the
# `st-anns-church` the scene fixture references. The import would catch it, but a
# fixture set that only works because a slug rule happens to agree is a fixture set
# waiting to break when someone renames a location.
LOCATIONS = LocationBook(
    (
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
            "St. Ann's Church",
            "Brooklyn",
            "NY",
            id="st-anns-church",
            latitude=40.7025,
            longitude=-73.9903,
            timezone="America/New_York",
        ),
        Location(
            "Silvercup Studios",
            "Queens",
            "NY",
            id="silvercup-studios",
            latitude=40.7423,
            longitude=-73.9382,
            timezone="America/New_York",
        ),
    )
)

# Availability lives in the constraint file, not on the `CastMember`. It is a bound on
# the schedule, so it reaches the solver the way every other bound does -- through a
# record with provenance, an id, and a place in the snapshot hash.
ROSTER = Roster(
    (
        CastMember("SARAH", "S. Idowu", "MAYA", contracted_days=3),
        CastMember("TOM", "D. Whitfield", "DEV"),
        CastMember("NINA", "A. Okonkwo", "RUTH"),
        CastMember("RAY", "J. Alvarez", "FRANK"),
    )
)

CALENDAR = ProductionCalendar(
    tuple(dt.date(2026, 9, 14) + dt.timedelta(days=i) for i in range(5))
)
"""Monday 14 September to Friday 18 September 2026."""

COMPANY = Company()


def build_problem(fixtures: pathlib.Path = FIXTURES) -> ScheduleProblem:
    """Load the fixture production and assemble the problem to be solved.

    Raises rather than defaulting at every step. A scene that fails import, a
    constraint that names a performer who is not on the roster, or a work item at a
    location the production does not have all stop here -- because a bound that
    silently fails to apply is how a board comes to violate a rule nobody removed.
    """
    scenes: tuple[SceneRecord, ...] = load_scenes(
        fixtures / "scenes.json", roster=ROSTER, locations=LOCATIONS
    )
    constraints = load_constraints(fixtures / "constraints.json")

    # Only active records convert. A candidate scene is a proposal, and scheduling a
    # proposal is how work nobody accepted ends up on a call sheet.
    work: tuple[WorkItem, ...] = tuple(s.to_work_item() for s in scenes)

    return ScheduleProblem(
        problem_id="UC-00",
        production_calendar=CALENDAR,
        work_items=work,
        constraints=constraints,
        roster=ROSTER,
        locations=LOCATIONS,
        company=COMPANY,
    )


def render(problem: ScheduleProblem, result: SolveResult) -> str:
    """The demo artifact: what went in, what came out, and what decided it."""
    out: list[str] = [
        "=" * 78,
        "UC-00  Build an MVP board from structured fixtures",
        "=" * 78,
        "",
        f"Production calendar   {len(problem.production_calendar)} days, "
        f"{min(problem.production_calendar):%a %d %b} to "
        f"{max(problem.production_calendar):%a %d %b %Y}",
        f"Work items            {len(problem.work_items)} "
        f"({sum(w.estimated_duration_minutes for w in problem.work_items) / 60:.1f}h "
        f"of coverage)",
        f"Locations             {len(problem.locations)}",
        f"Roster                {len(problem.roster)}",
        "",
        "CONSTRAINTS -- every bound that reaches the solver, and what produced it",
        "-" * 78,
    ]
    for record in problem.constraints:
        out.append(f"  {record.explain()}")
    out += [
        "",
        f"  snapshot {problem.constraint_snapshot_hash[:12]}  "
        f"({len(problem.constraints.binding)} binding)",
        "",
    ]

    if not result.viable_boards:
        out += [
            "NO BOARD",
            "-" * 78,
            f"  status: {result.status}",
        ]
        if result.conflict_set is not None:
            out.append(f"  {result.conflict_set}")
        out.extend(f"  {d}" for d in result.diagnostics)
        return "\n".join(out)

    board = result.board
    if board is None:
        raise RuntimeError("solver reported viable boards without returning a board")
    out += [
        stripboard(
            board,
            work_items=problem.work_items,
            locations=problem.locations,
            roster=problem.roster,
        ),
        "",
        "WHY THIS STRIP IS WHERE IT IS  (AUD-001)",
        "-" * 78,
        "",
    ]
    # One trace rather than eight. The point is that any strip can be traced, and a
    # wall of eight near-identical traces buries that rather than showing it.
    traced = board.days[0].assignments[0].work_id
    out.append(
        explain_assignment(
            board,
            traced,
            constraints=problem.constraints,
            work_items=problem.work_items,
        )
    )
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    description = (__doc__ or "UC-00 demo").splitlines()[0]
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--fixtures",
        type=pathlib.Path,
        default=FIXTURES,
        help="directory holding scenes.json and constraints.json",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="solver seed; boards are deterministic per seed",
    )
    parser.add_argument(
        "--out", type=pathlib.Path, default=None, help="also write the artifact here"
    )
    args = parser.parse_args(argv)

    problem = build_problem(args.fixtures)
    result = solve(problem, seed=args.seed)
    artifact = render(problem, result)
    print(artifact)
    if args.out is not None:
        args.out.write_text(artifact + "\n")

    # A demo that exits 0 having produced no board is a demo that will be remembered
    # as passing.
    return 0 if result.viable_boards else 1


if __name__ == "__main__":
    sys.exit(main())
