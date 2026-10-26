@echo off
REM ==============================================================================
REM JobRadar Local Automation Runner for Windows
REM ==============================================================================
cd /d "%~dp0"

echo [%DATE% %TIME%] Starting JobRadar execution... >> data\run.log 2>&1

REM 1. Process Telegram Bot Commands (/add, /ignore)
.\.venv\Scripts\python -m jobradar commands >> data\run.log 2>&1

REM 2. Run Job Discovery, Scoring, and Alerting Pipeline
.\.venv\Scripts\python -m jobradar run >> data\run.log 2>&1

echo [%DATE% %TIME%] JobRadar execution finished. >> data\run.log 2>&1
