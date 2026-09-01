---
title: Full UI Screen Implementation Plan
date: 2026-09-01
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
---

## Goal Capsule

| Field | Value |
| --- | --- |
| Objective | Turn the v4 UI reference screens in `docs/ui-sling/` into navigable, functional Next.js application screens backed by the API workflows already shipped on `main`. |
| Primary users | First AD, Second AD, Script Supervisor, Director, UPM/Line Producer, Producer/read-only recipients. |
| Source of truth | `SPEC.md` for product semantics and authority boundaries; `docs/ui-sling/validation.md` and `docs/ui-sling/*.v4.html` for visual/reference coverage; `src/coverset/api/main.py` and `src/coverset/api/schemas.py` for API contracts. |
| Execution profile | Frontend-first implementation with thin API-client/types extraction, then route-by-route UI wiring, then Playwright coverage for each use case. |
| Non-negotiables | Do not move scheduling authority into the browser; do not let monitor automation select boards; do not bypass actor authority gates; do not re-run scheduling when rendering call sheets. |
| Stop condition | All eleven reference screens have in-app routes or panels; `scripts/check.sh` passes; a deployed private Cloud Run smoke can walk UC-01 through UC-09 from the web app; `scripts/check_ui_reference.py` still passes for the reference archive. |

---

## Product Contract

### Summary

The current application has a working backend and a consolidated root UI, but the full UI reference set remains static HTML in `docs/ui-sling/`. This plan implements those reference screens as production frontend surfaces inside the Next.js app, preserving the proven API semantics and authority boundaries already delivered on `main`.

### Problem Frame

A user can access the deployed app at `/`, but the app does not yet expose the full operational cockpit implied by the reference screens. The static comps show complete workflows for stripboard review, breakdown review, replan options, grounded provenance, coverage/pickup, call sheets, audit, infeasibility, plain-English constraints, locked actuals, and cost approval. Those workflows now exist in the API, but most are only reachable through tests or direct HTTP calls.

The implementation should close that gap by making the app navigable and task-oriented without changing the backend authority model.

### Requirements

#### Application shell and navigation

- R1. The web app must expose a persistent production operations shell with navigation to every v4 reference screen category.
- R2. The app must support deep links for each screen so a reviewer can open a specific workflow directly.
- R3. The app must keep the existing fast demo path so a new user can seed a production and reach a solved board quickly.
- R4. The UI must preserve the dark dense cockpit visual language from `docs/ui-sling/*.v4.html` without copying prototype-only architecture into production code.

#### Screen parity

- R5. The stripboard dashboard must show shoot days, ordered work, scene ids, location, cast, day/night, call/wrap, company moves, schedule objective summary, snapshot hash, board selection state, and lock state.
- R6. The scene breakdown/review screen must support screenplay upload, candidate discrepancy review, candidate edit, advisory status, and human accept/reject decisions.
- R7. The replan options screen must show replan requests, option diffs, moved work, changed calls, added pickup days, required approvals, and First AD board-selection controls.
- R8. The grounded facts screen must show grounding evidence, grounded value provenance, validator results, excerpt/full-content mode, conflicts, and activation eligibility.
- R9. The coverage pickup screen must show coverage items, shot status, findings, Director pickup decisions, incomplete specs, confirmed specs, and pickup replan entry points.
- R10. The call sheet screen must generate, list, preview, and export call sheets from persisted solved board-day snapshots; it must show recipients as read-only.
- R11. The audit log screen must show authority/provenance events and provide JSON/CSV export affordances.
- R12. The infeasible board screen must show solver failures and conflicting constraints when the API exposes infeasibility detail; until then it must render a clear empty/deferred state instead of inventing conflicts.
- R13. The constraint entry screen must translate plain English into inactive typed proposals, let authorized humans accept/reject proposals, and activate/deactivate accepted constraints as a separate act.
- R14. The lock day/actuals screen must record actuals/shot coverage, lock shot days, show immutable locked assignments, and route findings to human review.
- R15. The cost approval screen must show boards pending cost approval, schedule diff cost exposure, added shoot days, and UPM/Line Producer approval/rejection.

#### Authority and provenance

- R16. UI actions must make actor role explicit for authority-gated API calls instead of hiding role defaults.
- R17. Unauthorized actions must surface the API rejection in production terms, not as generic errors.
- R18. Advisory outputs from Gemini/Parallel/monitoring must be labelled advisory and visually separated from human decisions.
- R19. Grounded values and constraints must display source mode, derived-from family, source URL/span/hash/validator metadata when available.

#### State, resilience, and usability

- R20. Shared production state must be refreshed consistently after mutations without forcing a full page reload.
- R21. Long-running jobs must keep the current poll/hydrate behavior and show terminal success/failure clearly.
- R22. Each workflow screen must have an empty state, loading state, and error state that names the next useful action.
- R23. The UI must be responsive enough for laptop and large-monitor demos, with the reference 2048px layout treated as the high-density target.
- R24. The implementation must be maintainable: split the current monolithic `apps/web/app/page.tsx` into typed API clients, shared components, and route-specific screens.

### Key Flows

- F1. Screenplay to board: create or demo-seed a production, upload screenplay, review candidates, accept ready scenes, run solver, inspect stripboard.
- F2. Plain-English constraints: enter production rule text, inspect inactive proposals, accept one as a human, activate/deactivate the resulting constraint, observe solver participation state.
- F3. Grounded provenance: run or inspect grounding evidence, bind grounded values, see validator/conflict outcomes, and understand why a source can or cannot drive scheduling.
- F4. Monitor replan: register/view monitored sources, process/view material changes, generate replan options, compare diffs, and require First AD board selection.
- F5. Coverage pickup: record planned coverage and shot actuals, raise a Script Supervisor finding, request pickup as Director, confirm pickup spec as First AD, generate replan options.
- F6. Call sheet: Second AD generates a call sheet for a solved board day, previews text/structured sections, exports text/JSON, and recipients remain read-only.
- F7. Lock day/actuals: record a day lock after actuals, show immutable assignments, and verify replans preserve locked work.
- F8. Cost approval: review diff cost exposure, reject non-authorized approval attempts, approve/reject as UPM or Line Producer, and observe board approval state.
- F9. Audit/provenance: inspect chronological events linking advisory findings, human decisions, constraints, board versions, call sheets, and exports.

### Acceptance Examples

- AE1. Given a fresh dev deployment, when a user opens `/` and runs the demo flow, then they can navigate to the stripboard route and see a solved board with day cards, strips, objective summary, and call-sheet entry points.
- AE2. Given a solved board, when a First AD enters `Maximum daily hours 11` on the constraint route, then the UI displays an inactive typed proposal before any activation control appears.
- AE3. Given a monitor material-change replan request, when options are generated, then the replan route shows production-readable schedule diffs and only First AD selection controls can select a board.
- AE4. Given a shot coverage item with a finding, when a Director requests pickup but no pickup spec has been confirmed, then the pickup replan control is blocked with the API message; after First AD confirmation, replan options become available.
- AE5. Given a revised board with positive cost exposure, when a First AD attempts cost approval, then the UI shows an authorization rejection; when a UPM approves with added shoot days, the board state changes to approved.
- AE6. Given a generated call sheet, when a read-only recipient is displayed, then the UI never offers board-changing controls from the call-sheet recipient context.

### Scope Boundaries

#### In scope

- Implement production Next.js routes/components corresponding to the eleven v4 reference screens.
- Reuse and refactor the current root UI behavior instead of starting from an unrelated frontend architecture.
- Add typed frontend models for the API responses already present in `src/coverset/api/schemas.py`.
- Add Playwright coverage for route navigation and each feature-bearing UI workflow.
- Keep the reference archive and `scripts/check_ui_reference.py` intact as design-regression protection.

#### Deferred for later

- Real authentication, session management, and per-user authorization. The current actor/role selectors remain explicit demo controls.
- A full production design system package. This plan creates shared components inside `apps/web/` only.
- Rich collaborative editing, websocket updates, or background subscriptions. Polling/manual refresh is acceptable.
- Implementing missing backend infeasibility-detail APIs if not already available; the frontend should render a truthful placeholder until a backend unit adds it.

#### Outside this product's identity

- Browser-side scheduling or browser-side selection of advisory candidates.
- Treating static `docs/ui-sling` HTML as runtime code.
- Public unauthenticated Cloud Run access for dev.

### Sources

- `docs/ui-sling/validation.md` — UI reference baseline, required screens, and requirement coverage.
- `docs/ui-sling/01-stripboard-dashboard.v4.html` through `docs/ui-sling/11-cost-approval.v4.html` — visual layout and content density reference.
- `SPEC.md` — product requirement and authority source of truth.
- `apps/web/app/page.tsx` — current consolidated UI and fetch/polling patterns to extract.
- `apps/web/app/api/coverset/[...path]/route.ts` — existing frontend-to-private-API proxy.
- `src/coverset/api/main.py` and `src/coverset/api/schemas.py` — backend route and payload contracts.
- `tests/test_api.py` and `apps/web/tests/p1-flow.spec.ts` — current workflow assertions to mirror in UI tests.

---

## Planning Contract

### Key Technical Decisions

- KTD1. Route-based UI, not static comp embedding. Implement each reference screen as a real app route under `apps/web/app`, while preserving `/` as a dashboard/demo entry. Static HTML files remain references only because `docs/ui-sling/validation.md` explicitly says they are prototype/reference code, not production frontend architecture.
- KTD2. Shared typed API client. Move `jsonFetch` and response types out of `apps/web/app/page.tsx` into `apps/web/shared/coverset-api.ts` and `apps/web/shared/coverset-types.ts` so every route uses one error-handling and proxy path convention.
- KTD3. Server-rendered shell with client workflow islands. Keep route files thin and put mutation-heavy workflows in client components under `apps/web/components/screens/`. This matches the current Next App Router structure while allowing forms, polling, and local UI state.
- KTD4. Production context is URL-addressable. Use `productionId`, `boardId`, `replanRequestId`, and related ids in route params or query params where possible, with graceful empty states when an id is missing. Avoid hidden singleton state that makes demos brittle.
- KTD5. API authority remains authoritative. The UI may disable obviously unauthorized controls based on selected role, but it must still call the API for final enforcement and display 403/400 responses in domain language.
- KTD6. Reference visual language becomes reusable primitives. Extract cards, status pills, timeline rows, board strips, diff rows, actor-role controls, provenance chips, and empty/error states into shared components instead of copy-pasting eleven screens.
- KTD7. Demo seed remains one-click. The root shell should preserve the current `/demo/run` flow so every route can be reached with realistic ids during local/dev demos.
- KTD8. Implement truthful placeholders where backend support is partial. For infeasible conflict detail, render a route that explains no conflict subset is available unless an actual failed schedule response carries one; do not invent screen data just to match the static comp.

### High-Level Technical Design

```mermaid
flowchart TB
  Browser[Next.js app routes] --> Proxy[apps/web/app/api/coverset/[...path]/route.ts]
  Proxy --> API[Private Cloud Run API]
  API --> DB[(Cloud SQL Postgres)]

  Browser --> Shell[ProductionShell]
  Shell --> Nav[Screen navigation]
  Shell --> Context[ProductionBoardContext]

  Context --> ApiClient[coverset-api.ts]
  ApiClient --> Proxy

  Nav --> Board[Stripboard dashboard]
  Nav --> Breakdown[Scene breakdown review]
  Nav --> Constraints[Constraint entry]
  Nav --> Grounding[Grounded facts]
  Nav --> Replan[Replan options]
  Nav --> Coverage[Coverage pickup + actuals]
  Nav --> CallSheet[Call sheet]
  Nav --> Audit[Audit log]
  Nav --> Cost[Cost approval]
  Nav --> Infeasible[Infeasible conflict]
```

### Proposed Route Map

| Route | Screen | Primary data |
| --- | --- | --- |
| `/` | Landing/dashboard and demo seed | production, current board, quick links |
| `/productions/[productionId]` | Production overview shell default | production, cast, locations, calendar, jobs |
| `/productions/[productionId]/board/[boardId]` | `01-stripboard-dashboard.v4.html` | board, constraints, locks, call sheets |
| `/productions/[productionId]/breakdown` | `02-scene-breakdown-review.v4.html` | screenplay assets, breakdown run, candidates |
| `/productions/[productionId]/replans` | `03-replan-options.v4.html` | replan requests, schedule diffs, board selection |
| `/productions/[productionId]/grounding` | `04-grounded-facts.v4.html` | grounding evidence, grounded values, constraints |
| `/productions/[productionId]/coverage` | `05-coverage-pickup.v4.html` and `10-lock-day-actuals.v4.html` | coverage items/findings, pickup tasks, locks |
| `/productions/[productionId]/call-sheets` | `06-call-sheet.v4.html` | board days, call sheets, exports |
| `/productions/[productionId]/audit` | `07-audit-log.v4.html` | audit events, export links |
| `/productions/[productionId]/infeasible` | `08-infeasible-conflict.v4.html` | failed schedule runs/conflict placeholder |
| `/productions/[productionId]/constraints` | `09-constraint-entry.v4.html` | proposals, constraints, actor actions |
| `/productions/[productionId]/costs` | `11-cost-approval.v4.html` | pending boards, schedule diffs, cost approvals |

### Shared Frontend State

- Production id comes from route params or from the result of `/demo/run`.
- Current board id should be route-addressable; if absent, the shell can use the latest known board from demo/schedule responses or ask the user to run a demo/solve.
- Mutations return authoritative API rows; after mutations, refresh only the affected resources and any dependent summaries.
- Jobs remain poll-based using the existing `refreshJob`, `hydrateCompletedJob`, and `pollJob` concepts extracted from `apps/web/app/page.tsx`.

### Sequencing

1. Extract frontend API/types and shared UI primitives before adding routes.
2. Preserve the current root flow while moving it into the new shell.
3. Implement read-heavy route surfaces first: board, audit, call sheets.
4. Implement mutation-heavy authority workflows next: constraints, replan selection, coverage/pickup, cost approval.
5. Add the infeasible route with truthful current-data behavior.
6. Expand Playwright coverage after each route group, not at the very end.
7. Deploy/smoke only after local gates pass.

### Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| The monolithic page refactor breaks the existing P1 flow. | Keep `/` behavior intact in U1 and add regression coverage before moving screens. |
| Static comps contain invented sample data. | Treat comps as visual/semantic references only; bind all runtime data to API responses and fixtures. |
| Frontend role selectors could imply real auth. | Label them as demo actor controls and keep API enforcement visible. |
| Replan/cost flows require ids that are hard to create manually. | Provide demo helper actions on the relevant screens that create a realistic request from existing board data. |
| Infeasible conflict UI may outrun backend support. | Ship a truthful empty/failed-run route now; create a separate backend follow-up only if product requires live conflict subsets. |
| Large route rollout can become hard to review. | Land in 3-5 commits or PRs grouped by foundational extraction, read surfaces, decision surfaces, and verification. |

---

## Implementation Units

### U1. Frontend foundation and app shell

- **Goal:** Split the current single-page UI into maintainable frontend infrastructure without losing the existing demo/setup flow.
- **Requirements:** R1, R2, R3, R4, R20, R21, R22, R24.
- **Files:** `apps/web/app/page.tsx`, `apps/web/app/layout.tsx`, `apps/web/app/globals.css`, `apps/web/shared/coverset-api.ts`, `apps/web/shared/coverset-types.ts`, `apps/web/components/app-shell.tsx`, `apps/web/components/ui/*`, `apps/web/components/actor-role-control.tsx`.
- **Approach:** Extract API fetch/error handling, existing response types, polling helpers, status class helpers, and common formatting from `page.tsx`. Create a `ProductionShell` with navigation slots, selected production/board summary, actor controls, and empty states. Keep the root route focused on setup/demo and redirect/deep-link cards to the new routes once ids exist.
- **Patterns:** Reuse the existing proxy route `apps/web/app/api/coverset/[...path]/route.ts`; preserve existing `jsonFetch` error semantics; keep dark theme tokens from `globals.css` and v4 reference screens.
- **Test Scenarios:**
  - Loading `/` shows the demo/setup path and does not require a production id.
  - Running fast demo still creates a production and solved board.
  - Shell navigation links include every screen route once production/board ids are known.
  - API errors render as visible domain messages rather than uncaught promise failures.
- **Verification:** `npm --prefix apps/web run lint`; existing `apps/web/tests/p1-flow.spec.ts` still passes after extraction.

### U2. Stripboard dashboard route

- **Goal:** Implement the main First AD board view from `01-stripboard-dashboard.v4.html` as a route backed by `GET /boards/{board_id}` and related resources.
- **Requirements:** R5, R16, R17, R18, R20, R22.
- **Files:** `apps/web/app/productions/[productionId]/board/[boardId]/page.tsx`, `apps/web/components/screens/stripboard-dashboard.tsx`, `apps/web/components/board/day-card.tsx`, `apps/web/components/board/strip-card.tsx`, `apps/web/components/board/objective-summary.tsx`, `apps/web/components/board/constraint-snapshot.tsx`, `apps/web/tests/full-ui.spec.ts`.
- **Approach:** Render `Board.result.days`, `Board.result.strips`, objective values, explanation traces, board `approval_state`, schedule run id, and lock indicators. Add actions linking to call sheets, locks/actuals, replans, and costs. If multiple boards are available only by known ids, keep this route board-specific and let other screens link to revised boards.
- **Test Scenarios:**
  - A demo board route shows all days and at least one strip with scene, location, cast, day/night, call, and wrap.
  - Company move/objective/snapshot metadata appears when present.
  - A board with `pending_cost_approval` shows a cost approval route link instead of pretending it is final.
  - Locked days are visually distinguished after `POST /boards/{board_id}/locks`.
- **Verification:** Playwright navigates from demo seed to board route and asserts the route contains schedule and authority metadata.

### U3. Scene breakdown and candidate review route

- **Goal:** Move current screenplay intake and candidate review into a dedicated route matching `02-scene-breakdown-review.v4.html`.
- **Requirements:** R6, R16, R17, R18, R20, R21, R22.
- **Files:** `apps/web/app/productions/[productionId]/breakdown/page.tsx`, `apps/web/components/screens/breakdown-review.tsx`, `apps/web/components/candidates/candidate-editor.tsx`, `apps/web/components/jobs/job-panel.tsx`, `apps/web/tests/full-ui.spec.ts`.
- **Approach:** Reuse existing upload, breakdown, candidate edit, accept/reject, batch accept, and schedule job logic. Emphasize candidate advisory status, discrepancy blockers, structural fields, and human review decisions. Keep solver launch as a separate action after accepted candidates exist.
- **Test Scenarios:**
  - Uploading screenplay or running fixture/demo creates candidate rows.
  - Editing a candidate persists changes and clears/updates blocker state.
  - Accept/reject controls show actor role and propagate API errors.
  - Solving after accepted candidates creates a board link.
- **Verification:** Extend existing P1 Playwright flow to use the dedicated route while preserving root smoke coverage.

### U4. Constraint entry route

- **Goal:** Implement `09-constraint-entry.v4.html` for plain-English constraint translation, proposal decisions, and activation.
- **Requirements:** R13, R16, R17, R18, R20, R22.
- **Files:** `apps/web/app/productions/[productionId]/constraints/page.tsx`, `apps/web/components/screens/constraint-entry.tsx`, `apps/web/components/constraints/proposal-card.tsx`, `apps/web/components/constraints/constraint-card.tsx`, `apps/web/tests/full-ui.spec.ts`.
- **Approach:** Add text input for `POST /productions/{production_id}/constraints/translate`, list resulting proposals, support `POST /constraint-proposals/{proposal_id}/accept` and `/reject`, list constraints via `GET /productions/{production_id}/constraints`, and support `PATCH /constraints/{constraint_id}/activation`. Show inactive/proposed/active as separate states.
- **Test Scenarios:**
  - Translating `Maximum daily hours 11` creates an inactive proposal.
  - Accepting as First AD creates a constraint but does not hide activation provenance.
  - Activation toggles active state and shows activation validation.
  - Unauthorized or invalid activation displays the API message.
- **Verification:** Playwright covers proposal creation, acceptance, activation, and visible fail-closed labels.

### U5. Grounded facts and provenance route

- **Goal:** Implement `04-grounded-facts.v4.html` as the inspection surface for evidence, grounded values, validators, conflicts, and source modes.
- **Requirements:** R8, R18, R19, R20, R22.
- **Files:** `apps/web/app/productions/[productionId]/grounding/page.tsx`, `apps/web/components/screens/grounded-facts.tsx`, `apps/web/components/grounding/evidence-card.tsx`, `apps/web/components/grounding/grounded-value-card.tsx`, `apps/web/components/grounding/provenance-table.tsx`, `apps/web/tests/full-ui.spec.ts`.
- **Approach:** Use existing grounding endpoints for evidence listing and grounded value creation where practical. Display quote/span, URL, content hash, query, retrieval timestamp, response id, extract mode, units, validator result, and accepted/refused/conflict state. Link accepted evidence to constraints.
- **Test Scenarios:**
  - Existing grounding evidence appears with provider/source metadata.
  - A grounded value form can record normalized value, units, quote, and validator metadata for an evidence row.
  - Conflict/refusal metadata renders without offering activation.
  - Daylight algorithm-derived facts are labelled algorithmic, not URL-grounded.
- **Verification:** Add Playwright coverage using fixture/demo evidence where available; otherwise use API setup calls inside the test to create deterministic evidence before route assertions.

### U6. Replan options and board selection route

- **Goal:** Implement `03-replan-options.v4.html` for monitor/manual replan requests, schedule diffs, and First AD board selection.
- **Requirements:** R7, R16, R17, R18, R20, R22.
- **Files:** `apps/web/app/productions/[productionId]/replans/page.tsx`, `apps/web/components/screens/replan-options.tsx`, `apps/web/components/replans/replan-request-list.tsx`, `apps/web/components/replans/schedule-diff-card.tsx`, `apps/web/components/replans/board-selection-panel.tsx`, `apps/web/tests/full-ui.spec.ts`.
- **Approach:** List replan requests via `GET /productions/{production_id}/replan-requests`, generate options via `POST /replan-requests/{replan_request_id}/options`, list diffs via `GET /productions/{production_id}/schedule-diffs`, show rendered diff text and structured changes, and call `POST /boards/{board_id}/selection` only through explicit First AD controls.
- **Test Scenarios:**
  - A material monitor event creates a replan request visible on the route.
  - Generating options creates at least one schedule diff with required approvals.
  - First AD can select a board; non-First AD selection shows authorization rejection.
  - Monitor-origin replan copy never implies automatic board selection.
- **Verification:** Playwright uses API setup to create a material event, then drives option generation and selection UI.

### U7. Coverage pickup and lock-day actuals route

- **Goal:** Implement `05-coverage-pickup.v4.html` and `10-lock-day-actuals.v4.html` as one production-floor workflow surface.
- **Requirements:** R9, R14, R16, R17, R18, R20, R22.
- **Files:** `apps/web/app/productions/[productionId]/coverage/page.tsx`, `apps/web/components/screens/coverage-workflow.tsx`, `apps/web/components/coverage/coverage-item-card.tsx`, `apps/web/components/coverage/finding-card.tsx`, `apps/web/components/pickups/pickup-task-card.tsx`, `apps/web/components/locks/lock-day-panel.tsx`, `apps/web/tests/full-ui.spec.ts`.
- **Approach:** Provide forms for coverage item creation, shot actual recording, finding creation, pickup request, pickup spec confirmation, pickup replan creation, and lock-day recording. Show a shared timeline from coverage item to finding to pickup to replan. Treat UC-07 and UC-09 as one surface, matching the reference rationale.
- **Test Scenarios:**
  - Script Supervisor records shot actuals and raises a finding.
  - Director requests pickup from the finding.
  - Replan before spec confirmation is blocked and visible.
  - First AD confirms pickup spec; replan becomes available.
  - Locking a day displays locked assignments and future replans preserve them.
- **Verification:** Playwright mirrors `tests/test_api.py::test_pickup_workflow_requires_confirmed_spec_and_preserves_locked_days` through UI actions where feasible, with API setup only for expensive preconditions.

### U8. Call sheet route

- **Goal:** Upgrade the existing UC-05 root-panel functionality into a dedicated `06-call-sheet.v4.html` route.
- **Requirements:** R10, R16, R17, R20, R22.
- **Files:** `apps/web/app/productions/[productionId]/call-sheets/page.tsx`, `apps/web/components/screens/call-sheet-screen.tsx`, `apps/web/components/call-sheets/call-sheet-preview.tsx`, `apps/web/components/call-sheets/call-sheet-export-links.tsx`, `apps/web/tests/full-ui.spec.ts`.
- **Approach:** Use `POST /boards/{board_id}/call-sheets`, `GET /boards/{board_id}/call-sheets`, `GET /call-sheets/{call_sheet_id}`, and `GET /call-sheets/{call_sheet_id}/export`. Render both production-readable preview and structured sections: day, scenes, locations, cast calls, crew call, wrap, daylight, turnaround, permit notes, recipients, schedule version.
- **Test Scenarios:**
  - First AD call-sheet generation is rejected and displayed.
  - Second AD generation succeeds.
  - Text export contains `CALL SHEET`; JSON export id matches selected sheet.
  - Recipient rows are visibly read-only and offer no schedule mutation controls.
- **Verification:** Playwright extends current call-sheet smoke assertions into route-level coverage.

### U9. Audit log route

- **Goal:** Implement `07-audit-log.v4.html` as the chronological authority/provenance ledger.
- **Requirements:** R11, R18, R19, R20, R22.
- **Files:** `apps/web/app/productions/[productionId]/audit/page.tsx`, `apps/web/components/screens/audit-log.tsx`, `apps/web/components/audit/audit-event-row.tsx`, `apps/web/components/audit/audit-export-panel.tsx`, `apps/web/tests/full-ui.spec.ts`.
- **Approach:** Consume `GET /productions/{production_id}/audit` and export endpoints. Group or filter events by category: screenplay/breakdown, constraints, grounding, monitors, replans, selections, locks, pickups, call sheets, cost. Show actor name/role, event type, created time, and payload highlights.
- **Test Scenarios:**
  - After demo and call-sheet generation, audit route shows human and system events.
  - Export links for JSON/CSV are present and reachable.
  - Advisory-origin events are labelled advisory and decision events name human actor/role.
- **Verification:** Playwright creates a small action sequence and verifies ledger rows and export responses.

### U10. Cost approval route

- **Goal:** Implement `11-cost-approval.v4.html` for pending revised boards and UPM/Line Producer approval.
- **Requirements:** R15, R16, R17, R20, R22.
- **Files:** `apps/web/app/productions/[productionId]/costs/page.tsx`, `apps/web/components/screens/cost-approval.tsx`, `apps/web/components/costs/cost-diff-summary.tsx`, `apps/web/components/costs/cost-approval-form.tsx`, `apps/web/tests/full-ui.spec.ts`.
- **Approach:** Use schedule diffs as the source of cost exposure. Show `cost_delta`, `added_days`, required approvals, revised board state, and cost approval form. Require the UI to send explicit `added_shoot_days` whenever approving positive exposure.
- **Test Scenarios:**
  - A revised pickup board appears as `pending_cost_approval`.
  - First AD approval attempt surfaces a 403 authorization message.
  - UPM approval with added shoot days changes the board to approved.
  - Rejection changes the board to cost-rejected and remains visible.
- **Verification:** Playwright reuses the pickup workflow setup, then drives cost approval UI.

### U11. Infeasible conflict route

- **Goal:** Implement `08-infeasible-conflict.v4.html` without overstating backend support.
- **Requirements:** R12, R17, R18, R22.
- **Files:** `apps/web/app/productions/[productionId]/infeasible/page.tsx`, `apps/web/components/screens/infeasible-conflict.tsx`, `apps/web/components/infeasible/conflict-set-card.tsx`, `apps/web/tests/full-ui.spec.ts`.
- **Approach:** Inspect schedule runs/jobs for failures and render the available error, involved constraints when available, and recommended next actions. If the API does not yet expose minimal conflicting subsets, show a clear placeholder and link to constraints instead of static invented conflict math. Optionally add a follow-up backend unit only after product review confirms live conflict subset priority.
- **Test Scenarios:**
  - With no failed schedule, the route shows an honest empty state.
  - With a failed schedule/job error, the route shows the solver failure in production terms.
  - The route never displays hard-coded conflicts unrelated to the current production.
- **Verification:** Playwright covers empty state immediately; failed-run coverage can use an API fixture or remain a unit test until a deterministic frontend setup exists.

### U12. Test, reference, and deployment coverage

- **Goal:** Make the full UI implementation safely shippable and demoable.
- **Requirements:** R1-R24.
- **Files:** `apps/web/tests/full-ui.spec.ts`, `apps/web/tests/p1-flow.spec.ts`, `scripts/check_ui_reference.py`, `docs/ui-sling/validation.md`, `README.md`, `SPEC.md` if traceability text needs a frontend-maturity note.
- **Approach:** Add Playwright tests that use a mix of UI actions and API setup calls to avoid brittle slow end-to-end sequences. Keep `scripts/check_ui_reference.py` as static comp validation; add new app UI assertions in Playwright instead of repurposing the reference checker. Update docs with route access instructions and a demo walkthrough.
- **Test Scenarios:**
  - Root demo seed to board route.
  - Breakdown route can review candidates.
  - Constraint route translates/accepts/activates.
  - Replan route generates options from monitor event setup.
  - Coverage route drives finding/pickup/spec/replan happy path.
  - Call sheet route verifies authority and exports.
  - Cost route verifies approval authority.
  - Audit route verifies event visibility.
  - Infeasible route verifies truthful empty/failure state.
- **Verification:** `./scripts/check.sh`; `./scripts/check.sh --live` only when external-provider env is available; deployed private Cloud Run smoke through `gcloud run services proxy`.

---

## Verification Contract

| Gate | Command | Proves |
| --- | --- | --- |
| TypeScript/frontend lint | `npm --prefix apps/web run lint` | Route/component typing, API client types, and JSX correctness. |
| Web build | `npm --prefix apps/web run build` | App Router route compilation and production bundle success. |
| Full local gate | `./scripts/check.sh` | Existing Python tests, traceability, UI reference validation, Terraform static checks, web lint/build/e2e. |
| UI reference guard | `uv run python scripts/check_ui_reference.py` | Static v4 comp archive remains internally consistent while implementation proceeds. |
| Playwright route coverage | `npm --prefix apps/web run test:e2e` | Browser-visible user journeys still work after route extraction. |
| Optional live gate | `./scripts/check.sh --live` | External-provider/live tests pass when local env supplies credentials. |
| Deployed smoke | Private Cloud Run proxy for web/API, then route walkthrough | The merged app is reachable in the same private dev deployment model users will demo. |

### Playwright Coverage Strategy

- Keep `apps/web/tests/p1-flow.spec.ts` as the legacy smoke until the new route suite reaches parity.
- Add `apps/web/tests/full-ui.spec.ts` for the new screen routes.
- Use API setup inside Playwright for expensive preconditions such as material monitor events or pickup diffs, then assert the UI renders and acts on those entities.
- Prefer stable text anchored in product semantics (`pending_cost_approval`, `Read-only`, `First AD`, `Second AD`, `CALL SHEET`) over brittle CSS selectors.
- Include negative authority tests for call sheets, board selection, and cost approval.

---

## Definition of Done

- Every v4 reference screen listed in `docs/ui-sling/validation.md` has a corresponding production route or a deliberately combined route with documented rationale.
- The root app still supports fast demo setup and links into the new route map.
- Current `apps/web/app/page.tsx` no longer contains most workflow logic; API client, types, shared UI primitives, and screen components are split into maintainable files.
- All mutation controls name the actor/role and surface API authorization failures clearly.
- Advisory evidence and human decisions are visually distinct on breakdown, grounding, monitor/replan, coverage, and audit screens.
- Call sheets are generated only from persisted board-day snapshots and never by re-running the scheduler.
- Replan option selection remains First AD-only; cost approval remains UPM/Line Producer-only.
- Locked-day actuals and pickup replans visibly preserve immutable locked assignments.
- Playwright covers each implemented route at least once and covers the critical negative authority cases.
- `./scripts/check.sh` passes locally.
- `./scripts/check.sh --live` passes or is explicitly skipped because external-provider credentials are unavailable.
- Merged `main` is deployed to dev, smoke-tested through private Cloud Run proxies, and Cloud Run error logs remain clean after rollout.
- Abandoned prototype or duplicate route code is removed; static `docs/ui-sling` artifacts remain reference-only and are not imported as runtime code.
