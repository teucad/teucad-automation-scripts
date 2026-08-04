"""System tray battery monitor for connected Bluetooth/USB peripherals.

Click the tray icon to open a small window listing battery levels. Devices
are read from four sources: the BLE Battery Service property (see
battery_query.ps1) that Settings > Bluetooth & devices uses, the inbox HID
Battery Strength driver which covers USB dongle-based mice/keyboards that
report battery over standard HID, Logitech's HID++ protocol (see
logitech_hidpp.py) for Lightspeed/Bolt/Unifying receivers, and AirPods/
AirPods Pro/AirPods Max (see airpods_ble.py), read by passively scanning
their BLE advertisements since Windows exposes no PnP/WMI property for
them. Classic Bluetooth HID
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
    """Persists user-adjustable options: refresh interval and device display order."""

    def __init__(self, path):
        self.path = path
        self.refresh_seconds = DEFAULT_REFRESH_SECONDS
        self.device_order = []
        self._load()

    def _load(self):
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError, json.JSONDecodeError):
            return
        value = data.get("refresh_seconds")
        if isinstance(value, (int, float)) and value > 0:
            self.refresh_seconds = value
        order = data.get("device_order")
        if isinstance(order, list) and all(isinstance(n, str) for n in order):
            self.device_order = order

    def _save(self):
        try:
            self.path.write_text(json.dumps({
                "refresh_seconds": self.refresh_seconds,
                "device_order": self.device_order,
            }))
        except OSError:
            pass

    def set_refresh_seconds(self, value):
        self.refresh_seconds = value
        self._save()

    def set_device_order(self, order):
        self.device_order = list(order)
        self._save()


def order_devices(devices, order):
    """Sorts devices by the user's saved order; devices not yet in it (new
    arrivals) are appended at the end, worst-battery-first, so they're still
    visible and don't silently displace the user's chosen ordering."""
    position = {name: i for i, name in enumerate(order)}
    known = sorted((d for d in devices if d["name"] in position), key=lambda d: position[d["name"]])
    unknown = sorted((d for d in devices if d["name"] not in position), key=lambda d: d["battery"])
    return known + unknown


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
ROW_TOTAL_HEIGHT = ROW_HEIGHT + 6  # + pady (3 top + 3 bottom) from render()'s row.pack
MAX_VISIBLE_ROWS = 8


class BatteryWindow:
    """Borderless flyout popup - the device battery list, plus small ▲▼
    controls per row so the user can drag their preferred devices to the
    top; that order then also drives which devices the tray tooltip shows."""

    def __init__(self, root, settings):
        self.root = root
        self.settings = settings
        self.rendered_names = []
        self._last_hide_time = 0.0
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.resizable(False, False)
        self.root.configure(bg="#1e1e1e", highlightthickness=1, highlightbackground="#555555")

        self.frame = tk.Frame(root, bg="#1e1e1e", padx=14, pady=10)
        self.frame.pack(fill="both", expand=True)

        # Canvas + inner frame instead of packing rows straight into self.frame:
        # a plain Frame has no way to cap its own height and scroll the
        # overflow, so once the device list got past ~5 rows the popup either
        # ran off the bottom of the screen or got silently clipped by the
        # window manager. The canvas's explicit height caps it at
        # MAX_VISIBLE_ROWS and scrolls the rest.
        self.canvas = tk.Canvas(
            self.frame, bg="#1e1e1e", highlightthickness=0, width=WINDOW_WIDTH - 28,
        )
        self.scrollbar = tk.Scrollbar(
            self.frame, orient="vertical", command=self.canvas.yview,
            bg="#1e1e1e", troughcolor="#1e1e1e", activebackground="#555555",
            highlightthickness=0, bd=0, width=8,
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)

        self.rows_frame = tk.Frame(self.canvas, bg="#1e1e1e")
        self._rows_window = self.canvas.create_window((0, 0), window=self.rows_frame, anchor="nw")
        self.rows_frame.bind(
            "<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas.bind(
            "<Configure>", lambda e: self.canvas.itemconfigure(self._rows_window, width=e.width)
        )

        self.root.bind("<Escape>", lambda e: self.hide())
        # Dismiss on click-away rather than click-inside: overrideredirect
        # windows get no FocusOut just from moving the mouse, only from the
        # user actually clicking another window/the desktop, so this is a
        # reliable "clicked outside" signal without it firing on every
        # in-window interaction (e.g. the reorder arrows or scrolling).
        self.root.bind("<FocusOut>", lambda e: self.hide())

    def _placeholder(self, text):
        for child in self.rows_frame.winfo_children():
            child.destroy()
        tk.Label(
            self.rows_frame, text=text, fg="#aaaaaa", bg="#1e1e1e", anchor="w",
        ).pack(fill="x", pady=6)
        self._resize_to_content()

    def _resize_to_content(self):
        self.root.update_idletasks()
        content_height = self.rows_frame.winfo_reqheight()
        max_height = MAX_VISIBLE_ROWS * ROW_TOTAL_HEIGHT
        overflowing = content_height > max_height
        self.canvas.configure(height=min(content_height, max_height))
        if overflowing:
            self.scrollbar.pack(side="right", fill="y")
        else:
            self.scrollbar.pack_forget()
        self.root.update_idletasks()
        self._reposition()

    def render(self, devices):
        for child in self.rows_frame.winfo_children():
            child.destroy()

        if not devices:
            self._placeholder("No trackable devices found.")
            return

        ordered = order_devices(devices, self.settings.device_order)
        self.rendered_names = [d["name"] for d in ordered]

        for i, d in enumerate(ordered):
            row = tk.Frame(self.rows_frame, bg="#1e1e1e", height=ROW_HEIGHT)
            row.pack(fill="x", pady=3)
            row.pack_propagate(False)

            arrows = tk.Frame(row, bg="#1e1e1e", width=14)
            arrows.pack(side="left", fill="y")
            arrows.pack_propagate(False)
            self._make_arrow(arrows, "▲", i, -1, enabled=i > 0)
            self._make_arrow(arrows, "▼", i, 1, enabled=i < len(ordered) - 1)

            tk.Label(
                row, text=d["name"], anchor="w", fg="#eeeeee", bg="#1e1e1e",
            ).pack(side="left", fill="x", expand=True)
            pct = d["battery"]
            suffix = " ⚡" if d.get("charging") else ""
            color = "#{:02x}{:02x}{:02x}".format(*battery_color(pct))
            tk.Label(
                row, text=f"{pct}%{suffix}", fg=color, bg="#1e1e1e", anchor="e",
            ).pack(side="right")

        self._resize_to_content()

    def _make_arrow(self, parent, symbol, index, direction, enabled):
        label = tk.Label(
            parent, text=symbol, font=("Segoe UI", 6),
            fg="#aaaaaa" if enabled else "#3a3a3a", bg="#1e1e1e",
            cursor="hand2" if enabled else "arrow",
        )
        label.pack(side="top")
        if enabled:
            label.bind("<Button-1>", lambda e: self._move(index, direction))

    def _move(self, index, direction):
        order = list(self.rendered_names)
        target = index + direction
        order[index], order[target] = order[target], order[index]
        self.settings.set_device_order(order)
        self.render(get_cached_batteries())
        return "break"

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

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def show(self):
        # Map the window before measuring/rendering into it: winfo_reqheight()
        # and winfo_width()/height() on a still-withdrawn toplevel can return
        # stale values from whenever it last had a real geometry pass, so
        # sizing the popup while hidden could leave it stuck at an old size
        # (this was the actual cause of the popup appearing capped at ~5
        # devices regardless of how many were actually connected).
        self.root.deiconify()
        cached = get_cached_batteries()
        if cached:
            self.render(cached)
        else:
            self._placeholder("Loading...")
        self.canvas.yview_moveto(0)
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.focus_force()
        # bind_all rather than binding the canvas directly, so the wheel
        # scrolls the list even while the cursor is over a row label/arrow
        # rather than only over canvas whitespace; scoped to while the popup
        # is open so it doesn't steal wheel events from other apps.
        self.root.bind_all("<MouseWheel>", self._on_mousewheel)
        self.refresh()

    def hide(self):
        self.root.unbind_all("<MouseWheel>")
        self.root.withdraw()
        self._last_hide_time = time.monotonic()

    def toggle(self):
        if self.root.state() == "withdrawn":
            # Clicking the tray icon to close the popup makes it lose focus
            # first, which triggers the FocusOut auto-hide above; the click
            # itself then reaches this handler a beat later (via the Tk
            # event queue) and would otherwise immediately reopen what the
            # user just closed. Treat a withdraw that happened moments ago
            # as "still the same click" rather than as "already closed".
            if time.monotonic() - self._last_hide_time < 0.3:
                return
            self.show()
        else:
            self.hide()


def build_tooltip(devices, order):
    if not devices:
        return "Device Batteries: no devices found"
    shown = order_devices(devices, order)[:TOOLTIP_MAX_DEVICES]
    return "\n".join(
        f"{d['name']}: {d['battery']}%" + (" (charging)" if d.get("charging") else "")
        for d in shown
    )


def main():
    airpods_ble.start()

    settings = Settings(SETTINGS_PATH)
    root = tk.Tk()
    window = BatteryWindow(root, settings)

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
        icon.title = build_tooltip(devices, settings.device_order)

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
        "battery-tray-monitor", make_icon(initial_devices),
        build_tooltip(initial_devices, settings.device_order), menu,
    )

    threading.Thread(target=icon.run, daemon=True).start()
    threading.Thread(target=icon_refresh_loop, args=(icon,), daemon=True).start()

    root.after(150, poll_queue)
    root.mainloop()


if __name__ == "__main__":
    main()
