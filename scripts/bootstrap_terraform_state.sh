#!/usr/bin/env bash
# Bootstrap Coverset's remote Terraform state bucket and migrate local state to it.
#
# Defaults:
#   PROJECT_ID: current gcloud project
#   REGION: us-central1
#   TF_STATE_BUCKET: coverset-${PROJECT_ID}-terraform-state
#   TF_STATE_PREFIX: coverset/dev
#   TF_BACKEND_CONFIG: infra/terraform/backend.auto.hcl (gitignored)
#
# Use --no-init when another script only needs the bucket/config created before
# running its own `terraform init`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
TF_DIR="${TF_DIR:-${ROOT}/infra/terraform}"
TF_BACKEND_CONFIG="${TF_BACKEND_CONFIG:-${TF_DIR}/backend.auto.hcl}"
TF_STATE_BUCKET="${TF_STATE_BUCKET:-coverset-${PROJECT_ID}-terraform-state}"
TF_STATE_PREFIX="${TF_STATE_PREFIX:-coverset/dev}"
RUN_INIT=1

while [[ $# -gt 0 ]]; do
  case "$1" in
  --no-init)
    RUN_INIT=0
    shift
    ;;
  *)
    echo "unknown argument: $1" >&2
    exit 2
    ;;
  esac
done

if [[ -z "${PROJECT_ID}" ]]; then
  echo "PROJECT_ID is required or must be configured in gcloud" >&2
  exit 1
fi

echo "== Terraform state backend =="
echo "project=${PROJECT_ID} region=${REGION} bucket=${TF_STATE_BUCKET} prefix=${TF_STATE_PREFIX}"

gcloud services enable storage.googleapis.com --project "${PROJECT_ID}" >/dev/null

if gcloud storage buckets describe "gs://${TF_STATE_BUCKET}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
  echo "state bucket exists: gs://${TF_STATE_BUCKET}"
else
  echo "creating state bucket: gs://${TF_STATE_BUCKET}"
  gcloud storage buckets create "gs://${TF_STATE_BUCKET}" \
    --project "${PROJECT_ID}" \
    --location "${REGION}" \
    --uniform-bucket-level-access \
    --public-access-prevention >/dev/null
fi

gcloud storage buckets update "gs://${TF_STATE_BUCKET}" \
  --project "${PROJECT_ID}" \
  --versioning >/dev/null

mkdir -p "$(dirname "${TF_BACKEND_CONFIG}")"
umask 077
cat >"${TF_BACKEND_CONFIG}" <<EOF
bucket = "${TF_STATE_BUCKET}"
prefix = "${TF_STATE_PREFIX}"
EOF

echo "wrote backend config: ${TF_BACKEND_CONFIG}"

if [[ "${RUN_INIT}" -eq 1 ]]; then
  terraform -chdir="${TF_DIR}" init \
    -input=false \
    -migrate-state \
    -force-copy \
    -backend-config="${TF_BACKEND_CONFIG}"
fi
