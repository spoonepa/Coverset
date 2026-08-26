## Review — spec-improvement findings

- **Blocker — `PROJECT_BRIEF.md:212-219`, conflicts with `SPEC.md:179-183`**
  - Finding: The demo calls all three returned options “viable boards,” but Option A contains turnaround violations and Option C falls outside the permit window. Those are hard constraints elsewhere in the spec, so labeling them viable undermines the “solver only returns valid boards” claim.
  - Suggested wording: “Returned `viable_boards` MUST satisfy every active hard constraint. If Coverset surfaces options that relax or violate constraints, they MUST be emitted separately as `exception_scenarios`, each listing the violated constraint IDs, production consequence, required approving role, and activation status. Exception scenarios are not schedules until approved.”

- **High — `PROJECT_BRIEF.md:95-112`, `PROJECT_BRIEF.md:167-168`, `SPEC.md:183`, `SPEC.md:224`**
  - Finding: Weather is described as a hard solver bound, a risk signal, and a pickup constraint, but it is omitted from the five solver constraint families. This makes weather-driven replanning and “viable” weather alternatives under-specified and hard to test.
  - Suggested wording: “Weather facts are typed as `ForecastRisk` records with `issued_at`, `valid_for_date`, forecast horizon, condition, probability, source, and confidence tier. A production policy MUST declare whether each weather risk is a hard constraint, soft objective penalty, or informational alert. Solver requirements MUST include weather when policy maps it to feasibility.”

- **High — `PROJECT_BRIEF.md:59-65`, `SPEC.md:178-180`, `SPEC.md:234-236`**
  - Finding: “Because a solver produced it” is not enough to prove a returned board satisfies the intended rules. A CP-SAT model can be miscompiled, time out, return `UNKNOWN`, or solve against an incomplete/misbound constraint set.
  - Suggested wording: “No board may be returned unless the solver status is `FEASIBLE` or `OPTIMAL` and an independent schedule validator checks every active hard constraint against the proposed board. Each returned board records the constraint snapshot hash, model version, solver status, objective value, and validation result. `UNKNOWN` or unvalidated solutions are not schedules.”

- **High — `PROJECT_BRIEF.md:52-57`, `PROJECT_BRIEF.md:79-81`, `SPEC.md:163-172`**
  - Finding: The spec says Gemini translates scripts and plain-English constraints into structured records, but does not require human acceptance, omission detection, or blocking unresolved low-confidence fields before solving. A solver can produce a valid board against a wrong scene list or dropped constraint.
  - Suggested wording: “LLM-derived scene records and constraints enter the system as `Candidate` records only. They become active only after schema validation, provenance/confidence checks, and human acceptance or explicit waiver. Board generation is blocked by unresolved unknown cast/location IDs, missing scene fields, low-confidence extraction, or ungrounded externally-derived constraints.”

- **High — `PROJECT_BRIEF.md:119-133`, `SPEC.md:135-145`, `SPEC.md:171-172`, `SPEC.md:235-236`**
  - Finding: Grounding is mostly URL-level. A source URL alone does not prove the exact extracted value, effective date, retrieval time, or conflict resolution. That leaves the same silent-corruption path the brief warns about: a real source can support the wrong bound.
  - Suggested wording: “Every grounded value MUST store the query, source URL, Parallel session/response ID, retrieval timestamp, source publication/effective timestamp when available, extracted quote/span or table row, full-content/excerpt flag, content hash, normalized typed value, and validator result. Conflicting authoritative values MUST raise a `GroundingConflict` and cannot silently bind.”

- **Medium — `PROJECT_BRIEF.md:137-144`, `SPEC.md:127-129`, `SPEC.md:185-190`**
  - Finding: Monitoring is specified as “a source changed,” but not as “the typed schedule-relevant fact changed.” Page chrome, ads, or unrelated text could trigger replans; conversely, source disappearance or monitor failure is not specified.
  - Suggested wording: “A monitor event becomes a replan trigger only after Coverset re-extracts the watched fact, normalizes the old and new typed values, and proves a material change under a per-fact threshold. Non-material page changes are ignored. Monitor failures, source disappearance, and stale facts emit alerts and cannot silently leave a schedule marked current.”

- **High — `PROJECT_BRIEF.md:170-171`, `PROJECT_BRIEF.md:188-190`, `SPEC.md:181`, `SPEC.md:224-225`, `SPEC.md:294-299`**
  - Finding: “Days already shot are immutable” is underspecified. It does not define whether planned board rows, actual shot records, call/wrap times, call sheets, costs, or partial/in-progress days are locked. Replanning could accidentally rewrite history while claiming compliance.
  - Suggested wording: “A `LockedDayRecord` includes scheduled scenes, actual shot status, date, location, cast, call/wrap times, call sheet version, and actuals. The solver may reference locked records as constraints but MUST NOT mutate, delete, resequence, or reassign them. Replans start after an explicit cutoff. Retroactive fact changes create audit exceptions, not edited past schedules.”

- **High — `PROJECT_BRIEF.md:181-202`, `SPEC.md:220-226`, `SPEC.md:101-102`, `SPEC.md:301-306`**
  - Finding: Pickup authorization, task creation, and cost approval are not tightly connected. The spec says a rejection or pickup request yields exactly one task, but does not define idempotence, human confirmation of cast/location/duration, multi-shot pickups, or whether a board that adds a shoot day can become active before UPM approval.
  - Suggested wording: “A `ReviewDecision` authorizes pickup intent; a `PickupTask` becomes schedulable only after a human-confirmed task spec defines scene, coverage/shot, cast, location, estimated duration, and priority. Task creation is idempotent by decision and coverage key. Any revised board adding a shoot day or exceeding declared budget remains `pending_cost_approval` until approved by UPM or Line Producer.”

- **Medium — `SPEC.md:19-32`**
  - Finding: Live verification is described, but the spec does not gate statuses or traceability on live evidence for external-facing claims. “Built” can therefore still mean mock-verified only, while the brief’s own findings show mocks missed the important failures.
  - Suggested wording: “External-facing requirements declare `live_required: true`. They cannot be reported as fully built unless at least one live test verifies the provider response shape and the fact-binding invariant against the real service. Traceability reports missing live coverage as a release-blocking verification gap for track-critical requirements.”

- **Medium — `PROJECT_BRIEF.md:43-44`, `PROJECT_BRIEF.md:89`, `SPEC.md:180`, `SPEC.md:286-292`**
  - Finding: “Minimal conflicting constraint set” is ambiguous and likely untestable without defining minimality. Minimal cardinality, irreducible subset, and solver-derived unsat core are different promises with different costs and guarantees.
  - Suggested wording: “When no valid schedule exists, Coverset returns an irreducible conflicting constraint subset: removing any one listed constraint makes the reported conflict no longer proven. If a cardinality-minimum conflict is claimed, the proof method and time limit MUST be recorded. Otherwise the UI must say ‘irreducible conflict set,’ not ‘minimal set.’”