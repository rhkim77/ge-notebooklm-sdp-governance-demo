output "project_number" {
  description = "Resolved Google Cloud Project Number"
  value       = data.google_project.current.number
}

output "raw_bucket_url" {
  description = "GCS URI for Raw (Unmasked) Sample Documents"
  value       = "gs://${google_storage_bucket.raw_docs.name}"
}

output "masked_bucket_url" {
  description = "GCS URI for Masked (Cloud DLP De-identified) Documents"
  value       = "gs://${google_storage_bucket.masked_docs.name}"
}

output "bigquery_audit_table" {
  description = "Full BigQuery Table ID for SDP ContentPolicyActionLog"
  value       = "${var.project_id}.${google_bigquery_dataset.sdp_audit_logs.dataset_id}.${google_bigquery_table.content_policy_action_logs.table_id}"
}
