# Coverset — working notes

An agentic shooting-schedule partner for first assistant directors.

`PROJECT_BRIEF.md` says why. `SPEC.md` is the contract — 135 requirements with stable
IDs, plus 10 use cases. This file is what you would otherwise get wrong.

## The spine

**Gemini interprets · Parallel grounds · humans decide · CP-SAT schedules.**

No language model emits a schedule. No advisory agent decides anything. These are not
style preferences — they are the product's whole claim to being auditable, and they are
enforced **structurally rather than by convention**, because a rule that lives only in a
docstring gets refactored away under deadline pressure.

Existing examples of that enforcement, worth matching:

- `ReviewFinding` has no disposition field, so it cannot express an outcome even in
  principle. The strongest thing it can do is put an item in front of a human.
- `Role` has no member an automated agent could occupy, so an agent cannot be
  constructed as a decider. That beats a name blocklist, which only catches names
  someone thought of.
- `PickupTask` cannot be constructed without a human decision authorising it.
- `Evidence` cannot be constructed without at least one source URL.
- `SceneRecord` must be `active` before it converts to a `WorkItem`.
- `Board` has no way to exist without a passing `ValidationReport` for the same
  constraint snapshot, so an unvalidated board is not a board carrying a warning.
- `ValidationReport` requires the ids it was obliged to check, so a vacuous report
  that silently checked nothing cannot be constructed.
- A `ConstraintRecord` in the `daylight` family rejects URL provenance outright, so a
  retrieved sunset cannot masquerade as a computed one.
- `validate.py` imports neither `solver` nor `ortools`. The independence is a fact
  about the import graph, not about anyone remembering.
- `ConflictSet` cannot be built naming nothing, and cannot call itself irreducible
  while naming no relaxable constraint. An empty conflict reads as an answer.
- Daylight binds only through a constraint record. `ScheduleProblem` synthesises
  `SYN-DAYLIGHT` rather than letting the bound apply invisibly, so it reaches the
  snapshot hash and the validation report like any other.

When you add a boundary, make it unrepresentable rather than checked.

## The one non-negotiable

**Parallel Search is called at runtime, on every grounding request.** No cache, no
precomputed fact table, no offline fallback. This is track eligibility, not a
performance trade-off. Two tests assert the POST to `/v1/search` *at the wire* so a
refactor cannot satisfy it on paper while bypassing it in practice. If they fail,
restore the runtime call — do not relax the test.

## The characteristic failure mode

Read this before writing anything that produces a value.

Every real bug found in this project has been **well-formed, type-correct, plausible,
and wrong**:

- A sunset time correct for *today* rather than the shoot date — 0 of 8 live sources
  contained the requested date, and three were dense with plausible clock times.
- A precipitation percentage bound to no particular day.
- A daylight window an hour off across a DST boundary, from a hardcoded UTC offset.
- A second hour-shaped one by a different road: `wrap - call` on two aware datetimes
  that share a tzinfo returns the *wall-clock* difference, so a twelve-hour night the
  clocks went back inside measured twelve hours and ran thirteen. Both the model and
  the validator subtracted the same way and agreed. Use `clock.elapsed`.
- A cast id typo (`SARA` for `SARAH`) that schedules nobody while the real performer is
  never called.
- A miscompiled CP-SAT objective term: company moves counted against the previous
  *calendar* day rather than the previous *worked* day, so a board with a gap day was
  proven optimal against a cost it did not have. Every hard constraint held; the
  solver said `OPTIMAL`. Caught only by measuring the cost off the finished board and
  refusing to return one when the two readings disagree. See `NNG-003` / `SOL-007`.
- A conflict set naming the daylight constraint for a problem that was infeasible
  with every constraint switched off. The explanation, not the value, was the
  confident wrong answer. Two readings do not help here: **both** the model and the
  measurement defined a company move wrongly and agreed with each other. Cross-checks
  catch disagreement, never a shared misconception.

None of these throw. None look wrong downstream. So:

- **Raise rather than default.** A missing constraint the solver never learns about is
  one the board is free to violate.
- **Prove the binding, not just the value.** A source URL is not provenance for a dated
  value; the date must be demonstrably present (`GRD-003`, `coverage.py`).
- **Validate against known-good values**, not against another instance of the same
  method. Computed daylight is checked against published almanac tables.
- **Prefer computing to retrieving** where a closed form exists. Daylight is arithmetic;
  weather and permits genuinely are not.

## Conventions actually followed here

- Frozen dataclasses with `slots=True`. Transitions return new instances, so a decision
  never overwrites the one before it and the audit trail is real rather than
  reconstructed.
- **Typed entities, never bare strings** for domain references. `Actor` not `str`,
  `CastMember` not a name, `Location` with a stable id. Two of this project's bugs were
  exactly an untyped string where an entity belonged.
- **Report every failure at once, not the first.** `Roster.resolve`, `LocationBook.resolve`
  and `load_scenes` all do this — someone fixing a breakdown wants the whole list, not
  one error per run. Independent checks must not cascade.
- Comments explain *why*, especially why a guard exists. Several guards here look like
  ceremony until you know which bug produced them.
- Tests declare what they verify: `@pytest.mark.req("GRD-003")`. Untagged tests are
  reported; a requirement claiming implementation with no test fails the gate.

## Workflow

1. **Specify first.** Add the requirement to `SPEC.md` with an ID, a maturity, a
   verification tier and a slice.
2. **Probe before trusting.** Anything depending on an external service gets a throwaway
   script against the real API *before* code is designed around it. Every finding in the
   brief came from doing this; the one time it was skipped, the design was built on an
   assumption that turned out false.
3. Build, with failure loud.
4. Test at both tiers, citing the requirement.
5. Record surprises in the brief's *Findings and learnings*.

```sh
uv run pytest                              # offline: deterministic, no key needed
uv run pytest -m live                      # real Parallel API; needs PARALLEL_API_KEY
uv run python scripts/traceability.py      # add --matrix for every requirement
./scripts/check.sh [--live]                # all gates; run before committing
```

**Offline tests cannot catch a false assumption** — their fixtures encode what the API
was *assumed* to return. That is not hypothetical: the suite was green while the sunset
grounding was completely wrong. The live tier exists for this. `PARALLEL_API_KEY` lives
in `.env` (gitignored).

## Layout

| Module | Holds |
|---|---|
| `locations.py` | `Location`, `LocationBook` — shared domain type |
| `people.py` | `CastMember`, `Roster`, `Engagement`, `Company` |
| `actors.py` | `Role`, `Actor` — who may decide what |
| `clock.py` | `elapsed` / `advance` — real time, never wall-clock |
| `daylight.py` | NOAA solar computation. Never retrieved |
| `scenes.py` / `work.py` | `SceneRecord` → `WorkItem` |
| `fixtures.py` | Validated fixture import — `load_scenes`, `load_constraints` |
| `demo.py` | `UC-00` end to end: fixtures → board → stripboard |
| `review.py` | Findings, decisions, pickups |
| `constraints.py` | `ConstraintRecord` — the only way a fact reaches the solver |
| `solver.py` | CP-SAT compilation, objective, conflict shrink |
| `validate.py` | The second, independent reading of every binding constraint |
| `board.py` | `Assignment`, `Board`, `ValidationReport` — inert records |
| `stripboard.py` | `OUT-003` stripboard and `AUD-001` per-strip tracing |
| `grounding/` | Parallel Search/Extract → `Evidence` |

`grounding/coverage.py` is *date* coverage (does this text concern the target date), not
shot coverage. Shot coverage lives in `review.py`.

## Things that look like improvements and are not

- Caching Parallel Search results. Breaks track eligibility.
- Retrieving daylight instead of computing it. Tried; it was wrong in the worst way.
- Adding a `Role` for cast or crew. They are recipients and constraint sources, never
  deciding actors — `ACT-010` asserts no such role exists.
- Subtracting two aware datetimes, or `+=`-ing a timedelta onto one. Both are
  wall-clock operations. `clock.elapsed` and `clock.advance` exist because the
  difference is invisible on every date except two a year.
- Trusting solver output because a solver produced it. CP-SAT guarantees a solution
  satisfies *the model it was given*, which is not the same as satisfying the actual
  constraints.
- Marking a requirement `built`/`unit-built` without a test citing it. The gate fails,
  and correctly.

## Open

- `PIK-008`: `PickupTask.from_decision` copies cast, location and duration from the
  original coverage item, asserting a pickup needs identical resources. Often false, and
  false expensively — calling cast who are not needed accrues holding days.
- **UC-00 is deliverable** (25/25 demo-ready) — the only one. `coverset.demo` runs
  `fixtures/uc00/` → `load_scenes`/`load_constraints` → `solve` → `validate` →
  `stripboard`, and `tests/test_demo.py` asserts the fixture bounds reached the
  finished board rather than merely that a board came back. Every other use case
  still needs requirements built, not just wired up; `scripts/traceability.py` ranks
  them. `SOL-004` (locked days) blocks three.
- The demo board leaves a 75-minute Monday standing, because nothing prices a shoot
  day. Moves, holding days and overtime are the declared weights (§4.1), so a board
  that calls the company for one strip costs the same as one that folds it into
  Tuesday and the solver is genuinely indifferent. Real productions price the day.
  Adding that weight changes every board, so it is a decision rather than a fix.
- The solve budget is CP-SAT **deterministic** time, never `max_time_in_seconds`. A
  wall-clock cutoff makes the board depend on machine speed and silently undoes the
  reason the seed is recorded. `SOL-010` asserts the parameter is not there.
- The model reasons in **calendar-day offsets**, never in a day's index in the
  calendar. Calendars skip dark days; index arithmetic silently misdates everything
  downstream of the first gap.
- Daylight bounds the **prefix** of a day, not its total. Sun-bound locations are
  emitted first and the bound is on that prefix, so an interior scene may run past
  sunset while an exterior one may not. A bound on a total says nothing about when in
  the day the total falls.
- A cast daily-hours limit means **call to wrap**, not the sum of scene durations. A
  performer waiting through a company move is still at work.
- **Call times are derived, not chosen.** `_call_time` fixes a day's call from the
  location, the date and whether the day is a night — day work calls at sunrise or
  07:00, night work calls at sunset. The solver picks *which day* work lands on and
  never *when the day starts*. One consequence is not obvious and bites immediately:
  under a twelve-hour turnaround a night day cannot be followed by a shooting day at
  all, because a sunset call wrapping at 21:00 cannot be followed by a 07:00 call.
  Night work therefore has to end a week or sit against a dark day. The first UC-00
  fixture was infeasible for exactly this reason and the conflict set named it
  correctly — `C-CHURCH-PERMIT`, `C-SARAH-AVAILABILITY`, `C-TURNAROUND` — which is
  the machinery working, not a bug.
- A shoot day is a day shoot or a night shoot. Split days are post-MVP, and the model
  refuses to mix them rather than approximating one.
- `SOL-005` weights are settled and declared in `SPEC.md` §4.1: one company move = 3
  holding days, one overtime hour = 0.5. Boards are only comparable under one weight
  set, which is why the board records the weights it was solved under.
