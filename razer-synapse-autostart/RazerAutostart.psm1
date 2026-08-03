# Shared logic for Razer Synapse autostart-on-USB-arrival.
# Imported by both the watcher (production) and the test harness, so the
# matching/launch behavior tested is exactly the behavior that runs live.

$script:DefaultSynapsePath = "C:\Program Files\Razer\RazerAppEngine\RazerAppEngine.exe"
$script:DefaultSynapseArgs = "--url-params=apps=synapse"
$script:DefaultLogPath = "$env:LOCALAPPDATA\RazerSynapseAutostart\watcher.log"

function Write-RazerLog {
    param(
        [Parameter(Mandatory)][string]$Message,
        [string]$LogPath = $script:DefaultLogPath
    )
    $dir = Split-Path $LogPath
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Path $LogPath -Value $line
    Write-Verbose $line
}

function Test-IsRazerDevice {
    <#
    Matches a PnP DeviceID string against a USB vendor ID.
    Real Razer device IDs look like: USB\VID_1532&PID_00AB\000000000000
    #>
    param(
        [string]$DeviceId,
        [string]$VendorId = "1532"
    )
    if ([string]::IsNullOrWhiteSpace($DeviceId)) { return $false }
    return $DeviceId -match "VID_$VendorId"
}

function Start-RazerSynapseIfNeeded {
    param(
        [string]$SynapsePath = $script:DefaultSynapsePath,
        [string]$SynapseArgs = $script:DefaultSynapseArgs,
        [string]$LogPath = $script:DefaultLogPath
    )
    $procName = [IO.Path]::GetFileNameWithoutExtension($SynapsePath)
    $running = Get-Process -Name $procName -ErrorAction SilentlyContinue
    if ($running) {
        Write-RazerLog -LogPath $LogPath -Message "Synapse already running (PID $($running[0].Id)); skipping launch."
        return $false
    }
    if (-not (Test-Path $SynapsePath)) {
        Write-RazerLog -LogPath $LogPath -Message "ERROR: Synapse executable not found at $SynapsePath"
        return $false
    }
    Write-RazerLog -LogPath $LogPath -Message "Launching Synapse: `"$SynapsePath`" $SynapseArgs"
    Start-Process -FilePath $SynapsePath -ArgumentList $SynapseArgs
    return $true
}

Export-ModuleMember -Function Write-RazerLog, Test-IsRazerDevice, Start-RazerSynapseIfNeeded
