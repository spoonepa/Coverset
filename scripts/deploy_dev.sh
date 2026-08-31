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

if [[ -z "${PROJECT_ID}" || -z "${ACCOUNT}" ]]; then
  echo "gcloud project/account is not configured" >&2
  exit 1
fi

echo "== Coverset dev deploy =="
echo "project=${PROJECT_ID} region=${REGION} tag=${TAG} principal=${DEVELOPER_PRINCIPAL} agent_mode=${AGENT_MODE}"

echo "== enabling required APIs =="
gcloud services enable \
  aiplatform.googleapis.com \
  artifactregistry.googleapis.com \
  bigquery.googleapis.com \
  cloudbuild.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  run.googleapis.com \
  secretmanager.googleapis.com \
  serviceusage.googleapis.com \
  sqladmin.googleapis.com \
  storage.googleapis.com \
  --project "${PROJECT_ID}" >/dev/null

echo "== terraform init/validate =="
terraform -chdir="${TF_DIR}" init -input=false
terraform -chdir="${TF_DIR}" validate

echo "== terraform bootstrap/apply with placeholder images =="
terraform -chdir="${TF_DIR}" apply -auto-approve -input=false \
  -var "project_id=${PROJECT_ID}" \
  -var "region=${REGION}" \
  -var "repository_id=${REPOSITORY}" \
  -var "developer_principal=${DEVELOPER_PRINCIPAL}" \
  -var "agent_mode=${AGENT_MODE}" \
  -var "api_image=${PLACEHOLDER_IMAGE}" \
  -var "worker_image=${PLACEHOLDER_IMAGE}" \
  -var "web_image=${PLACEHOLDER_IMAGE}"

echo "== optionally updating Secret Manager from shell environment =="
PROJECT_ID="${PROJECT_ID}" "${ROOT}/scripts/bootstrap_gcp_secrets.sh"

API_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/coverset-api:${TAG}"
WORKER_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/coverset-worker:${TAG}"
WEB_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/coverset-web:${TAG}"

echo "== Cloud Build images =="
gcloud builds submit . \
  --project "${PROJECT_ID}" \
  --config cloudbuild.yaml \
  --substitutions "_REGION=${REGION},_REPOSITORY=${REPOSITORY},_TAG=${TAG}"

echo "== writing generated Terraform image vars =="
cat > "${GENERATED_TFVARS}" <<EOF
project_id          = "${PROJECT_ID}"
region              = "${REGION}"
repository_id       = "${REPOSITORY}"
developer_principal = "${DEVELOPER_PRINCIPAL}"
agent_mode          = "${AGENT_MODE}"
api_image           = "${API_IMAGE}"
worker_image        = "${WORKER_IMAGE}"
web_image           = "${WEB_IMAGE}"
EOF

echo "== terraform apply real images =="
terraform -chdir="${TF_DIR}" apply -auto-approve -input=false

identity_token() {
  local audience="$1"
  gcloud auth print-identity-token --audiences="${audience}" 2>/dev/null \
    || gcloud auth print-identity-token
}

API_URL="$(terraform -chdir="${TF_DIR}" output -raw api_url)"
WEB_URL="$(terraform -chdir="${TF_DIR}" output -raw web_url)"
TOKEN="$(identity_token "${API_URL}")"

echo "== smoke: API health =="
curl -fsS -H "Authorization: Bearer ${TOKEN}" "${API_URL}/healthz"
echo

echo "== smoke: fixture demo end-to-end =="
DEMO_OUT="$(mktemp)"
curl -fsS -X POST -H "Authorization: Bearer ${TOKEN}" "${API_URL}/demo/run" > "${DEMO_OUT}"
python - <<'PY' "${DEMO_OUT}"
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
