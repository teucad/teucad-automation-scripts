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

$venvPythonw = Join-Path (Split-Path $PSScriptRoot -Parent) ".venv\Scripts\pythonw.exe"
if (Test-Path $venvPythonw) {
    $pythonwPath = $venvPythonw
} else {
    $pythonw = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if (-not $pythonw) {
        throw "pythonw.exe not found (no .venv, and none on PATH). Install Python and ensure it's on PATH, or edit this script to point at your install."
    }
    $pythonwPath = $pythonw.Source
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

Write-Host "Scheduled task '$TaskName' installed. It will start the tray app at your next logon."
Write-Host "To start it immediately without logging off/on, run:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
