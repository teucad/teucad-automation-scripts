<#
Hardware-free test harness for the Razer Synapse autostart automation.
You don't need your Razer mouse plugged in to run this.

Modes (combine as needed):
  (default)     Unit-tests the VID-matching logic against real device-ID
                strings recorded on this machine from your Razer Basilisk V3
                Pro's last connection, plus negative cases. No side effects.
  -TestLaunch   Also calls the real launch function, to prove Synapse
                actually starts (or is correctly skipped if already running).
  -Live         Full end-to-end pipeline test using a USB device you *do*
                have on hand (e.g. a flash drive) as a stand-in for the
                mouse: registers the real WMI watcher against that device's
                vendor ID, then asks you to unplug/replug it.
  -ListUsb      Just lists currently connected USB devices with their vendor
                IDs, to help you pick one for -Live.
#>
param(
    [switch]$TestLaunch,
    [switch]$Live,
    [switch]$ListUsb,
    [string]$VendorId,
    [int]$LiveTimeoutSeconds = 60
)

Import-Module "$PSScriptRoot\RazerAutostart.psm1" -Force

function Assert-Equal($actual, $expected, $label) {
    $pass = $actual -eq $expected
    $status = if ($pass) { "PASS" } else { "FAIL" }
    $color = if ($pass) { "Green" } else { "Red" }
    Write-Host ("[{0}] {1} (got {2}, expected {3})" -f $status, $label, $actual, $expected) -ForegroundColor $color
    return $pass
}

if ($ListUsb) {
    Get-PnpDevice | Where-Object { $_.InstanceId -match '^USB\\VID_' -and $_.Present } |
        ForEach-Object {
            if ($_.InstanceId -match 'VID_([0-9A-Fa-f]{4})') {
                [PSCustomObject]@{ VendorId = $Matches[1]; FriendlyName = $_.FriendlyName; InstanceId = $_.InstanceId }
            }
        } | Sort-Object VendorId -Unique | Format-Table -AutoSize
    return
}

Write-Host "== Unit tests: VID matching logic ==" -ForegroundColor Cyan

# Real device-ID strings recorded on this machine from the Razer Basilisk V3 Pro
# (via Get-PnpDevice) -- used here instead of live hardware.
$realRazerIds = @(
    "USB\VID_1532&PID_00AB\000000000000",
    "USB\VID_1532&PID_00AB&MI_02\6&2C5B2018&0&0002",
    "HID\VID_1532&PID_00AB&MI_01&COL02\7&206076E&0&0001"
)
$nonRazerIds = @(
    "USB\VID_046D&PID_C52B\5&1A2B3C4D&0&1",   # Logitech
    "USB\VID_8087&PID_0025\5&2D4F1A&0&2"       # Intel
)

$allPass = $true
foreach ($id in $realRazerIds) {
    $allPass = (Assert-Equal (Test-IsRazerDevice -DeviceId $id -VendorId "1532") $true "Matches real Razer ID: $id") -and $allPass
}
foreach ($id in $nonRazerIds) {
    $allPass = (Assert-Equal (Test-IsRazerDevice -DeviceId $id -VendorId "1532") $false "Rejects non-Razer ID: $id") -and $allPass
}
$allPass = (Assert-Equal (Test-IsRazerDevice -DeviceId $null -VendorId "1532") $false "Rejects null/empty DeviceID") -and $allPass

if ($allPass) {
    Write-Host "All matching unit tests passed.`n" -ForegroundColor Green
} else {
    Write-Host "Some matching unit tests FAILED -- see above.`n" -ForegroundColor Red
}

if ($TestLaunch) {
    Write-Host "== Launch test: Start-RazerSynapseIfNeeded ==" -ForegroundColor Cyan
    Write-Host "This will actually attempt to launch Razer Synapse now."
    $started = Start-RazerSynapseIfNeeded
    if ($started) {
        Write-Host "Launch command issued. Check that Synapse opened." -ForegroundColor Green
    } else {
        Write-Host "Launch skipped (already running) or failed -- check log at $env:LOCALAPPDATA\RazerSynapseAutostart\watcher.log" -ForegroundColor Yellow
    }
    Write-Host ""
}

if ($Live) {
    if (-not $VendorId) {
        Write-Host "Pick a stand-in USB device's vendor ID to test the full pipeline with (run -ListUsb to see options), then re-run with -Live -VendorId <VID>." -ForegroundColor Yellow
        return
    }
    Write-Host "== Live end-to-end test: watching for VID_$VendorId arrival ==" -ForegroundColor Cyan
    Write-Host "Unplug and then replug the matching USB device now. Waiting up to $LiveTimeoutSeconds seconds..."

    $query = "SELECT * FROM __InstanceCreationEvent WITHIN 2 WHERE TargetInstance ISA 'Win32_PnPEntity'"
    $sourceId = "RazerAutostartLiveTest"
    $detected = $false

    Register-CimIndicationEvent -Query $query -SourceIdentifier $sourceId | Out-Null
    try {
        $deadline = (Get-Date).AddSeconds($LiveTimeoutSeconds)
        while ((Get-Date) -lt $deadline) {
            $ev = Wait-Event -SourceIdentifier $sourceId -Timeout 2
            if ($ev) {
                $deviceId = $ev.SourceEventArgs.NewEvent.TargetInstance.DeviceID
                Remove-Event -SourceIdentifier $sourceId
                if (Test-IsRazerDevice -DeviceId $deviceId -VendorId $VendorId) {
                    Write-Host "Detected matching device: $deviceId" -ForegroundColor Green
                    $detected = $true
                    Start-RazerSynapseIfNeeded | Out-Null
                    break
                }
            }
        }
    }
    finally {
        Unregister-Event -SourceIdentifier $sourceId -ErrorAction SilentlyContinue
    }

    if ($detected) {
        Write-Host "Live test PASSED: arrival event fired and launch was attempted." -ForegroundColor Green
    } else {
        Write-Host "Live test: no matching arrival detected within $LiveTimeoutSeconds seconds." -ForegroundColor Red
    }
}
