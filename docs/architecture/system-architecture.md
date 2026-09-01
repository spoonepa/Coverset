# Coverset system architecture

## Product boundary

Coverset is an agentic scheduling partner for first assistant directors. The system is intentionally split by authority:

- Gemini and future agents create candidate records and explanations.
- Parallel retrieves external facts at runtime for grounded fact requests.
- Humans accept, reject, or waive candidate records.
- The deterministic scheduling engine (`coverset.solver`) decides board placement.

This boundary protects the product from plausible-but-wrong agent output becoming a schedule.

## Runtime components

```text
Browser / Next.js frontend
  -> FastAPI backend
      -> Postgres system of record
      -> GCS screenplay/artifact storage
      -> Worker job orchestration
      -> BigQuery telemetry export
  -> Cloud Run worker
      -> Gemini breakdown
      -> Parallel grounding
      -> coverset.solver CP-SAT scheduling
```

## Backend API

The API is an orchestration layer around existing domain modules. It should not duplicate scheduling logic.

Core responsibilities:

- production CRUD for the dev MVP,
- screenplay upload metadata,
- breakdown run lifecycle,
- candidate scene review/activation,
- schedule run lifecycle,
- board retrieval and text/CSV/JSON export,
- monitor findings, locked-day records, replan requests, board selection, and cost approvals,
- audit listing/export plus optional BigQuery audit export,
- health/smoke checks.

## Domain library

Existing modules remain the source of truth:

- `src/coverset/breakdown.py` parses model readings into candidate scene records and resolves cast/locations.
- `src/coverset/solver.py` compiles and solves CP-SAT scheduling problems.
- `src/coverset/constraints.py` owns typed constraints and validation.
- `src/coverset/board.py` owns returned board objects and validation reports.
- `src/coverset/stripboard.py` renders boards for humans.

## Data stores

### Postgres / Cloud SQL

Primary transactional state:

- productions,
- screenplay assets,
- breakdown runs,
- candidate scenes,
- accepted scenes,
- schedule runs,
- boards,
- board days,
- board assignments,
- audit events.

### GCS

Durable blobs:

- uploaded screenplays,
- raw agent outputs,
- generated artifacts and exports.

### BigQuery

Append-only analytics/telemetry:

- agent run timing and model metadata,
- solver run metrics,
- explicit audit/event export rows,
- cost/performance trends.

BigQuery is not the system of record for interactive product state.

## Agent boundary

Agents sit behind narrow protocols:

- `BreakdownAgent.extract(document, media)` for screenplay reading,
- future `ConstraintAgent.extract(text/evidence)` for plain-English constraints.

Each agent returns candidate records. Candidate records require validation and/or human acceptance before they reach the solver.

## Scheduling boundary

The scheduler worker builds a `ScheduleProblem` from accepted state, calls `coverset.solver.solve`, and persists a complete result snapshot. No model output may directly choose board order.

A schedule run stores:

- input hash,
- solver version and parameters,
- accepted scene snapshot,
- active constraint snapshot,
- board output or conflict set,
- validation report,
- rendered stripboard.
