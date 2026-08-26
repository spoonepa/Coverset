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
