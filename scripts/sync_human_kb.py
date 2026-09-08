#!/usr/bin/env python3
"""
vQA — Human-Learned KB Sync Script
=====================================
Module: scripts/sync_human_kb.py

Uploads the human-captured selectors from ``knowledge/human_learned.jsonl``
to S3, then triggers a Bedrock Knowledge Base ingestion job so the agent
learns from every human takeover session autonomously.

Usage
-----
Run manually (or from ``make kb-human-sync``) after a takeover session:

    python scripts/sync_human_kb.py

Or with explicit overrides:

    python scripts/sync_human_kb.py \\
        --staging knowledge/human_learned.jsonl \\
        --s3-bucket my-bucket \\
        --s3-prefix vqa \\
        --kb-id abc123 \\
        --data-source-id def456 \\
        --dry-run

Environment Variables (read from .env if dotenv is installed)
-------------------------------------------------------------
    AWS_ACCESS_KEY_ID
    AWS_SECRET_ACCESS_KEY
    AWS_REGION / AWS_BEDROCK_REGION
    S3_BUCKET
    S3_PREFIX
    BEDROCK_ROLES_KB_ID         — Bedrock Knowledge Base ID
    BEDROCK_KB_DATA_SOURCE_ID   — Bedrock Data Source ID within the KB

What it does
------------
1. Reads ``knowledge/human_learned.jsonl`` (one JSON record per line).
2. Converts it to a Markdown document (``knowledge/human_learned_<ts>.md``)
   that Bedrock can ingest as a KB chunk.
3. Uploads the .md file to S3 under:
       s3://<S3_BUCKET>/<S3_PREFIX>/kb-documents/human_learned_<ts>.md
4. Calls ``BedrockAgent:StartIngestionJob`` to re-index the KB.
5. Archives the processed JSONL by appending to
       knowledge/human_learned.archive.jsonl
   and truncates the staging file.

After running, the agent will pick up the new selectors on the next run
that queries the Bedrock KB.
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("sync_human_kb")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)

# ---------------------------------------------------------------------------
# Defaults (overridden by CLI args or env vars)
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).parent.parent  # vQA root

STAGING_FILE = _ROOT / "knowledge" / "human_learned.jsonl"
ARCHIVE_FILE = _ROOT / "knowledge" / "human_learned.archive.jsonl"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_env() -> None:
    """Load .env if python-dotenv is available."""
    try:
        from dotenv import load_dotenv

        env_path = _ROOT / ".env"
        if env_path.exists():
            load_dotenv(env_path)
            logger.debug("Loaded .env from %s", env_path)
    except ImportError:
        pass  # python-dotenv not installed; rely on shell env


def _read_staging(staging_path: Path) -> list[dict]:
    """Read all records from the JSONL staging file."""
    if not staging_path.exists():
        return []
    records = []
    with staging_path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning("Line %d is invalid JSON (skipped): %s", lineno, e)
    return records


def _records_to_markdown(records: list[dict], timestamp: str) -> str:
    """
    Convert human-learned selector records into a Bedrock-ingestible Markdown doc.

    Each record becomes a section with:
    - AC step text as the heading
    - Playwright action as a code block
    - Ticket ID and source for traceability
    """
    lines = [
        f"# vQA Human-Learned Selectors — {timestamp}",
        "",
        "This document contains selector patterns captured from human takeover sessions.",
        "Each pattern was manually validated by a QA operator and represents the",
        "correct way to interact with a specific UI element in vProMedia/vSuite.",
        "",
        "---",
        "",
    ]

    for i, record in enumerate(records, 1):
        ac_step = record.get("ac_step", "Unknown step")
        pw_action = record.get("pw_action", {})
        ticket_id = record.get("ticket_id", "")
        ts = record.get("timestamp", "")
        source = record.get("source", "human_takeover")

        lines.append(f"## Step {i}: {ac_step}")
        lines.append("")
        if ticket_id:
            lines.append(f"**Jira Ticket:** {ticket_id}")
        lines.append(f"**Source:** {source}  |  **Captured:** {ts[:19].replace('T', ' ')} UTC")
        lines.append("")
        lines.append("**Playwright Action:**")
        lines.append("```json")
        lines.append(json.dumps(pw_action, indent=2))
        lines.append("```")
        lines.append("")

        # Emit a natural-language description the LLM can retrieve via RAG
        action = pw_action.get("action", "click")
        strategy = pw_action.get("strategy", "")
        name = pw_action.get("name", "")
        role = pw_action.get("role", "")

        if strategy == "get_by_role":
            nl = f'To {action} for \'{ac_step}\': use `page.get_by_role("{role}", name="{name}").{action}()`'
        elif strategy == "get_by_text":
            nl = f"To {action} for '{ac_step}': use `page.get_by_text(\"{name}\").{action}()`"
        elif strategy == "get_by_label":
            nl = f"To {action} for '{ac_step}': use `page.get_by_label(\"{name}\").{action}()`"
        elif strategy == "get_by_test_id":
            nl = f"To {action} for '{ac_step}': use `page.get_by_test_id(\"{name}\").{action}()`"
        elif strategy == "css":
            nl = f"To {action} for '{ac_step}': use `page.locator(\"{name}\").{action}()`"
        else:
            nl = f"To {action} for '{ac_step}': action={json.dumps(pw_action)}"

        lines.append(f"**Natural Language:** {nl}")
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def _upload_to_s3(
    content: str,
    bucket: str,
    s3_key: str,
    region: str,
    dry_run: bool,
) -> str:
    """Upload markdown content to S3. Returns the S3 URI."""
    s3_uri = f"s3://{bucket}/{s3_key}"
    if dry_run:
        logger.info("[DRY RUN] Would upload %d bytes to %s", len(content), s3_uri)
        return s3_uri

    import boto3

    s3 = boto3.client("s3", region_name=region)
    s3.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=content.encode("utf-8"),
        ContentType="text/markdown",
    )
    logger.info("Uploaded %d bytes → %s", len(content), s3_uri)
    return s3_uri


def _start_ingestion_job(
    kb_id: str,
    data_source_id: str,
    region: str,
    dry_run: bool,
) -> str:
    """Start a Bedrock KB ingestion job. Returns the job ID."""
    if dry_run:
        logger.info(
            "[DRY RUN] Would call StartIngestionJob on KB=%s DataSource=%s",
            kb_id,
            data_source_id,
        )
        return "dry-run-job-id"

    import boto3

    client = boto3.client("bedrock-agent", region_name=region)
    response = client.start_ingestion_job(
        knowledgeBaseId=kb_id,
        dataSourceId=data_source_id,
    )
    job_id = response["ingestionJob"]["ingestionJobId"]
    status = response["ingestionJob"]["status"]
    logger.info(
        "Ingestion job started: id=%s  status=%s  KB=%s",
        job_id,
        status,
        kb_id,
    )
    return job_id


def _archive_records(records: list[dict], staging_path: Path, archive_path: Path) -> None:
    """Append records to archive and truncate staging file."""
    with archive_path.open("a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")

    # Truncate staging file (keep file, zero size)
    staging_path.write_text("", encoding="utf-8")
    logger.info(
        "Archived %d records to %s — staging file cleared.",
        len(records),
        archive_path,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    _load_env()

    parser = argparse.ArgumentParser(
        description="Upload human-learned selectors to S3 and re-sync Bedrock KB.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--staging",
        default=str(STAGING_FILE),
        help="Path to the JSONL staging file (default: knowledge/human_learned.jsonl)",
    )
    parser.add_argument(
        "--s3-bucket",
        default=os.environ.get("S3_BUCKET", ""),
        help="S3 bucket name (env: S3_BUCKET)",
    )
    parser.add_argument(
        "--s3-prefix",
        default=os.environ.get("S3_PREFIX", "vqa"),
        help="S3 key prefix (env: S3_PREFIX)",
    )
    parser.add_argument(
        "--kb-id",
        default=os.environ.get("BEDROCK_ROLES_KB_ID", ""),
        help="Bedrock Knowledge Base ID (env: BEDROCK_ROLES_KB_ID)",
    )
    parser.add_argument(
        "--data-source-id",
        default=os.environ.get("BEDROCK_KB_DATA_SOURCE_ID", ""),
        help="Bedrock Data Source ID within the KB (env: BEDROCK_KB_DATA_SOURCE_ID)",
    )
    parser.add_argument(
        "--region",
        default=os.environ.get("AWS_BEDROCK_REGION") or os.environ.get("AWS_REGION", "us-east-1"),
        help="AWS region (env: AWS_BEDROCK_REGION or AWS_REGION)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen without uploading or starting an ingestion job.",
    )
    parser.add_argument(
        "--no-archive",
        action="store_true",
        help="Skip archiving + truncating the staging file after upload.",
    )

    args = parser.parse_args()

    staging_path = Path(args.staging)

    # ── Step 1: Read staging ──────────────────────────────────────────
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  vQA KB Human Sync — Self-Learning KB Ingestion")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    records = _read_staging(staging_path)
    if not records:
        print(f"\n  ✓ Staging file is empty: {staging_path}")
        print("    Nothing to sync — good job! Run the agent and perform a takeover")
        print("    session first to generate human-learned selectors.\n")
        return 0

    print(f"\n  → Found {len(records)} record(s) in {staging_path}")

    # ── Step 2: Validate required args ───────────────────────────────
    if not args.dry_run:
        missing = []
        if not args.s3_bucket:
            missing.append("--s3-bucket / S3_BUCKET")
        if not args.kb_id:
            missing.append("--kb-id / BEDROCK_ROLES_KB_ID")
        if not args.data_source_id:
            missing.append("--data-source-id / BEDROCK_KB_DATA_SOURCE_ID")
        if missing:
            logger.error("Missing required arguments: %s", ", ".join(missing))
            print("\n  ✗ Set these in .env or pass as CLI args:\n")
            for m in missing:
                print(f"      {m}")
            print()
            return 1

    # ── Step 3: Convert to Markdown ───────────────────────────────────
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    md_content = _records_to_markdown(records, ts)
    s3_key = f"{args.s3_prefix}/kb-documents/human_learned_{ts}.md"

    print(f"  → Converted to {len(md_content)} chars of Markdown")
    print(f"  → S3 key: s3://{args.s3_bucket}/{s3_key}")

    # ── Step 4: Upload to S3 ──────────────────────────────────────────
    _upload_to_s3(
        content=md_content,
        bucket=args.s3_bucket,
        s3_key=s3_key,
        region=args.region,
        dry_run=args.dry_run,
    )

    # ── Step 5: Start Bedrock ingestion job ───────────────────────────
    job_id = _start_ingestion_job(
        kb_id=args.kb_id,
        data_source_id=args.data_source_id,
        region=args.region,
        dry_run=args.dry_run,
    )
    print(f"  → Ingestion job ID: {job_id}")

    # ── Step 6: Archive + clear staging ──────────────────────────────
    if not args.no_archive and not args.dry_run:
        _archive_records(records, staging_path, ARCHIVE_FILE)
        print(f"  → Staging cleared, archive: {ARCHIVE_FILE}")
    elif args.dry_run:
        print("  [DRY RUN] Staging file NOT cleared.")

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  ✓ KB sync complete.")
    if not args.dry_run:
        print("    Ingestion typically takes 2–5 minutes.")
        print("    The agent will pick up new selectors on the next query.")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
