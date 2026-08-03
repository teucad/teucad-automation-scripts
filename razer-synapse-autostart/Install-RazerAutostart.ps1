<#
Registers a Scheduled Task that runs RazerSynapseWatcher.ps1 hidden in the
background whenever the current user logs on. No admin rights required.
#>
param(
    [string]$TaskName = "RazerSynapseAutostart"
)

$scriptPath = Join-Path $PSScriptRoot "RazerSynapseWatcher.ps1"
if (-not (Test-Path $scriptPath)) {
    throw "Watcher script not found at $scriptPath"
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$scriptPath`""

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
    -Description "Watches for Razer USB device arrival and launches Razer Synapse."

Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null

Write-Host "Scheduled task '$TaskName' installed. It will start the watcher at your next logon."
Write-Host "To start it immediately without logging off/on, run:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
