variable "project_id" {
  type        = string
  description = "Google Cloud Project ID for the Gemini Enterprise & NotebookLM SDP Demo"
}

variable "region" {
  type        = string
  description = "Default Google Cloud Region for GCS Buckets (e.g., us-central1, asia-northeast3)"
  default     = "us-central1"
}

variable "bq_location" {
  type        = string
  description = "BigQuery Dataset location for SDP ContentPolicyActionLog (e.g., US, global, asia-northeast3)"
  default     = "US"
}

variable "raw_bucket_name" {
  type        = string
  description = "Optional custom name for Raw GCS Bucket (defaults to <project_id>-ge-sdp-raw-docs)"
  default     = ""
}

variable "masked_bucket_name" {
  type        = string
  description = "Optional custom name for Masked GCS Bucket (defaults to <project_id>-ge-sdp-masked-docs)"
  default     = ""
}

variable "bq_dataset_id" {
  type        = string
  description = "BigQuery Dataset ID for SDP ContentPolicy Action Logs"
  default     = "sdp_audit_logs"
}

variable "bq_table_id" {
  type        = string
  description = "BigQuery Table ID for SDP ContentPolicy Action Logs"
  default     = "content_policy_action_logs"
}
