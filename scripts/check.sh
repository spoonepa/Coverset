#!/usr/bin/env bash
# All gates. Everything must pass before a commit lands.
#
#   ./scripts/check.sh          offline gates only (no API key needed)
#   ./scripts/check.sh --live   also verify against the real Parallel API
set -uo pipefail
cd "$(dirname "$0")/.."
status=0
run() {
  printf '\n\033[1m== %s ==\033[0m\n' "$1"
  shift
  "$@" || status=1
}

secret_scan() {
  local tracked_artifacts
  tracked_artifacts="$(git ls-files | grep -E '(^|/)\.env$|\.tfvars$|backend\.auto\.hcl$|credentials.*\.json$|service_account.*\.json$|secret.*\.json$' || true)"
  if [[ -n "${tracked_artifacts}" ]]; then
    echo "tracked secret/config artifacts are forbidden:"
    echo "${tracked_artifacts}"
    return 1
  fi

  python - <<'PY'
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

skip = {"uv.lock", "apps/web/package-lock.json"}
secret_patterns = [
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(
        r"(?:PARALLEL_API_KEY|GEMINI_API_KEY|GOOGLE_API_KEY|COVERSET_APP_SECRET)"
        r"\s*=\s*['\"]?(?!\.\.\.)[A-Za-z0-9_./+=-]{16,}"
    ),
]
files = subprocess.check_output(["git", "ls-files"], text=True).splitlines()
offenders: list[str] = []
for name in files:
    if name in skip:
        continue
    path = pathlib.Path(name)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    if any(pattern.search(text) for pattern in secret_patterns):
        offenders.append(name)
if offenders:
    print("secret-looking values found in tracked files:")
    for name in offenders:
        print(name)
    sys.exit(1)
PY
}

terraform_static() {
  terraform -chdir=infra/terraform fmt -check -recursive || return 1
  if [[ -f infra/terraform/backend.auto.hcl ]]; then
    terraform -chdir=infra/terraform init -input=false -backend-config=backend.auto.hcl >/dev/null || return 1
  else
    terraform -chdir=infra/terraform init -backend=false -input=false >/dev/null || return 1
  fi
  terraform -chdir=infra/terraform validate -no-color
}

run "workspace whitespace" git diff --check
run "secret hygiene" secret_scan
run "offline tests" uv run pytest
run "traceability" uv run python scripts/traceability.py
run "ui reference" uv run python scripts/check_ui_reference.py
run "python lock" uv lock --check
run "python build" uv build
run "terraform static" terraform_static
run "web lint" npm --prefix apps/web run lint
run "web build" npm --prefix apps/web run build
run "web e2e" npm --prefix apps/web run test:e2e

if [[ "${1:-}" == "--live" ]]; then
  run "live verification" uv run pytest -m live
else
  printf '\n(skipping live verification; pass --live to include it)\n'
fi

printf '\n'
[[ $status -eq 0 ]] && echo "ALL GATES PASS" || echo "GATES FAILED"
exit $status
