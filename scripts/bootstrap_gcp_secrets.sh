#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
if [[ -z "${PROJECT_ID}" ]]; then
  echo "PROJECT_ID is not set and gcloud has no active project" >&2
  exit 1
fi

ensure_secret() {
  local secret_id="$1"
  if ! gcloud secrets describe "${secret_id}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud secrets create "${secret_id}" --project "${PROJECT_ID}" --replication-policy="automatic" >/dev/null
    echo "created ${secret_id}"
  fi
}

add_version_from_env() {
  local env_name="$1"
  local secret_id="$2"
  ensure_secret "${secret_id}"
  local value="${!env_name:-}"
  if [[ -z "${value}" ]]; then
    echo "skipped ${secret_id}: ${env_name} is not set"
    return 0
  fi
  printf '%s' "${value}" | gcloud secrets versions add "${secret_id}" \
    --project "${PROJECT_ID}" \
    --data-file=- >/dev/null
  echo "updated ${secret_id} from ${env_name}"
}

add_version_from_env GEMINI_API_KEY coverset-gemini-api-key
add_version_from_env GOOGLE_API_KEY coverset-google-api-key
add_version_from_env PARALLEL_API_KEY coverset-parallel-api-key
add_version_from_env COVERSET_APP_SECRET coverset-app-secret
