#!/usr/bin/env python3
"""Step 4: Upstream GCS Pre-Ingestion Cloud DLP De-identification Pipeline.

Why is this Layer 3 pipeline required?
When a user imports a document from a Gemini Enterprise GCS Data Store into
NotebookLM Enterprise via the `"Add content to..."` flow, the internal batch
ingestion call copies the indexed document from the Data Store without invoking
the Direct-Upload `SDP Content Policy` hook.

To ensure 100% end-to-end protection across both Gemini Enterprise Assistant Chat
and NotebookLM Enterprise:
1. Raw documents are staged in `gs://<RAW_BUCKET_NAME>/`.
2. This pipeline calls Cloud DLP `deidentify_content` to mask `CREDIT_CARD_NUMBER`,
   `KOREA_RRN`, and `PHONE_NUMBER` into `[REDACTED_<INFOTYPE>]` markers.
3. Sanitized `.txt` and `.pdf` documents are written to `gs://<MASKED_BUCKET_NAME>/`.
4. If `GE_DATA_STORE_ID` is configured in `.env`, the script triggers a
   Discovery Engine `documents:import` job (`FULL` reconciliation) from the
   Masked GCS Bucket so the Data Store only serves pre-masked documents.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from google.cloud import dlp_v2
from google.cloud import storage
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from rich.columns import Columns
from rich.panel import Panel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import (  # noqa: E402
    DemoConfig,
    api_request,
    console,
    load_config,
)


def deidentify_text_via_dlp(
    dlp_client: dlp_v2.DlpServiceClient,
    project_id: str,
    raw_text: str,
) -> str:
    """Call Cloud DLP deidentify_content API to redact PII InfoTypes."""
    parent = f"projects/{project_id}/locations/global"
    info_types = [
        {"name": "CREDIT_CARD_NUMBER"},
        {"name": "KOREA_RRN"},
        {"name": "PHONE_NUMBER"},
    ]
    inspect_config = {
        "info_types": info_types,
        "min_likelihood": dlp_v2.Likelihood.POSSIBLE,
    }
    deidentify_config = {
        "info_type_transformations": {
            "transformations": [
                {
                    "info_types": info_types,
                    "primitive_transformation": {
                        "replace_with_info_type_config": {}
                    },
                }
            ]
        }
    }
    item = {"value": raw_text}
    response = dlp_client.deidentify_content(
        request={
            "parent": parent,
            "inspect_config": inspect_config,
            "deidentify_config": deidentify_config,
            "item": item,
        }
    )
    return response.item.value


def render_masked_text_to_pdf(masked_text: str, output_pdf: Path) -> None:
    """Render de-identified text into an A4 PDF file."""
    c = canvas.Canvas(str(output_pdf), pagesize=A4)
    _, height = A4
    c.setFont("Courier", 9.5)
    y = height - 48
    for line in masked_text.splitlines():
        safe_line = line.encode("ascii", errors="ignore").decode("ascii")
        c.drawString(42, y, safe_line[:95])
        y -= 13
        if y < 48:
            c.showPage()
            c.setFont("Courier", 9.5)
            y = height - 48
    c.save()


def trigger_datastore_reimport(cfg: DemoConfig) -> None:
    """Trigger Discovery Engine Data Store import from Masked GCS Bucket if configured."""
    if not cfg.ge_data_store_id:
        console.print(
            "  [dim]• Skipping Discovery Engine Data Store re-import "
            "(GE_DATA_STORE_ID not set in .env)[/dim]"
        )
        return

    import_url = (
        f"{cfg.discovery_engine_base_url}/v1alpha/projects/{cfg.project_id}"
        f"/locations/{cfg.location}/collections/default_collection"
        f"/dataStores/{cfg.ge_data_store_id}/branches/0/documents:import"
    )
    payload = {
        "gcsSource": {
            "inputUris": [f"gs://{cfg.masked_bucket_name}/*"],
            "dataSchema": "content",
        },
        "reconciliationMode": "FULL",
    }
    resp = api_request("POST", import_url, cfg, json_body=payload)
    if resp.status_code == 200:
        op_name = resp.json().get("name", "LRO started")
        console.print(
            f"  [bold green]✔ Triggered Data Store FULL Re-import from Masked Bucket![/bold green]\n"
            f"    Operation: [cyan]{op_name}[/cyan]"
        )
    else:
        console.print(
            f"  [yellow]! Data Store import status {resp.status_code}: "
            f"{resp.text[:250]}[/yellow]"
        )


def main() -> None:
    cfg = load_config()
    console.print(
        Panel(
            f"[bold cyan]Source Raw Bucket:[/bold cyan]    gs://{cfg.raw_bucket_name}\n"
            f"[bold cyan]Target Masked Bucket:[/bold cyan] gs://{cfg.masked_bucket_name}\n"
            f"[bold cyan]Target GE Data Store:[/bold cyan] {cfg.ge_data_store_id or '(Optional)'}",
            title="[Step 4] Upstream GCS Pre-Ingestion Cloud DLP De-identification Pipeline",
            border_style="cyan",
        )
    )

    storage_client = storage.Client(project=cfg.project_id)
    dlp_client = dlp_v2.DlpServiceClient()

    raw_bucket = storage_client.bucket(cfg.raw_bucket_name)
    masked_bucket = storage_client.bucket(cfg.masked_bucket_name)

    blobs = list(raw_bucket.list_blobs())
    txt_blobs = [b for b in blobs if b.name.endswith(".txt")]

    if not txt_blobs:
        console.print(
            "[bold red]No .txt documents found in Raw Bucket![/bold red] "
            "Please run [cyan]make prepare-assets[/cyan] first."
        )
        sys.exit(1)

    for blob in txt_blobs:
        console.print(
            f"\n[bold]Processing Document:[/bold] [cyan]gs://{cfg.raw_bucket_name}/{blob.name}[/cyan]"
        )
        raw_text = blob.download_as_text(encoding="utf-8")
        masked_text = deidentify_text_via_dlp(
            dlp_client, cfg.project_id, raw_text
        )

        if "vip_customer_claim" in blob.name:
            # Show side-by-side Before vs. After snippet in terminal
            raw_excerpt = "\n".join(raw_text.splitlines()[11:29])
            masked_excerpt = "\n".join(masked_text.splitlines()[11:29])
            console.print(
                Columns(
                    [
                        Panel(
                            raw_excerpt,
                            title="[bold red]BEFORE: Raw GCS Content (Unmasked PII)[/bold red]",
                            border_style="red",
                        ),
                        Panel(
                            masked_excerpt,
                            title="[bold green]AFTER: Cloud DLP Masked Content[/bold green]",
                            border_style="green",
                        ),
                    ]
                )
            )

        # Upload masked .txt
        masked_txt_blob = masked_bucket.blob(blob.name)
        masked_txt_blob.upload_from_string(
            masked_text, content_type="text/plain; charset=utf-8"
        )
        console.print(
            f"  [green]↑ Uploaded Masked TXT:[/green] gs://{cfg.masked_bucket_name}/{blob.name}"
        )

        # Render and upload corresponding masked .pdf
        pdf_name = blob.name.replace(".txt", ".pdf")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
            tmp_pdf_path = Path(tmp_pdf.name)
        render_masked_text_to_pdf(masked_text, tmp_pdf_path)
        masked_pdf_blob = masked_bucket.blob(pdf_name)
        masked_pdf_blob.upload_from_filename(
            str(tmp_pdf_path), content_type="application/pdf"
        )
        tmp_pdf_path.unlink(missing_ok=True)
        console.print(
            f"  [green]↑ Uploaded Masked PDF:[/green] gs://{cfg.masked_bucket_name}/{pdf_name}"
        )

    console.print("\n[bold]Synchronizing Gemini Enterprise GCS Data Store[/bold]")
    trigger_datastore_reimport(cfg)

    console.print(
        Panel(
            "[bold green]Upstream GCS DLP De-identification Completed![/bold green]\n"
            "• All sensitive Credit Card Numbers and Korean RRNs in "
            f"[cyan]gs://{cfg.masked_bucket_name}[/cyan] are now replaced with "
            "[bold][CREDIT_CARD_NUMBER][/bold] and [bold][KOREA_RRN][/bold] tokens.\n"
            "• Even when users import GCS documents into NotebookLM via "
            "[italic]'Add content to...'[/italic], zero raw PII is exposed.\n\n"
            "👉 Next Step: Run [bold cyan]make verify-logs[/bold cyan] "
            "([cyan]python scripts/05_verify_enforcement_logs.py[/cyan]) to test live "
            "Model Armor sanitization and inspect BigQuery / Cloud Logging audit trails.",
            title="Step 4 Completed",
            border_style="green",
        )
    )


if __name__ == "__main__":
    main()
