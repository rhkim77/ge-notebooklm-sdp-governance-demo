# ==============================================================================
# Service Identities (Service Agents) & Least-Privilege IAM Bindings
# ==============================================================================

resource "google_project_service_identity" "discoveryengine_sa" {
  provider   = google-beta
  project    = var.project_id
  service    = "discoveryengine.googleapis.com"
  depends_on = [time_sleep.wait_for_apis]
}

resource "google_project_service_identity" "dlp_sa" {
  provider   = google-beta
  project    = var.project_id
  service    = "dlp.googleapis.com"
  depends_on = [time_sleep.wait_for_apis]
}

resource "time_sleep" "wait_for_service_identities" {
  create_duration = "20s"
  depends_on = [
    google_project_service_identity.discoveryengine_sa,
    google_project_service_identity.dlp_sa,
  ]
}

# 1. Grant Discovery Engine Service Agent permission to invoke Cloud DLP & Model Armor
resource "google_project_iam_member" "discoveryengine_dlp_user" {
  for_each = toset([
    "roles/discoveryengine.serviceAgent",
    "roles/dlp.user",
    "roles/storage.objectViewer",
  ])
  project    = var.project_id
  role       = each.value
  member     = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-discoveryengine.iam.gserviceaccount.com"
  depends_on = [time_sleep.wait_for_service_identities]
}

# 2. Grant Cloud DLP Service Agent permission to stream ContentPolicyActionLog rows to BigQuery
resource "google_project_iam_member" "dlp_bigquery_editor" {
  project    = var.project_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:service-${data.google_project.current.number}@dlp-api.iam.gserviceaccount.com"
  depends_on = [time_sleep.wait_for_service_identities]
}
