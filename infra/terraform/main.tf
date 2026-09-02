data "google_project" "current" {
  project_id = var.project_id
}

locals {
  services = toset([
    "aiplatform.googleapis.com",
    "artifactregistry.googleapis.com",
    "bigquery.googleapis.com",
    "billingbudgets.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudtasks.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "monitoring.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "serviceusage.googleapis.com",
    "sqladmin.googleapis.com",
    "storage.googleapis.com",
  ])

  cloudbuild_service_account = "serviceAccount:${data.google_project.current.number}@cloudbuild.gserviceaccount.com"
  developer_email            = startswith(var.developer_principal, "user:") ? trimprefix(var.developer_principal, "user:") : ""
  dev_actor_roles = [
    "first_ad",
    "second_ad",
    "script_supervisor",
    "director",
    "upm",
    "line_producer",
  ]
}

resource "google_project_service" "required" {
  for_each = local.services

  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

resource "random_id" "suffix" {
  byte_length = 4
}

resource "random_password" "db_password" {
  length  = 32
  special = true
}

resource "google_artifact_registry_repository" "containers" {
  project       = var.project_id
  location      = var.region
  repository_id = var.repository_id
  description   = "Coverset dev containers"
  format        = "DOCKER"

  depends_on = [google_project_service.required]
}

resource "google_storage_bucket" "screenplays" {
  project                     = var.project_id
  name                        = "${var.name_prefix}-${var.project_id}-screenplays-${random_id.suffix.hex}"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = true

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      age = 30
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_storage_bucket" "artifacts" {
  project                     = var.project_id
  name                        = "${var.name_prefix}-${var.project_id}-artifacts-${random_id.suffix.hex}"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = true

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      age = 90
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_cloud_tasks_queue" "jobs" {
  project  = var.project_id
  name     = "${var.name_prefix}-jobs-dev"
  location = var.region

  rate_limits {
    max_dispatches_per_second = 1
    max_concurrent_dispatches = 2
  }

  retry_config {
    max_attempts = 3
    min_backoff  = "10s"
    max_backoff  = "300s"
  }

  depends_on = [google_project_service.required]
}

resource "google_bigquery_dataset" "analytics" {
  project                    = var.project_id
  dataset_id                 = "coverset_analytics_dev"
  friendly_name              = "Coverset Analytics Dev"
  description                = "Append-only analytics and audit export target for Coverset dev."
  location                   = "US"
  delete_contents_on_destroy = true

  depends_on = [google_project_service.required]
}

resource "google_bigquery_table" "audit_events" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.analytics.dataset_id
  table_id            = "audit_events"
  deletion_protection = false

  description = "Append-only exported Coverset audit events."

  time_partitioning {
    type  = "DAY"
    field = "created_at"
  }

  clustering = ["production_id", "event_type"]

  schema = jsonencode([
    {
      name = "id"
      type = "STRING"
      mode = "REQUIRED"
    },
    {
      name = "production_id"
      type = "STRING"
      mode = "NULLABLE"
    },
    {
      name = "event_type"
      type = "STRING"
      mode = "REQUIRED"
    },
    {
      name = "actor"
      type = "STRING"
      mode = "REQUIRED"
    },
    {
      name = "payload"
      type = "JSON"
      mode = "NULLABLE"
    },
    {
      name = "created_at"
      type = "TIMESTAMP"
      mode = "REQUIRED"
    },
  ])

  depends_on = [google_bigquery_dataset.analytics]
}

resource "google_sql_database_instance" "main" {
  project             = var.project_id
  name                = "${var.name_prefix}-dev"
  region              = var.region
  database_version    = "POSTGRES_16"
  deletion_protection = false

  settings {
    tier              = var.db_tier
    edition           = "ENTERPRISE"
    availability_type = "ZONAL"
    disk_type         = "PD_HDD"
    disk_size         = 10

    backup_configuration {
      enabled                        = true
      start_time                     = "03:00"
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 7

      backup_retention_settings {
        retained_backups = 7
        retention_unit   = "COUNT"
      }
    }

    ip_configuration {
      ipv4_enabled = true
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_sql_database" "coverset" {
  project  = var.project_id
  name     = "coverset"
  instance = google_sql_database_instance.main.name
}

resource "google_sql_user" "coverset" {
  project  = var.project_id
  name     = "coverset"
  instance = google_sql_database_instance.main.name
  password = random_password.db_password.result
}

resource "google_secret_manager_secret" "db_password" {
  project   = var.project_id
  secret_id = "${var.name_prefix}-db-password"

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "db_password" {
  secret      = google_secret_manager_secret.db_password.id
  secret_data = random_password.db_password.result
}

resource "google_secret_manager_secret" "gemini_api_key" {
  project   = var.project_id
  secret_id = "${var.name_prefix}-gemini-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret" "google_api_key" {
  project   = var.project_id
  secret_id = "${var.name_prefix}-google-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret" "parallel_api_key" {
  project   = var.project_id
  secret_id = "${var.name_prefix}-parallel-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret" "app_secret" {
  project   = var.project_id
  secret_id = "${var.name_prefix}-app-secret"

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "gemini_api_key_placeholder" {
  secret      = google_secret_manager_secret.gemini_api_key.id
  secret_data = "placeholder"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

resource "google_secret_manager_secret_version" "google_api_key_placeholder" {
  secret      = google_secret_manager_secret.google_api_key.id
  secret_data = "placeholder"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

resource "google_secret_manager_secret_version" "parallel_api_key_placeholder" {
  secret      = google_secret_manager_secret.parallel_api_key.id
  secret_data = "placeholder"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

resource "google_secret_manager_secret_version" "app_secret_placeholder" {
  secret      = google_secret_manager_secret.app_secret.id
  secret_data = "placeholder"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

resource "google_service_account" "api" {
  project      = var.project_id
  account_id   = "${var.name_prefix}-api-dev"
  display_name = "Coverset API dev"
}

resource "google_service_account" "worker" {
  project      = var.project_id
  account_id   = "${var.name_prefix}-worker-dev"
  display_name = "Coverset worker dev"
}

resource "google_service_account" "web" {
  project      = var.project_id
  account_id   = "${var.name_prefix}-web-dev"
  display_name = "Coverset web dev"
}

resource "google_project_iam_member" "api_cloudsql" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = google_service_account.api.member
}

resource "google_project_iam_member" "worker_cloudsql" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = google_service_account.worker.member
}

resource "google_project_iam_member" "cloudbuild_artifact_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = local.cloudbuild_service_account

  depends_on = [google_project_service.required]
}

resource "google_project_iam_member" "api_tasks_enqueuer" {
  project = var.project_id
  role    = "roles/cloudtasks.enqueuer"
  member  = google_service_account.api.member

  depends_on = [google_project_service.required]
}

resource "google_service_account_iam_member" "cloudtasks_api_token_creator" {
  service_account_id = google_service_account.api.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-cloudtasks.iam.gserviceaccount.com"

  depends_on = [google_project_service.required]
}

resource "google_service_account_iam_member" "api_task_oidc_act_as" {
  service_account_id = google_service_account.api.name
  role               = "roles/iam.serviceAccountUser"
  member             = google_service_account.api.member
}

resource "google_storage_bucket_iam_member" "api_screenplay_writer" {
  bucket = google_storage_bucket.screenplays.name
  role   = "roles/storage.objectAdmin"
  member = google_service_account.api.member
}

resource "google_storage_bucket_iam_member" "worker_screenplay_reader" {
  bucket = google_storage_bucket.screenplays.name
  role   = "roles/storage.objectViewer"
  member = google_service_account.worker.member
}

resource "google_storage_bucket_iam_member" "api_artifact_writer" {
  bucket = google_storage_bucket.artifacts.name
  role   = "roles/storage.objectAdmin"
  member = google_service_account.api.member
}

resource "google_storage_bucket_iam_member" "worker_artifact_writer" {
  bucket = google_storage_bucket.artifacts.name
  role   = "roles/storage.objectAdmin"
  member = google_service_account.worker.member
}

resource "google_bigquery_dataset_iam_member" "api_analytics_writer" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = google_service_account.api.member
}

resource "google_bigquery_dataset_iam_member" "worker_analytics_writer" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = google_service_account.worker.member
}

resource "google_secret_manager_secret_iam_member" "api_db_secret" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.db_password.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.api.member
}

resource "google_secret_manager_secret_iam_member" "worker_db_secret" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.db_password.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.worker.member
}

resource "google_secret_manager_secret_iam_member" "api_gemini_secret" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.gemini_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.api.member
}

resource "google_secret_manager_secret_iam_member" "worker_gemini_secret" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.gemini_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.worker.member
}

resource "google_secret_manager_secret_iam_member" "api_google_secret" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.google_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.api.member
}

resource "google_secret_manager_secret_iam_member" "worker_google_secret" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.google_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.worker.member
}

resource "google_secret_manager_secret_iam_member" "api_parallel_secret" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.parallel_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.api.member
}

resource "google_secret_manager_secret_iam_member" "worker_parallel_secret" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.parallel_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.worker.member
}

resource "google_secret_manager_secret_iam_member" "api_app_secret" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.app_secret.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.api.member
}

resource "google_secret_manager_secret_iam_member" "worker_app_secret" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.app_secret.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.worker.member
}

resource "google_cloud_run_v2_service" "api" {
  project             = var.project_id
  name                = "${var.name_prefix}-api-dev"
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"

  lifecycle {
    # The Cloud Run v2 API returns service-level zero/default scaling fields
    # that the Google provider repeatedly wants to remove. Ignore that
    # provider-normalized block so dev plans stay meaningful; revision max
    # instances remains configured in template.scaling.
    ignore_changes = [scaling]
  }

  template {
    service_account = google_service_account.api.email

    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.main.connection_name]
      }
    }

    containers {
      image = var.api_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GOOGLE_CLOUD_REGION"
        value = var.region
      }
      env {
        name  = "COVERSET_ENV"
        value = "dev"
      }
      env {
        name  = "COVERSET_AGENT_MODE"
        value = var.agent_mode
      }
      env {
        name  = "COVERSET_DB_USER"
        value = google_sql_user.coverset.name
      }
      env {
        name  = "COVERSET_DB_NAME"
        value = google_sql_database.coverset.name
      }
      env {
        name  = "COVERSET_CLOUDSQL_INSTANCE"
        value = google_sql_database_instance.main.connection_name
      }
      env {
        name  = "COVERSET_UPLOAD_BUCKET"
        value = google_storage_bucket.screenplays.name
      }
      env {
        name  = "COVERSET_ARTIFACT_BUCKET"
        value = google_storage_bucket.artifacts.name
      }
      env {
        name  = "COVERSET_BIGQUERY_DATASET"
        value = google_bigquery_dataset.analytics.dataset_id
      }
      env {
        name  = "COVERSET_BIGQUERY_AUDIT_TABLE"
        value = google_bigquery_table.audit_events.table_id
      }
      env {
        name  = "COVERSET_TASK_QUEUE"
        value = google_cloud_tasks_queue.jobs.name
      }
      env {
        name  = "COVERSET_WORKER_URL"
        value = google_cloud_run_v2_service.worker.uri
      }
      env {
        name  = "COVERSET_TASK_OIDC_SERVICE_ACCOUNT"
        value = google_service_account.api.email
      }
      env {
        name = "COVERSET_DB_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.db_password.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "GEMINI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gemini_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "GOOGLE_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.google_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "PARALLEL_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.parallel_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "COVERSET_APP_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.app_secret.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  depends_on = [
    google_secret_manager_secret_version.db_password,
    google_secret_manager_secret_version.gemini_api_key_placeholder,
    google_secret_manager_secret_version.google_api_key_placeholder,
    google_secret_manager_secret_version.parallel_api_key_placeholder,
    google_secret_manager_secret_version.app_secret_placeholder,
    google_sql_database.coverset,
    google_project_service.required,
  ]
}

resource "google_cloud_run_v2_service" "worker" {
  project             = var.project_id
  name                = "${var.name_prefix}-worker-dev"
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"

  lifecycle {
    # The Cloud Run v2 API returns service-level zero/default scaling fields
    # that the Google provider repeatedly wants to remove. Ignore that
    # provider-normalized block so dev plans stay meaningful; revision max
    # instances remains configured in template.scaling.
    ignore_changes = [scaling]
  }

  template {
    service_account = google_service_account.worker.email

    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.main.connection_name]
      }
    }

    containers {
      image = var.worker_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GOOGLE_CLOUD_REGION"
        value = var.region
      }
      env {
        name  = "COVERSET_ENV"
        value = "dev"
      }
      env {
        name  = "COVERSET_AGENT_MODE"
        value = var.agent_mode
      }
      env {
        name  = "COVERSET_DB_USER"
        value = google_sql_user.coverset.name
      }
      env {
        name  = "COVERSET_DB_NAME"
        value = google_sql_database.coverset.name
      }
      env {
        name  = "COVERSET_CLOUDSQL_INSTANCE"
        value = google_sql_database_instance.main.connection_name
      }
      env {
        name  = "COVERSET_UPLOAD_BUCKET"
        value = google_storage_bucket.screenplays.name
      }
      env {
        name  = "COVERSET_ARTIFACT_BUCKET"
        value = google_storage_bucket.artifacts.name
      }
      env {
        name  = "COVERSET_BIGQUERY_DATASET"
        value = google_bigquery_dataset.analytics.dataset_id
      }
      env {
        name  = "COVERSET_BIGQUERY_AUDIT_TABLE"
        value = google_bigquery_table.audit_events.table_id
      }
      env {
        name = "COVERSET_DB_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.db_password.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "GEMINI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gemini_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "GOOGLE_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.google_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "PARALLEL_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.parallel_api_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "COVERSET_APP_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.app_secret.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  depends_on = [
    google_secret_manager_secret_version.db_password,
    google_secret_manager_secret_version.gemini_api_key_placeholder,
    google_secret_manager_secret_version.google_api_key_placeholder,
    google_secret_manager_secret_version.parallel_api_key_placeholder,
    google_secret_manager_secret_version.app_secret_placeholder,
    google_sql_database.coverset,
    google_project_service.required,
  ]
}

resource "google_cloud_run_v2_service" "web" {
  project             = var.project_id
  name                = "${var.name_prefix}-web-dev"
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"

  lifecycle {
    # The Cloud Run v2 API returns service-level zero/default scaling fields
    # that the Google provider repeatedly wants to remove. Ignore that
    # provider-normalized block so dev plans stay meaningful; revision max
    # instances remains configured in template.scaling.
    ignore_changes = [scaling]
  }

  template {
    service_account = google_service_account.web.email

    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances
    }

    containers {
      image = var.web_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }

      env {
        name  = "COVERSET_API_BASE_URL"
        value = google_cloud_run_v2_service.api.uri
      }
      env {
        name  = "COVERSET_API_AUDIENCE"
        value = google_cloud_run_v2_service.api.uri
      }
      env {
        name  = "NEXT_TELEMETRY_DISABLED"
        value = "1"
      }
      env {
        name  = "COVERSET_ACTOR_EMAIL"
        value = local.developer_email
      }
      env {
        name  = "COVERSET_ACTOR_ROLES"
        value = join(",", local.dev_actor_roles)
      }
      env {
        name  = "COVERSET_AUTH_ROLE_MAP"
        value = local.developer_email == "" ? "{}" : jsonencode({ (local.developer_email) = local.dev_actor_roles })
      }
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_cloud_run_v2_service_iam_member" "api_developer_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = var.developer_principal
}

resource "google_cloud_run_v2_service_iam_member" "worker_developer_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.worker.name
  role     = "roles/run.invoker"
  member   = var.developer_principal
}

resource "google_cloud_run_v2_service_iam_member" "api_invokes_worker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.worker.name
  role     = "roles/run.invoker"
  member   = google_service_account.api.member
}

resource "google_cloud_run_v2_service_iam_member" "web_developer_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.web.name
  role     = "roles/run.invoker"
  member   = var.developer_principal
}

resource "google_cloud_run_v2_service_iam_member" "web_invokes_api" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = google_service_account.web.member
}

resource "google_logging_metric" "cloud_run_errors" {
  project = var.project_id
  name    = "${var.name_prefix}_cloud_run_errors"
  filter = join(" AND ", [
    "resource.type=\"cloud_run_revision\"",
    "resource.labels.service_name=~\"^${var.name_prefix}-(api|worker|web)-dev$\"",
    "severity>=ERROR",
  ])

  metric_descriptor {
    metric_kind  = "DELTA"
    value_type   = "INT64"
    unit         = "1"
    display_name = "Coverset Cloud Run errors"

    labels {
      key         = "service"
      value_type  = "STRING"
      description = "Cloud Run service name."
    }
  }

  label_extractors = {
    service = "EXTRACT(resource.labels.service_name)"
  }

  depends_on = [google_project_service.required]
}

resource "google_monitoring_alert_policy" "cloud_run_errors" {
  project      = var.project_id
  display_name = "Coverset dev Cloud Run errors"
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "Cloud Run emitted error logs"

    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.cloud_run_errors.name}\" AND resource.type=\"cloud_run_revision\""
      duration        = "60s"
      comparison      = "COMPARISON_GT"
      threshold_value = 0

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_DELTA"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["metric.label.service"]
      }
    }
  }

  notification_channels = var.notification_channel_ids

  documentation {
    content   = "Coverset dev Cloud Run services emitted error logs. Check Cloud Run logs for the affected service and revision."
    mime_type = "text/markdown"
  }

  depends_on = [google_logging_metric.cloud_run_errors]
}

resource "google_billing_budget" "dev" {
  count           = var.billing_account_id == "" ? 0 : 1
  billing_account = var.billing_account_id
  display_name    = "Coverset dev monthly budget"

  budget_filter {
    projects = ["projects/${data.google_project.current.number}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.monthly_budget_amount_usd)
    }
  }

  threshold_rules {
    threshold_percent = 0.5
  }

  threshold_rules {
    threshold_percent = 0.9
  }

  threshold_rules {
    threshold_percent = 1.0
  }

  all_updates_rule {
    monitoring_notification_channels = var.notification_channel_ids
    disable_default_iam_recipients   = false
  }

  depends_on = [google_project_service.required]
}
