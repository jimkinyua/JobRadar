# Job-Radar Deployment & Automation Guide 🚀

This document covers running and automating `job-radar` both on your live production Ubuntu 24.04 Linux VPS and on your local Windows PC.

---

## 🌟 Production Linux VPS (`167.86.109.143`)

The application is deployed at `/opt/jobradar` with a native PostgreSQL instance and Python 3.12 virtual environment.

### 1. Connecting to the Server

```bash
ssh root@167.86.109.143
```

### 2. Setting Telegram Credentials

To receive instant Telegram alerts on your phone, edit the production `.env`:

```bash
nano /opt/jobradar/.env
```

Add your credentials:
```ini
TELEGRAM_BOT_TOKEN="your_token_from_botfather"
TELEGRAM_CHAT_ID="your_telegram_chat_id"
```

Test the connection immediately:
```bash
/opt/jobradar/venv/bin/python -m jobradar test-telegram
```

### 3. Active Systemd Timers (Automated Background Execution)

Two native systemd timers run 24/7 in the cloud:

| Timer | Interval | Target Service | Purpose |
|---|---|---|---|
| `jobradar.timer` | Every 3 hours | `jobradar.service` | Crawls all 12 corporate & bank sources, scores matches, sends alerts |
| `jobradar-commands.timer` | Every 5 minutes | `jobradar-commands.service` | Polls Telegram for `/add <id>` & `/ignore <id>` employer commands |

To view timer schedules:
```bash
systemctl list-timers | grep jobradar
```

To view live pipeline logs:
```bash
journalctl -u jobradar.service -n 50 --no-pager
```

To manually trigger a run immediately on the VPS:
```bash
systemctl start jobradar.service
# OR directly via CLI:
cd /opt/jobradar && /opt/jobradar/venv/bin/python -m jobradar run
```

---

## 💻 Local Windows Development & Execution

If you also wish to run `job-radar` locally on your Windows PC:

### 1. Set Up Telegram in Local `.env`

Edit [`.env`](file:///c:/Job%20Crawler/.env) in the project root:
```ini
TELEGRAM_BOT_TOKEN="your_token_from_botfather"
TELEGRAM_CHAT_ID="your_telegram_chat_id"
```

### 2. Run Commands

```powershell
# Test Telegram connection
.\.venv\Scripts\python -m jobradar test-telegram

# Ingest and alert
.\.venv\Scripts\python -m jobradar run

# Dry-run without sending alerts
.\.venv\Scripts\python -m jobradar run --dry-run

# Run full automated test suite (34 tests)
.\.venv\Scripts\pytest tests/
```
