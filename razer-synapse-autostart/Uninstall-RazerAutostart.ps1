<#
Removes the scheduled task and stops any running watcher instance.
#>
param(
    [string]$TaskName = "RazerSynapseAutostart"
)

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Scheduled task '$TaskName' removed."
} else {
    Write-Host "Scheduled task '$TaskName' was not installed."
}

Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'RazerSynapseWatcher\.ps1' } |
    ForEach-Object {
        Write-Host "Stopping running watcher process (PID $($_.ProcessId))."
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
