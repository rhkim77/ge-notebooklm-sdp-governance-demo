#!/usr/bin/env python3
"""Step 3: Create & Bind Cloud DLP ContentPolicy and Model Armor Template.

This remediation script automates Layers 1 and 2 of the security architecture:
1. Creates (or updates) Cloud DLP `InspectTemplate` and `DeidentifyTemplate`
   covering `CREDIT_CARD_NUMBER` (Luhn-validated), `KOREA_RRN` (Korean Resident
   Registration Number), and `PHONE_NUMBER`.
2. Creates (or updates) the Cloud DLP `ContentPolicy` resource in the target
   Location (`global` or `us`) with:
   - `FALLBACK_ACTION_INPUT_TOO_LARGE = BLOCK` (prevents oversize file bypass)
   - `logToBigQuery` pointing to `sdp_audit_logs.content_policy_action_logs`
3. Creates (or updates) the `Model Armor Template` with:
   - `sdpSettings` (Sensitive Data Protection Filter enabled)
   - `piAndJailbreakFilterSettings` (Prompt Injection & Jailbreak Filter enabled)
   - `logSanitizeOperations = true`
4. Binds both resources to Project-level `NotebookLM Enterprise` via
   `PATCH /v1alpha/projects/{PROJECT_NUMBER}/locations/{LOCATION}?update_mask=customerProvidedConfig`
   and optionally to the Gemini Enterprise App `default_assistant`.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from rich.panel import Panel
from rich.progress import Progress

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import (  # noqa: E402
    DemoConfig,
    api_request,
    console,
    load_config,
)


def ensure_dlp_templates(cfg: DemoConfig) -> tuple[str, str]:
    """Create or update Cloud DLP InspectTemplate and DeidentifyTemplate."""
    parent = f"projects/{cfg.project_id}/locations/{cfg.location}"

    # 1. InspectTemplate
    inspect_name = f"{parent}/inspectTemplates/{cfg.dlp_inspect_template_id}"
    inspect_payload = {
        "displayName": "GE & NotebookLM SDP Inspect Template",
        "description": "Detects Credit Cards (Luhn), Korean RRN, and Phone Numbers",
        "inspectConfig": {
            "infoTypes": [
                {"name": "CREDIT_CARD_NUMBER"},
                {"name": "KOREA_RRN"},
                {"name": "PHONE_NUMBER"},
            ],
            "minLikelihood": "POSSIBLE",
            "includeQuote": False,
        },
    }
    resp = api_request("GET", f"{cfg.dlp_base_url}/v2/{inspect_name}", cfg)
    if resp.status_code == 200:
        api_request(
            "PATCH",
            f"{cfg.dlp_base_url}/v2/{inspect_name}",
            cfg,
            json_body={"inspectTemplate": inspect_payload},
        )
        console.print(
            f"  [green]✔[/green] Updated DLP InspectTemplate: [bold]{inspect_name}[/bold]"
        )
    else:
        create_resp = api_request(
            "POST",
            f"{cfg.dlp_base_url}/v2/{parent}/inspectTemplates",
            cfg,
            json_body={
                "templateId": cfg.dlp_inspect_template_id,
                "inspectTemplate": inspect_payload,
            },
        )
        if create_resp.status_code in (200, 201):
            console.print(
                f"  [bold green]+ Created DLP InspectTemplate:[/bold green] [bold]{inspect_name}[/bold]"
            )
        else:
            console.print(
                f"  [yellow]! InspectTemplate response ({create_resp.status_code}): "
                f"{create_resp.text[:200]}[/yellow]"
            )

    # 2. DeidentifyTemplate
    deid_name = f"{parent}/deidentifyTemplates/{cfg.dlp_deidentify_template_id}"
    deid_payload = {
        "displayName": "GE & NotebookLM SDP Deidentify Template",
        "description": "Replaces detected PII InfoTypes with [REDACTED_<INFOTYPE>] tags",
        "deidentifyConfig": {
            "infoTypeTransformations": {
                "transformations": [
                    {
                        "infoTypes": [
                            {"name": "CREDIT_CARD_NUMBER"},
                            {"name": "KOREA_RRN"},
                            {"name": "PHONE_NUMBER"},
                        ],
                        "primitiveTransformation": {
                            "replaceWithInfoTypeConfig": {}
                        },
                    }
                ]
            }
        },
    }
    resp = api_request("GET", f"{cfg.dlp_base_url}/v2/{deid_name}", cfg)
    if resp.status_code == 200:
        api_request(
            "PATCH",
            f"{cfg.dlp_base_url}/v2/{deid_name}",
            cfg,
            json_body={"deidentifyTemplate": deid_payload},
        )
        console.print(
            f"  [green]✔[/green] Updated DLP DeidentifyTemplate: [bold]{deid_name}[/bold]"
        )
    else:
        create_resp = api_request(
            "POST",
            f"{cfg.dlp_base_url}/v2/{parent}/deidentifyTemplates",
            cfg,
            json_body={
                "templateId": cfg.dlp_deidentify_template_id,
                "deidentifyTemplate": deid_payload,
            },
        )
        if create_resp.status_code in (200, 201):
            console.print(
                f"  [bold green]+ Created DLP DeidentifyTemplate:[/bold green] [bold]{deid_name}[/bold]"
            )
        else:
            console.print(
                f"  [yellow]! DeidentifyTemplate response ({create_resp.status_code}): "
                f"{create_resp.text[:200]}[/yellow]"
            )

    return inspect_name, deid_name


def ensure_sdp_content_policy(cfg: DemoConfig) -> str:
    """Create or update Cloud DLP ContentPolicy with BLOCK fallback and BigQuery logging."""
    parent = f"projects/{cfg.project_id}/locations/{cfg.location}"
    policy_name = cfg.sdp_policy_resource_name

    fallback_enum = (
        "FALLBACK_ACTION_INPUT_TOO_LARGE_BLOCK"
        if cfg.sdp_fallback_action == "BLOCK"
        else "FALLBACK_ACTION_INPUT_TOO_LARGE_ALLOW"
    )

    policy_body: dict[str, Any] = {
        "displayName": "GE & NotebookLM Enterprise SDP Content Policy",
        "description": (
            "Blocks uploads and connector sources containing Credit Card Numbers "
            "or Korean RRN, and logs all verdicts to BigQuery."
        ),
        "contentPolicyConfig": {
            "rules": [
                {
                    "infoTypeRule": {
                        "infoTypes": [
                            {"name": "CREDIT_CARD_NUMBER"},
                            {"name": "KOREA_RRN"},
                        ],
                        "minLikelihood": "POSSIBLE",
                    },
                    "action": {"block": {}},
                }
            ],
            "fallbackActions": {
                "fallbackActionInputTooLarge": fallback_enum,
            },
        },
        "loggingConfigs": [
            {
                "logToBigQuery": {
                    "bigQueryTable": {
                        "projectId": cfg.project_id,
                        "datasetId": cfg.bq_dataset_id,
                        "tableId": cfg.bq_table_id,
                    }
                }
            }
        ],
    }

    get_resp = api_request("GET", f"{cfg.dlp_base_url}/v2/{policy_name}", cfg)
    if get_resp.status_code == 200:
        patch_resp = api_request(
            "PATCH",
            f"{cfg.dlp_base_url}/v2/{policy_name}",
            cfg,
            json_body={"contentPolicy": policy_body},
        )
        if patch_resp.status_code == 200:
            console.print(
                f"  [green]✔[/green] Updated Cloud DLP ContentPolicy: [bold]{policy_name}[/bold]"
            )
        else:
            console.print(
                f"  [yellow]! ContentPolicy PATCH status {patch_resp.status_code}: "
                f"{patch_resp.text[:250]}[/yellow]"
            )
    else:
        create_resp = api_request(
            "POST",
            f"{cfg.dlp_base_url}/v2/{parent}/contentPolicies",
            cfg,
            params={"contentPolicyId": cfg.sdp_policy_id},
            json_body={"contentPolicy": policy_body},
        )
        if create_resp.status_code in (200, 201):
            console.print(
                f"  [bold green]+ Created Cloud DLP ContentPolicy:[/bold green] "
                f"[bold]{policy_name}[/bold]"
            )
        else:
            console.print(
                f"  [yellow]! ContentPolicy POST status {create_resp.status_code}: "
                f"{create_resp.text[:300]}[/yellow]\n"
                f"  [dim]Note: If ContentPolicy creation requires Console UI in your tenant, "
                f"create '{cfg.sdp_policy_id}' in Security > Sensitive Data Protection and re-run.[/dim]"
            )
    return policy_name


def ensure_model_armor_template(
    cfg: DemoConfig, inspect_template_name: str, deidentify_template_name: str
) -> str:
    """Create or update Model Armor Template with Advanced SDP Filter enabled."""
    parent = f"projects/{cfg.project_id}/locations/{cfg.location}"
    tmpl_name = cfg.model_armor_template_resource_name

    template_body: dict[str, Any] = {
        "filterConfig": {
            "piAndJailbreakFilterSettings": {
                "filterEnforcement": "ENABLED",
                "confidenceLevel": "MEDIUM_AND_ABOVE",
            },
            "sdpSettings": {
                "advancedSdpSettings": {
                    "inspectTemplate": inspect_template_name,
                    "deidentifyTemplate": deidentify_template_name,
                }
            },
        },
        "templateMetadata": {
            "logSanitizeOperations": True,
            "logTemplateOperations": True,
        },
    }

    get_resp = api_request(
        "GET", f"{cfg.model_armor_base_url}/v1/{tmpl_name}", cfg
    )
    if get_resp.status_code == 200:
        patch_resp = api_request(
            "PATCH",
            f"{cfg.model_armor_base_url}/v1/{tmpl_name}",
            cfg,
            params={"updateMask": "filterConfig,templateMetadata"},
            json_body=template_body,
        )
        if patch_resp.status_code == 200:
            console.print(
                f"  [green]✔[/green] Updated Model Armor Template: [bold]{tmpl_name}[/bold]"
            )
        else:
            console.print(
                f"  [yellow]! Model Armor PATCH status {patch_resp.status_code}: "
                f"{patch_resp.text[:250]}[/yellow]"
            )
    else:
        create_resp = api_request(
            "POST",
            f"{cfg.model_armor_base_url}/v1/{parent}/templates",
            cfg,
            params={"templateId": cfg.model_armor_template_id},
            json_body=template_body,
        )
        if create_resp.status_code in (200, 201):
            console.print(
                f"  [bold green]+ Created Model Armor Template:[/bold green] "
                f"[bold]{tmpl_name}[/bold]"
            )
        else:
            console.print(
                f"  [yellow]! Model Armor POST status {create_resp.status_code}: "
                f"{create_resp.text[:250]}[/yellow]"
            )
    return tmpl_name


def bind_notebooklm_project_config(
    cfg: DemoConfig, sdp_policy_name: str, armor_template_name: str
) -> bool:
    """Bind SDP ContentPolicy and Model Armor Template to Project-level NotebookLM config."""
    patch_body = {
        "customerProvidedConfig": {
            "notebooklmConfig": {
                "dataProtectionPolicy": {
                    "sensitiveDataProtectionPolicy": {
                        "policy": sdp_policy_name,
                    }
                },
                "modelArmorConfig": {
                    "userPromptTemplate": armor_template_name,
                    "responseTemplate": armor_template_name,
                    "failureMode": "FAIL_CLOSED",
                },
            }
        }
    }

    url = (
        f"{cfg.discovery_engine_base_url}/v1alpha/projects/{cfg.project_number}"
        f"/locations/{cfg.location}"
    )
    resp = api_request(
        "PATCH",
        url,
        cfg,
        params={"updateMask": "customerProvidedConfig"},
        json_body=patch_body,
    )
    if resp.status_code != 200:
        # Fallback to top-level projects/{project_number} endpoint
        alt_url = f"{cfg.discovery_engine_base_url}/v1alpha/projects/{cfg.project_number}"
        resp = api_request(
            "PATCH",
            alt_url,
            cfg,
            params={"updateMask": "customerProvidedConfig"},
            json_body=patch_body,
        )

    if resp.status_code == 200:
        console.print(
            "  [bold green]✔ Bound SDP Content Policy & Model Armor Template to "
            "Project-level NotebookLM Enterprise![/bold green]"
        )
        return True

    console.print(
        f"  [bold red]✘ Failed to PATCH NotebookLM customerProvidedConfig "
        f"(HTTP {resp.status_code}):[/bold red]\n  {resp.text[:350]}"
    )
    return False


def bind_ge_assistant_armor(cfg: DemoConfig, armor_template_name: str) -> None:
    """Optionally bind Model Armor Template to GE App default_assistant."""
    if not cfg.ge_engine_id:
        console.print(
            "  [dim]• Skipping GE App binding (GE_ENGINE_ID not set in .env)[/dim]"
        )
        return

    assistant_url = (
        f"{cfg.discovery_engine_base_url}/v1alpha/projects/{cfg.project_id}"
        f"/locations/{cfg.location}/collections/default_collection"
        f"/engines/{cfg.ge_engine_id}/assistants/default_assistant"
    )
    patch_body = {
        "customerPolicy": {
            "modelArmorConfig": {
                "promptTemplate": armor_template_name,
                "responseTemplate": armor_template_name,
            }
        }
    }
    resp = api_request(
        "PATCH",
        assistant_url,
        cfg,
        params={"updateMask": "customerPolicy"},
        json_body=patch_body,
    )
    if resp.status_code == 200:
        console.print(
            f"  [bold green]✔ Bound Model Armor Template to GE App Assistant:[/bold green] "
            f"engines/{cfg.ge_engine_id}/assistants/default_assistant"
        )
    else:
        console.print(
            f"  [yellow]! GE Assistant PATCH status {resp.status_code}: "
            f"{resp.text[:250]}[/yellow]"
        )


def main() -> None:
    cfg = load_config()
    console.print(
        Panel(
            f"[bold cyan]Project:[/bold cyan] {cfg.project_id} ({cfg.project_number})  |  "
            f"[bold cyan]Location:[/bold cyan] {cfg.location}\n"
            f"[bold cyan]SDP ContentPolicy:[/bold cyan] {cfg.sdp_policy_resource_name}\n"
            f"[bold cyan]Model Armor Template:[/bold cyan] {cfg.model_armor_template_resource_name}",
            title="[Step 3] Apply & Bind SDP Content Policy and Model Armor Template",
            border_style="cyan",
        )
    )

    console.print("\n[bold]1. Provisioning Cloud DLP Inspect & Deidentify Templates[/bold]")
    inspect_tmpl, deid_tmpl = ensure_dlp_templates(cfg)

    console.print("\n[bold]2. Provisioning Cloud DLP ContentPolicy (Fallback=BLOCK + BigQuery Log)[/bold]")
    sdp_policy_name = ensure_sdp_content_policy(cfg)

    console.print("\n[bold]3. Provisioning Model Armor Template (SDP + Prompt Injection Filters)[/bold]")
    armor_tmpl_name = ensure_model_armor_template(cfg, inspect_tmpl, deid_tmpl)

    console.print("\n[bold]4. Binding Policies to Both NotebookLM & Gemini Enterprise Control Planes[/bold]")
    bind_notebooklm_project_config(cfg, sdp_policy_name, armor_tmpl_name)
    bind_ge_assistant_armor(cfg, armor_tmpl_name)

    if cfg.wait_for_cache_ttl:
        console.print(
            "\n[bold yellow]Waiting 10 minutes for NotebookLM CustomerConfigurationCache "
            "TTL expiration (WAIT_FOR_CACHE_TTL=true)...[/bold yellow]"
        )
        with Progress() as progress:
            task = progress.add_task("[cyan]Cache TTL Countdown...", total=600)
            for _ in range(600):
                time.sleep(1)
                progress.update(task, advance=1)

    console.print(
        Panel(
            "[bold green]Control Plane Security Remediation Applied![/bold green]\n"
            "• [bold]Important Operational Note:[/bold] If NotebookLM Enterprise was accessed "
            "within the last 10 minutes, its in-memory [cyan]CustomerConfigurationCache[/cyan] "
            "may take up to [bold]10 minutes[/bold] to refresh.\n"
            "• While the cache refreshes, run [bold cyan]make mask-gcs[/bold cyan] "
            "([cyan]python scripts/04_run_gcs_dlp_masking.py[/cyan]) to sanitize the "
            "GCS Data Store documents.",
            title="Step 3 Completed",
            border_style="green",
        )
    )


if __name__ == "__main__":
    main()
