## Review

- **Correct:** `SPEC.md` has a coherent traceability foundation: stable requirement IDs, explicit status vocabulary, pytest `req` markers, and use cases mapped to requirement IDs (`SPEC.md:6-17`, `SPEC.md:239-244`). I verified the current matrix with `uv run python scripts/traceability.py --matrix`: 70 requirements, 45 verifiable, 0 gaps, 110 mapped tests, no untagged tests. `uv run pytest` also passes: 181 passed, 8 deselected.
- **Correct:** The strongest parts of the spec are the authority boundary and grounding/date-binding requirements. They are reflected in code and tests: role authority in `src/coverset/actors.py:36-94`, coverage/pickup workflow in `src/coverset/review.py`, and runtime Search/Extract/date-coverage tests in `tests/test_search_grounding.py:46-322`.
- **Fixed:** No files changed; this was a review-only task.

### Prioritized findings and concrete suggested edits

1. **Blocker — hard constraints vs “viable” boards are contradictory/ambiguous.**  
   Evidence:
   - `SPEC.md:179` says every returned board “provably satisfies its constraint set.”
   - `SPEC.md:190` says replanning returns “multiple viable boards.”
   - `PROJECT_BRIEF.md:212-219` describes those viable options as including “2 turnaround violations” and “church scenes fall outside the permit window (location unavailable on that date).”
   - `PROJECT_BRIEF.md:156-165` and `SPEC.md:183` list turnaround and location/permit windows as constraint families, not merely reporting dimensions.

   Why it matters: a board outside a permit window is not viable under the stated solver contract. Turnaround may be waivable/costed in production reality, but the spec does not define which constraints are hard, which are soft, and which require human approval.

   Concrete edits:
   - Add a short section before `SOL` in `SPEC.md`:
     > **Hard and soft constraints.** Hard constraints must never be violated by a returned board: already-shot immutability, permit/location availability, cast availability, daylight feasibility where required, and legal child-labor limits. Soft production costs may be optimized or surfaced for approval: company moves, holding days, overtime exposure, and waivable turnaround penalties where production policy permits. A returned board may carry required approvals, but it must not be labelled viable if it violates a hard constraint.
   - Revise `SOL-002`:
     > Every board returned satisfies all hard constraints. Soft costs and waivable exposures are represented as objective terms or required approvals, not hidden constraint violations.
   - Revise `MON-002`:
     > Replanning returns multiple boards that satisfy hard constraints, each with production-readable cost deltas and any required approvals stated.
   - Revise the demo in `PROJECT_BRIEF.md:215-219`: make Option C an infeasible/rejected option, or replace it with a feasible-but-costly permit mitigation. For Option A, say “2 turnaround waiver/overtime exposures requiring approval” if turnaround is intended to be soft.

2. **High — monitoring daylight contradicts the computed-daylight design.**  
   Evidence:
   - `PROJECT_BRIEF.md:37-40` says Coverset watches “weather, permit pages, daylight.”
   - `SPEC.md:151` says daylight is computed from coordinates/date and “never retrieved.”
   - `PROJECT_BRIEF.md:114-117` also says daylight is not retrieved and is computed.

   Why it matters: Parallel Monitor watches changing external sources. Daylight has no source to monitor; it should be recomputed when the schedule date/location changes.

   Concrete edits:
   - Change `PROJECT_BRIEF.md:37-40` to:
     > It then watches the mutable real-world facts the schedule depends on — weather and permit pages — and recomputes deterministic daylight windows when dates or locations change.
   - Add a `MON`/`TRK` note in `SPEC.md`:
     > Monitor watches mutable external source URLs only. Deterministic algorithms such as daylight are rerun during solve/replan, not monitored as sources.
   - Revise `TRK-003`:
     > Parallel Monitor watches the weather and permit source URLs a live schedule depends on and emits change events.

3. **High — `UPM / Line Producer` authority is specified but only UPM exists in the implementation/tests.**  
   Evidence:
   - `SPEC.md:57` lists “UPM / Line Producer.”
   - `SPEC.md:102` says added shoot-day work requires approval from “the UPM or Line Producer.”
   - `src/coverset/actors.py:39-43` has `Role.UPM` but no Line Producer role.
   - `src/coverset/actors.py:91-94` grants cost approval only to `Role.UPM`.
   - `tests/test_actors.py:73-77` verifies only UPM approval.

   Why it matters: `ACT-005` is marked partial, but the missing slice is not stated in the spec. A reader cannot tell whether “Line Producer” is an alias, an unimplemented role, or intentionally folded into UPM.

   Concrete edits:
   - Either explicitly define it as an alias:
     > `UPM` represents the production cost-approval role; on productions where the Line Producer holds this authority, that person is recorded under the UPM/cost-approver role.
   - Or add a distinct role requirement:
     > `ACT-005a`: Cost approval may be granted by UPM or Line Producer authority.
     > `ACT-005b`: Any schedule selection or pickup that adds a shoot day records the cost approver before it becomes selectable.
   - Add a partial-status note:
     > Implemented: UPM cost-approval capability flag. Missing: Line Producer role/alias decision and enforcement at board-selection or pickup-day creation.

4. **Medium — partial status lacks an explicit implemented/missing/test mapping.**  
   Evidence:
   - `SPEC.md:15-17` defines `partial`, but individual partial rows do not say which slice is implemented.
   - `SPEC.md:101-102` and `SPEC.md:235` mark `ACT-004`, `ACT-005`, and `AUD-002` partial with no explanation.
   - `scripts/traceability.py:34` treats `partial` as needing tests, and `scripts/traceability.py:196-199`, `220-223` treat use cases as blocked only by `planned`, not by `partial`.

   Why it matters: traceability can show “OK” for a partial requirement while the spec does not explain what remains. Future use cases could be reported “READY” even with partial requirements.

   Concrete edits:
   - Add a fourth column to requirement tables, or a short “Partial scope” table:
     > `ACT-004`: Implemented: First AD capability flag. Missing: BoardSelection object, decision audit record, and enforcement when selecting among replan options.  
     > `ACT-005`: Implemented: UPM cost-approval capability flag. Missing: Line Producer handling and enforcement when work adds a shoot day.  
     > `AUD-002`: Implemented: sourced evidence URLs and computed daylight algorithm provenance. Missing: provenance on every typed constraint handed to the solver.
   - Change use-case prose at `SPEC.md:241-244`:
     > A use case is deliverable only when every exercised requirement is `built`; `partial` requirements count as blockers unless the use case explicitly names the implemented slice.
   - Align `scripts/traceability.py` later so `partial` appears as `PARTIAL`/blocked rather than `READY`.

5. **Medium — several planned requirements are too broad to be “narrow enough to test.”**  
   Evidence:
   - `BRK-001` bundles PDF parsing, scene identity, INT/EXT, day/night, location, page eighths, and cast into one requirement (`SPEC.md:163`).
   - `CON-002` says extraction is validated against “known-good values” without defining the oracle (`SPEC.md:171`).
   - `SOL-003` requires “the minimal conflicting constraint set” but does not define the kind of minimality (`SPEC.md:180`).

   Concrete edits:
   - Split `BRK-001` into smaller requirements:
     > scene headings are detected with stable scene IDs; INT/EXT and day/night are normalized; page eighths are positive and rounded by a documented rule; cast mentions resolve to roster IDs; unreadable/low-confidence pages raise or mark review-needed.
   - Revise `CON-002`:
     > A typed constraint derived from retrieved text is validated by fact-family-specific checks: weather probability 0–100 with units/date/source coverage, wind/temperature unit normalization, permit windows as valid local time intervals, and blackout dates as dates in the production calendar.
   - Revise `SOL-003`:
     > When no valid schedule exists, return an irreducible infeasible subset: removing any one returned constraint makes the subset no longer sufficient to prove infeasibility. If cardinality-minimal is intended, say that explicitly.

6. **Medium — `CON-003` should distinguish evidence-level coverage from source-level binding.**  
   Evidence:
   - `GRD-003` requires at least one source to mention the date (`SPEC.md:137`).
   - `CON-003` says extraction may bind a dated value only from a source satisfying `GRD-003` (`SPEC.md:172`).
   - Code has source-level `covering_urls` / `dated_sources` (`tests/test_search_grounding.py:130-137`), but the spec wording could be read as “the evidence set passed GRD-003, therefore any source in it can be used.”

   Concrete edit:
   - Revise `CON-003`:
     > Extraction may bind a dated value only from the evidence sources recorded as covering the target date; non-covering sources in the same evidence set are context only and cannot supply the bound value.

7. **Low — README live-verification wording underspecifies the test tier.**  
   Evidence:
   - `README.md:29-33` says to confirm live grounding via `uv run python scripts/smoke_grounding.py`.
   - `SPEC.md:25-32` and `README.md:60-69` define live verification as `uv run pytest -m live`.

   Concrete edit:
   - Change `README.md:29` to “Smoke one live grounding path,” then add:
     ```sh
     uv run pytest -m live      # full live verification tier
     ```
   - Keep `smoke_grounding.py` documented as a quick manual smoke, not a substitute for requirement-level live tests.

8. **Note — requested scratch files were not present.**  
   `plan.md` and `progress.md` were requested as inputs, but both paths returned `ENOENT`. I did not treat that as a repo finding; the review used `SPEC.md`, `PROJECT_BRIEF.md`, `README.md`, traceability output, and source/tests instead.