#!/usr/bin/env bash
# All gates. Everything must pass before a commit lands.
#
#   ./scripts/check.sh          offline gates only (no API key needed)
#   ./scripts/check.sh --live   also verify against the real Parallel API
set -uo pipefail
cd "$(dirname "$0")/.."
status=0
run() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; shift; "$@" || status=1; }

run "offline tests"  uv run pytest
run "traceability"   uv run python scripts/traceability.py
run "ui reference"   uv run python scripts/check_ui_reference.py

if [[ "${1:-}" == "--live" ]]; then
  run "live verification" uv run pytest -m live
else
  printf '\n(skipping live verification; pass --live to include it)\n'
fi

printf '\n'
[[ $status -eq 0 ]] && echo "ALL GATES PASS" || echo "GATES FAILED"
exit $status
