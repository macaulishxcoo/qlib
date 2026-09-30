# Register a Windows Scheduled Task: run the qlib daily update after market close.
#
# Why Windows Task Scheduler and not WSL cron/systemd timers:
#   the WSL2 VM shuts itself down when idle, so in-VM timers do not fire reliably;
#   invoking wsl.exe starts the distro on demand.
#
# ASCII-only on purpose: Windows PowerShell 5.1 reads .ps1 as ANSI when there is no
# BOM, which corrupts non-ASCII text and breaks parsing.

$ErrorActionPreference = 'Stop'

$taskName = 'qlib-daily-update'
$script   = '/mnt/d/workspaces/qlib/scripts/migration/wsl_run_daily_update.sh'
$distro   = 'Ubuntu'

$action = New-ScheduledTaskAction -Execute 'wsl.exe' -Argument "-d $distro bash $script"

# 18:00 local: A-share closes 15:00; the daily_basic updater refuses same-day data
# before 17:00, so leave margin.
try {
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At '18:00'
    Write-Output "[trigger] weekly Mon-Fri 18:00"
} catch {
    $trigger = New-ScheduledTaskTrigger -Daily -At '18:00'
    Write-Output "[trigger] fallback: daily 18:00 (weekends are no-ops)"
}

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Output "[replaced] removed existing task with the same name"
}

$desc = 'qlib daily strategy: update market data, regenerate holdings (with 10-day rebalance grid guard), mark paper book to market'
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description $desc | Out-Null

Write-Output "[ok] registered scheduled task: $taskName"
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State | Format-List
Get-ScheduledTaskInfo -TaskName $taskName | Select-Object LastRunTime, LastTaskResult, NextRunTime | Format-List
