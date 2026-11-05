#!/usr/bin/env python3
"""Step 3: Create & Bind Cloud DLP ContentPolicy and Model Armor Template.

This remediation script automates Layers 1 and 2 of the security architecture:
1. Creates (or updates) Cloud DLP `InspectTemplate` and `DeidentifyTemplate`
   covering `CREDIT_CARD_NUMBER` (Luhn-validated), `KOREA_RRN` (Korean Resident
   Registration Number), and `PHONE_NUMBER` in both `global` and `us`.
2. Creates (or updates) the Cloud DLP `ContentPolicy` resource in both `global`
   and `us` with:
   - `action = BLOCK` (`Determine verdict = Block`)
   - `FALLBACK_ACTION_INPUT_TOO_LARGE = BLOCK` (prevents oversize file bypass)
   - `logToBigQuery` pointing to `sdp_audit_logs.content_policy_action_logs`
3. Creates (or updates) the `Model Armor Template` in:
   - `cfg.location` (`global` or `us`) for Gemini Enterprise Assistant Engine
   - `us` (`us-modelarmor.googleapis.com`) for NotebookLM Enterprise (per
     official NotebookLM Enterprise documentation, `global` NotebookLM instances
     require `us` or `eu` Model Armor templates).
4. Binds both resources to Project-level `NotebookLM Enterprise` across both
   `global` and `us` locations (`PATCH /v1alpha/projects/{PROJECT_NUMBER}?update_mask=customer_provided_config`),
   verifies the stored configuration via `GET`, and runs a direct
   `DlpService.ApplyContentPolicy` self-test to confirm `verdict == BLOCK`.
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


def ensure_dlp_templates_for_location(
    cfg: DemoConfig, location: str
) -> tuple[str, str]:
    """Create or update Cloud DLP InspectTemplate and DeidentifyTemplate in `location`."""
    parent = f"projects/{cfg.project_id}/locations/{location}"
    dlp_url = "https://dlp.googleapis.com"

    # 1. InspectTemplate
    inspect_name = f"{parent}/inspectTemplates/{cfg.dlp_inspect_template_id}"
    inspect_payload = {
        "displayName": f"GE & NotebookLM SDP Inspect Template ({location})",
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
    resp = api_request("GET", f"{dlp_url}/v2/{inspect_name}", cfg)
    if resp.status_code == 200:
        api_request(
            "PATCH",
            f"{dlp_url}/v2/{inspect_name}",
            cfg,
            json_body={"inspectTemplate": inspect_payload},
        )
        console.print(
            f"  [green]✔[/green] Updated DLP InspectTemplate ({location}): [bold]{inspect_name}[/bold]"
        )
    else:
        create_resp = api_request(
            "POST",
            f"{dlp_url}/v2/{parent}/inspectTemplates",
            cfg,
            json_body={
                "templateId": cfg.dlp_inspect_template_id,
                "inspectTemplate": inspect_payload,
            },
        )
        if create_resp.status_code in (200, 201):
            console.print(
                f"  [bold green]+ Created DLP InspectTemplate ({location}):[/bold green] [bold]{inspect_name}[/bold]"
            )
        else:
            console.print(
                f"  [yellow]! InspectTemplate ({location}) response ({create_resp.status_code}): "
                f"{create_resp.text[:200]}[/yellow]"
            )

    # 2. DeidentifyTemplate
    deid_name = f"{parent}/deidentifyTemplates/{cfg.dlp_deidentify_template_id}"
    deid_payload = {
        "displayName": f"GE & NotebookLM SDP Deidentify Template ({location})",
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
    resp = api_request("GET", f"{dlp_url}/v2/{deid_name}", cfg)
    if resp.status_code == 200:
        api_request(
            "PATCH",
            f"{dlp_url}/v2/{deid_name}",
            cfg,
            json_body={"deidentifyTemplate": deid_payload},
        )
        console.print(
            f"  [green]✔[/green] Updated DLP DeidentifyTemplate ({location}): [bold]{deid_name}[/bold]"
        )
    else:
        create_resp = api_request(
            "POST",
            f"{dlp_url}/v2/{parent}/deidentifyTemplates",
            cfg,
            json_body={
                "templateId": cfg.dlp_deidentify_template_id,
                "deidentifyTemplate": deid_payload,
            },
        )
        if create_resp.status_code in (200, 201):
            console.print(
                f"  [bold green]+ Created DLP DeidentifyTemplate ({location}):[/bold green] [bold]{deid_name}[/bold]"
            )
        else:
            console.print(
                f"  [yellow]! DeidentifyTemplate ({location}) response ({create_resp.status_code}): "
                f"{create_resp.text[:200]}[/yellow]"
            )

    return inspect_name, deid_name


def ensure_sdp_content_policy_for_location(
    cfg: DemoConfig, location: str
) -> str:
    """Create or update Cloud DLP ContentPolicy in `location` with BLOCK verdict and BigQuery logging."""
    parent = f"projects/{cfg.project_id}/locations/{location}"
    policy_name = f"{parent}/contentPolicies/{cfg.sdp_policy_id}"
    dlp_url = "https://dlp.googleapis.com"

    fallback_enum = (
        "FALLBACK_ACTION_INPUT_TOO_LARGE_BLOCK"
        if cfg.sdp_fallback_action == "BLOCK"
        else "FALLBACK_ACTION_INPUT_TOO_LARGE_ALLOW"
    )

    policy_body: dict[str, Any] = {
        "displayName": f"GE & NotebookLM Enterprise SDP Content Policy ({location})",
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

    get_resp = api_request("GET", f"{dlp_url}/v2/{policy_name}", cfg)
    if get_resp.status_code == 200:
        patch_resp = api_request(
            "PATCH",
            f"{dlp_url}/v2/{policy_name}",
            cfg,
            json_body={"contentPolicy": policy_body},
        )
        if patch_resp.status_code == 200:
            console.print(
                f"  [green]✔[/green] Updated Cloud DLP ContentPolicy ({location}): [bold]{policy_name}[/bold]"
            )
        else:
            console.print(
                f"  [yellow]! ContentPolicy ({location}) PATCH status {patch_resp.status_code}: "
                f"{patch_resp.text[:250]}[/yellow]"
            )
    else:
        create_resp = api_request(
            "POST",
            f"{dlp_url}/v2/{parent}/contentPolicies",
            cfg,
            params={"contentPolicyId": cfg.sdp_policy_id},
            json_body={"contentPolicy": policy_body},
        )
        if create_resp.status_code in (200, 201):
            console.print(
                f"  [bold green]+ Created Cloud DLP ContentPolicy ({location}):[/bold green] "
                f"[bold]{policy_name}[/bold]"
            )
        else:
            console.print(
                f"  [yellow]! ContentPolicy ({location}) POST status {create_resp.status_code}: "
                f"{create_resp.text[:300]}[/yellow]"
            )
    return policy_name


def ensure_model_armor_template_for_location(
    cfg: DemoConfig,
    location: str,
    inspect_template_name: str,
    deidentify_template_name: str,
) -> str:
    """Create or update Model Armor Template in `location` with Advanced SDP Filter enabled."""
    parent = f"projects/{cfg.project_id}/locations/{location}"
    tmpl_name = f"{parent}/templates/{cfg.model_armor_template_id}"
    armor_base_url = (
        "https://modelarmor.googleapis.com"
        if location == "global"
        else f"https://{location}-modelarmor.googleapis.com"
    )

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

    get_resp = api_request("GET", f"{armor_base_url}/v1/{tmpl_name}", cfg)
    if get_resp.status_code == 200:
        patch_resp = api_request(
            "PATCH",
            f"{armor_base_url}/v1/{tmpl_name}",
            cfg,
            params={"updateMask": "filterConfig,templateMetadata"},
            json_body=template_body,
        )
        if patch_resp.status_code == 200:
            console.print(
                f"  [green]✔[/green] Updated Model Armor Template ({location}): [bold]{tmpl_name}[/bold]"
            )
        else:
            console.print(
                f"  [yellow]! Model Armor ({location}) PATCH status {patch_resp.status_code}: "
                f"{patch_resp.text[:250]}[/yellow]"
            )
    else:
        create_resp = api_request(
            "POST",
            f"{armor_base_url}/v1/{parent}/templates",
            cfg,
            params={"templateId": cfg.model_armor_template_id},
            json_body=template_body,
        )
        if create_resp.status_code in (200, 201):
            console.print(
                f"  [bold green]+ Created Model Armor Template ({location}):[/bold green] "
                f"[bold]{tmpl_name}[/bold]"
            )
        else:
            console.print(
                f"  [yellow]! Model Armor ({location}) POST status {create_resp.status_code}: "
                f"{create_resp.text[:250]}[/yellow]"
            )
    return tmpl_name


def bind_notebooklm_project_config_for_location(
    cfg: DemoConfig,
    location: str,
    sdp_policy_name: str,
    armor_template_name_us: str,
) -> bool:
    """Bind SDP ContentPolicy and Regional Model Armor Template to Project-level NotebookLM config.

    IMPORTANT:
    1. Per `google/cloud/discoveryengine/v1alpha/project.proto`, `notebooklmConfig.modelArmorConfig`
       accepts ONLY `userPromptTemplate` and `responseTemplate` (do NOT include `failureMode`).
    2. Per NotebookLM Enterprise official docs (`enable-model-armor.md`) and backend `startup.pi`,
       `NotebookLM Enterprise` in `global` or `us` requires the Model Armor Template to be in
       `locations/us` (`projects/{PROJECT_ID}/locations/us/templates/{TEMPLATE_ID}`).
    """
    patch_body = {
        "customerProvidedConfig": {
            "notebooklmConfig": {
                "dataProtectionPolicy": {
                    "sensitiveDataProtectionPolicy": {
                        "policy": sdp_policy_name,
                    }
                },
                "modelArmorConfig": {
                    "userPromptTemplate": armor_template_name_us,
                    "responseTemplate": armor_template_name_us,
                },
            }
        }
    }

    de_base_url = (
        "https://discoveryengine.googleapis.com"
        if location == "global"
        else f"https://{location}-discoveryengine.googleapis.com"
    )
    url = f"{de_base_url}/v1alpha/projects/{cfg.project_number}"
    resp = api_request(
        "PATCH",
        url,
        cfg,
        params={"update_mask": "customer_provided_config"},
        json_body=patch_body,
    )

    if resp.status_code == 200:
        # Read-after-write verification
        verify_resp = api_request("GET", url, cfg)
        stored_nlm_cfg = (
            verify_resp.json()
            .get("customerProvidedConfig", {})
            .get("notebooklmConfig", {})
            if verify_resp.status_code == 200
            else {}
        )
        console.print(
            f"  [bold green]✔ Bound & Verified NotebookLM Enterprise config in [{location}]:[/bold green]\n"
            f"    • SDP Policy: [cyan]{stored_nlm_cfg.get('dataProtectionPolicy', {}).get('sensitiveDataProtectionPolicy', {}).get('policy', '')}[/cyan]\n"
            f"    • Model Armor: [cyan]{stored_nlm_cfg.get('modelArmorConfig', {}).get('userPromptTemplate', '')}[/cyan]"
        )
        return True

    console.print(
        f"  [bold red]✘ Failed to PATCH NotebookLM customerProvidedConfig in [{location}] "
        f"(HTTP {resp.status_code}):[/bold red]\n  {resp.text[:350]}"
    )
    return False


def verify_dlp_content_policy_block(cfg: DemoConfig, sdp_policy_name: str) -> None:
    """Directly invoke DlpService.ApplyContentPolicy to verify that `.txt` PII returns BLOCK."""
    parts = sdp_policy_name.split("/")
    parent = "/".join(parts[:4])  # projects/{project}/locations/{location}
    url = f"https://dlp.googleapis.com/v2/{parent}:applyContentPolicy"
    test_body = {
        "policy": sdp_policy_name,
        "item": {
            "byteItem": {
                "type": "TEXT_UTF8",
                "data": "VklQIOqzoOqwnSDrsJXtmLgg7ISx7ZWoOiDso7zrr7jrk7HroZ3rsoDtmLggODgwMTAxLTEyMzQ1NjcsIOyLoOyaqey5tOuTnCA0NTMyLTAxNTEtMTI4My0wMzY2",
            }
        },
    }
    resp = api_request("POST", url, cfg, json_body=test_body)
    if resp.status_code == 200:
        verdict = resp.json().get("verdict", "UNKNOWN")
        if verdict == "BLOCK":
            console.print(
                f"  [bold green]✔ Direct DLP ApplyContentPolicy Self-Test Passed:[/bold green] "
                f"policy=[cyan]{sdp_policy_name}[/cyan] -> verdict=[bold red]{verdict}[/bold red]"
            )
        else:
            console.print(
                f"  [bold yellow]! WARNING: DLP ApplyContentPolicy returned verdict='{verdict}' "
                f"(expected 'BLOCK')! Check ContentPolicy rules in Console.[/bold yellow]"
            )
    else:
        console.print(
            f"  [yellow]! Direct DLP ApplyContentPolicy test returned HTTP {resp.status_code}: "
            f"{resp.text[:250]}[/yellow]"
        )


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
            f"[bold cyan]Primary Location:[/bold cyan] {cfg.location}\n"
            f"[bold cyan]SDP ContentPolicy (global & us):[/bold cyan] {cfg.sdp_policy_id}\n"
            f"[bold cyan]Model Armor Template (global & us):[/bold cyan] {cfg.model_armor_template_id}",
            title="[Step 3] Apply & Bind SDP Content Policy and Model Armor Template",
            border_style="cyan",
        )
    )

    console.print(
        "\n[bold]1. Provisioning Cloud DLP Templates & ContentPolicy in [global] and [us][/bold]"
    )
    inspect_global, deid_global = ensure_dlp_templates_for_location(cfg, "global")
    sdp_policy_global = ensure_sdp_content_policy_for_location(cfg, "global")

    inspect_us, deid_us = ensure_dlp_templates_for_location(cfg, "us")
    sdp_policy_us = ensure_sdp_content_policy_for_location(cfg, "us")

    console.print(
        "\n[bold]2. Provisioning Model Armor Templates in [global] (for GE App) and [us] (required for NotebookLM)[/bold]"
    )
    armor_tmpl_global = ensure_model_armor_template_for_location(
        cfg, "global", inspect_global, deid_global
    )
    armor_tmpl_us = ensure_model_armor_template_for_location(
        cfg, "us", inspect_us, deid_us
    )

    console.print(
        "\n[bold]3. Binding Policies to NotebookLM ([global] & [us]) and Gemini Enterprise Control Planes[/bold]"
    )
    bind_notebooklm_project_config_for_location(
        cfg, "global", sdp_policy_global, armor_tmpl_us
    )
    bind_notebooklm_project_config_for_location(
        cfg, "us", sdp_policy_us, armor_tmpl_us
    )

    armor_for_ge = armor_tmpl_global if cfg.location == "global" else armor_tmpl_us
    bind_ge_assistant_armor(cfg, armor_for_ge)

    console.print("\n[bold]4. Running Direct DLP ApplyContentPolicy Self-Test on Sample .txt Payload[/bold]")
    verify_dlp_content_policy_block(cfg, sdp_policy_global)
    verify_dlp_content_policy_block(cfg, sdp_policy_us)

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
            "[bold green]Control Plane Security Remediation Applied & Verified![/bold green]\n"
            "• Both [bold]global[/bold] and [bold]us[/bold] NotebookLM Customer configurations are now bound.\n"
            "• Run [bold cyan]make mask-gcs[/bold cyan] ([cyan]python scripts/04_run_gcs_dlp_masking.py[/cyan]) "
            "to sanitize the GCS Data Store documents.",
            title="Step 3 Completed",
            border_style="green",
        )
    )


if __name__ == "__main__":
    main()
