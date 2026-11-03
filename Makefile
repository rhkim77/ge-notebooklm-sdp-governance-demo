# ==============================================================================
# Makefile — Gemini Enterprise & NotebookLM SDP Governance Demo
# ==============================================================================

PYTHON ?= uv run python
TF_DIR := terraform

.PHONY: help install prepare-assets inspect apply-policy mask-gcs verify-logs reset-policy demo-all tf-init tf-plan tf-apply

help:
	@echo "================================================================================"
	@echo " Gemini Enterprise & NotebookLM SDP Governance Demo — Command Reference"
	@echo "================================================================================"
	@echo "  make install         : Install Python dependencies via uv (or pip)"
	@echo "  make prepare-assets  : [Step 1] Create Raw/Masked GCS Buckets, BigQuery Audit"
	@echo "                         Table, and upload sample PDF/TXT files (valid Luhn CC)"
	@echo "  make inspect         : [Step 2] Compare GE App vs. NotebookLM Control Plane"
	@echo "                         SDP & Model Armor configuration (Diagnose Gap)"
	@echo "  make apply-policy    : [Step 3] Create DLP ContentPolicy & Model Armor Template"
	@echo "                         and bind to both GE App & Project NotebookLM Config"
	@echo "  make mask-gcs        : [Step 4] Run Upstream GCS DLP De-identification Pipeline"
	@echo "                         (Raw Bucket -> DLP Masking -> Masked Bucket -> Data Store)"
	@echo "  make verify-logs     : [Step 5] Test Model Armor Runtime & Query BigQuery /"
	@echo "                         Cloud Logging SDP Audit Trails"
	@echo "  make reset-policy    : [Reset] Unbind NotebookLM Project-level SDP/Model Armor"
	@echo "                         to repeat the 'Before vs. After' live demo"
	@echo "  make tf-init         : (Optional) Initialize Terraform in ./terraform"
	@echo "  make tf-apply        : (Optional) Provision base GCP APIs, IAM, GCS & BigQuery"
	@echo "================================================================================"

install:
	@if command -v uv >/dev/null 2>&1; then \
		uv sync; \
	else \
		python3 -m venv .venv && .venv/bin/pip install -e .; \
	fi

prepare-assets:
	$(PYTHON) scripts/01_prepare_demo_assets.py

inspect:
	$(PYTHON) scripts/02_inspect_current_config.py

apply-policy:
	$(PYTHON) scripts/03_apply_sdp_and_armor.py

mask-gcs:
	$(PYTHON) scripts/04_run_gcs_dlp_masking.py

verify-logs:
	$(PYTHON) scripts/05_verify_enforcement_logs.py

reset-policy:
	$(PYTHON) scripts/06_reset_demo_policies.py

demo-all: prepare-assets inspect apply-policy mask-gcs verify-logs

tf-init:
	cd $(TF_DIR) && terraform init

tf-plan:
	cd $(TF_DIR) && terraform plan

tf-apply:
	cd $(TF_DIR) && terraform apply
