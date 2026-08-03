<#
Watches for USB arrival of a Razer device (by vendor ID) and launches
Razer Synapse if it isn't already running. Intended to run persistently,
hidden, in the background, started at user logon by the scheduled task
created via Install-RazerAutostart.ps1.
#>
param(
    [string]$VendorId = "1532",
    [string]$SynapsePath = "C:\Program Files\Razer\RazerAppEngine\RazerAppEngine.exe",
    [string]$SynapseArgs = "--url-params=apps=synapse",
    [string]$LogPath = "$env:LOCALAPPDATA\RazerSynapseAutostart\watcher.log"
)

Import-Module "$PSScriptRoot\RazerAutostart.psm1" -Force

Write-RazerLog -LogPath $LogPath -Message "Watcher started. Watching for VID_$VendorId USB arrivals (PID $PID)."

$query = "SELECT * FROM __InstanceCreationEvent WITHIN 2 WHERE TargetInstance ISA 'Win32_PnPEntity'"
$messageData = [PSCustomObject]@{
    VendorId    = $VendorId
    SynapsePath = $SynapsePath
    SynapseArgs = $SynapseArgs
    LogPath     = $LogPath
}

$action = {
    $deviceId = $Event.SourceEventArgs.NewEvent.TargetInstance.DeviceID
    $cfg = $Event.MessageData
    if (Test-IsRazerDevice -DeviceId $deviceId -VendorId $cfg.VendorId) {
        Write-RazerLog -LogPath $cfg.LogPath -Message "Razer device detected: $deviceId"
        Start-RazerSynapseIfNeeded -SynapsePath $cfg.SynapsePath -SynapseArgs $cfg.SynapseArgs -LogPath $cfg.LogPath
    }
}

$subscription = Register-CimIndicationEvent -Query $query -Action $action -MessageData $messageData -SourceIdentifier "RazerSynapseWatcher"

try {
    while ($true) {
        Wait-Event -SourceIdentifier "RazerSynapseWatcher" -Timeout 3600 | Remove-Event -ErrorAction SilentlyContinue
    }
}
finally {
    Unregister-Event -SourceIdentifier "RazerSynapseWatcher" -ErrorAction SilentlyContinue
    Write-RazerLog -LogPath $LogPath -Message "Watcher stopped."
}
