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
                      │  ★ AI Fallback Extractor (Gemini 2.0 Flash)  │
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
                      │    🥇 Gold Layer: Multi-Track Scoring & AI   │
                      │  Table: `scored_matches`                     │
                      │  - Multi-Persona weighted keyword scoring    │
                      │  ★ AI Career Copilot (Gemini 2.0 Flash)      │
                      │    • Semantic Fit & Match Rationale          │
                      │    • Candidate Skill Gap Analysis            │
                      │    • Tailored CV Bullet Point Generation     │
                      │  - Location & Seniority multipliers          │
                      └──────────────────────┬───────────────────────┘
                                             │
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │          Serving & Observability             │
                      │  - Telegram Alerts (with AI Briefing & Gaps) │
                      │  - Weekly Monday Near-Miss Digest (min-2)    │
                      │  - 3-Day Deadline Reminders                  │
                      │  - Source Health Anomaly Alerts (>50% drop)  │
                      │  - Web UI Dashboard with Match Breakdown     │
                      │  - Two-way Telegram bot commands (/add, /ign)│
                      └──────────────────────────────────────────────┘
```

---

## 🤖 Why AI in JobRadar? (Architectural Rationale)

While deterministic Python and PostgreSQL handle the data engineering backbone, traditional rules-based systems fail at two critical edges:

1. **Self-Healing Ingestion (Brittle HTML Scrapers)**:
   - *Problem*: Traditional CSS selectors fail whenever corporate career portals (e.g. Co-operative Bank of Kenya) adjust their DOM classes or render non-standard markup.
   - *AI Solution*: When CSS selectors extract 0 items from an active job page, JobRadar engages **Gemini 2.0 Flash** as a schema-constrained fallback extractor, converting unstructured HTML directly into validated Pydantic job entities.
2. **Contextual Semantic Matching (Beyond Flat Keywords)**:
   - *Problem*: Keyword counts miss semantic nuance (e.g., scoring *"Junior Sales Rep for Kafka software"* while missing *"Architect for high-throughput distributed event streams"*).
   - *AI Solution*: High-scoring matches are enriched by an **AI Career Copilot** that evaluates role requirements against your master profile, producing:
     - **Semantic Fit Rationale**: Plain-English explanation of why the role matches your career trajectory.
     - **Skill Gap Analysis**: Pinpointing missing prerequisites (e.g., required tools or certifications).
     - **Tailored Application Pitch**: Custom bullet points crafted specifically for that role's problem domain.

---

## 🎯 Scoring Strategy: Multi-Track Persona Matching

Rather than a single flat keyword score that over-indexes on one technology, `job-radar` scores jobs across **6 distinct professional tracks** and selects the best matching persona:

1. **Track A: Data Engineering & Streaming** (`kafka`, `etl`, `data engineer`, `sql`, `azure data factory`, `spark`, `pipeline`)
2. **Track B: Enterprise Cloud & .NET** (`.net`, `c#`, `asp.net`, `azure`, `functions`, `logic apps`, `entra id`)
3. **Track C: Modern Backend (Python / Go / Laravel)** (`python`, `golang`, `go`, `laravel`, `php`, `fastapi`, `django`, `rest api`)
4. **Track D: FinTech & System Integrations (Kenya / EMEA)** (`etims`, `tax`, `m-pesa`, `payments`, `integration`, `fintech`, `banking`)
5. **Track E: Engineering Leadership & Architecture** (`tech lead`, `team lead`, `architect`, `staff engineer`, `qa automation`)
6. **Track F: AI & Machine Learning Engineering** (`llm`, `rag`, `embeddings`, `langchain`, `langgraph`, `fine-tuning`, `pytorch`, `agents`, `vector database`)

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
# Run full ingestion, scoring, and notification pipeline (auto-syncs with Notion)
.\.venv\Scripts\python -m jobradar run [--dry-run]

# Trigger standalone two-way Notion synchronization
.\.venv\Scripts\python -m jobradar sync-notion

# Poll Telegram for pending /add, /ignore, and /apply commands
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

## 📑 Notion "Job Applications" Two-Way Synchronization

JobRadar integrates bidirectionally with your personal Notion workspace to act as a unified career intelligence system:

```
┌─────────────────────────────────┐                 ┌─────────────────────────────────┐
│        JobRadar System          │                 │       Notion Workspace          │
│ • Web Dashboard                 │ ◄─────────────► │ • "Job Applications" Database   │
│ • Telegram Bot [✅ Mark Applied] │   Two-Way Sync  │ • Status: Applied, Interview... │
│ • Automated 3-Hour Crawlers     │                 │ • Source of Truth for Pipeline  │
└─────────────────────────────────┘                 └─────────────────────────────────┘
```

### Key Capabilities
1. **Reminder & Alert Gatekeeping**: Once a job is marked `Applied`, `Screening`, `Interview`, `Final round`, `Offer`, `Rejected`, `No response`, or `Withdrawn` (in either JobRadar or Notion), all future Telegram alerts, Monday near-miss mentions, and 3-day deadline reminders for that job are immediately silenced.
2. **Dashboard Application Status Segmentation**: The executive web dashboard categorizes listings into distinct views:
   - **`New Matches`**: Fresh unapplied vacancies.
   - **`Applied & In Flight`**: Active applications in review or interview rounds.
   - **`Closed / Archived`**: Rejected, withdrawn, or concluded positions.
   - **`All Postings`**: Comprehensive unfiltered repository.
3. **One-Click Application Marking**:
   - **Telegram Alerts**: Directly tap `[✅ Mark Applied]` under any job notification card, or reply `/apply <job_id>`.
   - **Web UI**: Tap `[+ Mark Applied]` on any job card or select the stage in the modal dropdown. The vacancy is immediately created/updated in Notion with Role, Company, Date Applied, Closing Date, Portal Link, and notes.
4. **Fuzzy Matching for Manual Notion Rows**: If you manually log an application in Notion without pasting a link, JobRadar's fuzzy token matching engine resolves the row against crawled jobs using normalized company names and role tokens, automatically backfilling the verified job link into your Notion tracker.
5. **Zero-Crash Graceful Degradation**: If `NOTION_API_KEY` or `NOTION_DATABASE_ID` is omitted, JobRadar operates smoothly with standard local status tracking.

### Setup Instructions
1. Create an Internal Integration at [notion.so/my-integrations](https://www.notion.so/my-integrations) and obtain your `NOTION_API_KEY` (format: `ntn_...` or `secret_...`).
2. Share your "Job Applications" database with the integration (**...** -> **Connections** -> Select your integration).
3. Copy the 32-character database ID from the database URL:
   `https://www.notion.so/{workspace_name}/{database_id}?v={view_id}`
4. Add to your `.env`:
   ```bash
   NOTION_API_KEY=ntn_your_notion_secret_key
   NOTION_DATABASE_ID=your_32_character_database_id
   ```

---

## 🚀 Production Deployment & Automation

The application is deployed on an Ubuntu 24.04 VPS with native systemd timers (`jobradar.timer` every 3 hours, `jobradar-commands.timer` every 5 minutes) and native PostgreSQL. See [DEPLOYMENT.md](file:///c:/Job%20Crawler/DEPLOYMENT.md) for complete operation instructions.

---

## 🧪 Testing & Quality Assurance

- **Zero-Network Tests**: Pytest test suite with offline JSON/HTML fixtures.
- **Comprehensive Coverage**: Unit tests for adapters, Pydantic schemas, deduplicator fingerprints, scoring explainability, and Telegram HTML entity escaping.

