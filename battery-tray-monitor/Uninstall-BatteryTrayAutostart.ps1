<#
Removes the scheduled task and stops any running tray app instance.
#>
param(
    [string]$TaskName = "BatteryTrayMonitorAutostart"
)

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Scheduled task '$TaskName' removed."
} else {
    Write-Host "Scheduled task '$TaskName' was not installed."
}

Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'battery_tray\.py' } |
    ForEach-Object {
        Write-Host "Stopping running tray app process (PID $($_.ProcessId))."
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
