#!/usr/bin/env python3
"""Shared configuration, authentication, endpoint builders, and Luhn validator."""

from __future__ import annotations

import dataclasses
import os
import sys
from pathlib import Path
from typing import Any

import google.auth
from google.auth.transport.requests import Request
from google.cloud import resourcemanager_v3
import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

console = Console()

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DATA_DIR = REPO_ROOT / "sample_data"
GENERATED_DATA_DIR = SAMPLE_DATA_DIR / "generated"


@dataclasses.dataclass
class DemoConfig:
    """Centralized configuration loaded from .env or environment variables."""

    project_id: str
    project_number: str
    location: str
    bucket_location: str
    bq_location: str
    ge_engine_id: str
    ge_data_store_id: str
    raw_bucket_name: str
    masked_bucket_name: str
    bq_dataset_id: str
    bq_table_id: str
    sdp_policy_id: str
    dlp_inspect_template_id: str
    dlp_deidentify_template_id: str
    model_armor_template_id: str
    sdp_fallback_action: str
    wait_for_cache_ttl: bool

    @property
    def discovery_engine_base_url(self) -> str:
        """Return regional or global Discovery Engine endpoint base URL."""
        if self.location == "global":
            return "https://discoveryengine.googleapis.com"
        return f"https://{self.location}-discoveryengine.googleapis.com"

    @property
    def dlp_base_url(self) -> str:
        """Return Cloud DLP v2 REST API base URL."""
        return "https://dlp.googleapis.com"

    @property
    def model_armor_base_url(self) -> str:
        """Return regional or global Model Armor v1 REST API base URL."""
        if self.location == "global":
            return "https://modelarmor.googleapis.com"
        return f"https://modelarmor.{self.location}.rep.googleapis.com"

    @property
    def sdp_policy_resource_name(self) -> str:
        """Return full Cloud DLP ContentPolicy resource name."""
        return (
            f"projects/{self.project_id}/locations/{self.location}"
            f"/contentPolicies/{self.sdp_policy_id}"
        )

    @property
    def model_armor_template_resource_name(self) -> str:
        """Return full Model Armor Template resource name."""
        return (
            f"projects/{self.project_id}/locations/{self.location}"
            f"/templates/{self.model_armor_template_id}"
        )

    @property
    def bq_full_table_id(self) -> str:
        """Return project.dataset.table identifier."""
        return f"{self.project_id}.{self.bq_dataset_id}.{self.bq_table_id}"


def resolve_project_number(project_id: str) -> str:
    """Resolve numeric GCP Project Number from Project ID via Resource Manager API."""
    try:
        client = resourcemanager_v3.ProjectsClient()
        project = client.get_project(name=f"projects/{project_id}")
        # project.name is formatted as 'projects/123456789012'
        return project.name.split("/")[-1]
    except Exception as exc:  # noqa: BLE001
        console.print(
            f"[yellow]Warning: Could not auto-resolve PROJECT_NUMBER via API ({exc}). "
            "Please set PROJECT_NUMBER in .env if needed.[/yellow]"
        )
        return project_id


def load_config() -> DemoConfig:
    """Load configuration from .env file and validate required parameters."""
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()

    project_id = os.getenv("PROJECT_ID", "").strip()
    if not project_id or project_id == "your-gcp-project-id":
        console.print(
            Panel(
                "[bold red]Missing PROJECT_ID configuration![/bold red]\n\n"
                "Please copy [cyan].env.example[/cyan] to [cyan].env[/cyan] and set your "
                "Google Cloud [bold]PROJECT_ID[/bold]:\n"
                "  [green]cp .env.example .env[/green]",
                title="Configuration Error",
                border_style="red",
            )
        )
        sys.exit(1)

    project_number = os.getenv("PROJECT_NUMBER", "").strip()
    if not project_number:
        project_number = resolve_project_number(project_id)

    location = os.getenv("LOCATION", "global").strip().lower()
    bucket_location = os.getenv("BUCKET_LOCATION", "us-central1").strip()
    bq_location = os.getenv("BQ_LOCATION", "US").strip()

    ge_engine_id = os.getenv("GE_ENGINE_ID", "").strip()
    if ge_engine_id == "your-ge-engine-id":
        ge_engine_id = ""

    ge_data_store_id = os.getenv("GE_DATA_STORE_ID", "").strip()
    if ge_data_store_id == "your-gcs-datastore-id":
        ge_data_store_id = ""

    raw_bucket_name = (
        os.getenv("RAW_BUCKET_NAME", "").strip()
        or f"{project_id}-ge-sdp-raw-docs"
    )
    masked_bucket_name = (
        os.getenv("MASKED_BUCKET_NAME", "").strip()
        or f"{project_id}-ge-sdp-masked-docs"
    )

    return DemoConfig(
        project_id=project_id,
        project_number=project_number,
        location=location,
        bucket_location=bucket_location,
        bq_location=bq_location,
        ge_engine_id=ge_engine_id,
        ge_data_store_id=ge_data_store_id,
        raw_bucket_name=raw_bucket_name,
        masked_bucket_name=masked_bucket_name,
        bq_dataset_id=os.getenv("BQ_DATASET_ID", "sdp_audit_logs").strip(),
        bq_table_id=os.getenv(
            "BQ_TABLE_ID", "content_policy_action_logs"
        ).strip(),
        sdp_policy_id=os.getenv(
            "SDP_POLICY_ID", "ge-notebooklm-sdp-policy"
        ).strip(),
        dlp_inspect_template_id=os.getenv(
            "DLP_INSPECT_TEMPLATE_ID", "ge-notebooklm-inspect-tmpl"
        ).strip(),
        dlp_deidentify_template_id=os.getenv(
            "DLP_DEIDENTIFY_TEMPLATE_ID", "ge-notebooklm-deid-tmpl"
        ).strip(),
        model_armor_template_id=os.getenv(
            "MODEL_ARMOR_TEMPLATE_ID", "ge-notebooklm-armor-tmpl"
        ).strip(),
        sdp_fallback_action=os.getenv("SDP_FALLBACK_ACTION", "BLOCK")
        .strip()
        .upper(),
        wait_for_cache_ttl=os.getenv("WAIT_FOR_CACHE_TTL", "false")
        .strip()
        .lower()
        in ("true", "1", "yes"),
    )


def get_auth_headers(quota_project_id: str | None = None) -> dict[str, str]:
    """Obtain OAuth2 Bearer token from Application Default Credentials (ADC)."""
    credentials, default_project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(Request())
    headers = {
        "Authorization": f"Bearer {credentials.token}",
        "Content-Type": "application/json",
    }
    target_project = quota_project_id or default_project
    if target_project:
        headers["x-goog-user-project"] = target_project
    return headers


def api_request(
    method: str,
    url: str,
    cfg: DemoConfig,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> httpx.Response:
    """Perform an authenticated HTTP request against Google Cloud REST APIs."""
    headers = get_auth_headers(cfg.project_id)
    with httpx.Client(timeout=timeout) as client:
        return client.request(
            method=method,
            url=url,
            headers=headers,
            json=json_body,
            params=params,
        )


def is_valid_luhn(card_number: str) -> bool:
    """Verify whether a credit card string satisfies the Luhn Checksum algorithm."""
    digits = [int(ch) for ch in card_number if ch.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for idx, digit in enumerate(digits):
        if idx % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0
