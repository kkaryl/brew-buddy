"""Deterministic validation of Cloud Run setup script, manifest, Dockerfile, and CI workflows."""

from __future__ import annotations

import importlib
import os
import subprocess
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
# The setup scripts need agents-cli or uvx on PATH. Prepend ~/.local/bin to the caller's
# PATH so dry-runs work across local user-tool installs and CI runners alike.
_SCRIPT_PATH = f"{Path.home() / '.local' / 'bin'}:{os.environ.get('PATH', '/usr/bin:/bin')}"


def _load_yaml(path: Path) -> dict[object, Any]:
    yaml_module = importlib.import_module("yaml")
    loaded: object = yaml_module.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_agents_cli_manifest_targets_cloud_run_and_preserves_coach() -> None:
    manifest = _load_yaml(REPO_ROOT / "agents-cli-manifest.yaml")
    assert manifest["name"] == "brew"
    assert manifest["region"] == "asia-southeast1"
    assert manifest["framework"] == "google-adk"
    params = manifest["create_params"]
    assert params["root_agent_name"] == "conversation_coach"
    assert params["app_name"] == "app"
    assert params["deployment_target"] == "cloud_run"
    assert params["cicd_runner"] == "github_actions"


def test_dockerfile_serves_react_spa_and_fastapi_as_non_root_with_healthcheck() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM node:22-bookworm-slim AS web-builder" in dockerfile
    assert "RUN npm run build" in dockerfile
    assert "COPY --chown=brew:brew --from=web-builder /web/dist ./web/dist" in dockerfile
    assert "USER brew" in dockerfile
    assert "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=NO_CONTENT" in dockerfile
    assert "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "/healthz" in dockerfile
    assert 'CMD ["python", "-m", "app.server"]' in dockerfile


def test_gcloud_setup_script_syntax_dry_run_and_zero_key_guarantees() -> None:
    script_path = REPO_ROOT / "gcloud_setup.sh"
    script_text = script_path.read_text(encoding="utf-8")

    # Never generate service account JSON keys
    for line in script_text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            assert "service-accounts keys create" not in stripped

    # Verify ordered sequence of enablement
    phase_markers = [
        "Phase 1: Enabling required Google Cloud APIs",
        "Phase 2: Provisioning Cloud Firestore database and required indexes",
        "Phase 3: Configuring least-privilege runtime service account",
        "Phase 4:",
        "Phase 5: Configuring Artifact Registry repository",
        "Phase 6: Configuring Secret Manager secrets",
        "Phase 7: Building reproducible container image and deploying via Agents CLI",
        "Phase 8: Configuring Cloud Run startup/readiness/liveness probes",
    ]
    positions = [script_text.index(marker) for marker in phase_markers]
    assert positions == sorted(positions)

    syntax_res = subprocess.run(
        ["bash", "-n", str(script_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert syntax_res.returncode == 0, syntax_res.stderr

    dry_run = subprocess.run(
        ["bash", str(script_path), "--dry-run"],
        check=False,
        capture_output=True,
        text=True,
        env={
            "PATH": _SCRIPT_PATH,
            "PROJECT_ID": "brew-unit-dryrun",
            "GITHUB_REPO": "acme/brew",
            "ENABLE_IAP": "true",
        },
    )
    assert dry_run.returncode == 0, dry_run.stderr
    assert "agents-cli deploy" in dry_run.stdout
    assert "--region asia-southeast1" in dry_run.stdout
    assert "--startup-probe=httpGet.path=/readyz" in dry_run.stdout
    assert "--liveness-probe=httpGet.path=/healthz" in dry_run.stdout
    # Per-stage model routing and durable storage reach the deployed service.
    assert "GEMINI_MODEL=gemini-3.8-flash" in dry_run.stdout
    assert "BREW_SYNTHESIS_MODEL=gemini-4-hydrogen" in dry_run.stdout
    assert "BREW_PERSISTENCE_BACKEND=firestore" in dry_run.stdout
    assert "BREW_ALLOW_EPHEMERAL_PERSISTENCE" not in dry_run.stdout


def test_deploy_workflow_routes_models_and_only_ci_smoke_allows_ephemeral_storage() -> None:
    workflows_dir = REPO_ROOT / ".github" / "workflows"
    deploy_raw = (workflows_dir / "deploy.yml").read_text(encoding="utf-8")
    ci_raw = (workflows_dir / "ci.yml").read_text(encoding="utf-8")

    assert "BREW_SYNTHESIS_MODEL=${BREW_SYNTHESIS_MODEL}" in deploy_raw
    assert "vars.BREW_SYNTHESIS_MODEL || 'gemini-4-hydrogen'" in deploy_raw
    assert "BREW_PERSISTENCE_BACKEND=firestore" in deploy_raw
    assert "BREW_ALLOW_EPHEMERAL_PERSISTENCE" not in deploy_raw
    # The container smoke test boots a production image on in-memory stores on purpose.
    assert "BREW_ALLOW_EPHEMERAL_PERSISTENCE=true" in ci_raw


def test_github_workflows_enforce_pr_gates_wif_auth_and_controlled_eval() -> None:
    workflows_dir = REPO_ROOT / ".github" / "workflows"
    ci_wf = _load_yaml(workflows_dir / "ci.yml")
    deploy_wf = _load_yaml(workflows_dir / "deploy.yml")
    eval_wf = _load_yaml(workflows_dir / "eval-controlled.yml")

    # PyYAML parses bare `on:` as boolean True in YAML 1.1
    ci_triggers = ci_wf.get("on") or ci_wf.get(True)
    assert isinstance(ci_triggers, dict)
    assert "pull_request" in ci_triggers
    assert "python-quality-and-unit" in ci_wf["jobs"]
    assert "integration-emulators" in ci_wf["jobs"]
    assert "frontend-quality-and-build" in ci_wf["jobs"]
    assert "container-build-validation" in ci_wf["jobs"]

    ci_raw = (workflows_dir / "ci.yml").read_text(encoding="utf-8")
    assert "live-agents-cli" not in ci_raw
    assert "FIRESTORE_EMULATOR_HOST" in ci_raw

    # Main deployment workflow uses WIF (no static credentials_json) and gates on authorization
    deploy_raw = (workflows_dir / "deploy.yml").read_text(encoding="utf-8")
    assert "google-github-actions/auth@v2" in deploy_raw
    assert "workload_identity_provider" in deploy_raw
    assert "credentials_json" not in deploy_raw
    assert "agents-cli" in deploy_raw
    assert "/readyz" in deploy_raw
    assert "GITHUB_STEP_SUMMARY" in deploy_raw
    assert "deploy-cloud-run" in deploy_wf["jobs"]
    assert deploy_wf["jobs"]["deploy-cloud-run"]["environment"]["name"] == "production"

    # Controlled evaluation workflow is strictly manual (workflow_dispatch only, never PR)
    eval_triggers = eval_wf.get("on") or eval_wf.get(True)
    assert isinstance(eval_triggers, dict)
    assert set(eval_triggers.keys()) == {"workflow_dispatch"}
    assert "pull_request" not in eval_triggers


def test_iap_setup_script_syntax_dry_run_and_domain_guardrails() -> None:
    script_path = REPO_ROOT / "iap_setup.sh"
    script_text = script_path.read_text(encoding="utf-8")

    for line in script_text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            assert "service-accounts keys create" not in stripped

    syntax_res = subprocess.run(
        ["bash", "-n", str(script_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert syntax_res.returncode == 0, syntax_res.stderr

    base_env = {
        "PATH": _SCRIPT_PATH,
        "PROJECT_ID": "brew-unit-dryrun",
        "REGION": "asia-southeast1",
        "IAP_CLIENT_ID": "123456-iap.apps.googleusercontent.com",
        "IAP_CLIENT_SECRET": "GOCSPX-top-secret-value",
        "WEB_SPA_CLIENT_ID": "999999-spa.apps.googleusercontent.com",
    }

    # Guardrail 1: Reject @gmail.com for IAP IAM binding (blocked by iam.allowedPolicyMemberDomains)
    gmail_attempt = subprocess.run(
        ["bash", str(script_path), "--dry-run", "--yes"],
        check=False,
        capture_output=True,
        text=True,
        env={**base_env, "IAP_USER_EMAIL": "personal@gmail.com"},
    )
    assert gmail_attempt.returncode != 0
    assert "iam.allowedPolicyMemberDomains" in gmail_attempt.stderr

    # Guardrail 2: Reject reusing the same OAuth Client ID for both IAP edge and Brew SPA
    same_client_attempt = subprocess.run(
        ["bash", str(script_path), "--dry-run", "--yes"],
        check=False,
        capture_output=True,
        text=True,
        env={
            **base_env,
            "IAP_USER_EMAIL": "dev@example-org.com",
            "IAP_CLIENT_ID": "999999-spa.apps.googleusercontent.com",
        },
    )
    assert same_client_attempt.returncode != 0
    assert "DIFFERENT" in same_client_attempt.stderr

    # Valid dry run succeeds without leaking IAP_CLIENT_SECRET to stdout/stderr
    dry_run = subprocess.run(
        ["bash", str(script_path), "--dry-run", "--yes"],
        check=False,
        capture_output=True,
        text=True,
        env={**base_env, "IAP_USER_EMAIL": "dev@example-org.com"},
    )
    assert dry_run.returncode == 0, dry_run.stderr
    assert "GOCSPX-top-secret-value" not in dry_run.stdout
    assert "GOCSPX-top-secret-value" not in dry_run.stderr
    assert (
        "https://iap.googleapis.com/v1/oauth/clientIds/"
        "123456-iap.apps.googleusercontent.com:handleRedirect"
    ) in dry_run.stdout
    assert "gcloud iap settings set" in dry_run.stdout
    assert "roles/iap.httpsResourceAccessor" in dry_run.stdout
