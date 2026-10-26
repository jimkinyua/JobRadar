# Job-Radar 📡

> **A production-grade, multi-track Job Ingestion, Entity Resolution, and Alerting Pipeline.**  
> Designed with Modern Data Engineering principles: Medallion Architecture (Bronze/Silver/Gold), Pydantic contracts, fault-isolated ETL/ELT adapters, and automated Telegram alert dispatching.

---

## 🏛️ System Architecture & Design

`job-radar` is built as an end-to-end data pipeline that ingests jobs from heterogeneous external sources (APIs, RSS feeds, and rate-limited HTML web scrapers), standardizes them into structured entities, deduplicates listings across boards, scores them using a **Multi-Track Persona Engine**, and alerts via Telegram with two-way employer discovery commands.

```
                      ┌──────────────────────────────────────────────┐
                      │             External Job Sources             │
                      │  (Greenhouse, Lever, SmartRecruiters, RSS,   │
                      │   Remotive, ReliefWeb, Custom HTML Crawlers) │
                      └──────────────────────┬───────────────────────┘
                                             │
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │       1. Ingestion Layer (Extract)           │
                      │  - Fault-isolated source execution           │
                      │  - Robots.txt compliance & 2s rate limit     │
                      │  - ATS sniffer (Employer discovery)          │
                      └──────────────────────┬───────────────────────┘
                                             │
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │       🥉 Bronze Layer: Raw Ingestion         │
                      │  Table: `raw_jobs`                           │
                      │  - Immutable audit trail of exact payload    │
                      │  - Native PostgreSQL JSONB & text storage    │
                      │  - Time-travel & zero data loss              │
                      └──────────────────────┬───────────────────────┘
                                             │
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │    🥈 Silver Layer: Cleanse & Entity Dedupe  │
                      │  Table: `jobs`                               │
                      │  - Strict Pydantic v2 domain schemas         │
                      │  - URL canonicalization & company aliases    │
                      │  - Fingerprint deduplication (title+company) │
                      │  - Lifecycle tracking (first_seen, last_seen)│
                      └──────────────────────┬───────────────────────┘
                                             │
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │    🥇 Gold Layer: Multi-Track Scoring        │
                      │  Table: `scored_matches`                     │
                      │  - Multi-Persona weighted keyword scoring    │
                      │  - Explainable JSON audit breakdown          │
                      │  - Disqualification gatekeeper filters       │
                      │  - Location & Seniority multipliers          │
                      └──────────────────────┬───────────────────────┘
                                             │
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │          Serving & Observability             │
                      │  - Telegram Alerts (HTML-safe, top 15)       │
                      │  - Weekly Monday Near-Miss Digest (min-2)    │
                      │  - 3-Day Deadline Reminders                  │
                      │  - Source Health Anomaly Alerts (>50% drop)  │
                      │  - Two-way Telegram bot commands (/add, /ign)│
                      └──────────────────────────────────────────────┘
```

---

## 🎯 Scoring Strategy: Multi-Track Persona Matching

Rather than a single flat keyword score that over-indexes on one technology, `job-radar` scores jobs across **5 distinct professional tracks** and selects the best matching persona:

1. **Track A: Data Engineering & Streaming** (`kafka`, `etl`, `data engineer`, `sql`, `azure data factory`, `spark`, `pipeline`)
2. **Track B: Enterprise Cloud & .NET** (`.net`, `c#`, `asp.net`, `azure`, `functions`, `logic apps`, `entra id`)
3. **Track C: Modern Backend (Python / Go / Laravel)** (`python`, `golang`, `go`, `laravel`, `php`, `fastapi`, `django`, `rest api`)
4. **Track D: FinTech & System Integrations (Kenya / EMEA)** (`etims`, `tax`, `m-pesa`, `payments`, `integration`, `fintech`, `banking`)
5. **Track E: Engineering Leadership & Architecture** (`tech lead`, `team lead`, `architect`, `staff engineer`, `qa automation`)

$$\text{Final Score} = \max(\text{Track Scores}) + \text{Location Multipliers} + \text{Seniority Multipliers} - \text{Disqualifiers}$$

---

## 🗄️ Database Architecture (PostgreSQL)

- **`raw_jobs` (Bronze)**: Untouched response payload (`JSONB` for APIs, `TEXT` for HTML), source name, URL, and extraction timestamp.
- **`jobs` (Silver)**: Standardized job entities with canonical fingerprint `hash(normalized_company + normalized_title)`, `first_seen`, `last_seen`, `is_closed`.
- **`scored_matches` (Gold)**: Matches meeting or exceeding `min_score` (default: 8.0) with granular scoring audit JSON and alert dispatch status.
- **`source_runs`**: Ingestion observability tracking records fetched, duplicates found, parse errors, and status drift per source run.
- **`discovered_employers`**: Sniffed ATS boards (SmartRecruiters, Greenhouse, Lever, Workable, JazzHR, Workday) awaiting approval via Telegram `/add <id>` or `/ignore <id>`.

---

## 🚀 CLI Commands

```powershell
# Run full ingestion, scoring, and notification pipeline
.\.venv\Scripts\python -m jobradar run [--dry-run]

# Poll Telegram for pending /add and /ignore commands
.\.venv\Scripts\python -m jobradar commands

# Verify Telegram bot credentials and test message delivery
.\.venv\Scripts\python -m jobradar test-telegram

# Display health and status of all configured sources
.\.venv\Scripts\python -m jobradar sources

# List pending, approved, and ignored discovered employers
.\.venv\Scripts\python -m jobradar employers

# Re-evaluate stored jobs against updated scoring keywords
.\.venv\Scripts\python -m jobradar rescore

# Export matched jobs to CSV
.\.venv\Scripts\python -m jobradar export-csv --output matches.csv
```

---

## 🚀 Production Deployment & Automation

The application is deployed on an Ubuntu 24.04 VPS with native systemd timers (`jobradar.timer` every 3 hours, `jobradar-commands.timer` every 5 minutes) and native PostgreSQL. See [DEPLOYMENT.md](file:///c:/Job%20Crawler/DEPLOYMENT.md) for complete operation instructions.

---

## 🧪 Testing & Quality Assurance

- **Zero-Network Tests**: Pytest test suite with offline JSON/HTML fixtures.
- **Comprehensive Coverage**: Unit tests for adapters, Pydantic schemas, deduplicator fingerprints, scoring explainability, and Telegram HTML entity escaping.

