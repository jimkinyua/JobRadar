"""
Pipeline Orchestrator for JobRadar.

Coordinates the end-to-end data lifecycle:
1. Load enabled sources & approved employers
2. Ingest listings with fault isolation
3. Store Bronze raw payloads (immutable audit)
4. Store & deduplicate Silver jobs (lifecycle tracking)
5. Sniff ATS hiring systems from job URLs (Employer Discovery)
6. Score against Multi-Track personas into Gold layer
7. Monitor source health anomalies (failures, 0-items, >50% drop)
8. Dispatch rate-limited Telegram alerts (top 15, or top 10 on baseline run)
9. Trigger 3-day deadline reminders & Monday near-miss digests
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from jobradar.adapters.sources.ats_sniffer import detect_ats_employer
from jobradar.adapters.sources.factory import get_source_adapter
from jobradar.adapters.storage.base import BaseStorageRepository
from jobradar.adapters.telegram.client import TelegramClient
from jobradar.config import AppConfig, SourceConfig, load_employers
from jobradar.domain.models import Job, RawJob, ScoredJob, SourceRun
from jobradar.services.scorer import JobScorer

logger = logging.getLogger(__name__)


class JobRadarPipeline:
    """End-to-end ETL/ELT pipeline orchestrator."""

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        repo: Optional[BaseStorageRepository] = None,
        telegram: Optional[TelegramClient] = None,
        ai_service: Optional[Any] = None,
    ) -> None:
        from jobradar.config import load_config
        from jobradar.adapters.storage.factory import get_repository
        from jobradar.services.ai_service import AIService
        self.config = config or load_config()
        self.repo = repo or get_repository()
        self.scorer = JobScorer(self.config)
        self.ai_service = ai_service or AIService(config=self.config)
        self.telegram = telegram or TelegramClient(
            bot_token=self.config.telegram_bot_token,
            chat_id=self.config.telegram_chat_id,
        )

    def run(
        self,
        dry_run: bool = False,
        force_digest: bool = False,
    ) -> dict[str, Any]:
        """Execute the full pipeline run."""
        run_start = datetime.now(timezone.utc)
        logger.info("Starting JobRadar pipeline run (dry_run=%s)", dry_run)

        # Baseline detection: Is this the first run with an empty database?
        total_jobs_before = self.repo.count_total_jobs()
        is_baseline_run = (total_jobs_before == 0)

        # 1. Assemble source list (Configured sources + Approved direct employers)
        active_sources = [s for s in self.config.sources if s.enabled]
        approved_employers = load_employers()

        for emp in approved_employers:
            if emp.get("status") == "approved":
                active_sources.append(
                    SourceConfig(
                        id=f"emp_{emp.get('system')}_{emp.get('identifier')}",
                        name=emp.get("company", "Direct Employer"),
                        type=emp.get("system", "smartrecruiters"),
                        company_identifier=emp.get("identifier"),
                        enabled=True,
                    )
                )

        logger.info("Active sources to process: %d", len(active_sources))

        # 2. Ingest from each source
        total_fetched = 0
        total_new_jobs = 0
        total_matches = 0
        unhealthy_sources: list[dict[str, Any]] = []

        for src_cfg in active_sources:
            try:
                adapter = get_source_adapter(src_cfg, self.config.crawler)
            except Exception as e:
                logger.error("Failed to initialize adapter for source '%s': %s", src_cfg.id, e)
                unhealthy_sources.append({"name": src_cfg.name, "reason": f"Adapter error: {e}"})
                continue

            items, run_stats = adapter.safe_fetch()
            total_fetched += len(items)

            new_in_source = 0
            matches_in_source = 0

            # Process fetched listings
            for raw_job, job in items:
                # 3. Bronze Layer: Save raw payload
                raw_id = self.repo.save_raw_job(raw_job)
                job.raw_id = raw_id

                # 4. Silver Layer: Upsert & Deduplicate
                saved_job, is_new = self.repo.upsert_job(job)
                if is_new:
                    new_in_source += 1

                # 5. Gold Layer: Multi-Track Scoring
                breakdown = self.scorer.score(saved_job)

                ai_insight = None
                if breakdown.is_match and is_new and self.ai_service.is_available():
                    ai_insight = self.ai_service.evaluate_job_fit(saved_job)

                scored = ScoredJob(
                    job=saved_job,
                    score_breakdown=breakdown,
                    ai_insight=ai_insight,
                )
                self.repo.save_scored_match(scored)

                if breakdown.is_match:
                    matches_in_source += 1

                    # 6. Employer Discovery: Sniff ATS apply URLs for matching jobs
                    sniffed_emp = detect_ats_employer(saved_job.url, company_hint=saved_job.company)
                    if sniffed_emp:
                        discovered_emp, is_new_emp = self.repo.upsert_discovered_employer(sniffed_emp)
                        # Notify about new high-match employer
                        if is_new_emp and not dry_run and self.telegram.is_configured():
                            self.telegram.send_employer_spotted(discovered_emp, matching_jobs=1)

            total_new_jobs += new_in_source
            total_matches += matches_in_source

            # Update run stats and record
            run_stats.new_items = new_in_source
            run_stats.matches_found = matches_in_source
            self.repo.record_source_run(run_stats)

            # 7. Observability: Health Evaluation per source
            self._evaluate_source_health(src_cfg, run_stats, unhealthy_sources)

        # 8. Send consolidated Source Health Alert if issues detected
        if unhealthy_sources and not dry_run and self.telegram.is_configured():
            self.telegram.send_health_alert(unhealthy_sources)

        # 9. Alert Dispatching
        alerts_sent = 0
        if not dry_run and self.telegram.is_configured():
            alert_limit = (
                self.config.pipeline.initial_run_baseline_alerts
                if is_baseline_run
                else self.config.pipeline.max_alerts_per_run
            )

            unnotified = self.repo.get_unnotified_matches(limit=alert_limit)
            for match in unnotified:
                success = self.telegram.send_job_alert(match)
                if success:
                    self.repo.mark_alert_sent(match.job.fingerprint)
                    alerts_sent += 1

            if len(unnotified) == alert_limit:
                summary_note = f"ℹ️ <i>Showing top {alert_limit} matches for this run.</i>"
                self.telegram.send_message(summary_note)

            # 10. Check 3-day deadline reminders
            closing_soon = self.repo.get_closing_soon_matches(
                days_ahead=self.config.pipeline.deadline_reminder_days
            )
            for expiring_match in closing_soon:
                if self.telegram.send_deadline_reminder(expiring_match):
                    self.repo.mark_deadline_reminder_sent(expiring_match.job.fingerprint)

            # 11. Monday Near-Miss Digest
            now_local = datetime.now()
            is_monday = (now_local.weekday() == 0)
            if is_monday or force_digest:
                near_misses = self.repo.get_near_misses(days_back=7)
                if near_misses:
                    self.telegram.send_near_miss_digest(near_misses)

        summary = {
            "duration_seconds": (datetime.now(timezone.utc) - run_start).total_seconds(),
            "sources_checked": len(active_sources),
            "items_fetched": total_fetched,
            "new_jobs": total_new_jobs,
            "matches_found": total_matches,
            "alerts_sent": alerts_sent,
            "is_baseline_run": is_baseline_run,
            "unhealthy_sources": len(unhealthy_sources),
        }
        logger.info("Pipeline run finished: %s", summary)
        return summary

    def _evaluate_source_health(
        self,
        src_cfg: SourceConfig,
        run_stats: SourceRun,
        unhealthy_sources: list[dict[str, Any]],
    ) -> None:
        """Check if a source failed, returned 0 items, or dropped >50% vs previous run."""
        # Check A: Execution failure
        if run_stats.status == "failed":
            unhealthy_sources.append({
                "name": src_cfg.name,
                "reason": f"Execution failed: {run_stats.error_message or 'Unknown error'}",
            })
            return

        # Check B: 0 items returned
        if run_stats.items_fetched == 0 and self.config.health_monitoring.alert_on_zero:
            unhealthy_sources.append({
                "name": src_cfg.name,
                "reason": "Returned 0 listings.",
            })
            return

        # Check C: Volume drop > 50% vs previous run
        prev_run = self.repo.get_previous_source_run(src_cfg.id)
        if prev_run and prev_run.items_fetched > 0:
            drop_threshold = self.config.health_monitoring.drop_threshold_percent / 100.0
            expected_min = prev_run.items_fetched * (1.0 - drop_threshold)
            if run_stats.items_fetched < expected_min:
                drop_pct = int((1.0 - (run_stats.items_fetched / prev_run.items_fetched)) * 100)
                unhealthy_sources.append({
                    "name": src_cfg.name,
                    "reason": f"Volume dropped by {drop_pct}% (from {prev_run.items_fetched} to {run_stats.items_fetched}).",
                })
