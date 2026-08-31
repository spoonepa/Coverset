variable "project_id" {
  description = "GCP project id."
  type        = string
  default     = "spoonepa"
}

variable "region" {
  description = "GCP region for regional services."
  type        = string
  default     = "us-central1"
}

variable "name_prefix" {
  description = "Name prefix for dev resources."
  type        = string
  default     = "coverset"
}

variable "repository_id" {
  description = "Artifact Registry repository id."
  type        = string
  default     = "coverset"
}

variable "developer_principal" {
  description = "IAM principal allowed to invoke private dev Cloud Run services."
  type        = string
  default     = "user:spoonepa@gmail.com"
}

variable "api_image" {
  description = "API container image URI. Use Cloud Build output for real deploys."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "worker_image" {
  description = "Worker container image URI. Use Cloud Build output for real deploys."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "web_image" {
  description = "Web container image URI. Use Cloud Build output for real deploys."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "agent_mode" {
  description = "Default API breakdown agent mode. Use fixture for safe deployed smoke, gemini for real uploads."
  type        = string
  default     = "fixture"

  validation {
    condition     = contains(["fixture", "gemini"], var.agent_mode)
    error_message = "agent_mode must be fixture or gemini."
  }
}

variable "db_tier" {
  description = "Cloud SQL machine tier for dev."
  type        = string
  default     = "db-f1-micro"
}

variable "max_instances" {
  description = "Max Cloud Run instances per service in dev."
  type        = number
  default     = 2
}
