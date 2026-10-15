# Registers the daily local update (scrape -> validate -> commit -> push).
# Local on purpose: sportsbook pages tend to block cloud IPs, so no GitHub Actions.
# Runs while you're logged in (uses your git credentials). Re-run to change the time.
param([string]$At = "9:00AM")
$name = "NBA Win Totals daily update"
# pythonw: no console window to get closed (or Ctrl+C'd) mid-run. update.py logs to logs\update.log.
$py = Join-Path (Split-Path (Get-Command python).Source) "pythonw.exe"
$action = New-ScheduledTaskAction -Execute $py -Argument "update.py" -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Description "Scrape NBA win totals and publish to GitHub Pages" -Force | Out-Null
Get-ScheduledTask -TaskName $name | Select-Object TaskName, State
