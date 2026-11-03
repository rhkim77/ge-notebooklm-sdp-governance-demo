locals {
  effective_raw_bucket    = var.raw_bucket_name != "" ? var.raw_bucket_name : "${var.project_id}-ge-sdp-raw-docs"
  effective_masked_bucket = var.masked_bucket_name != "" ? var.masked_bucket_name : "${var.project_id}-ge-sdp-masked-docs"
}

resource "google_storage_bucket" "raw_docs" {
  name                        = local.effective_raw_bucket
  project                     = var.project_id
  location                    = var.region
  force_destroy               = true
  uniform_bucket_level_access = true
  depends_on                  = [time_sleep.wait_for_apis]
}

resource "google_storage_bucket" "masked_docs" {
  name                        = local.effective_masked_bucket
  project                     = var.project_id
  location                    = var.region
  force_destroy               = true
  uniform_bucket_level_access = true
  depends_on                  = [time_sleep.wait_for_apis]
}

resource "google_bigquery_dataset" "sdp_audit_logs" {
  dataset_id                 = var.bq_dataset_id
  project                    = var.project_id
  location                   = var.bq_location
  description                = "Sensitive Data Protection (SDP) ContentPolicy Action Audit Logs"
  delete_contents_on_destroy = true
  depends_on                 = [time_sleep.wait_for_apis]
}

resource "google_bigquery_table" "content_policy_action_logs" {
  dataset_id          = google_bigquery_dataset.sdp_audit_logs.dataset_id
  table_id            = var.bq_table_id
  project             = var.project_id
  deletion_protection = false

  schema = jsonencode([
    {
      name        = "timestamp"
      type        = "TIMESTAMP"
      mode        = "NULLABLE"
      description = "UTC timestamp when DlpService.ApplyContentPolicy evaluated the content"
    },
    {
      name        = "content_policy_name"
      type        = "STRING"
      mode        = "NULLABLE"
      description = "Full resource name of the Cloud DLP ContentPolicy"
    },
    {
      name        = "returned_verdict"
      type        = "STRING"
      mode        = "NULLABLE"
      description = "Final enforcement verdict returned to caller (ALLOW or BLOCK)"
    },
    {
      name        = "matching_info_types"
      type        = "STRING"
      mode        = "REPEATED"
      description = "Detected Cloud DLP InfoTypes (e.g., CREDIT_CARD_NUMBER, KOREA_RRN)"
    },
    {
      name        = "policy_rule"
      type        = "STRING"
      mode        = "NULLABLE"
      description = "Matched rule inside ContentPolicy (e.g., INFOTYPE_RULE)"
    },
    {
      name        = "fallback_action"
      type        = "STRING"
      mode        = "NULLABLE"
      description = "Configured Fallback Action when input exceeds size limit (BLOCK or ALLOW)"
    },
    {
      name        = "container_id"
      type        = "STRING"
      mode        = "NULLABLE"
      description = "Source container identifier (Data Store ID or Notebook Workspace ID)"
    },
    {
      name        = "document_id"
      type        = "STRING"
      mode        = "NULLABLE"
      description = "Evaluated file name or GCS URI"
    },
    {
      name        = "correlation_id"
      type        = "STRING"
      mode        = "NULLABLE"
      description = "Trace ID linking to Gemini Enterprise AssistToken or Notebook session"
    }
  ])
}
