#!/usr/bin/env python3
"""Step 1: Prepare GCS Raw/Masked Buckets, BigQuery Audit Table & Sample PDF/TXT Docs.

This script performs the initial environment setup for the live demo:
1. Validates that the sample credit card numbers in `vip_customer_claim_raw.txt`
   pass the Luhn Checksum algorithm required by Cloud DLP `CREDIT_CARD_NUMBER`.
2. Renders both `.txt` and `.pdf` versions of the Sensitive VIP Claim document
   and the Clean Store Operation Policy document under `sample_data/generated/`.
3. Creates (idempotently) the Raw GCS Bucket (`gs://<PROJECT_ID>-ge-sdp-raw-docs`)
   and the Masked GCS Bucket (`gs://<PROJECT_ID>-ge-sdp-masked-docs`), uploading
   the raw sample documents to the Raw GCS Bucket.
4. Creates (idempotently) the BigQuery Dataset (`sdp_audit_logs`) and Table
   (`content_policy_action_logs`) with the exact `ContentPolicyActionLog` schema
   expected by Cloud DLP `logToBigQuery`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from google.api_core.exceptions import Conflict, NotFound
from google.cloud import bigquery
from google.cloud import storage
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from rich.panel import Panel
from rich.table import Table

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.common import (  # noqa: E402
    GENERATED_DATA_DIR,
    SAMPLE_DATA_DIR,
    console,
    is_valid_luhn,
    load_config,
)


def render_text_to_pdf(txt_path: Path, pdf_path: Path) -> None:
    """Render a plain-text file into an A4 PDF document for upload testing."""
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    _, height = A4
    c.setFont("Courier", 9.5)

    y = height - 48
    for line in txt_path.read_text(encoding="utf-8").splitlines():
        # Replace non-ASCII characters with romanized fallback if Courier lacks glyphs
        safe_line = line.encode("ascii", errors="ignore").decode("ascii")
        c.drawString(42, y, safe_line[:95])
        y -= 13
        if y < 48:
            c.showPage()
            c.setFont("Courier", 9.5)
            y = height - 48
    c.save()


def verify_sample_luhn_numbers(raw_text: str) -> list[tuple[str, bool]]:
    """Extract candidate card numbers from sample text and verify Luhn Checksum."""
    pattern = re.compile(r"\b(?:\d{4}-){3}\d{4}\b")
    matches = pattern.findall(raw_text)
    return [(card, is_valid_luhn(card)) for card in matches]


def ensure_gcs_bucket(
    storage_client: storage.Client, bucket_name: str, location: str
) -> storage.Bucket:
    """Create a GCS Bucket with uniform bucket-level access if it does not exist."""
    bucket = storage_client.bucket(bucket_name)
    try:
        bucket.reload()
        console.print(
            f"  [green]✔[/green] GCS Bucket exists: [bold]gs://{bucket_name}[/bold] "
            f"({bucket.location})"
        )
        return bucket
    except NotFound:
        bucket.iam_configuration.uniform_bucket_level_access_enabled = True
        created = storage_client.create_bucket(bucket, location=location)
        console.print(
            f"  [bold green]+ Created GCS Bucket:[/bold green] "
            f"[bold]gs://{bucket_name}[/bold] ({location})"
        )
        return created


def ensure_bigquery_audit_table(
    bq_client: bigquery.Client,
    dataset_id: str,
    table_id: str,
    location: str,
) -> str:
    """Create BigQuery Dataset and ContentPolicyActionLog Table if not present."""
    dataset_ref = f"{bq_client.project}.{dataset_id}"
    try:
        bq_client.get_dataset(dataset_ref)
        console.print(
            f"  [green]✔[/green] BigQuery Dataset exists: [bold]{dataset_ref}[/bold]"
        )
    except NotFound:
        ds = bigquery.Dataset(dataset_ref)
        ds.location = location
        ds.description = (
            "Sensitive Data Protection (SDP) ContentPolicy Action Audit Logs "
            "for Gemini Enterprise & NotebookLM Enterprise"
        )
        bq_client.create_dataset(ds, exists_ok=True)
        console.print(
            f"  [bold green]+ Created BigQuery Dataset:[/bold green] "
            f"[bold]{dataset_ref}[/bold] ({location})"
        )

    table_ref = f"{dataset_ref}.{table_id}"
    schema = [
        bigquery.SchemaField(
            "timestamp",
            "TIMESTAMP",
            mode="NULLABLE",
            description="UTC timestamp when DlpService.ApplyContentPolicy evaluated the content",
        ),
        bigquery.SchemaField(
            "content_policy_name",
            "STRING",
            mode="NULLABLE",
            description="Full resource name of the Cloud DLP ContentPolicy",
        ),
        bigquery.SchemaField(
            "returned_verdict",
            "STRING",
            mode="NULLABLE",
            description="Final enforcement verdict returned to caller (ALLOW or BLOCK)",
        ),
        bigquery.SchemaField(
            "matching_info_types",
            "STRING",
            mode="REPEATED",
            description="Detected Cloud DLP InfoTypes (e.g., CREDIT_CARD_NUMBER, KOREA_RRN)",
        ),
        bigquery.SchemaField(
            "policy_rule",
            "STRING",
            mode="NULLABLE",
            description="Matched rule inside ContentPolicy (e.g., INFOTYPE_RULE)",
        ),
        bigquery.SchemaField(
            "fallback_action",
            "STRING",
            mode="NULLABLE",
            description="Configured Fallback Action when input exceeds size limit (BLOCK or ALLOW)",
        ),
        bigquery.SchemaField(
            "container_id",
            "STRING",
            mode="NULLABLE",
            description="Source container identifier (Data Store ID or Notebook Workspace ID)",
        ),
        bigquery.SchemaField(
            "document_id",
            "STRING",
            mode="NULLABLE",
            description="Evaluated file name or GCS URI",
        ),
        bigquery.SchemaField(
            "correlation_id",
            "STRING",
            mode="NULLABLE",
            description="Trace ID linking to Gemini Enterprise AssistToken or Notebook session",
        ),
    ]
    try:
        bq_client.get_table(table_ref)
        console.print(
            f"  [green]✔[/green] BigQuery Audit Table exists: [bold]{table_ref}[/bold]"
        )
    except (NotFound, Conflict):
        table = bigquery.Table(table_ref, schema=schema)
        bq_client.create_table(table, exists_ok=True)
        console.print(
            f"  [bold green]+ Created BigQuery Audit Table:[/bold green] "
            f"[bold]{table_ref}[/bold]"
        )
    return table_ref


def main() -> None:
    cfg = load_config()
    console.print(
        Panel(
            f"[bold cyan]Project ID:[/bold cyan] {cfg.project_id} "
            f"(Number: {cfg.project_number})\n"
            f"[bold cyan]Control Plane Location:[/bold cyan] {cfg.location}\n"
            f"[bold cyan]Raw GCS Bucket:[/bold cyan] gs://{cfg.raw_bucket_name}\n"
            f"[bold cyan]Masked GCS Bucket:[/bold cyan] gs://{cfg.masked_bucket_name}\n"
            f"[bold cyan]BigQuery Audit Table:[/bold cyan] {cfg.bq_full_table_id}",
            title="[Step 1] Prepare Demo Assets (GCS Buckets, Sample Docs & BigQuery Audit Table)",
            border_style="cyan",
        )
    )

    # 1. Validate Luhn Checksum on sample data and generate PDFs
    console.print("\n[bold]1. Validating Sample Data & Generating PDF/TXT Artifacts[/bold]")
    raw_txt_src = SAMPLE_DATA_DIR / "vip_customer_claim_raw.txt"
    clean_txt_src = SAMPLE_DATA_DIR / "store_operation_policy_clean.txt"

    raw_text = raw_txt_src.read_text(encoding="utf-8")
    luhn_results = verify_sample_luhn_numbers(raw_text)

    luhn_table = Table(title="Sample Credit Card Luhn Checksum Verification")
    luhn_table.add_column("Sample File", style="cyan")
    luhn_table.add_column("Card Number Pattern", style="yellow")
    luhn_table.add_column("Luhn Checksum Status", style="green")
    for card, valid in luhn_results:
        status_str = (
            "[bold green]PASS (Valid Luhn Checksum)[/bold green]"
            if valid
            else "[bold red]FAIL (Invalid Luhn)[/bold red]"
        )
        luhn_table.add_row(raw_txt_src.name, card, status_str)
    console.print(luhn_table)

    GENERATED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw_pdf_dst = GENERATED_DATA_DIR / "vip_customer_claim_raw.pdf"
    clean_pdf_dst = GENERATED_DATA_DIR / "store_operation_policy_clean.pdf"
    render_text_to_pdf(raw_txt_src, raw_pdf_dst)
    render_text_to_pdf(clean_txt_src, clean_pdf_dst)
    console.print(
        f"  [green]✔[/green] Generated local PDFs for NotebookLM Upload testing:\n"
        f"    • Sensitive PDF : [bold]{raw_pdf_dst}[/bold]\n"
        f"    • Clean PDF     : [bold]{clean_pdf_dst}[/bold]"
    )

    # 2. Create Raw & Masked GCS Buckets and upload Raw sample files
    console.print("\n[bold]2. Provisioning GCS Raw & Masked Buckets[/bold]")
    storage_client = storage.Client(project=cfg.project_id)
    raw_bucket = ensure_gcs_bucket(
        storage_client, cfg.raw_bucket_name, cfg.bucket_location
    )
    ensure_gcs_bucket(
        storage_client, cfg.masked_bucket_name, cfg.bucket_location
    )

    files_to_upload = [
        (raw_txt_src, "vip_customer_claim_raw.txt", "text/plain"),
        (raw_pdf_dst, "vip_customer_claim_raw.pdf", "application/pdf"),
        (clean_txt_src, "store_operation_policy_clean.txt", "text/plain"),
        (clean_pdf_dst, "store_operation_policy_clean.pdf", "application/pdf"),
    ]
    for local_path, blob_name, content_type in files_to_upload:
        blob = raw_bucket.blob(blob_name)
        blob.upload_from_filename(str(local_path), content_type=content_type)
        console.print(
            f"  [green]↑ Uploaded:[/green] gs://{cfg.raw_bucket_name}/{blob_name}"
        )

    # 3. Create BigQuery Dataset & Audit Log Table
    console.print("\n[bold]3. Provisioning BigQuery Audit Dataset & Table[/bold]")
    bq_client = bigquery.Client(project=cfg.project_id)
    ensure_bigquery_audit_table(
        bq_client, cfg.bq_dataset_id, cfg.bq_table_id, cfg.bq_location
    )

    console.print(
        Panel(
            "[bold green]Demo assets are ready![/bold green]\n"
            "• Next Step: Run [bold cyan]make inspect[/bold cyan] "
            "([cyan]python scripts/02_inspect_current_config.py[/cyan]) to diagnose "
            "the current Control Plane configuration gap between Gemini Enterprise "
            "and NotebookLM Enterprise.",
            title="Step 1 Completed",
            border_style="green",
        )
    )


if __name__ == "__main__":
    main()
