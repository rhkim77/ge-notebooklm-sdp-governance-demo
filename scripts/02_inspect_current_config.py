#!/usr/bin/env python3
"""Step 2: Inspect and Compare GE App vs. NotebookLM Control Plane Security Configs.

This diagnostic script queries the Google Cloud Discovery Engine, Cloud DLP,
and Model Armor APIs to display a side-by-side comparison of:
1. Gemini Enterprise App (Engine / Assistant) configuration:
   - Bound Model Armor Template (Prompt & Response filters)
   - Data Connector / Data Store SDP Content Policy settings
2. Project-level NotebookLM Enterprise configuration (`customerProvidedConfig.notebooklmConfig`):
   - Bound `sensitiveDataProtectionPolicy` (DLP ContentPolicy)
   - Bound `modelArmorConfig` (Prompt & Response Model Armor Templates)
3. Existing Cloud DLP ContentPolicies and Model Armor Templates in the target Location.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from rich.panel import Panel
from rich.table import Table

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import (  # noqa: E402
    DemoConfig,
    api_request,
    console,
    load_config,
)


def fetch_project_customer_config(cfg: DemoConfig) -> dict[str, Any]:
    """Fetch Discovery Engine v1alpha Project resource to inspect notebooklmConfig."""
    url = (
        f"{cfg.discovery_engine_base_url}/v1alpha/projects/{cfg.project_number}"
        f"/locations/{cfg.location}"
    )
    resp = api_request("GET", url, cfg)
    if resp.status_code != 200:
        # Fallback to parent project resource without /locations/{loc}
        alt_url = f"{cfg.discovery_engine_base_url}/v1alpha/projects/{cfg.project_number}"
        resp = api_request("GET", alt_url, cfg)
    if resp.status_code == 200:
        return resp.json()
    return {"_error": f"HTTP {resp.status_code}: {resp.text[:250]}"}


def fetch_ge_engine_assistant_config(cfg: DemoConfig) -> dict[str, Any]:
    """Fetch Gemini Enterprise App (Engine) and default_assistant config if GE_ENGINE_ID is set."""
    if not cfg.ge_engine_id:
        return {"_skipped": "GE_ENGINE_ID not set in .env"}

    assistant_url = (
        f"{cfg.discovery_engine_base_url}/v1alpha/projects/{cfg.project_id}"
        f"/locations/{cfg.location}/collections/default_collection"
        f"/engines/{cfg.ge_engine_id}/assistants/default_assistant"
    )
    resp = api_request("GET", assistant_url, cfg)
    if resp.status_code == 200:
        return resp.json()
    return {"_error": f"HTTP {resp.status_code}: {resp.text[:250]}"}


def fetch_dlp_content_policy(cfg: DemoConfig) -> dict[str, Any]:
    """Fetch Cloud DLP ContentPolicy resource if it exists."""
    url = f"{cfg.dlp_base_url}/v2/{cfg.sdp_policy_resource_name}"
    resp = api_request("GET", url, cfg)
    if resp.status_code == 200:
        return resp.json()
    return {"_not_found": f"HTTP {resp.status_code}"}


def fetch_model_armor_template(cfg: DemoConfig) -> dict[str, Any]:
    """Fetch Model Armor Template resource if it exists."""
    url = f"{cfg.model_armor_base_url}/v1/{cfg.model_armor_template_resource_name}"
    resp = api_request("GET", url, cfg)
    if resp.status_code == 200:
        return resp.json()
    return {"_not_found": f"HTTP {resp.status_code}"}


def main() -> None:
    cfg = load_config()
    console.print(
        Panel(
            f"[bold cyan]Project:[/bold cyan] {cfg.project_id} ({cfg.project_number})  |  "
            f"[bold cyan]Location:[/bold cyan] {cfg.location}\n"
            f"[bold cyan]Target GE Engine ID:[/bold cyan] {cfg.ge_engine_id or '(Not specified)'}",
            title="[Step 2] Control Plane Security Configuration Inspector (GE App vs. NotebookLM)",
            border_style="cyan",
        )
    )

    project_data = fetch_project_customer_config(cfg)
    assistant_data = fetch_ge_engine_assistant_config(cfg)
    dlp_policy = fetch_dlp_content_policy(cfg)
    armor_tmpl = fetch_model_armor_template(cfg)

    # Extract NotebookLM CustomerProvidedConfig
    cust_cfg = project_data.get("customerProvidedConfig", {})
    nlm_cfg = cust_cfg.get("notebooklmConfig", {})
    nlm_sdp = (
        nlm_cfg.get("dataProtectionPolicy", {})
        .get("sensitiveDataProtectionPolicy", {})
        .get("sdpPolicy", "")
    )
    nlm_armor_prompt = (
        nlm_cfg.get("modelArmorConfig", {}).get("promptTemplate", "")
    )
    nlm_armor_resp = (
        nlm_cfg.get("modelArmorConfig", {}).get("responseTemplate", "")
    )

    # Extract GE Assistant Config
    ge_armor_cfg = assistant_data.get("customerPolicy", {}).get(
        "modelArmorConfig", {}
    )
    ge_armor_prompt = ge_armor_cfg.get("promptTemplate", "")
    ge_armor_resp = ge_armor_cfg.get("responseTemplate", "")

    # 1. Print Side-by-Side Control Plane Comparison Table
    comp_table = Table(
        title="Control Plane Binding Comparison: Gemini Enterprise App vs. NotebookLM Enterprise",
        show_lines=True,
    )
    comp_table.add_column("Security Control Layer", style="bold white", width=30)
    comp_table.add_column(
        f"Gemini Enterprise App\n(Engine: {cfg.ge_engine_id or 'N/A'})",
        width=38,
    )
    comp_table.add_column(
        f"NotebookLM Enterprise\n(Project {cfg.project_number} / {cfg.location})",
        width=38,
    )

    # Layer 1: SDP Content Policy (File Upload / Connector Scan)
    ge_sdp_str = (
        "[yellow]Configured per Data Connector / Engine[/yellow]"
        if cfg.ge_engine_id
        else "[dim]Set GE_ENGINE_ID in .env to inspect[/dim]"
    )
    nlm_sdp_str = (
        f"[bold green]BOUND[/bold green]\n[cyan]{nlm_sdp}[/cyan]"
        if nlm_sdp
        else "[bold red]UNBOUND (NULL)[/bold red]\n"
        "[dim]Direct file uploads are NOT scanned by SDP![/dim]"
    )
    comp_table.add_row(
        "Layer 1: SDP Content Policy\n(Direct Upload & Source Scan)",
        ge_sdp_str,
        nlm_sdp_str,
    )

    # Layer 2: Model Armor Prompt & Response Templates
    if "_skipped" in assistant_data:
        ge_armor_str = "[dim]GE_ENGINE_ID not set in .env[/dim]"
    elif ge_armor_prompt or ge_armor_resp:
        ge_armor_str = (
            f"[bold green]BOUND[/bold green]\n"
            f"Prompt: [cyan]{ge_armor_prompt}[/cyan]\n"
            f"Response: [cyan]{ge_armor_resp}[/cyan]"
        )
    else:
        ge_armor_str = "[bold yellow]UNBOUND on default_assistant[/bold yellow]"

    if nlm_armor_prompt or nlm_armor_resp:
        nlm_armor_str = (
            f"[bold green]BOUND[/bold green]\n"
            f"Prompt: [cyan]{nlm_armor_prompt}[/cyan]\n"
            f"Response: [cyan]{nlm_armor_resp}[/cyan]"
        )
    else:
        nlm_armor_str = (
            "[bold red]UNBOUND (NULL)[/bold red]\n"
            "[dim]NotebookLM Chat Prompts & Responses bypass Model Armor![/dim]"
        )

    comp_table.add_row(
        "Layer 2: Model Armor Filter\n(Prompt & Response Guardrail)",
        ge_armor_str,
        nlm_armor_str,
    )

    # Layer 3: GCS "Add content to..." Path Behavior
    comp_table.add_row(
        "Layer 3: GCS Data Store Source\n('Add content to...' vs. Chat)",
        "[green]Protected in Assistant Chat[/green]\n"
        "[dim](Model Armor SDP Filter inspects retrieved context/response)[/dim]",
        "[bold yellow]Requires Upstream GCS DLP Masking[/bold yellow]\n"
        "[dim]('Add content to...' copies indexed GCS docs directly into Notebook)[/dim]",
    )

    console.print("\n", comp_table)

    # 2. Print Resource Existence & Health Summary
    res_table = Table(
        title=f"Policy & Template Resource Status in Location '{cfg.location}'",
        show_lines=True,
    )
    res_table.add_column("Resource Type", style="bold cyan", width=26)
    res_table.add_column("Target Resource Name", width=48)
    res_table.add_column("Current Status & Details", width=32)

    if "_not_found" in dlp_policy:
        res_table.add_row(
            "Cloud DLP ContentPolicy",
            cfg.sdp_policy_resource_name,
            "[bold yellow]NOT CREATED YET[/bold yellow]",
        )
    else:
        errors = dlp_policy.get("errors", [])
        err_str = (
            f"[bold red]Errors: {errors}[/bold red]"
            if errors
            else "[green]Healthy (0 errors)[/green]"
        )
        res_table.add_row(
            "Cloud DLP ContentPolicy",
            cfg.sdp_policy_resource_name,
            f"[bold green]EXISTS[/bold green]\n{err_str}",
        )

    if "_not_found" in armor_tmpl:
        res_table.add_row(
            "Model Armor Template",
            cfg.model_armor_template_resource_name,
            "[bold yellow]NOT CREATED YET[/bold yellow]",
        )
    else:
        sdp_enabled = (
            armor_tmpl.get("filterConfig", {})
            .get("sdpSettings", {})
            .get("advancedSdpSettings", {})
            or armor_tmpl.get("filterConfig", {})
            .get("sdpSettings", {})
            .get("basicSdpSettings", {})
        )
        res_table.add_row(
            "Model Armor Template",
            cfg.model_armor_template_resource_name,
            f"[bold green]EXISTS[/bold green]\nSDP Filter: {bool(sdp_enabled)}",
        )

    console.print("\n", res_table)

    if not nlm_sdp or not nlm_armor_prompt:
        console.print(
            Panel(
                "[bold yellow]Root Cause Diagnosis Confirmed:[/bold yellow]\n"
                "• Project-level [cyan]customerProvidedConfig.notebooklmConfig[/cyan] is currently "
                "[bold red]UNBOUND[/bold red].\n"
                "• Policies configured on a Gemini Enterprise App ([cyan]engines/{id}[/cyan]) "
                "are NOT automatically inherited by NotebookLM Enterprise.\n\n"
                "👉 Run [bold green]make apply-policy[/bold green] "
                "([cyan]python scripts/03_apply_sdp_and_armor.py[/cyan]) to create and bind "
                "both the SDP Content Policy and Model Armor Template.",
                title="Diagnostic Summary",
                border_style="yellow",
            )
        )
    else:
        console.print(
            Panel(
                "[bold green]Both SDP Content Policy and Model Armor Template are bound to "
                "NotebookLM Enterprise![/bold green]\n"
                "👉 Next: Run [bold cyan]make mask-gcs[/bold cyan] to sanitize GCS Data Store "
                "documents, or [bold cyan]make verify-logs[/bold cyan] to audit BigQuery/Cloud Logging.",
                title="Diagnostic Summary",
                border_style="green",
            )
        )


if __name__ == "__main__":
    main()
