# automate-scripts

Personal Windows automation scripts. Each subfolder is a standalone project — see below for what each does and how to set it up.

## Requirements

- Windows 10/11
- PowerShell (5.1+, the version that ships with Windows)
- [Python 3.9+](https://www.python.org/downloads/) on `PATH`, for `battery-tray-monitor`

All installers register a per-user **Scheduled Task** to autostart at logon. No admin rights are required — they run under your own account with a "Limited" run level.

## Clone

```powershell
git clone https://github.com/teucad/teucad-automation-scripts.git
cd teucad-automation-scripts
```

---

## battery-tray-monitor

A system tray app that shows battery levels for your currently connected devices — Bluetooth/BLE mice, keyboards, headsets, Logitech wireless receivers, and AirPods (including AirPods Pro and Max). Click the tray icon for a popup listing every device's battery %, with charging status and low-battery coloring. Devices can be dragged into your preferred order via the popup, which then also drives what the tray tooltip shows.

Data comes from four sources, since no single Windows API covers everything:

| Source | Covers |
|---|---|
| `battery_query.ps1` — BLE Battery Service (`DEVPKEY_Bluetooth_Battery`) | BLE mice, keyboards, headsets — same data Settings > Bluetooth & devices uses |
| `battery_query.ps1` — inbox HID Battery Strength driver | USB dongle-based wireless mice/keyboards |
| `logitech_hidpp.py` — Logitech HID++ 2.0 protocol | Lightspeed/Bolt/Unifying receivers and direct-USB Logitech mice |
| `airpods_ble.py` — passive BLE advertisement scanning | AirPods, AirPods Pro, AirPods Max (Windows exposes no PnP/WMI property for these) |

Classic-Bluetooth-only HID devices using a vendor's proprietary protocol (e.g. a Logitech K380 over BT Classic) aren't visible to any Windows app — that's a platform limitation.

### Setup

```powershell
python -m venv .venv
.venv\Scripts\pip install -r battery-tray-monitor\requirements.txt
```

Run it directly (useful for testing — console stays open):

```powershell
.venv\Scripts\python battery-tray-monitor\battery_tray.py
```

### Autostart at logon

```powershell
powershell -ExecutionPolicy Bypass -File battery-tray-monitor\Install-BatteryTrayAutostart.ps1
```

Registers a scheduled task that launches the app hidden (via `pythonw.exe`, no console window) at every logon. To remove it:

```powershell
powershell -ExecutionPolicy Bypass -File battery-tray-monitor\Uninstall-BatteryTrayAutostart.ps1
```

### Files

- `battery_tray.py` — tray icon, popup UI, refresh loop, settings persistence
- `airpods_ble.py` — AirPods/AirPods Pro/Max battery via BLE advertisement scanning
- `logitech_hidpp.py` — Logitech receiver/mouse battery via HID++
- `battery_query.ps1` — BLE Battery Service + generic HID Battery Strength queries
- `settings.json` — persisted refresh interval and device display order (created/updated automatically)

---

## razer-synapse-autostart

Watches for USB device arrivals and launches Razer Synapse automatically as soon as a Razer peripheral (mouse, keyboard, etc.) is plugged in or reconnects — instead of Synapse launching at every logon regardless of whether a Razer device is actually present.

It matches devices by USB vendor ID (`1532` = Razer) via a WMI event subscription, and skips the launch if Synapse is already running.

### Autostart at logon

```powershell
powershell -ExecutionPolicy Bypass -File razer-synapse-autostart\Install-RazerAutostart.ps1
```

Registers a scheduled task that runs the watcher hidden at every logon (routed through `RunHidden.vbs` so no console window ever flashes, even briefly). To start it immediately without logging off/on:

```powershell
Start-ScheduledTask -TaskName RazerSynapseAutostart
```

To remove it:

```powershell
powershell -ExecutionPolicy Bypass -File razer-synapse-autostart\Uninstall-RazerAutostart.ps1
```

### Testing without hardware

```powershell
powershell -ExecutionPolicy Bypass -File razer-synapse-autostart\Test-RazerAutostart.ps1
```

Runs unit tests against recorded Razer/non-Razer device-ID strings — no Razer device needs to be plugged in. Other modes (combine as needed):

- `-TestLaunch` — actually calls the launch logic, to confirm Synapse starts (or is correctly skipped if already running)
- `-ListUsb` — lists currently connected USB devices with their vendor IDs
- `-Live -VendorId <VID>` — full end-to-end test: registers the real USB-arrival watcher against a stand-in device (e.g. a flash drive) and waits for you to unplug/replug it

### Files

- `RazerSynapseWatcher.ps1` — the persistent background watcher
- `RazerAutostart.psm1` — shared matching/launch logic, used by both the watcher and the test harness
- `RunHidden.vbs` — launches the watcher with zero visible window
- `Test-RazerAutostart.ps1` — hardware-free test harness
