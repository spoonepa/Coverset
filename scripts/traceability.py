"""Requirement traceability report.

Derives the matrix from the test suite rather than from a hand-maintained table.
Tests declare what they verify with `@pytest.mark.req("GRD-003")`; this reads those
markers straight out of the AST and reconciles them against `SPEC.md`.

That direction matters. A table maintained by hand drifts silently and then reads as
reassurance. Here a requirement with no test is a reported gap and a non-zero exit,
and a test citing a requirement that does not exist is the same.

    uv run python scripts/traceability.py           # summary + gaps
    uv run python scripts/traceability.py --matrix  # every requirement, every test

Exits non-zero when a `built` or `partial` requirement has no test, or when a test
cites an unknown requirement ID.
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

REQ_ROW = re.compile(r"^\|\s*([A-Z]{3}-\d{3})\s*\|\s*(.+?)\s*\|\s*`(\w+)`\s*\|")
VERIFIED_STATUSES = {"built", "partial"}
EXTERNAL_PREFIXES = ("TRK", "GRD")
"""Areas that depend on a live external service, where offline coverage alone is
not sufficient evidence -- every finding so far came from a live run."""

OFFLINE_SUFFICIENT = {
    "GRD-002": "failure path; an empty live result set cannot be provoked on demand",
    "GRD-007": "failure path; a live Extract failure cannot be provoked on demand",
    "GRD-009": "pure function over text, with no external dependency",
}
"""Requirements deliberately exempt from live verification, with the reason.

An explicit reviewed list rather than a silent gap: adding an entry here is a
decision someone made and can be argued with, which an absent check is not."""


@dataclass
class Requirement:
    id: str
    statement: str
    status: str
    tests: list[TestRef] = field(default_factory=list)

    @property
    def needs_test(self) -> bool:
        return self.status in VERIFIED_STATUSES

    @property
    def is_external(self) -> bool:
        return self.id.startswith(EXTERNAL_PREFIXES)

    @property
    def live_tests(self) -> list[TestRef]:
        return [t for t in self.tests if t.live]


@dataclass(frozen=True)
class TestRef:
    file: str
    name: str
    live: bool

    def __str__(self) -> str:
        return f"{self.file}::{self.name}{' [live]' if self.live else ''}"


def parse_spec() -> dict[str, Requirement]:
    reqs: dict[str, Requirement] = {}
    for line in SPEC.read_text().splitlines():
        if m := REQ_ROW.match(line):
            rid, statement, status = m.groups()
            reqs[rid] = Requirement(id=rid, statement=statement, status=status)
    return reqs


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
    """Map requirement ID -> tests, and list (file, test) pairs citing nothing."""
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
    reqs = parse_spec()
    found, untagged = parse_tests()

    orphans = sorted(set(found) - set(reqs))
    for rid, refs in found.items():
        if rid in reqs:
            reqs[rid].tests = refs

    by_status: dict[str, list[Requirement]] = defaultdict(list)
    for r in reqs.values():
        by_status[r.status].append(r)

    needs = [r for r in reqs.values() if r.needs_test]
    covered = [r for r in needs if r.tests]
    gaps = [r for r in needs if not r.tests]
    external_no_live = [
        r for r in needs
        if r.is_external and not r.live_tests and r.id not in OFFLINE_SUFFICIENT
    ]
    exempt = [r for r in needs if r.id in OFFLINE_SUFFICIENT]
    total_tests = len({(t.file, t.name) for refs in found.values() for t in refs})

    rule = "=" * 74
    print(f"\n{rule}\nCOVERSET REQUIREMENT TRACEABILITY\n{rule}")

    print(f"\n  Requirements       {len(reqs)}")
    for status in ("built", "partial", "planned"):
        if n := len(by_status.get(status, [])):
            print(f"    {status:<16} {n}")

    pct = 100 * len(covered) / len(needs) if needs else 100.0
    print(f"\n  Verification")
    print(f"    require a test   {len(needs)}")
    print(f"    have one         {len(covered)}  ({pct:.0f}%)")
    print(f"    gaps             {len(gaps)}")
    live_reqs = [r for r in needs if r.live_tests]
    print(f"    live-verified    {len(live_reqs)}  (of {len([r for r in needs if r.is_external])} external)")
    print(f"    tests mapped     {total_tests}")
    print(f"    untagged tests   {len(untagged)}")

    if show_matrix:
        area_of = lambda r: r.id[:3]
        for area in sorted({area_of(r) for r in reqs.values()}):
            print(f"\n{'-' * 74}\n{area}\n{'-' * 74}")
            for r in sorted((x for x in reqs.values() if area_of(x) == area), key=lambda x: x.id):
                mark = "OK " if r.tests else ("-- " if not r.needs_test else "GAP")
                print(f"  {mark} {r.id}  [{r.status}]  {r.statement[:52]}")
                for t in r.tests:
                    print(f"          {t}")

    if gaps:
        print(f"\n{rule}\nGAPS -- claimed built or partial, but nothing verifies them\n{rule}")
        for r in gaps:
            print(f"  {r.id}  [{r.status}]  {r.statement}")

    if orphans:
        print(f"\n{rule}\nORPHANS -- tests cite requirement IDs absent from SPEC.md\n{rule}")
        for rid in orphans:
            print(f"  {rid}: {', '.join(str(t) for t in found[rid])}")

    if external_no_live:
        print(f"\n{rule}\nUNDER-VERIFIED -- external dependency, offline tests only\n{rule}")
        print("  Offline tests encode what the API was assumed to return. Every finding")
        print("  in the brief came from a live run; these have not had one.\n")
        for r in external_no_live:
            print(f"  {r.id}  {r.statement[:62]}")

    if exempt:
        print(f"\n{rule}\nEXEMPT FROM LIVE VERIFICATION -- deliberate, with reason\n{rule}")
        for r in exempt:
            print(f"  {r.id}  {OFFLINE_SUFFICIENT[r.id]}")

    if untagged:
        print(f"\n{rule}\nUNTAGGED TESTS -- verify something, but say what\n{rule}")
        for file, name in untagged:
            print(f"  {file}::{name}")

    failed = bool(gaps or orphans)
    print(f"\n{rule}")
    print("FAIL: traceability incomplete" if failed else "PASS: every verifiable requirement is traced")
    print(rule)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
