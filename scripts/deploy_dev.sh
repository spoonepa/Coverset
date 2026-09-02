#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
REPOSITORY="${REPOSITORY:-coverset}"
TAG="${TAG:-$(git rev-parse --short HEAD)}"
ACCOUNT="${DEVELOPER_ACCOUNT:-$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -1)}"
DEVELOPER_PRINCIPAL="${DEVELOPER_PRINCIPAL:-user:${ACCOUNT}}"
AGENT_MODE="${AGENT_MODE:-fixture}"
PLACEHOLDER_IMAGE="us-docker.pkg.dev/cloudrun/container/hello"
TF_DIR="infra/terraform"
GENERATED_TFVARS="${TF_DIR}/dev.auto.tfvars"
TF_BACKEND_CONFIG="${TF_BACKEND_CONFIG:-${ROOT}/${TF_DIR}/backend.auto.hcl}"
TF_STATE_BUCKET="${TF_STATE_BUCKET:-coverset-${PROJECT_ID}-terraform-state}"
BILLING_ACCOUNT_ID="${BILLING_ACCOUNT_ID:-}"
if [[ -z "${BILLING_ACCOUNT_ID}" ]]; then
  BILLING_ACCOUNT_ID="$(gcloud billing projects describe "${PROJECT_ID}" --format='value(billingAccountName)' 2>/dev/null | sed 's#^billingAccounts/##' || true)"
fi

if [[ -z "${PROJECT_ID}" || -z "${ACCOUNT}" ]]; then
  echo "gcloud project/account is not configured" >&2
  exit 1
fi

echo "== Coverset dev deploy =="
echo "project=${PROJECT_ID} region=${REGION} tag=${TAG} principal=${DEVELOPER_PRINCIPAL} agent_mode=${AGENT_MODE} budget=$([[ -n "${BILLING_ACCOUNT_ID}" ]] && echo enabled || echo skipped)"

echo "== enabling required APIs =="
gcloud services enable \
  aiplatform.googleapis.com \
  artifactregistry.googleapis.com \
  bigquery.googleapis.com \
  billingbudgets.googleapis.com \
  cloudbuild.googleapis.com \
  cloudtasks.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  monitoring.googleapis.com \
  run.googleapis.com \
  secretmanager.googleapis.com \
  serviceusage.googleapis.com \
  sqladmin.googleapis.com \
  storage.googleapis.com \
  --project "${PROJECT_ID}" >/dev/null

echo "== terraform state backend =="
if [[ "${COVERSET_BOOTSTRAP_TF_STATE:-1}" != "0" ]]; then
  PROJECT_ID="${PROJECT_ID}" REGION="${REGION}" TF_BACKEND_CONFIG="${TF_BACKEND_CONFIG}" TF_STATE_BUCKET="${TF_STATE_BUCKET}" \
    "${ROOT}/scripts/bootstrap_terraform_state.sh" --no-init
else
  echo "skipping backend bootstrap because COVERSET_BOOTSTRAP_TF_STATE=0"
fi

echo "== terraform init/validate =="
terraform -chdir="${TF_DIR}" init -input=false -backend-config="${TF_BACKEND_CONFIG}"
terraform -chdir="${TF_DIR}" validate

API_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/coverset-api:${TAG}"
WORKER_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/coverset-worker:${TAG}"
WEB_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/coverset-web:${TAG}"

if [[ -f "${GENERATED_TFVARS}" ]]; then
  echo "== existing terraform image vars found; deferring apply until new images are built =="
else
  echo "== terraform bootstrap/apply with placeholder images =="
  terraform -chdir="${TF_DIR}" apply -auto-approve -input=false \
    -var "project_id=${PROJECT_ID}" \
    -var "region=${REGION}" \
    -var "repository_id=${REPOSITORY}" \
    -var "developer_principal=${DEVELOPER_PRINCIPAL}" \
    -var "agent_mode=${AGENT_MODE}" \
    -var "terraform_state_bucket=${TF_STATE_BUCKET}" \
    -var "billing_account_id=${BILLING_ACCOUNT_ID}" \
    -var "api_image=${PLACEHOLDER_IMAGE}" \
    -var "worker_image=${PLACEHOLDER_IMAGE}" \
    -var "web_image=${PLACEHOLDER_IMAGE}"
fi

echo "== optionally updating Secret Manager from shell environment =="
PROJECT_ID="${PROJECT_ID}" "${ROOT}/scripts/bootstrap_gcp_secrets.sh"

echo "== Cloud Build images =="
gcloud builds submit . \
  --project "${PROJECT_ID}" \
  --config cloudbuild.yaml \
  --substitutions "_REGION=${REGION},_REPOSITORY=${REPOSITORY},_TAG=${TAG}"

echo "== writing generated Terraform image vars =="
cat >"${GENERATED_TFVARS}" <<EOF
project_id             = "${PROJECT_ID}"
region                 = "${REGION}"
repository_id          = "${REPOSITORY}"
developer_principal    = "${DEVELOPER_PRINCIPAL}"
agent_mode             = "${AGENT_MODE}"
terraform_state_bucket = "${TF_STATE_BUCKET}"
billing_account_id    = "${BILLING_ACCOUNT_ID}"
api_image              = "${API_IMAGE}"
worker_image           = "${WORKER_IMAGE}"
web_image              = "${WEB_IMAGE}"
EOF
terraform -chdir="${TF_DIR}" fmt "$(basename "${GENERATED_TFVARS}")" >/dev/null

echo "== terraform apply real images =="
terraform -chdir="${TF_DIR}" apply -auto-approve -input=false

identity_token() {
  local audience="$1"
  gcloud auth print-identity-token --audiences="${audience}" 2>/dev/null ||
    gcloud auth print-identity-token
}

API_URL="$(terraform -chdir="${TF_DIR}" output -raw api_url)"
WEB_URL="$(terraform -chdir="${TF_DIR}" output -raw web_url)"
TOKEN="$(identity_token "${API_URL}")"

echo "== smoke: API readiness =="
curl -fsS -H "Authorization: Bearer ${TOKEN}" "${API_URL}/readyz"
echo

echo "== smoke: fixture demo end-to-end =="
DEMO_OUT="$(mktemp)"
curl -fsS -X POST -H "Authorization: Bearer ${TOKEN}" "${API_URL}/demo/run" >"${DEMO_OUT}"
python - "${DEMO_OUT}" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1]))
print('board_id=' + payload['id'])
print('solver_status=' + payload['solver_status'])
print(payload['stripboard'].splitlines()[0])
PY
rm -f "${DEMO_OUT}"

echo "== deployed URLs =="
echo "api=${API_URL}"
echo "web=${WEB_URL}"
echo "worker=$(terraform -chdir="${TF_DIR}" output -raw worker_url)"
echo
cat <<EOF
Private web access:
  gcloud run services proxy coverset-web-dev --project ${PROJECT_ID} --region ${REGION} --port 8088
  open http://127.0.0.1:8088
EOF
