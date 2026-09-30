# Register the monthly report task (ASCII only: Windows PowerShell 5.1 reads .ps1
# as ANSI when there is no BOM, which corrupts non-ASCII and breaks parsing).

$ErrorActionPreference = 'Stop'

$taskName = 'qlib-monthly-report'
$script   = '/mnt/d/workspaces/qlib/scripts/migration/wsl_run_monthly_report.sh'
$distro   = 'Ubuntu'

$action = New-ScheduledTaskAction -Execute 'wsl.exe' -Argument "-d $distro bash $script"

# 1st of each month at 09:00 local. Section [A] is the live paper track (advances with
# new data); section [B] recomputes the veto load-bearing check over the frozen
# research window (snapshot cache ends 2026-06-23).
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday,Saturday,Sunday -WeeksInterval 4 -At '09:00'
Write-Output "[trigger] every 4 weeks, 09:00 (approximating monthly)"

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Output "[replaced] removed existing task with the same name"
}

$desc = 'qlib monthly report: live paper-trading track plus veto load-bearing check over the frozen research window; exit code 2 means the veto contribution turned negative'
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description $desc | Out-Null

Write-Output "[ok] registered scheduled task: $taskName"
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State | Format-List
Get-ScheduledTaskInfo -TaskName $taskName | Select-Object LastRunTime, LastTaskResult, NextRunTime | Format-List
