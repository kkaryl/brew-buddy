#!/usr/bin/env bash
# ==============================================================================
# Brew — Cloud Run Custom IAP OAuth & Dual-Account Login Setup (`iap_setup.sh`)
# ==============================================================================
# Guides and automates the two-client Cloud Run IAP setup so you can:
#   1. Pass the Cloud Run IAP edge gate using your GCP organization domain email
#      (e.g. `you@your-gcp-domain.com`), bypassing Google's blocked default
#      internal IAP client (`ServiceNotAllowed`) and respecting Organization
#      Policy `constraints/iam.allowedPolicyMemberDomains`.
#   2. Sign into the Brew React web app itself using a separate account (such as
#      `xx@gmail.com`) via `brew-web-spa` (`GOOGLE_OAUTH_CLIENT_ID`), without
#      IAP stripping Brew's `Authorization: Bearer` header.
#
# Why Step 2 combines guided Console prompts + automated CLI checks:
#   Google Cloud retired `gcloud iap oauth-clients` on March 19, 2026 and does
#   not expose a public API/CLI to create `*.apps.googleusercontent.com` Web
#   Clients or edit Authorized JavaScript Origins / Redirect URIs. This script
#   discovers your exact Cloud Run URLs and Secret Manager Client ID, prints
#   exact copy-paste values (including the substituted `:handleRedirect` URI),
#   and automates all IAP settings, Cloud Run CORS/IAP flags, IAM bindings, and
#   live redirect verification.
#
# Usage (interactive — prompts for missing values and hides client secret):
#   ./iap_setup.sh
#
# Usage (non-interactive):
#   PROJECT_ID="your-gcp-project-id" \
#   REGION="asia-southeast1" \
#   IAP_USER_EMAIL="you@your-gcp-domain.com" \
#   IAP_CLIENT_ID="123456789-iap.apps.googleusercontent.com" \
#   IAP_CLIENT_SECRET="GOCSPX-..." \
#   ./iap_setup.sh --yes
#
# Preview without mutating GCP resources:
#   PROJECT_ID="your-gcp-project-id" \
#   IAP_USER_EMAIL="you@your-gcp-domain.com" \
#   IAP_CLIENT_ID="123456789-iap.apps.googleusercontent.com" \
#   IAP_CLIENT_SECRET="GOCSPX-dryrun" \
#   ./iap_setup.sh --dry-run
# ==============================================================================

set -euo pipefail

export GOOGLE_API_USE_CLIENT_CERTIFICATE="${GOOGLE_API_USE_CLIENT_CERTIFICATE:-false}"

DRY_RUN="false"
ASSUME_YES="false"

PROJECT_ID="${PROJECT_ID:-}"
REGION="${REGION:-asia-southeast1}"
SERVICE_NAME="${SERVICE_NAME:-brew}"
IAP_USER_EMAIL="${IAP_USER_EMAIL:-}"
IAP_CLIENT_ID="${IAP_CLIENT_ID:-}"
IAP_CLIENT_SECRET="${IAP_CLIENT_SECRET:-}"
WEB_SPA_CLIENT_ID="${WEB_SPA_CLIENT_ID:-}"
GOOGLE_OAUTH_SECRET_NAME="${GOOGLE_OAUTH_SECRET_NAME:-brew-google-oauth-client-id}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN="true"
      shift
      ;;
    --yes|-y)
      ASSUME_YES="true"
      shift
      ;;
    --project)
      PROJECT_ID="${2:-}"
      shift 2
      ;;
    --region)
      REGION="${2:-}"
      shift 2
      ;;
    --service)
      SERVICE_NAME="${2:-}"
      shift 2
      ;;
    --iap-user)
      IAP_USER_EMAIL="${2:-}"
      shift 2
      ;;
    --iap-client-id)
      IAP_CLIENT_ID="${2:-}"
      shift 2
      ;;
    --iap-client-secret)
      IAP_CLIENT_SECRET="${2:-}"
      shift 2
      ;;
    --web-client-id)
      WEB_SPA_CLIENT_ID="${2:-}"
      shift 2
      ;;
    -h|--help)
      sed -n '2,41p' "$0"
      exit 0
      ;;
    *)
      echo "ERROR: Unknown argument: $1 (run ./iap_setup.sh --help for usage)" >&2
      exit 2
      ;;
  esac
done

# Never permit static service account JSON keys (AGENTS.md §3.3)
if [[ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" ]]; then
  echo "ERROR: GOOGLE_APPLICATION_CREDENTIALS is set. Unset it and use gcloud user/ADC auth only." >&2
  exit 1
fi

TMP_FILES_TO_CLEAN=()
cleanup() {
  for f in "${TMP_FILES_TO_CLEAN[@]:-}"; do
    if [[ -n "${f}" && -e "${f}" ]]; then
      rm -rf "${f}"
    fi
  done
  return 0
}
trap cleanup EXIT INT TERM

log_step() {
  printf '\n==> %s\n' "$1"
}

run_cmd() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    printf '[dry-run]'
    printf ' %q' "$@"
    printf '\n'
    return 0
  fi
  "$@"
}

run_iam_cmd() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    run_cmd "$@"
    return 0
  fi

  local max_attempts=8
  local delay_seconds=3
  local attempt=1
  local output=""

  while (( attempt <= max_attempts )); do
    if output="$("$@" 2>&1)"; then
      [[ -n "${output}" ]] && printf '%s\n' "${output}"
      return 0
    fi

    if grep -Eqi "does not exist|not found|not_found|concurrent policy changes|aborted|409" <<<"${output}" \
      && (( attempt < max_attempts )); then
      echo "Waiting ${delay_seconds}s for IAM propagation (attempt ${attempt}/${max_attempts})..." >&2
      sleep "${delay_seconds}"
      attempt=$(( attempt + 1 ))
      delay_seconds=$(( delay_seconds * 2 ))
      if (( delay_seconds > 20 )); then
        delay_seconds=20
      fi
      continue
    fi

    printf '%s\n' "${output}" >&2
    return 1
  done
}

validate_iap_domain_email() {
  local email
  email="$(echo "$1" | xargs)"
  local lowered
  lowered="$(printf '%s' "${email}" | tr '[:upper:]' '[:lower:]')"

  if [[ -z "${lowered}" ]]; then
    echo "ERROR: IAP_USER_EMAIL cannot be empty." >&2
    return 1
  fi
  if [[ "${lowered}" == "allusers" || "${lowered}" == "allauthenticatedusers" ]]; then
    echo "ERROR: '${email}' is blocked by Domain-Restricted Sharing (iam.allowedPolicyMemberDomains)." >&2
    echo "Pass your GCP organization domain email (e.g. you@your-gcp-domain.com) instead." >&2
    return 1
  fi
  if [[ "${lowered}" != *@*.* ]]; then
    echo "ERROR: '${email}' is not a valid email address." >&2
    return 1
  fi
  if [[ "${lowered}" == *@gmail.com || "${lowered}" == *@googlemail.com ]]; then
    echo "ERROR: Do NOT pass '${email}' to IAP IAM (--iap-user / IAP_USER_EMAIL)." >&2
    echo "Organization Policy (iam.allowedPolicyMemberDomains) rejects @gmail.com in IAM bindings." >&2
    echo "Use your GCP domain email for IAP edge access, then sign in with ${email} inside Brew's web UI." >&2
    return 1
  fi
  return 0
}

# ------------------------------------------------------------------------------
# Step 1: Discover Project Number, Active Cloud Run URLs, & Brew SPA Client ID
# ------------------------------------------------------------------------------
log_step "Step 1: Discovering project metadata, Cloud Run URLs, and Secret Manager config"

if ! command -v gcloud >/dev/null 2>&1; then
  echo "ERROR: gcloud CLI is required." >&2
  exit 1
fi

if [[ -z "${PROJECT_ID}" && "${DRY_RUN}" != "true" ]]; then
  PROJECT_ID="$(gcloud config get-value project 2>/dev/null | tr -d '[:space:]' || true)"
  [[ "${PROJECT_ID}" == "(unset)" ]] && PROJECT_ID=""
fi

if [[ -z "${PROJECT_ID}" ]]; then
  if [[ "${ASSUME_YES}" == "true" || "${DRY_RUN}" == "true" ]]; then
    echo "ERROR: PROJECT_ID is required (pass PROJECT_ID=... or --project <id>)." >&2
    exit 1
  fi
  read -r -p "Enter GCP Project ID: " input_project
  PROJECT_ID="${input_project}"
  if [[ -z "${PROJECT_ID}" ]]; then
    echo "ERROR: PROJECT_ID is required." >&2
    exit 1
  fi
fi

ACTIVE_GCLOUD_ACCOUNT=""
if [[ "${DRY_RUN}" == "true" ]]; then
  PROJECT_NUMBER="000000000000"
  DISCOVERED_URLS=("https://${SERVICE_NAME}-${PROJECT_NUMBER}.${REGION}.run.app")
  EXISTING_SPA_CLIENT_ID="${WEB_SPA_CLIENT_ID:-999999999-spa.apps.googleusercontent.com}"
else
  ACTIVE_GCLOUD_ACCOUNT="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -n1 | tr -d '[:space:]' || true)"
  if [[ -z "${ACTIVE_GCLOUD_ACCOUNT}" ]]; then
    echo "ERROR: No active gcloud login found. Run: gcloud auth login" >&2
    exit 1
  fi

  PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"

  SERVICE_JSON="$(gcloud run services describe "${SERVICE_NAME}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --format=json)"

  mapfile -t DISCOVERED_URLS < <(
    SERVICE_JSON_PAYLOAD="${SERVICE_JSON}" \
    FALLBACK_URL="https://${SERVICE_NAME}-${PROJECT_NUMBER}.${REGION}.run.app" \
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

for item in urls:
    print(item)
'
  )

  EXISTING_SPA_CLIENT_ID="$(gcloud secrets versions access latest \
    --secret="${GOOGLE_OAUTH_SECRET_NAME}" \
    --project="${PROJECT_ID}" 2>/dev/null | tr -d '[:space:]' || true)"
fi

if [[ -z "${IAP_USER_EMAIL}" ]]; then
  if [[ -n "${ACTIVE_GCLOUD_ACCOUNT}" ]]; then
    if [[ "${ASSUME_YES}" == "true" ]]; then
      IAP_USER_EMAIL="${ACTIVE_GCLOUD_ACCOUNT}"
    else
      read -r -p "GCP domain email for IAP edge login [${ACTIVE_GCLOUD_ACCOUNT}]: " input_iap_user
      IAP_USER_EMAIL="${input_iap_user:-${ACTIVE_GCLOUD_ACCOUNT}}"
    fi
  elif [[ "${ASSUME_YES}" != "true" && "${DRY_RUN}" != "true" ]]; then
    read -r -p "GCP domain email for IAP edge login (NOT @gmail.com): " IAP_USER_EMAIL
  else
    echo "ERROR: IAP_USER_EMAIL is required (pass IAP_USER_EMAIL=you@your-gcp-domain.com)." >&2
    exit 1
  fi
fi

validate_iap_domain_email "${IAP_USER_EMAIL}"

echo "  Project ID          : ${PROJECT_ID} (number: ${PROJECT_NUMBER})"
echo "  Region / Service    : ${REGION} / ${SERVICE_NAME}"
echo "  IAP Edge User       : ${IAP_USER_EMAIL}"
echo "  Brew SPA Secret     : ${GOOGLE_OAUTH_SECRET_NAME} -> ${EXISTING_SPA_CLIENT_ID:-<not found in Secret Manager>}"
echo "  Cloud Run URLs      :"
for u in "${DISCOVERED_URLS[@]}"; do
  echo "    - ${u}"
done

# ------------------------------------------------------------------------------
# Step 2: Configure Client B (`brew-web-spa`) & Client A (`brew-iap-edge`)
# ------------------------------------------------------------------------------
log_step "Step 2: Preparing OAuth 2.0 Web Clients (brew-web-spa & brew-iap-edge)"

echo "Open these two pages in Google Cloud Console (${PROJECT_ID}):"
echo "  1. Audience (External + Test Users): https://console.cloud.google.com/auth/audience?project=${PROJECT_ID}"
echo "     -> Confirm User Type = External (Testing) and BOTH '${IAP_USER_EMAIL}' and your '@gmail.com' are in Test users."
echo "  2. OAuth Clients (Credentials)     : https://console.cloud.google.com/auth/clients?project=${PROJECT_ID}"
echo "     (Classic view: https://console.cloud.google.com/apis/credentials?project=${PROJECT_ID})"
echo ""
echo "------------------------------------------------------------------------------"
echo "Client B — brew-web-spa (for signing into Brew UI with your @gmail.com account)"
echo "------------------------------------------------------------------------------"
if [[ -n "${WEB_SPA_CLIENT_ID}" && "${WEB_SPA_CLIENT_ID}" != "${EXISTING_SPA_CLIENT_ID}" ]]; then
  echo "Updating Secret Manager '${GOOGLE_OAUTH_SECRET_NAME}' with new Client B ID: ${WEB_SPA_CLIENT_ID}"
  if [[ "${DRY_RUN}" == "true" ]]; then
    echo "[dry-run] Add secret version to ${GOOGLE_OAUTH_SECRET_NAME} (${WEB_SPA_CLIENT_ID})"
  else
    if ! gcloud secrets describe "${GOOGLE_OAUTH_SECRET_NAME}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
      gcloud secrets create "${GOOGLE_OAUTH_SECRET_NAME}" \
        --project="${PROJECT_ID}" \
        --replication-policy="user-managed" \
        --locations="${REGION}" \
        --quiet
    fi
    printf '%s' "${WEB_SPA_CLIENT_ID}" | gcloud secrets versions add "${GOOGLE_OAUTH_SECRET_NAME}" \
      --project="${PROJECT_ID}" \
      --data-file=- \
      --quiet >/dev/null
    RUNTIME_SA_EMAIL="brew-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
    run_iam_cmd gcloud secrets add-iam-policy-binding "${GOOGLE_OAUTH_SECRET_NAME}" \
      --project="${PROJECT_ID}" \
      --member="serviceAccount:${RUNTIME_SA_EMAIL}" \
      --role="roles/secretmanager.secretAccessor" \
      --format=none \
      --quiet
  fi
  EXISTING_SPA_CLIENT_ID="${WEB_SPA_CLIENT_ID}"
elif [[ -z "${EXISTING_SPA_CLIENT_ID}" && "${ASSUME_YES}" != "true" && "${DRY_RUN}" != "true" ]]; then
  read -r -p "No Client ID found in '${GOOGLE_OAUTH_SECRET_NAME}'. Paste brew-web-spa Client ID to save it now (or press Enter to skip): " maybe_spa_id
  maybe_spa_id="$(echo "${maybe_spa_id}" | xargs)"
  if [[ -n "${maybe_spa_id}" ]]; then
    if ! gcloud secrets describe "${GOOGLE_OAUTH_SECRET_NAME}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
      gcloud secrets create "${GOOGLE_OAUTH_SECRET_NAME}" \
        --project="${PROJECT_ID}" \
        --replication-policy="user-managed" \
        --locations="${REGION}" \
        --quiet
    fi
    printf '%s' "${maybe_spa_id}" | gcloud secrets versions add "${GOOGLE_OAUTH_SECRET_NAME}" \
      --project="${PROJECT_ID}" \
      --data-file=- \
      --quiet >/dev/null
    EXISTING_SPA_CLIENT_ID="${maybe_spa_id}"
  fi
fi

echo "Edit Web Client: ${EXISTING_SPA_CLIENT_ID:-<your brew-web-spa Web Client>}"
echo "Add ALL of the following under 'Authorized JavaScript origins' (no trailing slash):"
for u in "${DISCOVERED_URLS[@]}"; do
  echo "  ${u}"
done
echo "  http://localhost:8080"
echo ""

echo "------------------------------------------------------------------------------"
echo "Client A — brew-iap-edge (separate Web application client for Cloud Run IAP)"
echo "------------------------------------------------------------------------------"
if [[ -z "${IAP_CLIENT_ID}" ]]; then
  if [[ "${ASSUME_YES}" == "true" || "${DRY_RUN}" == "true" ]]; then
    echo "ERROR: IAP_CLIENT_ID is required in non-interactive/dry-run mode." >&2
    exit 1
  fi
  echo "In Cloud Console -> Create Client -> Application type: Web application -> Name: brew-iap-edge."
  read -r -p "Paste brew-iap-edge Client ID (*.apps.googleusercontent.com): " IAP_CLIENT_ID
fi
IAP_CLIENT_ID="$(echo "${IAP_CLIENT_ID}" | xargs)"

if [[ "${IAP_CLIENT_ID}" != *.apps.googleusercontent.com ]]; then
  echo "ERROR: IAP_CLIENT_ID ('${IAP_CLIENT_ID}') must end with '.apps.googleusercontent.com'." >&2
  exit 1
fi

if [[ -n "${EXISTING_SPA_CLIENT_ID}" && "${IAP_CLIENT_ID}" == "${EXISTING_SPA_CLIENT_ID}" ]]; then
  echo "ERROR: brew-iap-edge Client ID must be DIFFERENT from brew-web-spa (${EXISTING_SPA_CLIENT_ID})." >&2
  echo "Using two separate Web Clients prevents Cloud Run IAP from consuming Brew's Authorization Bearer token." >&2
  exit 1
fi

if [[ -z "${IAP_CLIENT_SECRET}" ]]; then
  if [[ "${ASSUME_YES}" == "true" || "${DRY_RUN}" == "true" ]]; then
    echo "ERROR: IAP_CLIENT_SECRET is required in non-interactive/dry-run mode." >&2
    exit 1
  fi
  read -r -s -p "Paste brew-iap-edge Client Secret (input hidden): " IAP_CLIENT_SECRET
  echo ""
fi
IAP_CLIENT_SECRET="$(echo "${IAP_CLIENT_SECRET}" | xargs)"
if [[ -z "${IAP_CLIENT_SECRET}" ]]; then
  echo "ERROR: IAP_CLIENT_SECRET cannot be empty." >&2
  exit 1
fi

IAP_REDIRECT_URI="https://iap.googleapis.com/v1/oauth/clientIds/${IAP_CLIENT_ID}:handleRedirect"
echo ""
echo "IMPORTANT — On Client A ('brew-iap-edge'), add this exact Authorized redirect URI and click Save:"
echo ""
echo "  ${IAP_REDIRECT_URI}"
echo ""

if [[ "${ASSUME_YES}" != "true" && "${DRY_RUN}" != "true" ]]; then
  read -r -p "Press [Enter] once you have saved the Redirect URI on brew-iap-edge and JavaScript origins on brew-web-spa... " _
fi

# ------------------------------------------------------------------------------
# Step 3: Bind Custom OAuth Client to Cloud Run IAP & Configure IAM Access
# ------------------------------------------------------------------------------
log_step "Step 3: Binding brew-iap-edge to Cloud Run IAP and granting '${IAP_USER_EMAIL}' access"

run_cmd gcloud services enable iap.googleapis.com --project="${PROJECT_ID}" --quiet

if [[ "${DRY_RUN}" == "true" ]]; then
  run_cmd gcloud beta services identity create --service=iap.googleapis.com --project="${PROJECT_ID}" --quiet
else
  gcloud beta services identity create --service=iap.googleapis.com --project="${PROJECT_ID}" --quiet >/dev/null 2>&1 || true
fi

# Ensure Cloud Run has --iap enabled, BREW_IAP_JWT_AUDIENCE set, and all discovered URLs in ALLOW_ORIGINS
IAP_AUDIENCE="/projects/${PROJECT_NUMBER}/locations/${REGION}/services/${SERVICE_NAME}"
IFS=',' eval 'ALLOW_ORIGINS_CSV="${DISCOVERED_URLS[*]}"'

run_cmd gcloud run services update "${SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --iap \
  --update-env-vars="^@^ALLOW_ORIGINS=${ALLOW_ORIGINS_CSV}@BREW_IAP_JWT_AUDIENCE=${IAP_AUDIENCE}" \
  --quiet

# Write custom OAuth client settings to a 0600 temp file (never echoed in logs or dry-run)
if [[ "${DRY_RUN}" == "true" ]]; then
  echo "[dry-run] Write temporary 0600 IAP settings YAML (clientId=${IAP_CLIENT_ID}, clientSecret=<REDACTED>)"
  echo "[dry-run] gcloud iap settings set <tmp-iap-oauth.yaml> --project=${PROJECT_ID} --resource-type=cloud-run --region=${REGION} --service=${SERVICE_NAME}"
else
  old_umask="$(umask)"
  umask 077
  tmp_iap_yaml="$(mktemp /tmp/brew-iap-oauth.XXXXXX.yaml)"
  umask "${old_umask}"
  TMP_FILES_TO_CLEAN+=("${tmp_iap_yaml}")

  IAP_CID_ENV="${IAP_CLIENT_ID}" IAP_CSEC_ENV="${IAP_CLIENT_SECRET}" python3 - "${tmp_iap_yaml}" <<'PY'
import json
import os
import sys

payload = {
    "accessSettings": {
        "oauthSettings": {
            "clientId": os.environ["IAP_CID_ENV"],
            "clientSecret": os.environ["IAP_CSEC_ENV"],
        }
    }
}
with open(sys.argv[1], "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2)
PY

  gcloud iap settings set "${tmp_iap_yaml}" \
    --project="${PROJECT_ID}" \
    --resource-type=cloud-run \
    --region="${REGION}" \
    --service="${SERVICE_NAME}" \
    --quiet

  rm -f "${tmp_iap_yaml}"
fi

# Remove any stale anonymous invoker bindings (safe no-op if absent)
if [[ "${DRY_RUN}" != "true" ]]; then
  gcloud run services remove-iam-policy-binding "${SERVICE_NAME}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --member="allUsers" \
    --role="roles/run.invoker" \
    --quiet >/dev/null 2>&1 || true
fi

# Grant IAP service agent permission to invoke Cloud Run
IAP_SA="service-${PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com"
run_iam_cmd gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --member="serviceAccount:${IAP_SA}" \
  --role="roles/run.invoker" \
  --format=none \
  --quiet

# Grant ONLY the GCP organization domain user IAP Web App User access
run_iam_cmd gcloud iap web add-iam-policy-binding \
  --project="${PROJECT_ID}" \
  --resource-type=cloud-run \
  --region="${REGION}" \
  --service="${SERVICE_NAME}" \
  --member="user:${IAP_USER_EMAIL}" \
  --role="roles/iap.httpsResourceAccessor" \
  --format=none \
  --quiet

# ------------------------------------------------------------------------------
# Step 4: Verify Active IAP Settings & OAuth Redirect Client ID
# ------------------------------------------------------------------------------
log_step "Step 4: Verifying Cloud Run IAP custom OAuth binding"

if [[ "${DRY_RUN}" == "true" ]]; then
  run_cmd gcloud iap settings get \
    --project="${PROJECT_ID}" \
    --resource-type=cloud-run \
    --region="${REGION}" \
    --service="${SERVICE_NAME}"
  echo "[dry-run] IAP custom OAuth dry-run completed successfully."
  exit 0
fi

APPLIED_CLIENT_ID="$(gcloud iap settings get \
  --project="${PROJECT_ID}" \
  --resource-type=cloud-run \
  --region="${REGION}" \
  --service="${SERVICE_NAME}" \
  --format='value(accessSettings.oauthSettings.clientId)' 2>/dev/null | tr -d '[:space:]' || true)"

if [[ "${APPLIED_CLIENT_ID}" == "${IAP_CLIENT_ID}" ]]; then
  echo "Confirmed Cloud Run IAP oauthSettings.clientId = ${APPLIED_CLIENT_ID}"
else
  echo "WARNING: Expected oauthSettings.clientId '${IAP_CLIENT_ID}', got '${APPLIED_CLIENT_ID:-<empty>}'." >&2
fi

PRIMARY_URL="${DISCOVERED_URLS[0]}"
REDIRECT_HEADERS="$(curl --silent --head --max-time 10 "${PRIMARY_URL}" || true)"
if grep -Fq "${IAP_CLIENT_ID}" <<<"${REDIRECT_HEADERS}"; then
  echo "Live HTTP 302 check confirmed: IAP edge is already redirecting with custom Client A (${IAP_CLIENT_ID})!"
else
  echo "Note: IAP edge redirect propagation typically takes 1-3 minutes to switch to ${IAP_CLIENT_ID}."
fi

echo ""
echo "=============================================================================="
echo "Brew Custom Cloud Run IAP Setup Complete"
echo "  1. Wait ~2 minutes if you just updated OAuth settings, then open an Incognito window:"
echo "       ${PRIMARY_URL}"
echo "  2. At the Google IAP login prompt, sign in with:"
echo "       ${IAP_USER_EMAIL}"
echo "  3. Once Brew loads, click 'Continue with Google' -> 'Use another account' ->"
echo "     sign in with your personal @gmail.com test user."
echo "=============================================================================="
