# Coverset

An agentic scheduling partner for first assistant directors.

---

## Overview

Coverset turns a screenplay into scheduler-ready scene records, lets humans review
and lock production decisions, then produces deterministic stripboards with CP-SAT
and Second AD call sheets for selected shoot days. Gemini and Parallel supply
candidates and evidence; they never select boards, approve costs, or mutate locked
shoot history.

## Architecture

Coverset keeps advisory agents out of the scheduling decision path:

```text
Next.js web UI -> FastAPI API -> Postgres/GCS
                         |
                         v
                  deterministic CP-SAT scheduler
                         ^
Gemini breakdown -> candidate records
Parallel Search  -> grounded evidence
```

See:

- `docs/architecture/system-architecture.md`
- `docs/architecture/deployment-architecture.md`

## Setup

```sh
uv sync
export PARALLEL_API_KEY=...   # required: Search is called at runtime
```

Local app code loads environment variables from `COVERSET_ENV_FILE`, then a
repo-local ignored `.env`, then `~/.config/coverset/Coverset.env`. Keep all real
keys out of Git and rotate any key that was ever pasted into a chat/transcript.

Run the tests (offline -- no API key needed, the Parallel SDK is driven through a
mock transport):

```sh
uv run pytest
```

Confirm the grounding path against the live API:

```sh
uv run python scripts/smoke_grounding.py
```

## Demo

Run the local API-backed vertical slice with a deterministic fixture agent:

```sh
uv run uvicorn coverset.api.main:app --reload --port 8080
curl -X POST http://127.0.0.1:8080/demo/run
```

Run the web UI locally:

```sh
cd apps/web
npm install
npm run dev
```

The web app proxies API calls to `COVERSET_API_BASE_URL` (default:
`http://127.0.0.1:8080`). Async breakdown, grounding, and solve requests create job
rows. In Cloud Run, Cloud Tasks dispatches those jobs to the worker; locally you can
run one queued job with:

```sh
uv run python -m coverset.worker.main run-once
```

## Dev deploy

The dev cloud stack is provisioned with Terraform and images are built by Cloud Build:

```sh
scripts/bootstrap_terraform_state.sh   # one-time GCS remote state bootstrap/migration
scripts/deploy_dev.sh
```

Default target: project `spoonepa`, region `us-central1`, private Cloud Run. The deploy
script bootstraps the GCS backend config when needed, smoke-tests `/readyz` and
`/demo/run` with an identity token, and applies the Cloud Build image tags through
Terraform.

Real Gemini/Parallel keys must live in Secret Manager. Rotate leaked keys first, then run:

```sh
export GEMINI_API_KEY=...
export GOOGLE_API_KEY=...
export PARALLEL_API_KEY=...
scripts/bootstrap_gcp_secrets.sh
```

Do not commit `.env`, credentials, generated `*.tfvars` files, or
`infra/terraform/backend.auto.hcl`.

## Exports and operations

Useful review artifacts are available from the private API:

```text
GET  /boards/{board_id}/export?format=text|csv|json
POST /boards/{board_id}/call-sheets
GET  /boards/{board_id}/call-sheets
GET  /call-sheets/{call_sheet_id}/export?format=text|json
GET  /productions/{production_id}/audit
GET  /productions/{production_id}/audit/export?format=csv|json
POST /productions/{production_id}/audit/bigquery
```

Cloud SQL remains the system of record. BigQuery receives append-only audit export
rows for analytics; it is not used as transactional state. The dev Terraform stack
also provisions Cloud SQL backups, a Cloud Run error log metric/alert, and an
optional monthly budget alert when a billing account is available.

## Development

`SPEC.md` holds the requirements, each with a stable ID. `PROJECT_BRIEF.md` says why;
the spec says what must be true.

### The loop

1. **Specify before building.** Add the requirement to `SPEC.md` with an ID and a
   statement narrow enough to test.
2. **Probe before trusting.** Anything that depends on an external service gets a
   throwaway script against the real API *before* code is designed around it. Every
   finding in the brief came from doing this; the one time it was skipped, the design
   was built on an assumption that turned out to be false.
3. **Build, with failure loud.** This system's characteristic hazard is the
   plausible-but-wrong value — a well-formed sunset time for the wrong date reaches the
   solver, proves out, and yields a wrong board. Anything that could produce one raises
   instead of guessing.
4. **Test at both tiers, citing the requirement.**
5. **Write down what surprised you** in the brief's *Findings and learnings*. It is for
   the surprises, not the successes.

### Verification tiers

| Tier | Command | Proves |
| --- | --- | --- |
| Offline | `uv run pytest` | Wiring, shape, invariants. Deterministic, no key. |
| Live | `uv run pytest -m live` | The external world behaves as assumed. Needs a key. |

Offline tests encode what the API was *assumed* to return, so they cannot catch a
false assumption. An externally-dependent requirement is not done on offline tests
alone.

### Traceability

Tests declare what they verify:

```python
@pytest.mark.req("GRD-003")
def test_weather_for_the_wrong_day_is_refused_rather_than_bound(...):
```

```sh
uv run python scripts/traceability.py            # summary and gaps
uv run python scripts/traceability.py --matrix   # every requirement, every test
```

The matrix is derived from the suite, not from a hand-maintained table, so it cannot
drift into reassurance. It exits non-zero when a requirement claiming implementation
has no test, when a test cites an ID absent from the spec, or when a requirement claims
`demo-ready` without the live verification the spec says it needs.

Requirements carry a maturity (`not-started` → `domain-model` → `unit-built` →
`integrated` → `demo-ready`), a required verification tier, and the slice (`MVP-0`
through `POST`) where they first matter. The report separates two kinds of blocker that
need different work: **needs building** (nothing exists) and **needs integration**
(behaviour exists and is tested, but is not wired into a journey).

### Before committing

```sh
./scripts/check.sh          # offline gates
./scripts/check.sh --live   # everything, including the real API
```
