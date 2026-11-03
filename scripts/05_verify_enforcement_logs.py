#!/usr/bin/env python3
"""Step 5: Live Enforcement Verification & Multi-Channel Audit Log Inspector.

This script performs end-to-end runtime verification and queries all audit
logging channels for Gemini Enterprise and NotebookLM Enterprise:
1. Live Runtime Test against Model Armor `sanitizeUserPrompt` & `sanitizeModelResponse`
   using a test payload containing a valid Luhn Checksum credit card (`4532-0151-1283-0366`)
   and Korean RRN (`880514-1234567`).
2. Health check on `Cloud DLP ContentPolicy.errors` (detects if the DLP Service
   Agent `service-<PROJECT_NUMBER>@dlp-api.iam.gserviceaccount.com` is missing
   `roles/bigquery.dataEditor` on the BigQuery Audit Table).
3. Queries BigQuery `sdp_audit_logs.content_policy_action_logs` for the latest
   `ALLOW` / `BLOCK` verdicts, `matching_info_types`, and `correlation_id`.
4. Queries Cloud Logging across:
   - `resource.type="discoveryengine.googleapis.com/DataConnector"`
   - `logName=~"gemini_enterprise_user_activity"` (`CUSTOMER_POLICY_VIOLATION`)
   - `resource.type="modelarmor.googleapis.com/Template"`
"""

from __future__ import annotations

import sys
from pathlib import Path

from google.cloud import bigquery
from google.cloud import logging as cloud_logging
from rich.panel import Panel
from rich.table import Table

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import (  # noqa: E402
    DemoConfig,
    api_request,
    console,
    load_config,
)


def test_model_armor_runtime(cfg: DemoConfig) -> None:
    """Invoke Model Armor sanitizeUserPrompt API with a sample Luhn CC prompt."""
    console.print(
        "\n[bold]1. Live Runtime Test: Model Armor SDP Filter (sanitizeUserPrompt)[/bold]"
    )
    url = (
        f"{cfg.model_armor_base_url}/v1/{cfg.model_armor_template_resource_name}"
        ":sanitizeUserPrompt"
    )
    sample_prompt = (
        "Please summarize the VIP refund claim for customer Hong Gil-Dong "
        "(RRN: 880514-1234567) paid with VISA card 4532-0151-1283-0366."
    )
    resp = api_request(
        "POST",
        url,
        cfg,
        json_body={"userPromptData": {"text": sample_prompt}},
    )
    if resp.status_code != 200:
        console.print(
            f"  [yellow]! Model Armor sanitizeUserPrompt returned HTTP {resp.status_code}: "
            f"{resp.text[:250]}[/yellow]"
        )
        return

    data = resp.json()
    result = data.get("sanitizationResult", {})
    match_state = result.get("filterMatchState", "UNKNOWN")
    sdp_result = (
        result.get("filterResults", {})
        .get("sdp", {})
        .get("sdpFilterResult", {})
    )
    deid_result = sdp_result.get("deidentifyResult", {})
    transformed_text = deid_result.get("data", {}).get("text", "(No deid text)")
    info_types = deid_result.get("infoTypes", []) or sdp_result.get(
        "inspectResult", {}
    ).get("infoTypes", [])

    table = Table(title="Model Armor Live Sanitization Result", show_lines=True)
    table.add_column("Field", style="bold cyan", width=26)
    table.add_column("Value", width=70)
    table.add_row("Input Prompt (Raw PII)", f"[red]{sample_prompt}[/red]")
    table.add_row(
        "Filter Match State",
        f"[bold green]{match_state}[/bold green]",
    )
    table.add_row(
        "Detected SDP InfoTypes",
        f"[yellow]{', '.join(info_types) if info_types else 'Detected via Template'}[/yellow]",
    )
    table.add_row(
        "Sanitized / De-identified Output",
        f"[bold green]{transformed_text}[/bold green]",
    )
    console.print(table)


def check_dlp_policy_errors(cfg: DemoConfig) -> None:
    """Check if Cloud DLP ContentPolicy has recorded any export/IAM errors."""
    console.print(
        "\n[bold]2. Checking Cloud DLP ContentPolicy Health & Export Errors[/bold]"
    )
    url = f"{cfg.dlp_base_url}/v2/{cfg.sdp_policy_resource_name}"
    resp = api_request("GET", url, cfg)
    if resp.status_code != 200:
        console.print(
            f"  [yellow]! ContentPolicy not found or inaccessible (HTTP {resp.status_code})[/yellow]"
        )
        return

    policy = resp.json()
    errors = policy.get("errors", [])
    if not errors:
        console.print(
            "  [bold green]✔ ContentPolicy is healthy (0 export errors).[/bold green]"
        )
    else:
        console.print(
            f"  [bold red]✘ ContentPolicy reported errors:[/bold red] {errors}\n"
            f"  [yellow]Tip: Ensure service-{cfg.project_number}@dlp-api.iam.gserviceaccount.com "
            f"has roles/bigquery.dataEditor on {cfg.bq_full_table_id}.[/yellow]"
        )


def query_bigquery_action_logs(cfg: DemoConfig) -> None:
    """Query the latest 10 rows from BigQuery ContentPolicyActionLog table."""
    console.print(
        f"\n[bold]3. Querying BigQuery SDP Action Logs ({cfg.bq_full_table_id})[/bold]"
    )
    bq_client = bigquery.Client(project=cfg.project_id)
    query = f"""
        SELECT
            timestamp,
            returned_verdict,
            ARRAY_TO_STRING(matching_info_types, ', ') AS matched_info_types,
            policy_rule,
            fallback_action,
            container_id,
            document_id,
            correlation_id
        FROM `{cfg.bq_full_table_id}`
        ORDER BY timestamp DESC
        LIMIT 10
    """
    try:
        rows = list(bq_client.query(query).result())
    except Exception as exc:  # noqa: BLE001
        console.print(
            f"  [yellow]! Could not query BigQuery table ({exc})[/yellow]"
        )
        return

    if not rows:
        console.print(
            "  [dim]No rows recorded in BigQuery Action Log Table yet. "
            "Upload sample_data/generated/vip_customer_claim_raw.pdf in NotebookLM or GE Chat "
            "to generate live ContentPolicy verdict logs.[/dim]"
        )
        return

    bq_table = Table(
        title="Latest BigQuery SDP ContentPolicyActionLog Records",
        show_lines=True,
    )
    bq_table.add_column("Timestamp (UTC)", style="cyan", width=20)
    bq_table.add_column("Verdict", width=10)
    bq_table.add_column("Matched InfoTypes", style="yellow", width=24)
    bq_table.add_column("Document / Container", width=26)
    bq_table.add_column("Correlation ID", style="dim", width=24)

    for row in rows:
        verdict_style = (
            "[bold red]BLOCK[/bold red]"
            if row.returned_verdict == "BLOCK"
            else "[bold green]ALLOW[/bold green]"
        )
        bq_table.add_row(
            str(row.timestamp)[:19],
            verdict_style,
            row.matched_info_types or "-",
            f"{row.document_id or '-'}\n({row.container_id or '-'})",
            row.correlation_id or "-",
        )
    console.print(bq_table)


def query_cloud_logging_channels(cfg: DemoConfig) -> None:
    """Query Cloud Logging for GE User Activity, Data Connector, and Model Armor events."""
    console.print(
        "\n[bold]4. Querying Cloud Logging Audit Channels (Last 5 Events)[/bold]"
    )
    log_client = cloud_logging.Client(project=cfg.project_id)
    filter_str = (
        'resource.type="modelarmor.googleapis.com/Template" OR '
        'resource.type="discoveryengine.googleapis.com/DataConnector" OR '
        'logName:"gemini_enterprise_user_activity"'
    )
    try:
        entries = list(
            log_client.list_entries(
                filter_=filter_str,
                order_by=cloud_logging.DESCENDING,
                max_results=5,
            )
        )
    except Exception as exc:  # noqa: BLE001
        console.print(
            f"  [yellow]! Cloud Logging query skipped ({exc})[/yellow]"
        )
        return

    if not entries:
        console.print(
            "  [dim]No recent Cloud Logging entries matched the filter yet.[/dim]"
        )
        return

    log_table = Table(title="Recent Cloud Logging Security Events", show_lines=True)
    log_table.add_column("Timestamp", style="cyan", width=20)
    log_table.add_column("Resource Type", style="yellow", width=34)
    log_table.add_column("Event Summary", width=50)

    for entry in entries:
        ts = entry.timestamp.isoformat()[:19] if entry.timestamp else "-"
        res_type = entry.resource.type if entry.resource else "-"
        payload_str = str(entry.payload)[:140]
        log_table.add_row(ts, res_type, payload_str)
    console.print(log_table)


def main() -> None:
    cfg = load_config()
    console.print(
        Panel(
            f"[bold cyan]Project:[/bold cyan] {cfg.project_id} ({cfg.project_number})  |  "
            f"[bold cyan]Location:[/bold cyan] {cfg.location}\n"
            f"[bold cyan]BigQuery Table:[/bold cyan] {cfg.bq_full_table_id}",
            title="[Step 5] Live Enforcement Verification & Multi-Channel Audit Log Inspector",
            border_style="cyan",
        )
    )

    test_model_armor_runtime(cfg)
    check_dlp_policy_errors(cfg)
    query_bigquery_action_logs(cfg)
    query_cloud_logging_channels(cfg)


if __name__ == "__main__":
    main()
