<#
Manual entry point for starting the battery tray monitor with no console
window. Ensures Python, the venv, and its requirements are installed, then
launches the app via pythonw.exe. Invoked by Start-BatteryTray.vbs.
#>
$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "battery_tray.py"
if (-not (Test-Path $scriptPath)) {
    throw "battery_tray.py not found at $scriptPath"
}

$pythonwPath = & (Join-Path $PSScriptRoot "Ensure-Env.ps1")
if (-not $pythonwPath -or -not (Test-Path $pythonwPath)) {
    throw "Failed to resolve pythonw.exe via Ensure-Env.ps1"
}

Start-Process -FilePath $pythonwPath -ArgumentList "`"$scriptPath`"" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
