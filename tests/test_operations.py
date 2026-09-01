from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.req("OPS-001", "OPS-004")
def test_remote_state_backend_is_bootstrapped_and_untracked():
    providers = (ROOT / "infra/terraform/providers.tf").read_text()
    bootstrap = (ROOT / "scripts/bootstrap_terraform_state.sh").read_text()
    gitignore = (ROOT / ".gitignore").read_text()
    check = (ROOT / "scripts/check.sh").read_text()

    assert 'backend "gcs"' in providers
    assert "gcloud storage buckets create" in bootstrap
    assert "--versioning" in bootstrap
    assert "backend.auto.hcl" in gitignore
    assert "tracked secret/config artifacts are forbidden" in check
    assert "secret-looking values found in tracked files" in check


@pytest.mark.req("OPS-002", "OPS-003")
def test_terraform_declares_backups_alerts_budget_and_audit_table():
    main = (ROOT / "infra/terraform/main.tf").read_text()
    variables = (ROOT / "infra/terraform/variables.tf").read_text()
    deploy = (ROOT / "scripts/deploy_dev.sh").read_text()

    assert 'resource "google_bigquery_table" "audit_events"' in main
    assert 'resource "google_logging_metric" "cloud_run_errors"' in main
    assert 'resource "google_monitoring_alert_policy" "cloud_run_errors"' in main
    assert 'resource "google_billing_budget" "dev"' in main
    assert "point_in_time_recovery_enabled = true" in main
    assert "retained_backups = 7" in main
    assert 'variable "billing_account_id"' in variables
    assert "gcloud billing projects describe" in deploy
    assert 'billing_account_id    = "${BILLING_ACCOUNT_ID}"' in deploy
