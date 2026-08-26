## Review

- Correct: The implemented slices are well-traced and tested. `scripts/traceability.py` parses `@pytest.mark.req(...)` markers from tests and reconciles them with `SPEC.md` (`scripts/traceability.py:31-35`, `scripts/traceability.py:120-149`), and the traceability run reported 45/45 verifiable built/partial requirements covered with no gaps. `uv run pytest` passed with `181 passed, 8 deselected`.
- Correct: Existing implementation is strongest where the spec already has concrete interfaces:
  - Authority is modeled structurally with `Role`/`Actor` (`src/coverset/actors.py:36-51`) and tested for scoped permissions (`tests/test_actors.py:58-77`).
  - Grounding has real request/evidence models (`src/coverset/grounding/facts.py:88-134`, `src/coverset/grounding/search.py:67-127`) and wire-level tests (`tests/test_search_grounding.py:46-63`).
  - Daylight has deterministic computation and almanac/DST tests (`tests/test_daylight.py:48-80`).
  - Review/pickup boundaries are enforced by data types (`src/coverset/review.py:90-128`, `src/coverset/review.py:228-277`) and tested end-to-end (`tests/test_review.py:78-90`, `tests/test_review.py:246-254`).
- Fixed: No files were changed; review-only task.
- Note: The requested `/Users/surpoone/work/git/Coverset/plan.md` and `/Users/surpoone/work/git/Coverset/progress.md` were not present, so the review used `SPEC.md`, `PROJECT_BRIEF.md`, `scripts/traceability.py`, `src/coverset`, and `tests` directly.

### Prioritized implementation-readiness findings

#### Blocker / P0 — Core scheduling and solver requirements are not implementable as written

- Evidence:
  - `SPEC.md` defines the solver in broad one-line requirements only: CP-SAT production, proof of constraint satisfaction, minimal conflict set, locked days, objective terms, and five constraint families (`SPEC.md:174-183`).
  - The brief promises `solve_schedule`, `explain_infeasibility`, `diff_schedules`, and `generate_call_sheet` tools (`PROJECT_BRIEF.md:77-91`) and a CP-SAT solver (`PROJECT_BRIEF.md:59-65`, `PROJECT_BRIEF.md:232`).
  - The repository has no schedule/board/problem/constraint/solver module, and `pyproject.toml` depends only on `parallel-web` at runtime, not OR-Tools (`pyproject.toml:10-12`).
  - Traceability reports 0/8 use cases deliverable; `SOL-004` alone blocks UC-03, UC-04, and UC-07.
- Why this blocks implementation: A developer cannot write meaningful tests for “provably satisfies,” “minimal conflicting constraint set,” or “objective minimises…” until the spec names the solver input/output model and what counts as a proof, conflict, objective term, or locked day.
- Concrete spec improvement:
  - Add canonical data models before implementing `SOL-*`:
    - `ScheduleProblem`
    - `WorkItem` / `SceneWork` / `PickupWork`
    - `ShootDay`
    - `Assignment`
    - `Board`
    - `BoardOption`
    - `SolveResult(status, boards, conflict_set, objective_breakdown)`
    - `LockedDay(day_id, assignments, recorded_by, recorded_at)`
  - Specify `solve_schedule(problem: ScheduleProblem) -> SolveResult`.
  - Decompose `SOL-002` into testable children:
    - every hard constraint returns a pass/fail `ConstraintEvaluation`;
    - a returned board includes evaluations for all input constraints;
    - no returned board may contain failed hard constraints.
  - Decompose `SOL-003`:
    - define “minimal” as subset-minimal or cardinality-minimal;
    - define whether soft objectives can appear in conflicts;
    - require conflict IDs to match input constraint IDs.
  - Add fixture-level acceptance criteria:
    - a 2-day, 2-scene fixture schedules without violations;
    - impossible cast availability returns a known conflict set;
    - a replan cannot move assignments on locked days;
    - objective breakdown reports company moves, holding days, and overtime exposure separately.

#### Blocker / P0 — Constraint translation lacks typed constraint schemas and overclaims auditability

- Evidence:
  - `CON-001`–`CON-003` require “typed constraint records,” validation against known-good values, and binding dated values only from GRD-003-compliant sources (`SPEC.md:166-172`), but no constraint schema exists in `src/coverset`.
  - `SearchGrounder` explicitly returns `Evidence`, not interpreted constraints (`src/coverset/grounding/search.py:7-8`), and `Evidence` is described as “deliberately not a constraint” (`src/coverset/grounding/facts.py:88-94`).
  - `AUD-003` says “A constraint records whether it was derived from full page content or from excerpts” (`SPEC.md:236`), but current tests assert only `Evidence.escalated` / `SourceExcerpt.full_content` behavior (`tests/test_search_grounding.py:264-283`).
- Why this blocks implementation: The extraction and solver layers need a stable contract for constraints. Without one, grounding can be “built” but cannot safely feed the solver or satisfy audit requirements.
- Concrete spec improvement:
  - Add a `ConstraintRecord` discriminated union with required fields:
    - `id`
    - `family`
    - `hard: bool`
    - `subject`
    - `value/window`
    - `source_urls` or `algorithm`
    - `evidence_id`
    - `derived_from: "full_content" | "excerpt" | "algorithm"`
    - `validated_against`
    - `created_by`
  - Define concrete constraint variants:
    - `CastAvailabilityConstraint`
    - `LocationPermitWindowConstraint`
    - `DaylightWindowConstraint`
    - `TurnaroundConstraint`
    - `CompanyMoveCostTerm`
    - `WeatherRiskFact` / `WeatherConstraint`
  - Either reword `AUD-003` to “Evidence records whether…” until constraints exist, or mark it `partial`.
  - Add tests that a derived permit/weather constraint carries source URLs, extraction mode, dated-source restriction, and validation metadata.

#### Blocker / P0 — Script breakdown requirements lack an input/output contract

- Evidence:
  - `BRK-001` and `BRK-002` require screenplay parsing into scene records and flags (`SPEC.md:159-164`), and the brief names `parse_screenplay` as a tool (`PROJECT_BRIEF.md:79-80`).
  - The current repository has no `SceneRecord` model or breakdown module. Existing review code carries only a `scene_id` string on `CoverageItem` (`src/coverset/review.py:131-140`).
- Why this blocks implementation: Solver and coverage work need normalized scene data, but the spec does not define exact scene fields, accepted enum values, page-eighth rules, cast ID validation, or failure modes.
- Concrete spec improvement:
  - Add `SceneRecord` schema:
    - `scene_id`
    - `scene_number`
    - `slugline`
    - `int_ext: INT | EXT | INT_EXT`
    - `day_night: DAY | NIGHT | DAWN | DUSK`
    - `location_ref`
    - `page_eighths`
    - `cast_ids`
    - `flags: {stunts, minors, vfx}`
    - `source_page_range`
  - Add `BreakdownResult(scenes, warnings, source_pdf_hash, model_version)`.
  - Acceptance tests:
    - parse a tiny fixture screenplay/PDF into exact scene records;
    - reject or warn on malformed page-eighths;
    - validate cast IDs against `Roster`;
    - verify minor flags align with `CastMember.is_minor`.

#### P1 — Monitoring/replanning requirements lack source registry, event, and trigger interfaces

- Evidence:
  - `TRK-003`, `MON-001`, and `MON-002` require monitoring, autonomous replanning, and multiple viable boards with production costs (`SPEC.md:127-129`, `SPEC.md:185-190`).
  - The brief describes monitor-triggered replanning from changed weather/permit pages (`PROJECT_BRIEF.md:135-144`).
  - Current grounding evidence records `source_urls`, `search_id`, `session_id`, and `covering_urls` (`src/coverset/grounding/facts.py:96-110`, `src/coverset/grounding/facts.py:125-134`) but does not attach them to a schedule version, affected scenes, or monitor subscription.
- Why this matters: There is no implementable boundary between “a monitored source changed” and “a replan request was generated,” nor any testable way to prove the monitor did not select a board.
- Concrete spec improvement:
  - Add models:
    - `MonitoredSource(schedule_version_id, evidence_id, url, fact_kind, affects_work_ids, fingerprint)`
    - `ChangeEvent(url, detected_at, old_fingerprint, new_fingerprint, summary)`
    - `ReplanRequest(trigger_event_id, current_board_id, locked_days, affected_work_ids)`
    - `ReplanOptions(options, generated_by_monitor=False, selected_by=None)`
  - Acceptance tests:
    - fake weather URL change produces exactly one `ReplanRequest`;
    - unchanged fingerprint does not replan;
    - monitor-generated options have no selection actor;
    - First AD selection is a separate audited action.

#### P1 — Authority spec conflicts with implementation on Line Producer approval and lacks decision records

- Evidence:
  - Spec names “UPM / Line Producer” as the cost authority (`SPEC.md:57`) and says ACT-005 requires UPM or Line Producer approval (`SPEC.md:101-102`).
  - Implementation has `Role.UPM` but no `Role.LINE_PRODUCER` (`src/coverset/actors.py:36-43`), and `may_approve_cost` returns true only for UPM (`src/coverset/actors.py:91-94`).
  - Tests assert only UPM approval (`tests/test_actors.py:73-77`).
  - ACT-004/ACT-005 are marked `partial` (`SPEC.md:101-102`), but current tests only verify boolean capabilities, not persisted board selection or cost approval records.
- Why this matters: Builders will not know whether Line Producer is a separate role or an alias, and the current permission booleans do not satisfy ACT-001’s “records the actor who made it” requirement for schedule-changing decisions.
- Concrete spec improvement:
  - Choose one:
    - add `Role.LINE_PRODUCER` and test it; or
    - explicitly state that `Role.UPM` represents UPM/Line Producer for this demo.
  - Add audited records:
    - `BoardSelection(actor, role, option_id, schedule_version_id, selected_at)`
    - `CostApproval(actor, role, cost_delta, adds_shoot_day, approved_at)`
  - Acceptance tests:
    - non-First AD cannot select a board;
    - a selected board persists the First AD actor;
    - work adding a shoot day cannot be accepted without UPM/Line Producer approval;
    - rejected approval blocks the extra-day option.

#### P1 — Pickup replanning requirements depend on missing solver contracts

- Evidence:
  - `PickupTask` has a concrete model carrying scene, coverage, cast, location, duration, decision, and optional deadline (`src/coverset/review.py:228-245`).
  - Tests verify pickup payload fields (`tests/test_review.py:246-254`).
  - But `PIK-005`–`PIK-007` require admitting pickup work to replanning, preserving constraints, locking shot days, and stating disruption cost (`SPEC.md:224-226`) without defining the schedule problem or cost model.
- Why this matters: The review-to-pickup path is buildable; pickup-to-replan is not yet spec-ready.
- Concrete spec improvement:
  - Define how `PickupTask` becomes a solver `WorkItem`.
  - Add `ScheduleProblem.required_work += pickup_task`.
  - Define `must_complete_by` feasibility behavior.
  - Acceptance tests:
    - pickup is inserted into remaining days only;
    - locked already-shot days are unchanged;
    - original cast/location/daylight/permit/weather constraints remain attached;
    - each revised board reports extra shoot days, holding-day delta, company moves, and turnaround/overtime exposure.

#### P2 — Weather forecast vs climatology distinction is too broad to test

- Evidence:
  - `GRD-010` says weather must distinguish near-term predictive forecasts from long-range climatology (`SPEC.md:144`).
  - The brief explains the issue and suggests two fact types (`PROJECT_BRIEF.md:332-343`).
  - Current query planning filters out sources older than `date - 14 days` and searches “extended forecast outlook” (`src/coverset/grounding/queries.py:75-93`), but no target-date horizon or classification exists.
  - Live tests only use `today + 6` (`tests/test_live_grounding.py:48-49`).
- Concrete spec improvement:
  - Define forecast horizon, e.g. “near-term forecast if target date <= N days from retrieval.”
  - Add `WeatherEvidence.classification: forecast | climatology`.
  - State monitor subscriptions may use only `forecast`, not `climatology`.
  - Acceptance tests:
    - near-date evidence is accepted as forecast;
    - 75-day evidence is classified as climatology or refused for monitor-triggered replanning;
    - climatology can contribute only to initial risk priors.

#### P2 — Output requirements lack call sheet and diff schemas

- Evidence:
  - `OUT-001` and `OUT-002` are one-line planned requirements (`SPEC.md:192-197`), while the brief names `generate_call_sheet` and `diff_schedules` tools (`PROJECT_BRIEF.md:90-91`).
  - No output/call-sheet/diff module exists in `src/coverset`.
- Concrete spec improvement:
  - Define `CallSheet(day, scenes, locations, cast_calls, crew_call, wrap_estimate, daylight_window, turnaround_notes, permit_notes, recipients)`.
  - Define `ScheduleDiff(added_days, moved_scenes, changed_call_times, added_pickups, cast_holding_delta, company_move_delta, overtime_delta)`.
  - Acceptance tests:
    - fixed scheduled day generates expected call sheet fields;
    - diffing two fixture boards quantifies the exact delta in production terms.