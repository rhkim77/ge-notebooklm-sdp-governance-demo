#!/usr/bin/env python3
"""Step 6 (Reset): Unbind NotebookLM Project-Level SDP & Model Armor Config.

Use this script when you want to reset the environment back to the initial
'Before' state (where Project-level `customerProvidedConfig.notebooklmConfig`
is unbound) so you can repeat the live customer demo from Step 2 (`make inspect`).
"""

from __future__ import annotations

import sys
from pathlib import Path

from rich.panel import Panel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import (  # noqa: E402
    api_request,
    console,
    load_config,
)


def main() -> None:
    cfg = load_config()
    console.print(
        Panel(
            f"Resetting Project-level [cyan]customerProvidedConfig.notebooklmConfig[/cyan] "
            f"on Project [bold]{cfg.project_id}[/bold] ({cfg.project_number}) in "
            f"Location [bold]{cfg.location}[/bold]...",
            title="[Reset] Unbind NotebookLM Enterprise Security Policies",
            border_style="yellow",
        )
    )

    empty_patch = {
        "customerProvidedConfig": {
            "notebooklmConfig": {
                "dataProtectionPolicy": {
                    "sensitiveDataProtectionPolicy": {
                        "sdpPolicy": "",
                    }
                },
                "modelArmorConfig": {
                    "promptTemplate": "",
                    "responseTemplate": "",
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
        json_body=empty_patch,
    )
    if resp.status_code != 200:
        alt_url = f"{cfg.discovery_engine_base_url}/v1alpha/projects/{cfg.project_number}"
        resp = api_request(
            "PATCH",
            alt_url,
            cfg,
            params={"updateMask": "customerProvidedConfig"},
            json_body=empty_patch,
        )

    if resp.status_code == 200:
        console.print(
            "[bold green]✔ Reset completed![/bold green] "
            "Run [bold cyan]make inspect[/bold cyan] to verify the 'Before' state."
        )
    else:
        console.print(
            f"[bold red]✘ Failed to reset customerProvidedConfig "
            f"(HTTP {resp.status_code}):[/bold red]\n{resp.text[:300]}"
        )


if __name__ == "__main__":
    main()
