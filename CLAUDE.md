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
- A cast id typo (`SARA` for `SARAH`) that schedules nobody while the real performer is
  never called.
- (Waiting to happen) a miscompiled CP-SAT constraint, where the solver proves
  optimality of the wrong problem. See `NNG-003` / `SOL-007`.

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
| `daylight.py` | NOAA solar computation. Never retrieved |
| `scenes.py` / `work.py` | `SceneRecord` → `WorkItem` |
| `fixtures.py` | Validated fixture import |
| `review.py` | Findings, decisions, pickups |
| `grounding/` | Parallel Search/Extract → `Evidence` |

`grounding/coverage.py` is *date* coverage (does this text concern the target date), not
shot coverage. Shot coverage lives in `review.py`.

## Things that look like improvements and are not

- Caching Parallel Search results. Breaks track eligibility.
- Retrieving daylight instead of computing it. Tried; it was wrong in the worst way.
- Adding a `Role` for cast or crew. They are recipients and constraint sources, never
  deciding actors — `ACT-010` asserts no such role exists.
- Trusting solver output because a solver produced it. CP-SAT guarantees a solution
  satisfies *the model it was given*, which is not the same as satisfying the actual
  constraints.
- Marking a requirement `built`/`unit-built` without a test citing it. The gate fails,
  and correctly.

## Open

- `SOL-005` names objective weights that **are not declared anywhere**. How many holding
  days is one company move worth? A production judgement, and it decides what the demo's
  three options look like. Settle before writing the objective.
- `PIK-008`: `PickupTask.from_decision` copies cast, location and duration from the
  original coverage item, asserting a pickup needs identical resources. Often false, and
  false expensively — calling cast who are not needed accrues holding days.
- MVP-0 is the live front: `SOL` ×10, `CON` ×3, `DAY` ×2, `AUD` ×2, `CST` ×1, `OUT` ×1.
