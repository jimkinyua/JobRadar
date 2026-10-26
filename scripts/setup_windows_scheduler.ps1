# ==============================================================================
# Setup Windows Task Scheduler for JobRadar (Every 3 Hours)
# ==============================================================================
$ErrorActionPreference = "Stop"

$ProjectDir = (Get-Item $PSScriptRoot).Parent.FullName
$BatchFile = Join-Path $ProjectDir "run_jobradar.bat"

Write-Host "Configuring Windows Task Scheduler for JobRadar..." -ForegroundColor Cyan
Write-Host "Batch Runner: $BatchFile"

$TaskName = "JobRadar_Pipeline"
$Action = New-ScheduledTaskAction -Execute $BatchFile -WorkingDirectory $ProjectDir
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 3)
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

# Unregister existing if present
try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
} catch {}

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Automated JobRadar ingestion and alert pipeline (Runs every 3 hours)"

Write-Host "✅ Task Scheduler configured successfully!" -ForegroundColor Green
Write-Host "Task Name: $TaskName (Runs every 3 hours)"
