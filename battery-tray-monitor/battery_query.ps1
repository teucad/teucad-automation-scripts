<#
Two sources of battery data, covering both Bluetooth and USB peripherals:

1. DEVPKEY_Bluetooth_Battery - the standard BLE "Battery" GATT
   characteristic. Same property Windows itself uses in Settings >
   Bluetooth & devices. Covers BLE mice, keyboards, and headsets.

2. The inbox HID Battery Strength driver (hidbatt.sys) - any USB or
   Bluetooth HID device that reports the standard HID "Battery Strength"
   usage shows up as a Class=Battery PnP device, backed by the same
   root\WMI battery provider used for the laptop's own battery. This is
   what covers USB wireless mice/keyboards (dongle-based) that support it,
   and is the same data source behind the Windows 11 taskbar battery
   flyout's per-device list.

Classic-Bluetooth-only HID devices (e.g. Logitech K380 over BT Classic,
which uses Logitech's proprietary HID++ protocol) will not appear here -
Windows has no public API for those, regardless of connection type.
AirPods Max is handled separately, via BLE advertisement scanning in
airpods_ble.py (see battery_tray.py's docstring).
#>

$results = @()

# --- Source 1: Bluetooth LE Battery Service ---
# Querying Get-PnpDeviceProperty once per device is slow (~0.4s each; systems
# with 50+ Bluetooth/HID entries can take 20+ seconds). Passing all instance
# IDs at once runs it as a single batched query instead.
$batteryKey = '{104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2'
$btClasses = 'Bluetooth', 'BluetoothLE', 'HIDClass'
$btDevices = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | Where-Object { $_.Class -in $btClasses }
if ($btDevices) {
    $nameByInstance = @{}
    foreach ($d in $btDevices) { $nameByInstance[$d.InstanceId] = $d.FriendlyName }

    $props = Get-PnpDeviceProperty -InstanceId $btDevices.InstanceId -KeyName $batteryKey -ErrorAction SilentlyContinue
    foreach ($p in $props) {
        if ($null -ne $p.Data) {
            $results += [PSCustomObject]@{
                Name    = $nameByInstance[$p.InstanceId]
                Battery = [int]$p.Data
            }
        }
    }
}

# --- Source 2: generic HID Battery Strength (covers USB dongle peripherals) ---
$status = Get-CimInstance -Namespace root\WMI -ClassName BatteryStatus -ErrorAction SilentlyContinue |
    Where-Object { $_.InstanceName -notmatch '^ACPI\\' }
$fullCap = Get-CimInstance -Namespace root\WMI -ClassName BatteryFullChargedCapacity -ErrorAction SilentlyContinue

foreach ($s in $status) {
    $full = $fullCap | Where-Object { $_.InstanceName -eq $s.InstanceName } | Select-Object -First 1
    if ($null -eq $full -or $full.FullChargedCapacity -le 0) { continue }

    $pnpInstanceId = $s.InstanceName -replace '_[0-9]+$', ''
    $dev = Get-PnpDevice -InstanceId $pnpInstanceId -ErrorAction SilentlyContinue
    $name = if ($dev) { $dev.FriendlyName } else { $pnpInstanceId }

    $pct = [Math]::Round(($s.RemainingCapacity / $full.FullChargedCapacity) * 100)
    $pct = [Math]::Min(100, [Math]::Max(0, $pct))

    $results += [PSCustomObject]@{
        Name    = $name
        Battery = [int]$pct
    }
}

$results = $results | Sort-Object Name -Unique

if ($results.Count -eq 0) {
    Write-Output '[]'
} else {
    ConvertTo-Json -InputObject @($results) -Compress
}
