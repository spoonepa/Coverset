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
