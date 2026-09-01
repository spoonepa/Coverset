output "api_url" {
  description = "Private Cloud Run API URL."
  value       = google_cloud_run_v2_service.api.uri
}

output "worker_url" {
  description = "Private Cloud Run worker URL."
  value       = google_cloud_run_v2_service.worker.uri
}

output "web_url" {
  description = "Private Cloud Run web URL."
  value       = google_cloud_run_v2_service.web.uri
}

output "artifact_registry_repository" {
  description = "Artifact Registry repository path."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.containers.repository_id}"
}

output "cloudsql_connection_name" {
  description = "Cloud SQL connection name."
  value       = google_sql_database_instance.main.connection_name
}

output "screenplay_bucket" {
  description = "GCS bucket for screenplay uploads."
  value       = google_storage_bucket.screenplays.name
}

output "artifact_bucket" {
  description = "GCS bucket for generated artifacts."
  value       = google_storage_bucket.artifacts.name
}

output "bigquery_dataset" {
  description = "BigQuery dataset for analytics/audit export."
  value       = google_bigquery_dataset.analytics.dataset_id
}

output "bigquery_audit_table" {
  description = "BigQuery table for append-only audit exports."
  value       = "${google_bigquery_dataset.analytics.dataset_id}.${google_bigquery_table.audit_events.table_id}"
}

output "terraform_state_bucket" {
  description = "GCS bucket configured for remote Terraform state."
  value       = var.terraform_state_bucket != "" ? var.terraform_state_bucket : "coverset-${var.project_id}-terraform-state"
}

output "cloud_run_error_alert_policy" {
  description = "Cloud Monitoring alert policy for Cloud Run error logs."
  value       = google_monitoring_alert_policy.cloud_run_errors.display_name
}
