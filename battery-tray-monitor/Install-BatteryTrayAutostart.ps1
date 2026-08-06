<#
Registers a Scheduled Task that launches the battery tray monitor hidden in
the background whenever the current user logs on. No admin rights required.
#>
param(
    [string]$TaskName = "BatteryTrayMonitorAutostart"
)

$scriptPath = Join-Path $PSScriptRoot "battery_tray.py"
if (-not (Test-Path $scriptPath)) {
    throw "battery_tray.py not found at $scriptPath"
}

$pythonwPath = & (Join-Path $PSScriptRoot "Ensure-Env.ps1")
if (-not $pythonwPath -or -not (Test-Path $pythonwPath)) {
    throw "Failed to resolve pythonw.exe via Ensure-Env.ps1"
}

$action = New-ScheduledTaskAction -Execute $pythonwPath -Argument "`"$scriptPath`"" -WorkingDirectory $PSScriptRoot

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "Runs the system-tray device battery monitor at logon."

Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host "Scheduled task '$TaskName' installed and the tray app has been started."
Write-Host "It will also start automatically at every future logon."
