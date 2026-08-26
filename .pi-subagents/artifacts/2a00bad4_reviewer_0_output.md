## Review

### Correct

- `PROJECT_BRIEF.md` and `SPEC.md` are aligned on the strongest architectural boundary: Gemini interprets, humans decide where human judgment is required, and the solver produces schedules. Evidence: `PROJECT_BRIEF.md:48-65`, `SPEC.md:42-48`, `SPEC.md:79-92`.
- The current implemented surface is strongest around grounding, daylight, actors/authority, cast economics, and coverage/pickup authorization:
  - Runtime Parallel Search path is implemented in `src/coverset/grounding/search.py:67-80` and calls the SDK at `src/coverset/grounding/search.py:139-148`.
  - Search/Extract evidence keeps source URLs and date coverage at `src/coverset/grounding/search.py:117-127`.
  - Human authority is explicit in `src/coverset/actors.py:36-44` and scoped at `src/coverset/actors.py:71-94`.
  - Coverage findings cannot directly decide or create pickup work; the human decision path is enforced in `src/coverset/review.py:90-128`, `src/coverset/review.py:165-211`, and `src/coverset/review.py:228-303`.
- Verification is healthy for what is claimed as built/partial: `uv run pytest` passed with `181 passed, 8 deselected`; `uv run python scripts/traceability.py` reported `45/45` verifiable requirements covered and `0` traceability gaps.

### Blocker: constraint validity vs “viable options” is internally inconsistent

**Severity: critical**

The brief/spec repeatedly say returned boards are valid and solver-proven, but the demo language presents options that violate constraints:

- `PROJECT_BRIEF.md:59-61` says every board Coverset outputs satisfies its constraint set because a solver produced it.
- `SPEC.md:178-180` specifies `SOL-001`/`SOL-002`: CP-SAT produces schedules and every board satisfies its constraint set.
- `SPEC.md:189-190` says replanning returns “multiple viable boards.”
- But `PROJECT_BRIEF.md:215-219` lists options with “2 turnaround violations” and “church scenes fall outside the permit window,” including a location unavailable on that date.

That creates a solver-contract ambiguity: are turnaround, weather, permits, and overtime hard constraints, soft penalties, or waivable violations requiring explicit human approval? Without that distinction, the solver cannot know whether an output is valid, infeasible, or a proposed relaxation.

**Recommendation**

Restructure the spec to introduce a constraint policy taxonomy before `SOL`:

- `hard`: never violated; invalid boards are not returned.
- `soft_penalty`: may be optimized/traded off, e.g. overtime exposure if allowed by production rules.
- `waivable_by_role`: may be returned only as a proposed waiver requiring a named role approval.
- `objective_only`: cost/ranking term, not a feasibility bound.

Then rewrite:

- `SOL-002`: “Every returned board satisfies all hard constraints and records any explicit waivers/soft penalties.”
- `MON-002`: “Replanning returns viable boards plus, separately, infeasible/waiver-required alternatives.”
- Permit unavailability should probably remain hard unless the spec explicitly models permit override authority.

### Blocker: no MVP slice is currently deliverable

**Severity: critical**

Traceability reports all eight use cases blocked:

- `uv run python scripts/traceability.py` output: `Use cases 8`, `deliverable 0`, `blocked 8`.
- UC-01, the core “Build the initial board from a screenplay,” is blocked on `BRK-001`, `BRK-002`, `CON-001`, `SOL-001`, `SOL-002`, and `SOL-006`.
- The codebase has no OR-Tools dependency yet: `pyproject.toml:10-12` lists only `parallel-web`.
- The implemented modules are useful foundations, but there is no schedule/board/solver surface in `src/`.

This is the main scope risk: the spec has strong satellite capabilities, but the central use case still has no thin vertical path.

**Recommendation**

Add an explicit “MVP / Demo slice” section near the top of `SPEC.md`, before detailed requirement families:

1. **MVP-0: Deterministic board from structured fixtures**
   - Accept pre-parsed scene records and typed constraints.
   - Build one 20-day board with 25–30 scenes, 8–10 roles, 5–6 locations.
   - Enforce only the minimum hard constraints: cast availability, location window, daylight/day-night, turnaround, company moves.
   - Produce a readable stripboard-style schedule.
2. **MVP-1: Runtime grounding**
   - Runtime Parallel Search/Extract for permit/weather facts feeding typed constraints.
3. **MVP-2: Replan**
   - Lock already-shot days and re-solve one changed weather/permit scenario.
4. **Post-MVP / stretch**
   - Full screenplay PDF parsing, Monitor API, call-sheet generation, pickup-day cost approval, union library plugins, import/export.

That preserves the full vision while making the next engineering steps right-sized.

### Finding: weather is not consistently defined as a solver input

**Severity: high**

The brief says retrieved facts become hard solver bounds and names weather as one of the grounded fact families:

- `PROJECT_BRIEF.md:95-117` says retrieved facts become hard bounds and lists weather outlooks and permit rules.
- `PROJECT_BRIEF.md:135-144` says monitored weather changes trigger replanning.
- `SPEC.md:144` has `GRD-010` for distinguishing near-term forecasts from climatology.
- But `SPEC.md:182-183` defines `SOL-006` as five constraint families and excludes weather.
- `SPEC.md:224` then says pickup replanning preserves “cast, location, daylight, permit and weather constraints.”

This blocks the solver design. Weather could be a hard constraint, a risk objective, a replan trigger, or an advisory fact — the current spec uses all of those meanings without choosing one.

**Recommendation**

Add a dedicated `WEA — Weather` section:

- `WEA-001`: classify retrieved weather as near-term forecast vs climatology/risk prior.
- `WEA-002`: define forecast horizon and staleness rules.
- `WEA-003`: define how precipitation/wind/temperature affect exterior scenes: hard no-go threshold, soft risk penalty, or human-waivable warning.
- `WEA-004`: define which weather facts are eligible for Monitor-triggered replans.

Then either add weather to `SOL-006` or explicitly state it is not a constraint family and only drives replan triggers/objective scoring.

### Finding: status vocabulary and traceability can overstate readiness

**Severity: high**

`SPEC.md` has only three statuses:

- `built`: implemented and covered by at least one test.
- `partial`: partly implemented, or implemented without full coverage.
- `planned`: specified, not yet built.

Evidence: `SPEC.md:11-17`.

The traceability script treats a use case as deliverable when no exercised requirement is `planned`:

- `scripts/traceability.py:196-199` counts use cases deliverable if all exercised requirements are not `planned`.
- `scripts/traceability.py:220-223` counts only `built` as ready but treats only `planned` as blockers.

That means a future use case composed entirely of `partial` requirements could be reported as `READY`, even if it only has unit-level scaffolding.

Current examples:

- `ACT-004` is `partial` in `SPEC.md:101`, but the implementation is only a capability property at `src/coverset/actors.py:81-84`; there is no board selection model/action yet.
- `ACT-005` is `partial` in `SPEC.md:102`, while `src/coverset/actors.py:91-94` only has `UPM` cost authority and no line producer role or cost-approval workflow.

**Recommendation**

Split status into at least two axes:

- **Implementation maturity:** `not-started`, `domain-model`, `unit-built`, `integrated`, `demo-ready`.
- **Verification tier:** `none`, `offline`, `live`, `manual-demo`.

Then have traceability count use-case deliverability only when all required IDs are `demo-ready` or explicitly accepted for the active MVP slice.

### Finding: broad planned requirements are too large to guide next work

**Severity: medium-high**

Several planned requirements are product-sized rather than implementation-sized:

- `BRK-001` full screenplay PDF to structured scene records: `SPEC.md:163`.
- `CON-001` plain-English production constraints to typed constraint records: `SPEC.md:170`.
- `SOL-003` minimal conflicting constraint set: `SPEC.md:180`.
- `MON-001` autonomous replan from monitored source change: `SPEC.md:189`.

These are valid product capabilities, but too broad for sequencing. For example, `CON-001` hides many smaller parsers/constraint schemas: actor availability, max day length, location windows, permits, daylight requirements, and company moves.

**Recommendation**

Break large planned requirements into testable increments:

- `BRK-MVP-001`: accepts structured scene JSON fixture.
- `BRK-002`: validates scene schema and cast/location references.
- `BRK-PDF-001`: Gemini PDF extraction adapter.
- `CON-CAST-001`: translates named actor availability windows.
- `CON-LOC-001`: translates location availability windows.
- `CON-DAY-001`: translates max day length/overtime rule.
- `CON-GRD-001`: binds retrieved permit evidence to typed permit windows.
- `SOL-MVP-001`: schedules scenes to days with one scene duration unit.
- `SOL-MVP-002`: enforces cast availability and location windows.
- `SOL-MVP-003`: enforces locked days during replan.

This would make the traceability report a useful build plan, not only a compliance matrix.

### Finding: critical path ranking currently pulls attention toward replan/immutability before first-board scheduling

**Severity: medium**

Traceability ranks `SOL-004` as the top critical path item because it blocks UC-03, UC-04, and UC-07. That is mechanically true:

- `SPEC.md:181` defines `SOL-004`.
- Use cases reference it at `SPEC.md:268`, `SPEC.md:276`, and `SPEC.md:299`.

But the product cannot produce an initial board yet, and UC-01 is blocked by six planned requirements at `SPEC.md:246-252`. Ranking by “number of journeys blocked” may push the team into replan immutability before there is a board to replan.

**Recommendation**

Add a priority/slice field independent of graph centrality:

- `P0 demo-critical`: initial board path.
- `P1 replan-critical`: locked days, diff, options.
- `P2 autonomous`: Monitor API, proactive triggers.
- `P3 post-hackathon`: union libraries, import/export, multi-unit.

Then have the script report both “journeys blocked” and “active MVP blockers.”

### Note: requested plan/progress files were not present

I attempted to read:

- `/Users/surpoone/work/git/Coverset/plan.md`
- `/Users/surpoone/work/git/Coverset/progress.md`

Both returned `ENOENT`. I proceeded with `PROJECT_BRIEF.md`, `SPEC.md`, source, tests, traceability, and pytest.

## Recommended SPEC.md restructuring

Suggested top-level order:

1. **Project contract / non-negotiables**
   - Parallel Search runtime requirement.
   - Gemini never emits schedules.
   - Humans decide; solver schedules.
2. **MVP slices**
   - MVP-0 initial board from structured data.
   - MVP-1 grounded constraints.
   - MVP-2 replan with locked days.
   - Stretch/post-MVP.
3. **Status model**
   - Separate implementation maturity, verification tier, and MVP slice.
4. **Constraint policy vocabulary**
   - Hard, soft penalty, waivable, objective-only.
   - Role required for each waiver.
5. **Core domain model**
   - Scene, cast member, location, constraint, schedule day, board, schedule version, decision/audit event.
6. **Input pipeline**
   - Structured fixture/import first.
   - Gemini PDF breakdown later.
   - Plain-English constraint translation split by constraint family.
7. **Grounding**
   - Parallel Search/Extract.
   - Evidence/source/date coverage.
   - Weather section split into forecast/climatology/monitor eligibility.
8. **Solver**
   - Minimal MVP solver.
   - Objectives.
   - Infeasibility explanations.
   - Locked days/replan.
9. **Outputs**
   - Stripboard first.
   - Call sheets second.
   - Schedule diff.
10. **Review/pickups**
   - Keep existing human-decision boundary.
   - Integrate into solver only after replan exists.
11. **Monitor/autonomy**
   - Last, because it depends on schedule versions, grounded sources, and replan.