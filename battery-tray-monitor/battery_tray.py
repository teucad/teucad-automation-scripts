"""System tray battery monitor for connected Bluetooth/USB peripherals.

Click the tray icon to open a small window listing battery levels. Devices
are read from four sources: the BLE Battery Service property (see
battery_query.ps1) that Settings > Bluetooth & devices uses, the inbox HID
Battery Strength driver which covers USB dongle-based mice/keyboards that
report battery over standard HID, Logitech's HID++ protocol (see
logitech_hidpp.py) for Lightspeed/Bolt/Unifying receivers, and AirPods Max
(see airpods_ble.py), read by passively scanning its BLE advertisements
since Windows exposes no PnP/WMI property for it. Classic Bluetooth HID
devices using other vendor protocols (e.g. the Logitech K380) are not
exposed by Windows to any app - that is a platform limitation, not a bug
here.
"""

import json
import queue
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

import airpods_ble
import logitech_hidpp

SCRIPT_DIR = Path(__file__).resolve().parent
QUERY_SCRIPT = SCRIPT_DIR / "battery_query.ps1"
SETTINGS_PATH = SCRIPT_DIR / "settings.json"
DEFAULT_REFRESH_SECONDS = 20
INTERVAL_OPTIONS_SECONDS = [5, 10, 20, 30, 60, 300]
TOOLTIP_MAX_DEVICES = 3


class Settings:
    """Persists user-adjustable options (currently just the refresh interval)."""

    def __init__(self, path):
        self.path = path
        self.refresh_seconds = DEFAULT_REFRESH_SECONDS
        self._load()

    def _load(self):
        try:
            data = json.loads(self.path.read_text())
            value = data.get("refresh_seconds")
            if isinstance(value, (int, float)) and value > 0:
                self.refresh_seconds = value
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    def set_refresh_seconds(self, value):
        self.refresh_seconds = value
        try:
            self.path.write_text(json.dumps({"refresh_seconds": value}))
        except OSError:
            pass


def get_peripheral_batteries():
    try:
        proc = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-File", str(QUERY_SCRIPT),
            ],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []

    raw = proc.stdout.strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    return [
        {"name": d.get("Name", "Unknown device"), "battery": int(d.get("Battery", 0)), "charging": False}
        for d in data
    ]


def get_logitech_batteries():
    try:
        return logitech_hidpp.get_batteries()
    except Exception:
        return []


def get_airpods_batteries():
    try:
        return airpods_ble.get_batteries()
    except Exception:
        return []


_last_devices = []
_last_devices_lock = threading.Lock()


def get_all_batteries():
    devices = get_peripheral_batteries()

    existing = {d["name"] for d in devices}
    for source in (get_logitech_batteries(), get_airpods_batteries()):
        for d in source:
            if d["name"] not in existing:
                devices.append(d)
                existing.add(d["name"])

    with _last_devices_lock:
        global _last_devices
        _last_devices = devices

    return devices


def get_cached_batteries():
    with _last_devices_lock:
        return list(_last_devices)


def battery_color(pct):
    if pct <= 20:
        return (220, 53, 69)
    if pct <= 50:
        return (255, 193, 7)
    return (40, 167, 69)


def make_icon(devices):
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if not devices:
        draw.rectangle([10, 18, 46, 46], outline=(150, 150, 150), width=4)
        draw.rectangle([46, 26, 54, 38], fill=(150, 150, 150))
        draw.line([16, 12, 40, 52], fill=(150, 150, 150), width=5)
        return img

    lowest = min(d["battery"] for d in devices)
    color = battery_color(lowest)

    draw.rectangle([6, 18, 50, 46], outline=color, width=4)
    draw.rectangle([50, 26, 58, 38], fill=color)
    fill_width = int(38 * (lowest / 100))
    if fill_width > 0:
        draw.rectangle([8, 20, 8 + fill_width, 44], fill=color)
    return img


WINDOW_WIDTH = 300
ROW_HEIGHT = 30


class BatteryWindow:
    """Borderless flyout popup - just the device battery list, nothing else."""

    def __init__(self, root):
        self.root = root
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.resizable(False, False)
        self.root.configure(bg="#1e1e1e", highlightthickness=1, highlightbackground="#555555")

        self.frame = tk.Frame(root, bg="#1e1e1e", padx=14, pady=10)
        self.frame.pack(fill="both", expand=True)

        # zero-height spacer to force a minimum width without freezing height
        tk.Frame(self.frame, bg="#1e1e1e", width=WINDOW_WIDTH - 28, height=1).pack()

        self.rows_frame = tk.Frame(self.frame, bg="#1e1e1e")
        self.rows_frame.pack(fill="both", expand=True)

        self.root.bind("<Escape>", lambda e: self.hide())
        self.root.bind("<Button-1>", lambda e: self.hide())

    def _placeholder(self, text):
        for child in self.rows_frame.winfo_children():
            child.destroy()
        tk.Label(
            self.rows_frame, text=text, fg="#aaaaaa", bg="#1e1e1e", anchor="w",
        ).pack(fill="x", pady=6)
        self.root.geometry("")
        self.root.update_idletasks()
        self._reposition()

    def render(self, devices):
        for child in self.rows_frame.winfo_children():
            child.destroy()

        if not devices:
            self._placeholder("No trackable devices found.")
            return

        for d in devices:
            row = tk.Frame(self.rows_frame, bg="#1e1e1e", height=ROW_HEIGHT)
            row.pack(fill="x", pady=3)
            row.pack_propagate(False)
            tk.Label(
                row, text=d["name"], anchor="w", fg="#eeeeee", bg="#1e1e1e",
            ).pack(side="left", fill="x", expand=True)
            pct = d["battery"]
            suffix = " ⚡" if d.get("charging") else ""
            color = "#{:02x}{:02x}{:02x}".format(*battery_color(pct))
            tk.Label(
                row, text=f"{pct}%{suffix}", fg=color, bg="#1e1e1e", anchor="e",
            ).pack(side="right")

        self.root.geometry("")  # let the window auto-size to its natural content size
        self.root.update_idletasks()
        self._reposition()

    def refresh(self):
        def worker():
            devices = get_all_batteries()
            self.root.after(0, lambda: self.render(devices))

        threading.Thread(target=worker, daemon=True).start()

    def _reposition(self):
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        x = screen_w - w - 20
        y = screen_h - h - 60
        self.root.geometry(f"+{x}+{y}")

    def show(self):
        cached = get_cached_batteries()
        if cached:
            self.render(cached)
        else:
            self._placeholder("Loading...")
        self.root.deiconify()
        self._reposition()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.focus_force()
        self.refresh()

    def hide(self):
        self.root.withdraw()

    def toggle(self):
        if self.root.state() == "withdrawn":
            self.show()
        else:
            self.hide()


def build_tooltip(devices):
    if not devices:
        return "Device Batteries: no devices found"
    shown = sorted(devices, key=lambda d: d["battery"])[:TOOLTIP_MAX_DEVICES]
    return "\n".join(
        f"{d['name']}: {d['battery']}%" + (" (charging)" if d.get("charging") else "")
        for d in shown
    )


def main():
    airpods_ble.start()

    root = tk.Tk()
    window = BatteryWindow(root)
    settings = Settings(SETTINGS_PATH)

    ui_queue = queue.Queue()

    def poll_queue():
        try:
            while True:
                action = ui_queue.get_nowait()
                action()
        except queue.Empty:
            pass
        root.after(150, poll_queue)

    def on_toggle(icon, item=None):
        ui_queue.put(window.toggle)

    def on_quit(icon, item=None):
        icon.stop()
        ui_queue.put(root.quit)

    def update_icon(icon):
        devices = get_all_batteries()
        icon.icon = make_icon(devices)
        icon.title = build_tooltip(devices)

    def icon_refresh_loop(icon):
        elapsed = 0
        while True:
            time.sleep(1)
            elapsed += 1
            if elapsed >= settings.refresh_seconds:
                elapsed = 0
                update_icon(icon)

    def interval_label(seconds):
        return f"{seconds}s" if seconds < 60 else f"{seconds // 60} min"

    def make_set_interval(seconds):
        def handler(icon, item):
            settings.set_refresh_seconds(seconds)
        return handler

    def make_is_checked(seconds):
        return lambda item: settings.refresh_seconds == seconds

    interval_menu = pystray.Menu(*(
        pystray.MenuItem(
            interval_label(seconds), make_set_interval(seconds),
            checked=make_is_checked(seconds), radio=True,
        )
        for seconds in INTERVAL_OPTIONS_SECONDS
    ))

    menu = pystray.Menu(
        pystray.MenuItem("Show batteries", on_toggle, default=True, visible=False),
        pystray.MenuItem("Show / Hide", on_toggle),
        pystray.MenuItem("Update interval", interval_menu),
        pystray.MenuItem("Quit", on_quit),
    )
    initial_devices = get_all_batteries()
    icon = pystray.Icon(
        "battery-tray-monitor", make_icon(initial_devices), build_tooltip(initial_devices), menu,
    )

    threading.Thread(target=icon.run, daemon=True).start()
    threading.Thread(target=icon_refresh_loop, args=(icon,), daemon=True).start()

    root.after(150, poll_queue)
    root.mainloop()


if __name__ == "__main__":
    main()
