"""
Command-line interface (CLI) for JobRadar.

Supported commands:
  python -m jobradar run [--dry-run] [--force-digest]
  python -m jobradar commands
  python -m jobradar test-telegram
  python -m jobradar sources
  python -m jobradar employers
  python -m jobradar rescore
  python -m jobradar export-csv [--output matches.csv]
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import datetime
from pathlib import Path
from jobradar.adapters.storage.factory import get_repository
from jobradar.adapters.telegram.client import TelegramClient
from jobradar.config import load_config
from jobradar.domain.models import ScoredJob
from jobradar.services.pipeline import JobRadarPipeline
from jobradar.services.scorer import JobScorer

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("jobradar.cli")


def cmd_run(args: argparse.Namespace) -> int:
    """Execute the full job ingestion, scoring, and alerting pipeline."""
    config = load_config()
    repo = get_repository(config.database_url)
    pipeline = JobRadarPipeline(config, repo)

    print(f"\n🚀 Running JobRadar Pipeline (dry_run={args.dry_run})...")
    summary = pipeline.run(dry_run=args.dry_run, force_digest=args.force_digest)

    print("\n" + "=" * 50)
    print("📋 Pipeline Execution Summary:")
    print(f" • Duration:        {summary['duration_seconds']:.2f}s")
    print(f" • Sources Checked: {summary['sources_checked']}")
    print(f" • Total Fetched:   {summary['items_fetched']}")
    print(f" • New Jobs Stored: {summary['new_jobs']}")
    print(f" • Matches Found:   {summary['matches_found']}")
    print(f" • Alerts Sent:     {summary['alerts_sent']}")
    print(f" • Baseline Run:    {summary['is_baseline_run']}")
    print(f" • Unhealthy Sources: {summary['unhealthy_sources']}")
    print("=" * 50 + "\n")
    return 0


def cmd_commands(args: argparse.Namespace) -> int:
    """Poll Telegram updates and apply /add and /ignore commands."""
    config = load_config()
    repo = get_repository(config.database_url)
    telegram = TelegramClient(bot_token=config.telegram_bot_token, chat_id=config.telegram_chat_id)

    print("\n🤖 Polling Telegram for /add and /ignore commands...")
    actions = telegram.process_incoming_commands(repo)

    if actions:
        print(f"✅ Executed {len(actions)} command(s):")
        for a in actions:
            print(f" • {a}")
    else:
        print("ℹ️ No new pending commands found.")
    return 0


def cmd_test_telegram(args: argparse.Namespace) -> int:
    """Verify Telegram credentials and send a test message."""
    config = load_config()
    telegram = TelegramClient(bot_token=config.telegram_bot_token, chat_id=config.telegram_chat_id)

    print("\n📡 Testing Telegram Bot Connection...")
    if not telegram.is_configured():
        print("❌ Error: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in your .env file.")
        return 1

    msg = (
        "✅ <b>Job-Radar Telegram Connection Verified!</b>\n"
        f"Server local time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        "Alert notifications and two-way commands are active."
    )
    success = telegram.send_message(msg)

    if success:
        print("🎉 Success! Test message sent to your Telegram chat.")
        return 0
    else:
        print("❌ Failed to deliver message. Please verify your bot token and chat ID.")
        return 1


def cmd_sources(args: argparse.Namespace) -> int:
    """Display health and stats for all configured sources."""
    config = load_config()
    repo = get_repository(config.database_url)

    print("\n📡 Configured Sources & Health Status:")
    print("-" * 80)
    print(f"{'Source ID':<25} {'Type':<15} {'Enabled':<10} {'Last Status':<15} {'Last Items'}")
    print("-" * 80)

    for src in config.sources:
        prev = repo.get_previous_source_run(src.id)
        status_str = prev.status if prev else "No runs yet"
        items_str = str(prev.items_fetched) if prev else "-"
        enabled_str = "Yes" if src.enabled else "No"
        print(f"{src.id:<25} {src.type:<15} {enabled_str:<10} {status_str:<15} {items_str}")
    print("-" * 80 + "\n")
    return 0


def cmd_employers(args: argparse.Namespace) -> int:
    """List discovered employers by status."""
    config = load_config()
    repo = get_repository(config.database_url)

    print("\n🏢 Discovered Employer ATS Endpoints:")
    employers = repo.get_discovered_employers()

    if not employers:
        print("ℹ️ No employers discovered yet. Ingest job listings to discover ATS endpoints.")
        return 0

    print("-" * 80)
    print(f"{'ID':<6} {'Company':<30} {'System':<15} {'Status':<12} {'Jobs Seen'}")
    print("-" * 80)
    for emp in employers:
        print(f"{emp.id or 0:<6} {emp.company[:28]:<30} {emp.system:<15} {emp.status:<12} {emp.jobs_seen}")
    print("-" * 80 + "\n")
    return 0


def cmd_rescore(args: argparse.Namespace) -> int:
    """Re-score all stored jobs in PostgreSQL against updated keywords."""
    config = load_config()
    repo = get_repository(config.database_url)
    scorer = JobScorer(config)

    print("\n🔄 Re-scoring all stored jobs against current config.yaml keywords...")
    jobs = repo.get_all_jobs_for_rescore()

    if not jobs:
        print("ℹ️ No jobs currently stored in database.")
        return 0

    matches_count = 0
    near_miss_count = 0

    for job in jobs:
        breakdown = scorer.score(job)
        scored = ScoredJob(job=job, score_breakdown=breakdown)
        repo.save_scored_match(scored)

        if breakdown.is_match:
            matches_count += 1
        elif breakdown.is_near_miss:
            near_miss_count += 1

    print("=" * 50)
    print("📊 Re-scoring Complete:")
    print(f" • Total Jobs Evaluated: {len(jobs)}")
    print(f" • Qualifying Matches:   {matches_count} (>= {config.pipeline.min_score})")
    print(f" • Near-Misses:          {near_miss_count} (within {config.pipeline.near_miss_delta} pts)")
    print("=" * 50 + "\n")
    return 0


def cmd_export_csv(args: argparse.Namespace) -> int:
    """Export all matching jobs to a CSV spreadsheet."""
    config = load_config()
    repo = get_repository(config.database_url)
    output_path = Path(args.output)

    print(f"\n📊 Exporting matches to {output_path}...")
    # Fetch all stored jobs and their scores
    jobs = repo.get_all_jobs_for_rescore()
    scorer = JobScorer(config)

    rows = []
    for job in jobs:
        breakdown = scorer.score(job)
        if breakdown.is_match:
            rows.append({
                "Title": job.title,
                "Company": job.company,
                "Location": job.location,
                "Score": f"{breakdown.final_score:.1f}",
                "Best Track": breakdown.best_track_name,
                "Source": job.source,
                "Deadline": job.deadline.strftime("%Y-%m-%d") if job.deadline else "",
                "First Seen": job.first_seen.strftime("%Y-%m-%d"),
                "URL": job.url,
                "Audit Breakdown": breakdown.details,
            })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        if rows:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        else:
            f.write("No matching jobs found.\n")

    print(f"✅ Exported {len(rows)} matching job(s) to {output_path}.\n")
    return 0


def main() -> int:
    """CLI entrypoint router."""
    parser = argparse.ArgumentParser(
        prog="jobradar",
        description="JobRadar - Production Job Ingestion, Multi-Track Scoring & Telegram Alert Pipeline",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # run
    p_run = subparsers.add_parser("run", help="Run full ingestion, scoring, and alerting pipeline")
    p_run.add_argument("--dry-run", action="store_true", help="Log matches without sending Telegram alerts")
    p_run.add_argument("--force-digest", action="store_true", help="Force sending Monday near-miss digest")
    p_run.set_defaults(func=cmd_run)

    # commands
    p_cmd = subparsers.add_parser("commands", help="Poll Telegram and apply /add and /ignore commands")
    p_cmd.set_defaults(func=cmd_commands)

    # test-telegram
    p_tg = subparsers.add_parser("test-telegram", help="Send a test message to verify Telegram configuration")
    p_tg.set_defaults(func=cmd_test_telegram)

    # sources
    p_src = subparsers.add_parser("sources", help="Show health and stats for all configured sources")
    p_src.set_defaults(func=cmd_sources)

    # employers
    p_emp = subparsers.add_parser("employers", help="List discovered employers (approved, ignored, pending)")
    p_emp.set_defaults(func=cmd_employers)

    # rescore
    p_res = subparsers.add_parser("rescore", help="Re-score all stored jobs against updated keywords")
    p_res.set_defaults(func=cmd_rescore)

    # export-csv
    p_exp = subparsers.add_parser("export-csv", help="Export matching jobs to CSV spreadsheet")
    p_exp.add_argument("--output", default="matches.csv", help="Path to output CSV file")
    p_exp.set_defaults(func=cmd_export_csv)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
