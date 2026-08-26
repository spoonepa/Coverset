"""Requirement traceability report.

Derives the matrix from the test suite rather than from a hand-maintained table.
Tests declare what they verify with `@pytest.mark.req("GRD-003")`; this reads those
markers straight out of the AST and reconciles them against `SPEC.md`.

That direction matters. A table maintained by hand drifts silently and then reads as
reassurance. Here a requirement claiming implementation with no test is a reported
gap and a non-zero exit, and a test citing a requirement that does not exist is the
same.

    uv run python scripts/traceability.py           # summary, slices, use cases
    uv run python scripts/traceability.py --matrix  # every requirement, every test

Exits non-zero when the spec document is malformed (unreadable row, unknown
vocabulary, duplicate ID, use case citing a requirement that does not exist), when an
implemented requirement has no test, when a test cites an unknown ID, or when a
requirement claims `demo-ready` without the verification tier it needs (TRK-005).
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC = ROOT / "SPEC.md"
TESTS = ROOT / "tests"

ROW = re.compile(r"^\|\s*([A-Z]{3}-\d{3})\s*\|(.+)$")
UC_HEADING = re.compile(r"^### (UC-\d+)\s+[-—]\s+(.+)$")
UC_EXERCISES = re.compile(r"^\*\*Exercises:\*\*\s*(.+)$")

MATURITY = ["not-started", "domain-model", "unit-built", "integrated", "demo-ready"]
RANK = {m: i for i, m in enumerate(MATURITY)}
TIERS = ["none", "offline", "live", "manual-demo"]
SLICES = ["MVP-0", "MVP-1", "MVP-2", "MVP-3", "POST"]

IMPLEMENTED = RANK["unit-built"]
"""At or above this maturity, a requirement claims working behaviour and must be tested."""
DELIVERABLE = RANK["demo-ready"]
"""A use case is deliverable only when everything it exercises reaches this."""


@dataclass(frozen=True)
class TestRef:
    file: str
    name: str
    live: bool

    def __str__(self) -> str:
        return f"{self.file}::{self.name}{' [live]' if self.live else ''}"


@dataclass
class Requirement:
    id: str
    statement: str
    maturity: str
    verification: str
    slice: str
    notes: str = ""
    tests: list[TestRef] = field(default_factory=list)

    @property
    def area(self) -> str:
        return self.id[:3]

    @property
    def claims_implementation(self) -> bool:
        return RANK.get(self.maturity, 0) >= IMPLEMENTED

    @property
    def is_deliverable(self) -> bool:
        return RANK.get(self.maturity, 0) >= DELIVERABLE

    @property
    def needs_live(self) -> bool:
        return self.verification == "live"

    @property
    def live_tests(self) -> list[TestRef]:
        return [t for t in self.tests if t.live]


@dataclass
class NonNegotiable:
    id: str
    contract: str


@dataclass
class UseCase:
    id: str
    title: str
    line: int = 0
    exercises: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SpecDefect:
    """Something wrong with the spec document itself, rather than with coverage.

    These exist because the parser used to skip anything it could not read. A
    mistyped maturity value made the requirement vanish from every report, and the
    only visible symptom was a total that nobody had memorised. Silence is the worst
    possible response to a malformed row.
    """

    line: int
    problem: str
    detail: str = ""

    def __str__(self) -> str:
        where = f"SPEC.md:{self.line}" if self.line else "SPEC.md"
        return f"{where}  {self.problem}" + (f" -- {self.detail}" if self.detail else "")


@dataclass
class ParsedSpec:
    requirements: dict[str, Requirement] = field(default_factory=dict)
    non_negotiables: list[NonNegotiable] = field(default_factory=list)
    use_cases: list[UseCase] = field(default_factory=list)
    defects: list[SpecDefect] = field(default_factory=list)


REQUIREMENT_CELLS = 5
"""statement | maturity | verification | slice | notes"""
NON_NEGOTIABLE_CELLS = 2
"""contract | rationale"""


def _cells(rest: str) -> list[str]:
    """Split a markdown row body, dropping the empty cell a trailing pipe leaves."""
    cells = [c.strip() for c in rest.split("|")]
    while cells and not cells[-1]:
        cells.pop()
    return cells


def parse_spec(text: str) -> ParsedSpec:
    """Parse and validate the spec. Every ID-bearing row must account for itself.

    A row that matches the ID pattern is either a well-formed requirement, a
    well-formed non-negotiable, or a defect. There is no fourth outcome, and in
    particular there is no silent skip.
    """
    spec = ParsedSpec()
    seen_at: dict[str, int] = {}

    for n, line in enumerate(text.splitlines(), start=1):
        if m := ROW.match(line):
            rid, cells = m.group(1), _cells(m.group(2))

            if rid in seen_at:
                spec.defects.append(SpecDefect(
                    n, f"duplicate requirement id {rid}",
                    f"first defined at line {seen_at[rid]}"))
                continue
            seen_at[rid] = n

            if rid.startswith("NNG"):
                if len(cells) != NON_NEGOTIABLE_CELLS:
                    spec.defects.append(SpecDefect(
                        n, f"malformed non-negotiable row {rid}",
                        f"expected {NON_NEGOTIABLE_CELLS} cells, found {len(cells)}"))
                    continue
                spec.non_negotiables.append(NonNegotiable(id=rid, contract=cells[0]))
                continue

            if len(cells) != REQUIREMENT_CELLS:
                spec.defects.append(SpecDefect(
                    n, f"malformed requirement row {rid}",
                    f"expected {REQUIREMENT_CELLS} cells "
                    f"(statement|maturity|verification|slice|notes), found {len(cells)}"))
                continue

            statement, maturity, verification, slice_, notes = cells
            bad = False
            if not statement:
                spec.defects.append(SpecDefect(n, f"{rid} has an empty statement"))
                bad = True
            if maturity not in RANK:
                spec.defects.append(SpecDefect(
                    n, f"{rid} has unknown maturity {maturity!r}",
                    f"expected one of {', '.join(MATURITY)}"))
                bad = True
            if verification not in TIERS:
                spec.defects.append(SpecDefect(
                    n, f"{rid} has unknown verification tier {verification!r}",
                    f"expected one of {', '.join(TIERS)}"))
                bad = True
            if slice_ not in SLICES:
                spec.defects.append(SpecDefect(
                    n, f"{rid} has unknown slice {slice_!r}",
                    f"expected one of {', '.join(SLICES)}"))
                bad = True
            if bad:
                continue

            spec.requirements[rid] = Requirement(
                id=rid, statement=statement, maturity=maturity,
                verification=verification, slice=slice_, notes=notes)

        elif m := UC_HEADING.match(line):
            uid = m.group(1)
            if any(uc.id == uid for uc in spec.use_cases):
                spec.defects.append(SpecDefect(n, f"duplicate use case id {uid}"))
            spec.use_cases.append(UseCase(id=uid, title=m.group(2).strip(), line=n))
        elif (m := UC_EXERCISES.match(line)) and spec.use_cases:
            if spec.use_cases[-1].exercises:
                spec.defects.append(SpecDefect(
                    n, f"{spec.use_cases[-1].id} has more than one Exercises line"))
            spec.use_cases[-1].exercises = re.findall(r"[A-Z]{3}-\d{3}", m.group(1))

    for uc in spec.use_cases:
        if not uc.exercises:
            spec.defects.append(SpecDefect(
                uc.line, f"{uc.id} exercises no requirements",
                "a use case with no Exercises line cannot be reported on"))
        for rid in uc.exercises:
            if rid not in spec.requirements:
                spec.defects.append(SpecDefect(
                    uc.line, f"{uc.id} cites unknown requirement {rid}"))

    return spec


def _marker_ids(node: ast.expr, wanted: str) -> list[str] | None:
    """Return the string args of `@pytest.mark.<wanted>(...)`, or [] for a bare marker."""
    target, args = node, []
    if isinstance(node, ast.Call):
        target, args = node.func, node.args
    if not isinstance(target, ast.Attribute) or target.attr != wanted:
        return None
    if not (isinstance(target.value, ast.Attribute) and target.value.attr == "mark"):
        return None
    return [a.value for a in args if isinstance(a, ast.Constant) and isinstance(a.value, str)]


def parse_tests() -> tuple[dict[str, list[TestRef]], list[tuple[str, str]]]:
    found: dict[str, list[TestRef]] = defaultdict(list)
    untagged: list[tuple[str, str]] = []

    for path in sorted(TESTS.glob("test_*.py")):
        tree = ast.parse(path.read_text())
        module_live = any(
            _marker_ids(d, "live") is not None
            for stmt in tree.body
            if isinstance(stmt, ast.Assign)
            and any(getattr(t, "id", "") == "pytestmark" for t in stmt.targets)
            for d in (stmt.value.elts if isinstance(stmt.value, ast.List) else [stmt.value])
        )
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
                continue
            ids: list[str] = []
            live = module_live
            for dec in node.decorator_list:
                if (got := _marker_ids(dec, "req")) is not None:
                    ids.extend(got)
                if _marker_ids(dec, "live") is not None:
                    live = True
            ref = TestRef(file=path.name, name=node.name, live=live)
            if not ids:
                untagged.append((path.name, node.name))
            for rid in ids:
                found[rid].append(ref)
    return found, untagged


def main() -> int:
    show_matrix = "--matrix" in sys.argv
    spec = parse_spec(SPEC.read_text())
    reqs, nngs, cases = spec.requirements, spec.non_negotiables, spec.use_cases
    found, untagged = parse_tests()

    orphans = sorted(set(found) - set(reqs))
    for rid, refs in found.items():
        if rid in reqs:
            reqs[rid].tests = refs

    implemented = [r for r in reqs.values() if r.claims_implementation]
    covered = [r for r in implemented if r.tests]
    gaps = [r for r in implemented if not r.tests]
    live_required = [r for r in implemented if r.needs_live]
    live_covered = [r for r in live_required if r.live_tests]
    # TRK-005: demo-ready plus live-required plus no live test is a false claim.
    false_demo_ready = [r for r in reqs.values() if r.is_deliverable and r.needs_live and not r.live_tests]

    rule = "=" * 76
    print(f"\n{rule}\nCOVERSET REQUIREMENT TRACEABILITY\n{rule}")

    print(f"\n  Requirements       {len(reqs)}   (+{len(nngs)} non-negotiable)")
    for m in MATURITY:
        if n := sum(1 for r in reqs.values() if r.maturity == m):
            print(f"    {m:<16} {n:>3}")

    print(f"\n  Verification required")
    for t in TIERS:
        if n := sum(1 for r in reqs.values() if r.verification == t):
            print(f"    {t:<16} {n:>3}")

    pct = 100 * len(covered) / len(implemented) if implemented else 100.0
    print(f"\n  Tests (requirements claiming implementation)")
    print(f"    require a test   {len(implemented):>3}")
    print(f"    have one         {len(covered):>3}  ({pct:.0f}%)")
    print(f"    gaps             {len(gaps):>3}")
    print(f"    live required    {len(live_required):>3}")
    print(f"    live covered     {len(live_covered):>3}")
    print(f"    untagged tests   {len(untagged):>3}")

    print(f"\n  Use cases          {len(cases)}")
    ready = [uc for uc in cases if all(reqs[r].is_deliverable for r in uc.exercises if r in reqs)]
    print(f"    deliverable      {len(ready):>3}")
    print(f"    blocked          {len(cases) - len(ready):>3}")

    print(f"\n{rule}\nSLICE PROGRESS\n{rule}")
    for s in SLICES:
        in_slice = [r for r in reqs.values() if r.slice == s]
        if not in_slice:
            continue
        done = sum(1 for r in in_slice if r.claims_implementation)
        bar = "#" * round(20 * done / len(in_slice)) if in_slice else ""
        print(f"  {s:<7} {done:>3}/{len(in_slice):<3} implemented  {bar:<20}")
        remaining = defaultdict(list)
        for r in in_slice:
            if not r.claims_implementation:
                remaining[r.area].append(r.id)
        if remaining:
            top = sorted(remaining.items(), key=lambda kv: -len(kv[1]))
            print(f"          remaining: " + "  ".join(f"{a}x{len(v)}" for a, v in top))

    print(f"\n{rule}\nUSE CASES -- can a user complete the journey?\n{rule}")
    for uc in cases:
        known = [reqs[r] for r in uc.exercises if r in reqs]
        unknown = [r for r in uc.exercises if r not in reqs]
        done = [r for r in known if r.is_deliverable]
        # Two different kinds of blocker, needing two different kinds of work.
        to_build = sorted(r.id for r in known if not r.claims_implementation)
        to_integrate = sorted(r.id for r in known if r.claims_implementation and not r.is_deliverable)
        state = "READY  " if not (to_build or to_integrate) else "BLOCKED"
        print(f"  {state} {uc.id}  {len(done)}/{len(uc.exercises):<3} {uc.title}")
        if to_build:
            print(f"            needs building     ({len(to_build)}): {', '.join(to_build[:6])}"
                  + (" ..." if len(to_build) > 6 else ""))
        if to_integrate:
            print(f"            needs integration  ({len(to_integrate)}): {', '.join(to_integrate[:6])}"
                  + (" ..." if len(to_integrate) > 6 else ""))
        if unknown:
            print(f"            UNKNOWN IDS: {', '.join(unknown)}")
            orphans.extend(unknown)

    blocking: dict[str, list[str]] = defaultdict(list)
    for uc in cases:
        for rid in uc.exercises:
            if rid in reqs and not reqs[rid].claims_implementation:
                blocking[rid].append(uc.id)
    if blocking:
        print(f"\n{rule}\nCRITICAL PATH -- unbuilt requirements ranked by journeys blocked\n{rule}")
        for rid, ucs in sorted(blocking.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:8]:
            r = reqs[rid]
            print(f"  {len(ucs)}x  {rid}  [{r.slice}]  {r.statement[:40]}")
            print(f"        blocks {', '.join(ucs)}")

    if show_matrix:
        for area in sorted({r.area for r in reqs.values()}):
            print(f"\n{'-' * 76}\n{area}\n{'-' * 76}")
            for r in sorted((x for x in reqs.values() if x.area == area), key=lambda x: x.id):
                mark = "OK " if r.tests else ("GAP" if r.claims_implementation else "-- ")
                print(f"  {mark} {r.id}  [{r.maturity}/{r.verification}/{r.slice}]  {r.statement[:40]}")
                for t in r.tests:
                    print(f"          {t}")

    if gaps:
        print(f"\n{rule}\nGAPS -- claims implementation, nothing verifies it\n{rule}")
        for r in gaps:
            print(f"  {r.id}  [{r.maturity}]  {r.statement}")

    if orphans:
        print(f"\n{rule}\nORPHANS -- tests cite IDs absent from SPEC.md\n{rule}")
        for rid in sorted(set(orphans)):
            print(f"  {rid}: {', '.join(str(t) for t in found.get(rid, []))}")

    if false_demo_ready:
        print(f"\n{rule}\nFALSE DEMO-READY -- live verification required, none present (TRK-005)\n{rule}")
        for r in false_demo_ready:
            print(f"  {r.id}  {r.statement[:60]}")

    if missing_live := [r for r in live_required if not r.live_tests]:
        print(f"\n{rule}\nLIVE COVERAGE MISSING -- spec requires live, only offline present\n{rule}")
        print("  Not a failure while these are below demo-ready, but they are verified")
        print("  against fixtures of our own writing, which cannot catch a false assumption.\n")
        for r in missing_live:
            print(f"  {r.id}  {r.statement[:58]}")

    if spec.defects:
        print(f"\n{rule}\nSPEC DEFECTS -- the document itself is malformed\n{rule}")
        print("  A row the parser cannot read used to be skipped, which made the")
        print("  requirement disappear from every report with no other symptom.\n")
        for d in spec.defects:
            print(f"  {d}")

    if unexercised := sorted(
        r.id for r in reqs.values()
        if not any(r.id in uc.exercises for uc in cases)
    ):
        print(f"\n{rule}\nEXERCISED BY NO USE CASE ({len(unexercised)})\n{rule}")
        print("  Not a failure -- cross-cutting requirements legitimately sit outside any")
        print("  single journey -- but a requirement no journey needs is worth questioning.\n")
        for i in range(0, len(unexercised), 6):
            print("  " + ", ".join(unexercised[i:i + 6]))

    if untagged:
        print(f"\n{rule}\nUNTAGGED TESTS -- verify something, but say what\n{rule}")
        for file, name in untagged:
            print(f"  {file}::{name}")

    failed = bool(spec.defects or gaps or orphans or false_demo_ready)
    print(f"\n{rule}")
    print("FAIL: traceability incomplete" if failed else "PASS: every implemented requirement is traced")
    print(rule)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
