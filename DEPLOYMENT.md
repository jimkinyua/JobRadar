# Job-Radar Local Windows Automation Guide 🚀

This document details how to run and automate `job-radar` natively on your Windows PC using Python 3.12+, local PostgreSQL, and Windows Task Scheduler.

---

## 1. Setting Up Your Telegram Bot Credentials

1. Open Telegram and message **[@BotFather](https://t.me/BotFather)**.
2. Send `/newbot`, choose a name (e.g., `James Job Radar`), and choose a username ending in `bot` (e.g., `james_jobradar_bot`).
3. Copy the HTTP API token provided by BotFather. This is your `TELEGRAM_BOT_TOKEN`.
4. Start a conversation with your new bot by pressing **Start** or sending `/start`.
5. In your web browser, open:
   ```text
   https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
   ```
6. Locate `"chat":{"id": 123456789, ...}`. That number is your `TELEGRAM_CHAT_ID`.
7. Paste both values into your local `.env` file:
   ```ini
   TELEGRAM_BOT_TOKEN=your_token_here
   TELEGRAM_CHAT_ID=your_chat_id_here
   ```

---

## 2. Verifying Telegram Connection

Open PowerShell in `c:\Job Crawler` and run:

```powershell
.\.venv\Scripts\python -m jobradar test-telegram
```
You will receive an instant test confirmation message on your Telegram.

---

## 3. Running the Pipeline Manually

```powershell
# 1. Dry-run test (prints matches to terminal without sending Telegram spam)
.\.venv\Scripts\python -m jobradar run --dry-run

# 2. Real execution (saves all jobs to PostgreSQL and sends matches to Telegram)
.\.venv\Scripts\python -m jobradar run

# 3. Check health and stats of all direct bank, Big 4, and remote sources
.\.venv\Scripts\python -m jobradar sources

# 4. Check discovered ATS employers (/add and /ignore list)
.\.venv\Scripts\python -m jobradar employers
```

---

## 4. Setting Up Automated Background Execution (Every 3 Hours)

To have Windows run `job-radar` in the background automatically every 3 hours:

Run the included PowerShell automation script:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_windows_scheduler.ps1
```

This registers a task named `JobRadar_Pipeline` in Windows Task Scheduler:
- **Interval**: Runs every 3 hours.
- **Actions**:
  1. Polls Telegram for any `/add <id>` or `/ignore <id>` employer commands you sent from your phone.
  2. Ingests all active direct career portals, feeds, and APIs.
  3. Evaluates your 5 profile tracks and sends fresh alerts to Telegram.
- **Logging**: Appends logs to `data/run.log`.
