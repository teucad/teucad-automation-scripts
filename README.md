# teucad-automation-scripts

Personal Windows automation scripts. Each subfolder is a standalone project — see below for what each does and how to set it up.

## Requirements

- Windows 10/11
- PowerShell (5.1+, the version that ships with Windows)
- [winget](https://learn.microsoft.com/en-us/windows/package-manager/winget/) (ships with modern Windows 10/11) — used to auto-install Python for `battery-tray-monitor` and `ollama-aider-setup` if it isn't already on `PATH`

All installers register a per-user **Scheduled Task** to autostart at logon. No admin rights are required — they run under your own account with a "Limited" run level.

The `battery-tray-monitor` and `ollama-aider-setup` install/start scripts install Python (via `winget`, if missing) and their pip requirements automatically — no manual `venv`/`pip` setup needed.

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

No manual setup needed — both entry points below install Python (via `winget`, if it's missing) and create `.venv` with the pip requirements automatically via `Ensure-Env.ps1`.

To start it manually without a console window (e.g. via a desktop/Start Menu shortcut), double-click `battery-tray-monitor\Start-BatteryTray.vbs` — it ensures the environment is set up, then launches the app via `pythonw.exe`.

To run it directly instead (useful for testing — console stays open, and lets you see install/setup output the first time):

```powershell
powershell -ExecutionPolicy Bypass -File battery-tray-monitor\Ensure-Env.ps1
.venv\Scripts\python battery-tray-monitor\battery_tray.py
```

### Autostart at logon

```powershell
powershell -ExecutionPolicy Bypass -File battery-tray-monitor\Install-BatteryTrayAutostart.ps1
```

Ensures Python/the venv/requirements are installed, then registers a scheduled task that launches the app hidden (via `pythonw.exe`, no console window) at every logon, and starts it immediately. To remove it:

```powershell
powershell -ExecutionPolicy Bypass -File battery-tray-monitor\Uninstall-BatteryTrayAutostart.ps1
```

### Files

- `battery_tray.py` — tray icon, popup UI, refresh loop, settings persistence
- `airpods_ble.py` — AirPods/AirPods Pro/Max battery via BLE advertisement scanning
- `logitech_hidpp.py` — Logitech receiver/mouse battery via HID++
- `battery_query.ps1` — BLE Battery Service + generic HID Battery Strength queries
- `settings.json` — persisted refresh interval and device display order (created/updated automatically)
- `Ensure-Env.ps1` — installs Python (via `winget`, if missing), creates `.venv`, and installs `requirements.txt`; used by both the installer and the manual start scripts
- `Start-BatteryTray.ps1` / `Start-BatteryTray.vbs` — manual entry point that ensures the environment, then starts the app with no console window

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

---

## ollama-aider-setup

Two scripts to install and run [Aider](https://aider.chat/) (an AI pair-programming CLI) against a local model served by [Ollama](https://ollama.com/), instead of a paid cloud API.

### 1. Install (once)

```powershell
powershell -ExecutionPolicy Bypass -File ollama-aider-setup\1-Install.ps1
```

Installs Python via `winget` if it isn't already present, installs Ollama via `winget` if it isn't already present, installs/upgrades Aider via `pip`, and pulls a model (defaults to `qwen2.5-coder:7b`; pass `-Model "<name>"` for a different one).

### 2. Run

```powershell
powershell -ExecutionPolicy Bypass -File ollama-aider-setup\2-Run-Aider.ps1
```

Starts the Ollama service in the background if it isn't already running, then launches Aider against a model. With no arguments it prompts you to pick from your installed models and asks for a project folder (defaults to the current directory). Both can be passed directly to skip the prompts:

```powershell
powershell -ExecutionPolicy Bypass -File ollama-aider-setup\2-Run-Aider.ps1 -Model "qwen2.5-coder:7b" -ProjectPath "C:\my-projects\project1"
```

### Files

- `1-Install.ps1` — one-time setup: Ollama, Aider, and a model
- `2-Run-Aider.ps1` — starts the Ollama service (if needed) and launches Aider against a chosen model/project
