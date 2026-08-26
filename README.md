# Coverset

An agentic scheduling partner for first assistant directors.

---

## Overview

<!-- TODO -->

## Architecture

<!-- TODO -->

## Setup

```sh
uv sync
export PARALLEL_API_KEY=...   # required: Search is called at runtime
```

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

<!-- TODO -->

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
|---|---|---|
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
drift into reassurance. A `built` requirement with no test exits non-zero, as does a
test citing an ID that is not in the spec.

### Before committing

```sh
./scripts/check.sh          # offline gates
./scripts/check.sh --live   # everything, including the real API
```
