#!/usr/bin/env bash
# ==============================================================================
# Brew — Minimal-Footprint Google Cloud Setup & Cloud Run Deployment Script
# ==============================================================================
# Provisions and deploys Brew as a single private-by-default Cloud Run service
# serving the compiled React SPA, FastAPI v1 API, A2A surface, and Google ADK
# Conversation Coach backed by Firestore, Vertex AI Gemini (ADC), Cloud Logging,
# and Google Cloud Trace.
#
# Security & Architecture Principles:
#   - Ordered sequence of enablement (APIs -> Firestore & Indexes -> Least-Privilege
#     IAM -> Optional GitHub WIF -> Artifact Registry -> Secret Manager -> Build &
#     Agents CLI Cloud Run Deploy -> Probes & Smoke Verification).
#   - Zero service account JSON keys: runtime uses attached `brew-runtime` SA
#     via Cloud Run metadata server Application Default Credentials (ADC); CI/CD
#     uses GitHub OIDC Workload Identity Federation (WIF).
#   - Private by default (`--no-allow-unauthenticated`), with optional Cloud Run
#     Identity-Aware Proxy (`ENABLE_IAP=true` -> `agents-cli deploy --iap`) for
#     zero-trust browser access.
#   - Refuses to expose a public Cloud Run endpoint unless verified user auth
#     (`GOOGLE_OAUTH_CLIENT_ID` or `FIREBASE_WEB_API_KEY`) is configured and
#     verifies that all memory/API endpoints reject unauthenticated callers.
#
# Usage:
#   PROJECT_ID="my-gcp-project" ./gcloud_setup.sh --dry-run
#   PROJECT_ID="my-gcp-project" GITHUB_REPO="owner/brew" ./gcloud_setup.sh --infra-only
#   PROJECT_ID="my-gcp-project" ENABLE_IAP="true" ./gcloud_setup.sh
# ==============================================================================

set -euo pipefail
umask 077

DRY_RUN="false"
INFRA_ONLY="false"

usage() {
  cat <<'EOF'
Usage: PROJECT_ID=<gcp-project-id> ./gcloud_setup.sh [options]

Options:
  --dry-run      Print all ordered commands without mutating Google Cloud resources.
  --infra-only   Provision APIs, Firestore, indexes, IAM, WIF, Artifact Registry,
                 and Secret Manager without building or deploying the container.
  -h, --help     Show this help message and exit.

Key Environment Variables:
  PROJECT_ID                   (Required) Target Google Cloud project ID.
  REGION                       Cloud Run & Artifact Registry region (default: asia-southeast1).
  FIRESTORE_LOCATION           Firestore Native database location (default: $REGION).
  FIRESTORE_DATABASE           Firestore database ID (default: (default)).
  SERVICE_NAME                 Cloud Run service name (default: brew).
  AR_REPO                      Artifact Registry Docker repository (default: brew).
  GEMINI_MODEL                 Configured Gemini model ID (default: gemini-3.8-flash).
  BREW_SYNTHESIS_MODEL         Model for initial brief synthesis (default: gemini-4-hydrogen).
  CLOUD_RUN_CPU                vCPU limit per instance (default: 1).
  CLOUD_RUN_MEMORY             Memory limit per instance (default: 1Gi).
  CLOUD_RUN_CONCURRENCY        Max concurrent requests per instance (default: 8).
  CLOUD_RUN_MIN_INSTANCES      Minimum warm instances, 0 = scale-to-zero (default: 0).
  CLOUD_RUN_MAX_INSTANCES      Maximum horizontal instances (default: 5).
  CLOUD_RUN_TIMEOUT            Request timeout in seconds (default: 120).
  ENABLE_IAP                   Enable Cloud Run Identity-Aware Proxy for browser access (default: false).
  IAP_ACCESSOR_MEMBERS         Optional comma-separated IAM members for IAP (e.g. user:you@example.com).
  ALLOW_PUBLIC_INGRESS         Make Cloud Run URL public ONLY after auth verification (default: false).
  GOOGLE_OAUTH_CLIENT_ID_VALUE Optional OAuth 2.0 Web Client ID stored in Secret Manager.
  FIREBASE_WEB_API_KEY_VALUE   Optional Firebase Web API key stored in Secret Manager.
  GITHUB_REPO                  Optional owner/repo (e.g. acme/brew) to configure GitHub Actions WIF.
  BUILD_MODE                   Container build mode: cloud_build | docker (default: cloud_build).
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run|-n)
      DRY_RUN="true"
      shift
      ;;
    --infra-only)
      INFRA_ONLY="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

# ------------------------------------------------------------------------------
# Configuration & Minimal-Footprint Defaults
# ------------------------------------------------------------------------------
PROJECT_ID="${PROJECT_ID:-${GOOGLE_CLOUD_PROJECT:-}}"
if [[ -z "${PROJECT_ID}" || "${PROJECT_ID}" == "your-gcp-project-id" ]]; then
  echo "ERROR: PROJECT_ID must be set to a real Google Cloud project ID." >&2
  exit 1
fi

REGION="${REGION:-asia-southeast1}"
FIRESTORE_LOCATION="${FIRESTORE_LOCATION:-${REGION}}"
FIRESTORE_DATABASE="${FIRESTORE_DATABASE:-(default)}"
SERVICE_NAME="${SERVICE_NAME:-brew}"
AR_REPO="${AR_REPO:-brew}"
GEMINI_MODEL="${GEMINI_MODEL:-gemini-3.8-flash}"
BREW_SYNTHESIS_MODEL="${BREW_SYNTHESIS_MODEL:-gemini-4-hydrogen}"
GOOGLE_CLOUD_LOCATION="${GOOGLE_CLOUD_LOCATION:-global}"

RUNTIME_SA_NAME="${RUNTIME_SA_NAME:-brew-runtime}"
RUNTIME_SA_EMAIL="${RUNTIME_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

BUILDER_SA_NAME="${BUILDER_SA_NAME:-brew-builder}"
BUILDER_SA_EMAIL="${BUILDER_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

CICD_SA_NAME="${CICD_SA_NAME:-brew-cicd}"
CICD_SA_EMAIL="${CICD_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
WIF_POOL_ID="${WIF_POOL_ID:-brew-github-pool}"
WIF_PROVIDER_ID="${WIF_PROVIDER_ID:-brew-github-oidc}"
GITHUB_REPO="${GITHUB_REPO:-}"

# Smallest reasonable Cloud Run resource & scaling footprint
CLOUD_RUN_CPU="${CLOUD_RUN_CPU:-1}"
CLOUD_RUN_MEMORY="${CLOUD_RUN_MEMORY:-1Gi}"
CLOUD_RUN_CONCURRENCY="${CLOUD_RUN_CONCURRENCY:-8}"
CLOUD_RUN_MIN_INSTANCES="${CLOUD_RUN_MIN_INSTANCES:-0}"
CLOUD_RUN_MAX_INSTANCES="${CLOUD_RUN_MAX_INSTANCES:-5}"
CLOUD_RUN_TIMEOUT="${CLOUD_RUN_TIMEOUT:-120}"

ENABLE_IAP="${ENABLE_IAP:-false}"
IAP_ACCESSOR_MEMBERS="${IAP_ACCESSOR_MEMBERS:-}"
ALLOW_PUBLIC_INGRESS="${ALLOW_PUBLIC_INGRESS:-false}"
BUILD_MODE="${BUILD_MODE:-cloud_build}"

SECRET_GOOGLE_OAUTH_CLIENT_ID="${SECRET_GOOGLE_OAUTH_CLIENT_ID:-brew-google-oauth-client-id}"
SECRET_FIREBASE_WEB_API_KEY="${SECRET_FIREBASE_WEB_API_KEY:-brew-firebase-web-api-key}"

# Prevent mTLS enterprise cert proxy errors when targeting standard external GCP projects
export GOOGLE_API_USE_CLIENT_CERTIFICATE="${GOOGLE_API_USE_CLIENT_CERTIFICATE:-false}"

TMP_FILES_TO_CLEAN=()
cleanup_temp_artifacts() {
  for path in "${TMP_FILES_TO_CLEAN[@]:-}"; do
    if [[ -n "${path}" ]]; then
      rm -rf "${path}" 2>/dev/null || true
    fi
  done
}
trap cleanup_temp_artifacts EXIT

log_step() {
  printf '\n==> %s\n' "$1"
}

run_cmd() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    printf '[dry-run] '
    printf '%q ' "$@"
    printf '\n'
    return 0
  fi
  "$@"
}

# Retry IAM policy bindings to handle Google Cloud IAM eventual consistency
# immediately after creating new service accounts, WIF pools, or service agents.
run_iam_cmd() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    run_cmd "$@"
    return 0
  fi

  local max_attempts=8
  local delay=2
  local attempt=1
  local err_output=""

  while (( attempt <= max_attempts )); do
    if err_output="$("$@" 2>&1)"; then
      return 0
    fi
    if grep -Eqi "does not exist|may not exist|not found|concurrent policy changes|aborted|try again|invalid_argument" <<<"${err_output}" \
      && (( attempt < max_attempts )); then
      echo "  Waiting ${delay}s for Google Cloud IAM propagation (attempt ${attempt}/${max_attempts})..."
      sleep "${delay}"
      delay=$(( delay + 3 ))
      attempt=$(( attempt + 1 ))
    else
      echo "${err_output}" >&2
      return 1
    fi
  done
}

# ------------------------------------------------------------------------------
# Phase 0: Pre-Flight Tooling, Zero-Key Guard, & ADC Verification
# ------------------------------------------------------------------------------
log_step "Phase 0: Verifying CLI tooling and Application Default Credentials (no JSON keys)"

# MANUAL STEP (one-time per workstation before running without --dry-run):
#   gcloud auth login
#   gcloud auth application-default login
#   gcloud auth application-default set-quota-project "${PROJECT_ID}"
#
# POLICY: Never run `gcloud iam service-accounts keys create`. All local, CI/CD,
# and Cloud Run authentication uses short-lived OAuth/OIDC tokens via ADC or WIF.
if [[ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" ]]; then
  echo "ERROR: GOOGLE_APPLICATION_CREDENTIALS is set (${GOOGLE_APPLICATION_CREDENTIALS})." >&2
  echo "       Unset static JSON key paths and use Application Default Credentials instead." >&2
  exit 1
fi

command -v gcloud >/dev/null 2>&1 || {
  echo "ERROR: gcloud CLI is required." >&2
  exit 1
}

AGENTS_CLI_BIN=()
if command -v agents-cli >/dev/null 2>&1; then
  AGENTS_CLI_BIN=("agents-cli")
elif command -v uvx >/dev/null 2>&1; then
  AGENTS_CLI_BIN=("uvx" "--from" "google-agents-cli==1.15.0" "agents-cli")
elif [[ "${INFRA_ONLY}" != "true" ]]; then
  echo "ERROR: agents-cli (or uvx) is required for Cloud Run deployment." >&2
  exit 1
fi

if [[ "${DRY_RUN}" != "true" ]]; then
  if ! gcloud_err="$(gcloud auth print-access-token 2>&1 >/dev/null)"; then
    echo "ERROR: No active gcloud session. Run: gcloud auth login" >&2
    echo "       gcloud details: ${gcloud_err}" >&2
    exit 1
  fi
  if ! adc_err="$(gcloud auth application-default print-access-token 2>&1 >/dev/null)"; then
    echo "ERROR: Application Default Credentials missing or expired." >&2
    echo "       Run explicitly: gcloud auth application-default login" >&2
    echo "       gcloud details: ${adc_err}" >&2
    exit 1
  fi
fi

# ------------------------------------------------------------------------------
# Phase 1: Enable Required Google Cloud APIs (Ordered Bootstrap -> Core)
# ------------------------------------------------------------------------------
log_step "Phase 1: Enabling required Google Cloud APIs in dependency order"

# 1a. Bootstrap APIs required before IAM, quota, or service checks can run
run_cmd gcloud services enable \
  serviceusage.googleapis.com \
  cloudresourcemanager.googleapis.com \
  --project="${PROJECT_ID}"

# Bind ADC quota project after Service Usage & Cloud Resource Manager are enabled
run_cmd gcloud auth application-default set-quota-project "${PROJECT_ID}" --quiet

# 1b. Identity, federation, and secrets management APIs
run_cmd gcloud services enable \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  secretmanager.googleapis.com \
  --project="${PROJECT_ID}"

# 1c. Runtime, build, persistence, Gemini AI, and observability APIs
CORE_APIS=(
  storage.googleapis.com
  firestore.googleapis.com
  aiplatform.googleapis.com
  artifactregistry.googleapis.com
  cloudbuild.googleapis.com
  run.googleapis.com
  logging.googleapis.com
  cloudtrace.googleapis.com
  monitoring.googleapis.com
  telemetry.googleapis.com
)
if [[ "${ENABLE_IAP}" == "true" ]]; then
  CORE_APIS+=(iap.googleapis.com)
fi
run_cmd gcloud services enable "${CORE_APIS[@]}" --project="${PROJECT_ID}"

# 1d. Materialize Google-managed service agents for Vertex AI and Cloud Run
run_cmd gcloud beta services identity create \
  --service=aiplatform.googleapis.com \
  --project="${PROJECT_ID}"
run_cmd gcloud beta services identity create \
  --service=run.googleapis.com \
  --project="${PROJECT_ID}"
if [[ "${ENABLE_IAP}" == "true" ]]; then
  run_cmd gcloud beta services identity create \
    --service=iap.googleapis.com \
    --project="${PROJECT_ID}"
fi

if [[ "${DRY_RUN}" == "true" ]]; then
  PROJECT_NUMBER="000000000000"
else
  PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
fi

# ------------------------------------------------------------------------------
# Phase 2: Provision Cloud Firestore (Native Mode) & Required Indexes
# ------------------------------------------------------------------------------
log_step "Phase 2: Provisioning Cloud Firestore database and required indexes"

if [[ "${DRY_RUN}" == "true" ]]; then
  run_cmd gcloud firestore databases create \
    --project="${PROJECT_ID}" \
    --database="${FIRESTORE_DATABASE}" \
    --location="${FIRESTORE_LOCATION}" \
    --type=firestore-native \
    --delete-protection
else
  if gcloud firestore databases describe \
    --project="${PROJECT_ID}" \
    --database="${FIRESTORE_DATABASE}" >/dev/null 2>&1; then
    echo "Firestore database '${FIRESTORE_DATABASE}' already exists in ${PROJECT_ID}."
  else
    gcloud firestore databases create \
      --project="${PROJECT_ID}" \
      --database="${FIRESTORE_DATABASE}" \
      --location="${FIRESTORE_LOCATION}" \
      --type=firestore-native \
      --delete-protection
  fi
fi

# 2a. Configure single-field COLLECTION_GROUP index exemptions required by:
#     - Brew cross-tenant ownership checks (`exists_for_any_owner` on `id` across
#       contacts, meetings, briefs, memoryProposals, memories)
#     - ADK `FirestoreSessionService.list_sessions` (`appName` across `sessions`)
#     Preserves default COLLECTION ascending + descending indexes alongside
#     COLLECTION_GROUP ascending.
ensure_collection_group_field_index() {
  local collection_group="$1"
  local field_path="$2"
  local encoded_db
  encoded_db="${FIRESTORE_DATABASE//(/%28}"
  encoded_db="${encoded_db//)/%29}"
  local url="https://firestore.googleapis.com/v1/projects/${PROJECT_ID}/databases/${encoded_db}/collectionGroups/${collection_group}/fields/${field_path}?updateMask=indexConfig"
  local payload
  payload=$(cat <<JSON
{
  "indexConfig": {
    "indexes": [
      {"queryScope": "COLLECTION", "fields": [{"fieldPath": "${field_path}", "order": "ASCENDING"}]},
      {"queryScope": "COLLECTION", "fields": [{"fieldPath": "${field_path}", "order": "DESCENDING"}]},
      {"queryScope": "COLLECTION_GROUP", "fields": [{"fieldPath": "${field_path}", "order": "ASCENDING"}]}
    ]
  }
}
JSON
)
  if [[ "${DRY_RUN}" == "true" ]]; then
    echo "[dry-run] PATCH ${url} (COLLECTION + COLLECTION_GROUP ASC on ${collection_group}.${field_path})"
    return 0
  fi

  local token http_code resp_file
  token="$(gcloud auth print-access-token)"
  resp_file="$(mktemp)"
  http_code="$(curl --silent --show-error --output "${resp_file}" --write-out '%{http_code}' \
    -X PATCH \
    -H "Authorization: Bearer ${token}" \
    -H "Content-Type: application/json" \
    -H "X-Goog-User-Project: ${PROJECT_ID}" \
    --data "${payload}" \
    "${url}")"

  if [[ "${http_code}" == "200" ]]; then
    rm -f "${resp_file}"
    echo "Configured COLLECTION_GROUP field index on ${collection_group}.${field_path}."
    return 0
  fi

  if grep -Eqi "already exists|already in progress|no changes|currently being" "${resp_file}"; then
    rm -f "${resp_file}"
    echo "COLLECTION_GROUP field index on ${collection_group}.${field_path} already configured or building."
    return 0
  fi

  echo "ERROR: Failed updating Firestore field index ${collection_group}.${field_path} (HTTP ${http_code}):" >&2
  cat "${resp_file}" >&2
  rm -f "${resp_file}"
  return 1
}

for subcollection in contacts meetings briefs memoryProposals memories; do
  ensure_collection_group_field_index "${subcollection}" "id"
done
ensure_collection_group_field_index "sessions" "appName"

# 2b. Create composite indexes supporting filtered + chronological queries
ensure_composite_index() {
  local collection_group="$1"
  local first_field="$2"
  local second_field="$3"

  if [[ "${DRY_RUN}" == "true" ]]; then
    run_cmd gcloud firestore indexes composite create \
      --project="${PROJECT_ID}" \
      --database="${FIRESTORE_DATABASE}" \
      --collection-group="${collection_group}" \
      --field-config="field-path=${first_field},order=ascending" \
      --field-config="field-path=${second_field},order=ascending" \
      --async
    return 0
  fi

  local output
  if output=$(gcloud firestore indexes composite create \
    --project="${PROJECT_ID}" \
    --database="${FIRESTORE_DATABASE}" \
    --collection-group="${collection_group}" \
    --field-config="field-path=${first_field},order=ascending" \
    --field-config="field-path=${second_field},order=ascending" \
    --async 2>&1); then
    echo "Submitted composite index: ${collection_group}(${first_field} ASC, ${second_field} ASC)."
  elif grep -qi "already exists" <<<"${output}"; then
    echo "Composite index already exists: ${collection_group}(${first_field} ASC, ${second_field} ASC)."
  else
    echo "${output}" >&2
    return 1
  fi
}

ensure_composite_index "memories" "contact_id" "created_at"
ensure_composite_index "memories" "scope" "created_at"
ensure_composite_index "memoryProposals" "status" "created_at"
ensure_composite_index "memoryProposals" "contact_id" "created_at"

# ------------------------------------------------------------------------------
# Phase 3: Least-Privilege Runtime Service Account (ADC Only — Zero Keys)
# ------------------------------------------------------------------------------
log_step "Phase 3: Configuring least-privilege runtime service account (${RUNTIME_SA_EMAIL})"

ensure_service_account() {
  local sa_name="$1"
  local sa_email="$2"
  local display_name="$3"

  if [[ "${DRY_RUN}" == "true" ]]; then
    run_cmd gcloud iam service-accounts create "${sa_name}" \
      --project="${PROJECT_ID}" \
      --display-name="${display_name}"
    return 0
  fi

  if gcloud iam service-accounts describe "${sa_email}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    echo "Service account ${sa_email} already exists."
  else
    gcloud iam service-accounts create "${sa_name}" \
      --project="${PROJECT_ID}" \
      --display-name="${display_name}"
  fi
}

ensure_service_account "${RUNTIME_SA_NAME}" "${RUNTIME_SA_EMAIL}" "Brew Cloud Run Runtime Identity"

# Least-privilege runtime roles ONLY (no roles/owner, roles/editor, or project-wide secretAdmin):
#   - roles/aiplatform.user       : Gemini model calls via Google Cloud Vertex AI
#   - roles/datastore.user        : Firestore persistent sessions & governed user memories
#   - roles/logging.logWriter     : Structured JSON logs to Cloud Logging
#   - roles/cloudtrace.agent      : OpenTelemetry span export to Cloud Trace
#   - roles/monitoring.metricWriter: OpenTelemetry runtime metrics
RUNTIME_ROLES=(
  roles/aiplatform.user
  roles/datastore.user
  roles/logging.logWriter
  roles/cloudtrace.agent
  roles/monitoring.metricWriter
)
for role in "${RUNTIME_ROLES[@]}"; do
  run_iam_cmd gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${RUNTIME_SA_EMAIL}" \
    --role="${role}" \
    --condition=None \
    --format=none \
    --quiet
done

if [[ "${BUILD_MODE}" != "docker" ]]; then
  # Dedicated Cloud Build SA avoids relying on the legacy Compute Engine default SA
  # (which may not exist when compute.googleapis.com is disabled or lacks default grants).
  ensure_service_account "${BUILDER_SA_NAME}" "${BUILDER_SA_EMAIL}" "Brew Cloud Build Image Builder"
  BUILDER_ROLES=(
    roles/cloudbuild.builds.builder
    roles/artifactregistry.writer
    roles/logging.logWriter
    roles/storage.admin
  )
  for role in "${BUILDER_ROLES[@]}"; do
    run_iam_cmd gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
      --member="serviceAccount:${BUILDER_SA_EMAIL}" \
      --role="${role}" \
      --condition=None \
      --format=none \
      --quiet
  done
fi

# ------------------------------------------------------------------------------
# Phase 4: GitHub Actions Workload Identity Federation (Keyless CI/CD)
# ------------------------------------------------------------------------------
if [[ -n "${GITHUB_REPO}" ]]; then
  log_step "Phase 4: Configuring GitHub OIDC Workload Identity Federation for ${GITHUB_REPO}"

  ensure_service_account "${CICD_SA_NAME}" "${CICD_SA_EMAIL}" "Brew GitHub Actions Deployer"

  CICD_PROJECT_ROLES=(
    roles/run.developer
    roles/run.invoker
    roles/artifactregistry.writer
    roles/cloudbuild.builds.builder
    roles/aiplatform.user
  )
  for role in "${CICD_PROJECT_ROLES[@]}"; do
    run_iam_cmd gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
      --member="serviceAccount:${CICD_SA_EMAIL}" \
      --role="${role}" \
      --condition=None \
      --format=none \
      --quiet
  done

  # Scope iam.serviceAccountUser strictly to the runtime SA (never project-wide)
  run_iam_cmd gcloud iam service-accounts add-iam-policy-binding "${RUNTIME_SA_EMAIL}" \
    --project="${PROJECT_ID}" \
    --member="serviceAccount:${CICD_SA_EMAIL}" \
    --role="roles/iam.serviceAccountUser" \
    --format=none \
    --quiet

  # Allow CI/CD SA to mint short-lived OIDC ID tokens for post-deploy smoke checks
  run_iam_cmd gcloud iam service-accounts add-iam-policy-binding "${CICD_SA_EMAIL}" \
    --project="${PROJECT_ID}" \
    --member="serviceAccount:${CICD_SA_EMAIL}" \
    --role="roles/iam.serviceAccountTokenCreator" \
    --format=none \
    --quiet

  if [[ "${DRY_RUN}" == "true" ]]; then
    run_cmd gcloud iam workload-identity-pools create "${WIF_POOL_ID}" \
      --project="${PROJECT_ID}" \
      --location="global" \
      --display-name="Brew GitHub Actions Pool"
    run_cmd gcloud iam workload-identity-pools providers create-oidc "${WIF_PROVIDER_ID}" \
      --project="${PROJECT_ID}" \
      --location="global" \
      --workload-identity-pool="${WIF_POOL_ID}" \
      --display-name="Brew GitHub OIDC Provider" \
      --issuer-uri="https://token.actions.githubusercontent.com" \
      --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
      --attribute-condition="assertion.repository == '${GITHUB_REPO}'"
  else
    if ! gcloud iam workload-identity-pools describe "${WIF_POOL_ID}" \
      --project="${PROJECT_ID}" --location="global" >/dev/null 2>&1; then
      gcloud iam workload-identity-pools create "${WIF_POOL_ID}" \
        --project="${PROJECT_ID}" \
        --location="global" \
        --display-name="Brew GitHub Actions Pool"
    fi
    if ! gcloud iam workload-identity-pools providers describe "${WIF_PROVIDER_ID}" \
      --project="${PROJECT_ID}" --location="global" \
      --workload-identity-pool="${WIF_POOL_ID}" >/dev/null 2>&1; then
      gcloud iam workload-identity-pools providers create-oidc "${WIF_PROVIDER_ID}" \
        --project="${PROJECT_ID}" \
        --location="global" \
        --workload-identity-pool="${WIF_POOL_ID}" \
        --display-name="Brew GitHub OIDC Provider" \
        --issuer-uri="https://token.actions.githubusercontent.com" \
        --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
        --attribute-condition="assertion.repository == '${GITHUB_REPO}'"
    fi
  fi

  WIF_PRINCIPAL="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL_ID}/attribute.repository/${GITHUB_REPO}"
  run_iam_cmd gcloud iam service-accounts add-iam-policy-binding "${CICD_SA_EMAIL}" \
    --project="${PROJECT_ID}" \
    --member="${WIF_PRINCIPAL}" \
    --role="roles/iam.workloadIdentityUser" \
    --format=none \
    --quiet
else
  log_step "Phase 4: Skipping GitHub WIF bootstrap (set GITHUB_REPO=owner/repo to enable)"
fi

# ------------------------------------------------------------------------------
# Phase 5: Artifact Registry Container Repository & Retention Policy
# ------------------------------------------------------------------------------
log_step "Phase 5: Configuring Artifact Registry repository (${AR_REPO} in ${REGION})"

if [[ "${DRY_RUN}" == "true" ]]; then
  run_cmd gcloud artifacts repositories create "${AR_REPO}" \
    --project="${PROJECT_ID}" \
    --location="${REGION}" \
    --repository-format=docker \
    --description="Brew Cloud Run container images"
else
  if ! gcloud artifacts repositories describe "${AR_REPO}" \
    --project="${PROJECT_ID}" --location="${REGION}" >/dev/null 2>&1; then
    gcloud artifacts repositories create "${AR_REPO}" \
      --project="${PROJECT_ID}" \
      --location="${REGION}" \
      --repository-format=docker \
      --description="Brew Cloud Run container images"
  fi
fi

# Grant Cloud Run serverless robot reader access strictly on this repository
run_iam_cmd gcloud artifacts repositories add-iam-policy-binding "${AR_REPO}" \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  --member="serviceAccount:service-${PROJECT_NUMBER}@serverless-robot-prod.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.reader" \
  --format=none \
  --quiet

# Keep only the 10 newest container versions so stale images do not accrue storage cost
CLEANUP_POLICY_JSON='[{"name":"keep-recent-10","action":{"type":"Keep"},"mostRecentVersions":{"keepCount":10}}]'
if [[ "${DRY_RUN}" == "true" ]]; then
  echo "[dry-run] gcloud artifacts repositories set-cleanup-policies ${AR_REPO} (keep-recent-10)"
else
  tmp_policy="$(mktemp)"
  printf '%s\n' "${CLEANUP_POLICY_JSON}" >"${tmp_policy}"
  gcloud artifacts repositories set-cleanup-policies "${AR_REPO}" \
    --project="${PROJECT_ID}" \
    --location="${REGION}" \
    --policy="${tmp_policy}" \
    --no-dry-run \
    --quiet >/dev/null || true
  rm -f "${tmp_policy}"
fi

# ------------------------------------------------------------------------------
# Phase 6: Secret Manager Containers & Secret-Scoped Runtime Access
# ------------------------------------------------------------------------------
log_step "Phase 6: Configuring Secret Manager secrets and least-privilege bindings"

# MANUAL STEPS FOR BROWSER AUTHENTICATION:
#   Option A — Private Cloud Run + Identity-Aware Proxy (Recommended Default for Browser UI):
#     1. In Google Cloud Console -> APIs & Services -> OAuth consent screen, configure
#        an Internal (Workspace) or External consent screen once per project.
#     2. Deploy with ENABLE_IAP=true (below) and grant authorized users/groups
#        `roles/iap.httpsResourceAccessor` via IAP_ACCESSOR_MEMBERS or Cloud Console.
#
#   Option B — Verified Google OAuth / Firebase Sign-In inside the React SPA:
#     1. In Google Cloud Console -> APIs & Services -> Credentials, create an OAuth 2.0
#        Web Client ID and add your Cloud Run URL (`https://brew-<PROJECT_NUMBER>.<REGION>.run.app`)
#        under "Authorized JavaScript origins".
#     2. Pass GOOGLE_OAUTH_CLIENT_ID_VALUE (and optional FIREBASE_WEB_API_KEY_VALUE)
#        when running this script, or add versions directly in Secret Manager:
#          printf '%s' "$CLIENT_ID" | gcloud secrets versions add brew-google-oauth-client-id --data-file=-

SECRET_BINDINGS=()

ensure_secret_if_populated() {
  local secret_id="$1"
  local env_var_name="$2"
  local secret_value="${3:-}"

  if [[ "${DRY_RUN}" == "true" ]]; then
    if [[ -n "${secret_value}" ]]; then
      run_cmd gcloud secrets create "${secret_id}" \
        --project="${PROJECT_ID}" \
        --replication-policy="automatic"
      echo "[dry-run] gcloud secrets versions add ${secret_id} --project=${PROJECT_ID} --data-file=- (value redacted)"
      run_cmd gcloud secrets add-iam-policy-binding "${secret_id}" \
        --project="${PROJECT_ID}" \
        --member="serviceAccount:${RUNTIME_SA_EMAIL}" \
        --role="roles/secretmanager.secretAccessor"
      SECRET_BINDINGS+=("${env_var_name}=${secret_id}:latest")
    fi
    return 0
  fi

  if [[ -n "${secret_value}" ]]; then
    if ! gcloud secrets describe "${secret_id}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
      gcloud secrets create "${secret_id}" \
        --project="${PROJECT_ID}" \
        --replication-policy="automatic" >/dev/null
    fi
    printf '%s' "${secret_value}" | gcloud secrets versions add "${secret_id}" \
      --project="${PROJECT_ID}" \
      --data-file=- >/dev/null
  fi

  if gcloud secrets describe "${secret_id}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    local latest_ver
    latest_ver="$(gcloud secrets versions list "${secret_id}" \
      --project="${PROJECT_ID}" \
      --filter='state=ENABLED' \
      --limit=1 \
      --format='value(name)' 2>/dev/null || true)"
    if [[ -n "${latest_ver}" ]]; then
      run_iam_cmd gcloud secrets add-iam-policy-binding "${secret_id}" \
        --project="${PROJECT_ID}" \
        --member="serviceAccount:${RUNTIME_SA_EMAIL}" \
        --role="roles/secretmanager.secretAccessor" \
        --format=none \
        --quiet
      SECRET_BINDINGS+=("${env_var_name}=${secret_id}:latest")
    fi
  fi
}

ensure_secret_if_populated \
  "${SECRET_GOOGLE_OAUTH_CLIENT_ID}" \
  "GOOGLE_OAUTH_CLIENT_ID" \
  "${GOOGLE_OAUTH_CLIENT_ID_VALUE:-}"

ensure_secret_if_populated \
  "${SECRET_FIREBASE_WEB_API_KEY}" \
  "FIREBASE_WEB_API_KEY" \
  "${FIREBASE_WEB_API_KEY_VALUE:-}"

if [[ "${INFRA_ONLY}" == "true" ]]; then
  log_step "Infrastructure setup complete (--infra-only specified; skipping container build & deploy)."
  if [[ -n "${GITHUB_REPO}" ]]; then
    echo "GitHub Actions WIF Provider: projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL_ID}/providers/${WIF_PROVIDER_ID}"
    echo "GitHub Actions CI/CD SA    : ${CICD_SA_EMAIL}"
  fi
  exit 0
fi

# ------------------------------------------------------------------------------
# Guardrail: Refuse Public Cloud Run Ingress Without Configured User Auth
# ------------------------------------------------------------------------------
if [[ "${ALLOW_PUBLIC_INGRESS}" == "true" && ${#SECRET_BINDINGS[@]} -eq 0 ]]; then
  echo "ERROR: Refusing ALLOW_PUBLIC_INGRESS=true without GOOGLE_OAUTH_CLIENT_ID or FIREBASE_WEB_API_KEY." >&2
  echo "       Keep the service private (--no-allow-unauthenticated / ENABLE_IAP=true) or configure" >&2
  echo "       verified browser identity secrets first." >&2
  exit 1
fi

# ------------------------------------------------------------------------------
# Phase 7: Reproducible Container Build & Agents CLI Cloud Run Deployment
# ------------------------------------------------------------------------------
log_step "Phase 7: Building reproducible container image and deploying via Agents CLI"

if command -v git >/dev/null 2>&1 && git rev-parse --short=12 HEAD >/dev/null 2>&1; then
  DEFAULT_TAG="$(git rev-parse --short=12 HEAD)"
else
  DEFAULT_TAG="manual-$(date -u +%Y%m%d%H%M%S)"
fi
IMAGE_TAG="${IMAGE_TAG:-${DEFAULT_TAG}}"
IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${SERVICE_NAME}:${IMAGE_TAG}"

if [[ "${BUILD_MODE}" == "docker" ]]; then
  run_cmd gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
  run_cmd docker build \
    --build-arg "AGENT_VERSION=${IMAGE_TAG}" \
    --tag "${IMAGE_URI}" \
    .
  run_cmd docker push "${IMAGE_URI}"
else
  # Default Cloud Build uses the dedicated brew-builder SA and regional staging bucket
  # so it never depends on the legacy Compute Engine default service account.
  if [[ "${DRY_RUN}" == "true" ]]; then
    run_cmd gcloud beta builds submit \
      --project="${PROJECT_ID}" \
      --region="${REGION}" \
      --service-account="projects/${PROJECT_ID}/serviceAccounts/${BUILDER_SA_EMAIL}" \
      --default-buckets-behavior=regional-user-owned-bucket \
      --tag "${IMAGE_URI}" \
      .
  else
    tmp_cb_config="$(mktemp --suffix=.yaml)"
    TMP_FILES_TO_CLEAN+=("${tmp_cb_config}")
    cat >"${tmp_cb_config}" <<CBEOF
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args:
      - 'build'
      - '--build-arg'
      - 'AGENT_VERSION=${IMAGE_TAG}'
      - '--tag'
      - '${IMAGE_URI}'
      - '.'
images:
  - '${IMAGE_URI}'
options:
  logging: CLOUD_LOGGING_ONLY
CBEOF
    # `gcloud beta builds submit` streams CLOUD_LOGGING_ONLY step logs live to the terminal
    gcloud beta builds submit \
      --project="${PROJECT_ID}" \
      --region="${REGION}" \
      --service-account="projects/${PROJECT_ID}/serviceAccounts/${BUILDER_SA_EMAIL}" \
      --default-buckets-behavior=regional-user-owned-bucket \
      --config="${tmp_cb_config}" \
      .
    rm -f "${tmp_cb_config}"
  fi
fi

EXPECTED_APP_URL="https://${SERVICE_NAME}-${PROJECT_NUMBER}.${REGION}.run.app"
IAP_AUDIENCE="/projects/${PROJECT_NUMBER}/locations/${REGION}/services/${SERVICE_NAME}"

RUNTIME_ENV_VARS=(
  "APP_NAME=${SERVICE_NAME}"
  "APP_ENV=production"
  "AGENT_VERSION=${IMAGE_TAG}"
  "APP_URL=${EXPECTED_APP_URL}"
  "ALLOW_ORIGINS=${EXPECTED_APP_URL}"
  "GOOGLE_CLOUD_PROJECT=${PROJECT_ID}"
  "GOOGLE_CLOUD_LOCATION=${GOOGLE_CLOUD_LOCATION}"
  "GOOGLE_GENAI_USE_ENTERPRISE=true"
  "GEMINI_MODEL=${GEMINI_MODEL}"
  "BREW_SYNTHESIS_MODEL=${BREW_SYNTHESIS_MODEL}"
  "BREW_PERSISTENCE_BACKEND=firestore"
  "FIRESTORE_DATABASE=${FIRESTORE_DATABASE}"
  "BREW_SESSION_BACKEND=firestore"
  "ADK_FIRESTORE_ROOT_COLLECTION=adk-session"
  "BREW_AUTH_MODE=verified"
  "OTEL_SERVICE_NAME=${SERVICE_NAME}"
  "OTEL_TO_CLOUD=true"
  "BREW_CLOUD_TRACE_ENABLED=true"
  "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=NO_CONTENT"
  "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false"
  "BREW_TELEMETRY_CAPTURE_CONTENT=false"
  "BREW_TELEMETRY_UPLOAD_COMPLETIONS=false"
)
if [[ "${ENABLE_IAP}" == "true" ]]; then
  RUNTIME_ENV_VARS+=("BREW_IAP_JWT_AUDIENCE=${IAP_AUDIENCE}")
fi

IFS=',' eval 'ENV_VARS_CSV="${RUNTIME_ENV_VARS[*]}"'

DEPLOY_CMD=(
  "${AGENTS_CLI_BIN[@]}" deploy
  --project "${PROJECT_ID}"
  --region "${REGION}"
  --service-name "${SERVICE_NAME}"
  --service-account "${RUNTIME_SA_EMAIL}"
  --no-agent-identity
  --image "${IMAGE_URI}"
  --port 8080
  --cpu "${CLOUD_RUN_CPU}"
  --memory "${CLOUD_RUN_MEMORY}"
  --concurrency "${CLOUD_RUN_CONCURRENCY}"
  --min-instances "${CLOUD_RUN_MIN_INSTANCES}"
  --max-instances "${CLOUD_RUN_MAX_INSTANCES}"
  --timeout "${CLOUD_RUN_TIMEOUT}"
  --clear-env-vars
  --update-env-vars "${ENV_VARS_CSV}"
  --no-confirm-project
)
if [[ ${#SECRET_BINDINGS[@]} -gt 0 ]]; then
  IFS=',' eval 'SECRETS_CSV="${SECRET_BINDINGS[*]}"'
  DEPLOY_CMD+=(--update-secrets "${SECRETS_CSV}")
fi
if [[ "${ENABLE_IAP}" == "true" ]]; then
  DEPLOY_CMD+=(--iap)
fi

# If switching an existing service away from public ingress (e.g. Public -> IAP),
# remove anonymous invoker bindings before `agents-cli deploy --iap` runs.
if [[ "${ALLOW_PUBLIC_INGRESS}" != "true" && "${DRY_RUN}" != "true" ]]; then
  gcloud run services remove-iam-policy-binding "${SERVICE_NAME}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --member="allUsers" \
    --role="roles/run.invoker" \
    --quiet >/dev/null 2>&1 || true
  gcloud run services remove-iam-policy-binding "${SERVICE_NAME}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --member="allAuthenticatedUsers" \
    --role="roles/run.invoker" \
    --quiet >/dev/null 2>&1 || true
fi

# Run `agents-cli deploy` from a clean directory containing ONLY `agents-cli-manifest.yaml`
# so local developer `.env` keys (such as reserved `PORT=8000`, `APP_ENV=local`, or a local
# `GOOGLE_OAUTH_CLIENT_ID` that would collide with `--update-secrets`) are never merged in.
if [[ "${DRY_RUN}" == "true" ]]; then
  run_cmd "${DEPLOY_CMD[@]}"
else
  SCRIPT_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  clean_deploy_dir="$(mktemp -d)"
  TMP_FILES_TO_CLEAN+=("${clean_deploy_dir}")
  cp "${SCRIPT_REPO_ROOT}/agents-cli-manifest.yaml" "${clean_deploy_dir}/agents-cli-manifest.yaml"
  (
    cd "${clean_deploy_dir}"
    "${DEPLOY_CMD[@]}"
  )
  rm -rf "${clean_deploy_dir}"
fi

# ------------------------------------------------------------------------------
# Phase 8: Health/Readiness Probes, Private Access Enforcement, & Smoke Check
# ------------------------------------------------------------------------------
log_step "Phase 8: Configuring Cloud Run startup/readiness/liveness probes and verifying security"

CPU_THROTTLING_FLAG="--no-cpu-throttling"
if [[ "${CLOUD_RUN_MIN_INSTANCES}" == "0" ]]; then
  # Enable request-based CPU billing when min-instances=0 for smallest billable footprint
  CPU_THROTTLING_FLAG="--cpu-throttling"
fi

IAP_UPDATE_FLAG="--no-iap"
if [[ "${ENABLE_IAP}" == "true" ]]; then
  IAP_UPDATE_FLAG="--iap"
fi

run_cmd gcloud run services update "${SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  "${CPU_THROTTLING_FLAG}" \
  "${IAP_UPDATE_FLAG}" \
  --startup-probe="httpGet.path=/readyz,httpGet.port=8080,initialDelaySeconds=2,periodSeconds=5,timeoutSeconds=4,failureThreshold=6" \
  --readiness-probe="httpGet.path=/readyz,httpGet.port=8080,periodSeconds=10,timeoutSeconds=4,failureThreshold=3,successThreshold=1" \
  --liveness-probe="httpGet.path=/healthz,httpGet.port=8080,initialDelaySeconds=15,periodSeconds=30,timeoutSeconds=5,failureThreshold=3" \
  --quiet

if [[ "${ALLOW_PUBLIC_INGRESS}" != "true" ]]; then
  # Enforce private-by-default Cloud Run IAM (remove anonymous bindings if any existed)
  if [[ "${DRY_RUN}" == "true" ]]; then
    echo "[dry-run] Ensure allUsers / allAuthenticatedUsers do not hold roles/run.invoker on ${SERVICE_NAME}"
  else
    gcloud run services remove-iam-policy-binding "${SERVICE_NAME}" \
      --project="${PROJECT_ID}" \
      --region="${REGION}" \
      --member="allUsers" \
      --role="roles/run.invoker" \
      --quiet >/dev/null 2>&1 || true
    gcloud run services remove-iam-policy-binding "${SERVICE_NAME}" \
      --project="${PROJECT_ID}" \
      --region="${REGION}" \
      --member="allAuthenticatedUsers" \
      --role="roles/run.invoker" \
      --quiet >/dev/null 2>&1 || true
  fi
fi

if [[ "${ENABLE_IAP}" == "true" ]]; then
  # Grant the Google-managed IAP service agent permission to invoke the private Cloud Run service
  IAP_SA="service-${PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com"
  run_iam_cmd gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --member="serviceAccount:${IAP_SA}" \
    --role="roles/run.invoker" \
    --format=none \
    --quiet

  if [[ -n "${IAP_ACCESSOR_MEMBERS}" ]]; then
    IFS=',' read -r -a IAP_MEMBERS_ARRAY <<<"${IAP_ACCESSOR_MEMBERS}"
    for member in "${IAP_MEMBERS_ARRAY[@]}"; do
      trimmed_member="$(echo "${member}" | xargs)"
      if [[ -n "${trimmed_member}" ]]; then
        run_iam_cmd gcloud beta iap web add-iam-policy-binding \
          --project="${PROJECT_ID}" \
          --resource-type=cloud-run \
          --service="${SERVICE_NAME}" \
          --region="${REGION}" \
          --member="${trimmed_member}" \
          --role="roles/iap.httpsResourceAccessor" \
          --format=none \
          --quiet
      fi
    done
  fi
fi

if [[ "${DRY_RUN}" == "true" ]]; then
  log_step "Dry run completed successfully."
  exit 0
fi

SERVICE_URL="$(gcloud run services describe "${SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --format='value(status.url)')"
SERVICE_JSON="$(gcloud run services describe "${SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --format=json)"
ALL_ORIGINS_CSV="$(
  SERVICE_JSON_PAYLOAD="${SERVICE_JSON}" \
  FALLBACK_URL="${EXPECTED_APP_URL}" \
  python3 -c '
import json, os

raw = json.loads(os.environ["SERVICE_JSON_PAYLOAD"])
urls = []

def add(u: str) -> None:
    cleaned = u.strip().rstrip("/")
    if cleaned.startswith("https://") and cleaned not in urls:
        urls.append(cleaned)

add(os.environ["FALLBACK_URL"])
status_url = (raw.get("status") or {}).get("url") or ""
if isinstance(status_url, str):
    add(status_url)

annotations = ((raw.get("metadata") or {}).get("annotations") or {})
raw_urls = annotations.get("run.googleapis.com/urls") or ""
if isinstance(raw_urls, str) and raw_urls.strip():
    try:
        parsed = json.loads(raw_urls)
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, str):
                    add(item)
    except json.JSONDecodeError:
        pass

print(",".join(urls))
'
)"

gcloud run services update "${SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --update-env-vars="^@^APP_URL=${SERVICE_URL}@ALLOW_ORIGINS=${ALL_ORIGINS_CSV}" \
  --quiet >/dev/null
LATEST_REVISION="$(gcloud run services describe "${SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --format='value(status.latestReadyRevisionName)')"

# Verify unauthenticated memory writes are ALWAYS rejected before/after any ingress change
# (401/403 from FastAPI/Cloud Run IAM, or 302 redirect to Google login when IAP is enabled)
UNAUTH_MEM_STATUS="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  -X POST "${SERVICE_URL}/api/v1/memories/propose" \
  -H 'Content-Type: application/json' \
  -d '{"notes":"unauthenticated probe"}')"
UNAUTH_ADK_MEM_STATUS="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  -X PATCH "${SERVICE_URL}/apps/app/users/probe/memory" \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"s1"}')"

if [[ "${UNAUTH_MEM_STATUS}" != "401" && "${UNAUTH_MEM_STATUS}" != "403" && "${UNAUTH_MEM_STATUS}" != "302" ]]; then
  echo "ERROR: Unauthenticated POST /api/v1/memories/propose returned HTTP ${UNAUTH_MEM_STATUS}!" >&2
  exit 1
fi
if [[ "${UNAUTH_ADK_MEM_STATUS}" != "401" && "${UNAUTH_ADK_MEM_STATUS}" != "403" && "${UNAUTH_ADK_MEM_STATUS}" != "302" ]]; then
  echo "ERROR: Unauthenticated PATCH /apps/app/users/probe/memory returned HTTP ${UNAUTH_ADK_MEM_STATUS}!" >&2
  exit 1
fi

if [[ "${ALLOW_PUBLIC_INGRESS}" == "true" ]]; then
  echo "Verified private API & writable memory routes enforce authentication; enabling public Cloud Run URL for SPA."
  run_iam_cmd gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --member="allUsers" \
    --role="roles/run.invoker" \
    --format=none \
    --quiet
fi

# Authenticated liveness & readiness smoke verification
if [[ "${ENABLE_IAP}" == "true" ]]; then
  # With Cloud Run IAP enabled, Cloud Run's own startup/readiness probes have already verified
  # /readyz on ${LATEST_REVISION}, while external curl requests without a browser IAP cookie
  # receive an IAP 302/401 gate.
  IAP_GATE_STATUS="$(curl --silent --output /dev/null --write-out '%{http_code}' "${SERVICE_URL}/healthz")"
  echo "Verified Cloud Run revision ${LATEST_REVISION} is Ready and IAP edge gate returned HTTP ${IAP_GATE_STATUS}."
else
  ID_TOKEN="$(gcloud auth print-identity-token)"
  curl --fail --silent --show-error \
    -H "Authorization: Bearer ${ID_TOKEN}" \
    "${SERVICE_URL}/healthz" >/dev/null
  curl --fail --silent --show-error \
    -H "Authorization: Bearer ${ID_TOKEN}" \
    "${SERVICE_URL}/readyz" >/dev/null
fi

echo ""
echo "=============================================================================="
echo "Brew Cloud Run Deployment Complete"
echo "  Project ID     : ${PROJECT_ID}"
echo "  Region         : ${REGION}"
echo "  Service URL    : ${SERVICE_URL}"
echo "  Ready Revision : ${LATEST_REVISION}"
echo "  Image          : ${IMAGE_URI}"
echo "  Access Mode    : $([[ "${ALLOW_PUBLIC_INGRESS}" == "true" ]] && echo "Public SPA + Verified API Auth" || ([[ "${ENABLE_IAP}" == "true" ]] && echo "Private Cloud Run + IAP" || echo "Private Cloud Run (IAM Invoker)"))"
echo "=============================================================================="
