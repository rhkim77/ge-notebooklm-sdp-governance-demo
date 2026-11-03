locals {
  required_apis = [
    "cloudresourcemanager.googleapis.com",
    "serviceusage.googleapis.com",
    "iam.googleapis.com",
    "discoveryengine.googleapis.com",
    "dlp.googleapis.com",
    "modelarmor.googleapis.com",
    "storage.googleapis.com",
    "bigquery.googleapis.com",
    "logging.googleapis.com",
    "aiplatform.googleapis.com",
  ]
}

data "google_project" "current" {
  project_id = var.project_id
}

resource "google_project_service" "enabled_apis" {
  for_each           = toset(local.required_apis)
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "time_sleep" "wait_for_apis" {
  create_duration = "30s"
  depends_on      = [google_project_service.enabled_apis]
}
