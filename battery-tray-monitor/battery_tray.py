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
import tkinter.font as tkfont
from pathlib import Path

import pystray
from PIL import Image, ImageDraw, ImageTk

import airpods_ble
import logitech_hidpp

SCRIPT_DIR = Path(__file__).resolve().parent
QUERY_SCRIPT = SCRIPT_DIR / "battery_query.ps1"
SETTINGS_PATH = SCRIPT_DIR / "settings.json"
DEFAULT_REFRESH_SECONDS = 20
INTERVAL_OPTIONS_SECONDS = [5, 10, 20, 30, 60, 300]
TOOLTIP_MAX_DEVICES = 3


class Settings:
    """Persists user-adjustable options: refresh interval, device display
    order, and per-device category overrides."""

    def __init__(self, path):
        self.path = path
        self.refresh_seconds = DEFAULT_REFRESH_SECONDS
        self.device_order = []
        self.category_overrides = {}
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
        overrides = data.get("category_overrides")
        if isinstance(overrides, dict) and all(
            isinstance(k, str) and isinstance(v, str) for k, v in overrides.items()
        ):
            self.category_overrides = {k.lower(): v for k, v in overrides.items()}

    def _save(self):
        try:
            self.path.write_text(json.dumps({
                "refresh_seconds": self.refresh_seconds,
                "device_order": self.device_order,
                "category_overrides": self.category_overrides,
            }))
        except OSError:
            pass

    def set_refresh_seconds(self, value):
        self.refresh_seconds = value
        self._save()

    def set_device_order(self, order):
        self.device_order = list(order)
        self._save()

    def set_category_override(self, name, category):
        self.category_overrides[name.lower().strip()] = category
        self._save()

    def clear_category_override(self, name):
        self.category_overrides.pop(name.lower().strip(), None)
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


def format_battery_text(d):
    """Renders a device's battery column. AirPods-style devices with more
    than one pod currently out of the case (see airpods_ble.py's "buds")
    show each pod's reading on the same line rather than as separate rows;
    a device with only one pod present (or any other device) falls back to
    the plain single percentage."""
    buds = d.get("buds")
    if buds and len(buds) > 1:
        return " / ".join(
            f"{b['battery']}%{b['label']}" + (" ⚡" if b.get("charging") else "")
            for b in buds
        )
    suffix = " ⚡" if d.get("charging") else ""
    return f"{d['battery']}%{suffix}"


def battery_color(pct):
    if pct <= 20:
        return (220, 53, 69)
    if pct <= 50:
        return (255, 193, 7)
    return (40, 167, 69)


# Windows exposes no device-class property for any of our battery sources
# (BLE battery service, HID Battery Strength, HID++, or AirPods BLE
# advertisements all report only a name), so category is inferred from the
# device name - generic keywords plus common Logitech model prefixes whose
# names don't otherwise contain "mouse"/"keyboard" (e.g. "MX Master").
CATEGORY_KEYWORDS = [
    ("headphones", ("airpods", "headphone", "headset", "earbud", "earphone", "buds")),
    ("mouse", (
        "mouse", "trackball", "mx master", "mx anywhere", "mx vertical", "superstrike",
        "g pro x superlight", "g303", "g403", "g502", "g602", "g604", "g703", "g903",
    )),
    ("keyboard", (
        "keyboard", "mx keys", "pop keys", "k380", "k400", "k480", "k580", "k780",
        "k835", "k845", "craft", "g913", "g915",
    )),
    ("controller", ("controller", "gamepad", "xbox", "dualsense", "dualshock", "joy-con", "joycon")),
    ("speaker", ("speaker", "soundbar")),
    ("trackpad", ("trackpad", "touchpad")),
    ("phone", ("iphone", "smartphone", "galaxy s", "galaxy z", "galaxy note", "pixel ", "oneplus", "phone")),
]

# Icon color per category, shown to the left of the device name in the
# popup window - not on the tray icon. The AirPods-style earbud
# sub-categories share the headphones color since they're the same family,
# just distinguished by icon shape (paired, left/right tilt, and the case).
CATEGORY_COLORS = {
    "headphones": (217, 83, 79),
    "earbud_pair": (217, 83, 79),
    "earbud_left": (217, 83, 79),
    "earbud_right": (217, 83, 79),
    "earbud_case": (217, 83, 79),
    "mouse": (74, 144, 217),
    "keyboard": (124, 92, 191),
    "controller": (92, 184, 92),
    "speaker": (224, 160, 48),
    "trackpad": (32, 178, 170),
    "phone": (232, 98, 168),
    "other": (136, 136, 136),
}

# Display order and labels for the right-click "set category" menu.
CATEGORY_ORDER = [
    "mouse", "keyboard", "headphones", "earbud_pair", "earbud_left",
    "earbud_right", "earbud_case", "controller", "speaker", "trackpad",
    "phone", "other",
]
CATEGORY_LABELS = {
    "mouse": "Mouse",
    "keyboard": "Keyboard",
    "headphones": "Headphones",
    "earbud_pair": "Earbuds (Pair)",
    "earbud_left": "Earbud (Left)",
    "earbud_right": "Earbud (Right)",
    "earbud_case": "Earbud (Case)",
    "controller": "Controller",
    "speaker": "Speaker",
    "trackpad": "Trackpad",
    "phone": "Phone",
    "other": "Other",
}


def categorize_device(name, overrides=None):
    lowered = name.lower()
    override = (overrides or {}).get(lowered.strip())
    if override:
        return override
    for category, keywords in CATEGORY_KEYWORDS:
        if any(k in lowered for k in keywords):
            if category == "headphones":
                if lowered.endswith("(left)"):
                    return "earbud_left"
                if lowered.endswith("(right)"):
                    return "earbud_right"
                if lowered.endswith("(case)"):
                    return "earbud_case"
                # AirPods Max is a single over-ear unit, not a pod pair, so
                # it keeps the generic headphones icon; "airpods"/"AirPods
                # Pro"/etc without a (Left)/(Right)/(Case) suffix is the
                # merged two-pod device (see airpods_ble.py's "buds" list)
                # and gets the side-by-side earbuds icon instead.
                if "airpods" in lowered and "max" not in lowered:
                    return "earbud_pair"
            return category
    return "other"


def _icon_mouse(d, s, color):
    lw = max(2, int(s * 0.05))
    d.rounded_rectangle([s*0.26, s*0.06, s*0.74, s*0.94], radius=s*0.24, outline=color, width=lw)
    d.line([s*0.5, s*0.08, s*0.5, s*0.42], fill=color, width=lw)


def _icon_keyboard(d, s, color):
    lw = max(2, int(s * 0.045))
    d.rounded_rectangle([s*0.04, s*0.26, s*0.96, s*0.74], radius=s*0.08, outline=color, width=lw)
    for y in (s*0.37, s*0.5, s*0.63):
        for x in (s*0.16, s*0.315, s*0.5, s*0.685, s*0.84):
            r = s*0.035
            d.rectangle([x - r, y - r, x + r, y + r], fill=color)


def _icon_headphones(d, s, color):
    lw = max(2, int(s * 0.06))
    d.arc([s*0.14, s*0.06, s*0.86, s*0.86], start=180, end=360, fill=color, width=lw)
    d.rounded_rectangle([s*0.08, s*0.5, s*0.28, s*0.86], radius=s*0.06, outline=color, width=lw)
    d.rounded_rectangle([s*0.72, s*0.5, s*0.92, s*0.86], radius=s*0.06, outline=color, width=lw)


def _icon_controller(d, s, color):
    lw = max(2, int(s * 0.05))
    d.rounded_rectangle([s*0.06, s*0.32, s*0.94, s*0.72], radius=s*0.2, outline=color, width=lw)
    r = s*0.06
    cx, cy = s*0.3, s*0.52
    d.line([cx - r, cy, cx + r, cy], fill=color, width=lw)
    d.line([cx, cy - r, cx, cy + r], fill=color, width=lw)
    d.ellipse([s*0.62, s*0.44, s*0.72, s*0.54], outline=color, width=max(1, int(lw*0.7)))
    d.ellipse([s*0.76, s*0.36, s*0.86, s*0.46], outline=color, width=max(1, int(lw*0.7)))


def _icon_speaker(d, s, color):
    lw = max(2, int(s * 0.05))
    d.rectangle([s*0.1, s*0.38, s*0.34, s*0.62], outline=color, width=lw)
    d.polygon([(s*0.34, s*0.38), (s*0.62, s*0.16), (s*0.62, s*0.84), (s*0.34, s*0.62)], outline=color, width=lw)
    d.arc([s*0.68, s*0.28, s*0.86, s*0.72], start=300, end=60, fill=color, width=lw)
    d.arc([s*0.74, s*0.14, s*0.98, s*0.86], start=300, end=60, fill=color, width=lw)


def _icon_trackpad(d, s, color):
    lw = max(2, int(s * 0.05))
    d.rounded_rectangle([s*0.08, s*0.14, s*0.92, s*0.86], radius=s*0.1, outline=color, width=lw)
    d.line([s*0.08, s*0.68, s*0.92, s*0.68], fill=color, width=lw)


def _icon_other(d, s, color):
    lw = max(2, int(s * 0.06))
    d.ellipse([s*0.2, s*0.2, s*0.8, s*0.8], outline=color, width=lw)
    r = s*0.08
    d.ellipse([s*0.5 - r, s*0.5 - r, s*0.5 + r, s*0.5 + r], fill=color)


def _draw_earbud(d, s, color, mirror):
    """A single AirPods-style earbud: a rounded in-ear bud with a stem
    hanging down and tilted outward - mirrored per side so left/right are
    visually distinct at a glance."""
    lw = max(2, int(s * 0.055))
    sign = -1 if mirror else 1
    bud_cx = s * 0.5
    bud_w, bud_h = s * 0.32, s * 0.34
    bud_box = [bud_cx - bud_w / 2, s * 0.08, bud_cx + bud_w / 2, s * 0.08 + bud_h]
    d.rounded_rectangle(bud_box, radius=bud_w / 2, outline=color, width=lw)
    stem_top = (bud_cx, s * 0.08 + bud_h - s * 0.04)
    stem_bottom = (bud_cx + sign * s * 0.22, s * 0.92)
    d.line([stem_top, stem_bottom], fill=color, width=lw)
    r = lw * 0.6
    d.ellipse([stem_bottom[0] - r, stem_bottom[1] - r, stem_bottom[0] + r, stem_bottom[1] + r], fill=color)


def _icon_earbud_left(d, s, color):
    _draw_earbud(d, s, color, mirror=True)


def _icon_earbud_right(d, s, color):
    _draw_earbud(d, s, color, mirror=False)


def _icon_earbud_pair(d, s, color):
    """Both AirPods-style earbuds side by side, tilted away from each
    other - the icon for a merged two-pod device (see categorize_device's
    "airpods, not max" case), distinct from the generic over-ear
    _icon_headphones so a pair reads at a glance as earbuds, not a headset."""
    lw = max(2, int(s * 0.05))
    bud_w, bud_h = s * 0.26, s * 0.3
    for bud_cx, sign in ((s * 0.28, -1), (s * 0.72, 1)):
        bud_box = [bud_cx - bud_w / 2, s * 0.1, bud_cx + bud_w / 2, s * 0.1 + bud_h]
        d.rounded_rectangle(bud_box, radius=bud_w / 2, outline=color, width=lw)
        stem_top = (bud_cx, s * 0.1 + bud_h - s * 0.035)
        stem_bottom = (bud_cx + sign * s * 0.16, s * 0.9)
        d.line([stem_top, stem_bottom], fill=color, width=lw)
        r = lw * 0.55
        d.ellipse([stem_bottom[0] - r, stem_bottom[1] - r, stem_bottom[0] + r, stem_bottom[1] + r], fill=color)


def _icon_earbud_case(d, s, color):
    lw = max(2, int(s * 0.055))
    d.rounded_rectangle([s*0.22, s*0.12, s*0.78, s*0.88], radius=s*0.16, outline=color, width=lw)
    d.line([s*0.22, s*0.42, s*0.78, s*0.42], fill=color, width=max(2, int(lw * 0.8)))
    r = s * 0.035
    d.ellipse([s*0.5 - r, s*0.26 - r, s*0.5 + r, s*0.26 + r], fill=color)


def _icon_phone(d, s, color):
    lw = max(2, int(s * 0.05))
    d.rounded_rectangle([s*0.32, s*0.06, s*0.68, s*0.94], radius=s*0.08, outline=color, width=lw)
    d.line([s*0.44, s*0.14, s*0.56, s*0.14], fill=color, width=max(2, int(lw * 0.8)))
    d.line([s*0.42, s*0.88, s*0.58, s*0.88], fill=color, width=max(2, int(lw * 0.8)))


CATEGORY_ICON_DRAW = {
    "mouse": _icon_mouse,
    "keyboard": _icon_keyboard,
    "headphones": _icon_headphones,
    "earbud_pair": _icon_earbud_pair,
    "earbud_left": _icon_earbud_left,
    "earbud_right": _icon_earbud_right,
    "earbud_case": _icon_earbud_case,
    "controller": _icon_controller,
    "speaker": _icon_speaker,
    "trackpad": _icon_trackpad,
    "phone": _icon_phone,
    "other": _icon_other,
}

ICON_DISPLAY_SIZE = 18
# Drawn at a higher resolution and downsampled with LANCZOS so curves/arcs
# don't look jagged at the tiny final display size.
ICON_SUPERSAMPLE = 128


def build_category_icon(category):
    img = Image.new("RGBA", (ICON_SUPERSAMPLE, ICON_SUPERSAMPLE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    CATEGORY_ICON_DRAW[category](draw, ICON_SUPERSAMPLE, CATEGORY_COLORS[category])
    return img.resize((ICON_DISPLAY_SIZE, ICON_DISPLAY_SIZE), Image.LANCZOS)


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


WINDOW_WIDTH = 300      # default/minimum popup width
WINDOW_MAX_WIDTH = 560  # cap so one very long device name can't take over the screen
FRAME_PADDING = 14      # matches BatteryWindow.frame's padx
ARROWS_WIDTH = 14
ICON_BLOCK_WIDTH = ICON_DISPLAY_SIZE + 2 + 6  # icon width + its packed padx=(2, 6)
NAME_PCT_GAP = 16       # minimum breathing room between the name and % text
CANVAS_MIN_WIDTH = WINDOW_WIDTH - FRAME_PADDING * 2
CANVAS_MAX_WIDTH = WINDOW_MAX_WIDTH - FRAME_PADDING * 2
ROW_HEIGHT = 30
ROW_TOTAL_HEIGHT = ROW_HEIGHT + 6  # + pady (3 top + 3 bottom) from render()'s row.pack
MAX_VISIBLE_ROWS = 8


class BatteryWindow:
    """Borderless flyout popup - the device battery list, plus small ▲▼
    controls per row so the user can drag their preferred devices to the
    top; that order then also drives which devices the tray tooltip shows.
    Right-clicking a row opens a menu to override its category icon."""

    def __init__(self, root, settings):
        self.root = root
        self.settings = settings
        self.rendered_names = []
        self._last_hide_time = 0.0
        # Built once and kept as an instance attribute - Tkinter drops a
        # PhotoImage as soon as nothing external still references it, even
        # while a Label is actively displaying it.
        self._category_icons = {
            category: ImageTk.PhotoImage(build_category_icon(category), master=root)
            for category in CATEGORY_COLORS
        }
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.resizable(False, False)
        self.root.configure(bg="#1e1e1e", highlightthickness=1, highlightbackground="#555555")

        self.frame = tk.Frame(root, bg="#1e1e1e", padx=FRAME_PADDING, pady=10)
        self.frame.pack(fill="both", expand=True)

        # Canvas + inner frame instead of packing rows straight into self.frame:
        # a plain Frame has no way to cap its own height and scroll the
        # overflow, so once the device list got past ~5 rows the popup either
        # ran off the bottom of the screen or got silently clipped by the
        # window manager. The canvas's explicit height caps it at
        # MAX_VISIBLE_ROWS and scrolls the rest.
        self.canvas = tk.Canvas(
            self.frame, bg="#1e1e1e", highlightthickness=0, width=CANVAS_MIN_WIDTH,
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
        self.canvas.configure(width=CANVAS_MIN_WIDTH)
        tk.Label(
            self.rows_frame, text=text, fg="#aaaaaa", bg="#1e1e1e", anchor="w",
        ).pack(fill="x", pady=6)
        self._resize_to_content()

    def _content_width(self, devices):
        """Widest row's natural content (name + gap + battery text), so the
        window grows to fit instead of the name label and the battery
        percentage overlapping - clamped to CANVAS_MAX_WIDTH so one
        excessively long device name can't blow the popup up to fill the
        screen."""
        font = tkfont.nametofont("TkDefaultFont")
        widest_row = 0
        for d in devices:
            pct_text = format_battery_text(d)
            row_content = font.measure(d["name"]) + NAME_PCT_GAP + font.measure(pct_text)
            widest_row = max(widest_row, row_content)
        needed = ARROWS_WIDTH + ICON_BLOCK_WIDTH + widest_row
        max_width = min(CANVAS_MAX_WIDTH, self.root.winfo_screenwidth() - 80 - FRAME_PADDING * 2)
        return max(CANVAS_MIN_WIDTH, min(max_width, needed))

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
        self.canvas.configure(width=self._content_width(ordered))

        for i, d in enumerate(ordered):
            row = tk.Frame(self.rows_frame, bg="#1e1e1e", height=ROW_HEIGHT)
            row.pack(fill="x", pady=3)
            row.pack_propagate(False)

            arrows = tk.Frame(row, bg="#1e1e1e", width=ARROWS_WIDTH)
            arrows.pack(side="left", fill="y")
            arrows.pack_propagate(False)
            self._make_arrow(arrows, "▲", i, -1, enabled=i > 0)
            self._make_arrow(arrows, "▼", i, 1, enabled=i < len(ordered) - 1)

            icon = self._category_icons[categorize_device(d["name"], self.settings.category_overrides)]
            icon_label = tk.Label(row, image=icon, bg="#1e1e1e", cursor="hand2")
            icon_label.pack(side="left", padx=(2, 6))

            name_label = tk.Label(
                row, text=d["name"], anchor="w", fg="#eeeeee", bg="#1e1e1e", cursor="hand2",
            )
            name_label.pack(side="left", fill="x", expand=True)
            color = "#{:02x}{:02x}{:02x}".format(*battery_color(d["battery"]))
            pct_label = tk.Label(
                row, text=format_battery_text(d), fg=color, bg="#1e1e1e", anchor="e", cursor="hand2",
            )
            pct_label.pack(side="right")

            # Right-click anywhere on the row to override its detected
            # category - keyword/model-name matching can't identify a
            # device with a name like "eekumbokum", and editing
            # settings.json by hand for that is not something to expect
            # of the user.
            for widget in (row, icon_label, name_label, pct_label):
                widget.bind("<Button-3>", lambda e, name=d["name"]: self._show_category_menu(e, name))

        self._resize_to_content()

    def _show_category_menu(self, event, name):
        current_override = self.settings.category_overrides.get(name.lower().strip(), "")
        auto_category = categorize_device(name)

        menu = tk.Menu(
            self.root, tearoff=0, bg="#2a2a2a", fg="#eeeeee",
            activebackground="#3a3a3a", activeforeground="#ffffff",
        )
        selected = tk.StringVar(value=current_override)

        def choose(category):
            if category:
                self.settings.set_category_override(name, category)
            else:
                self.settings.clear_category_override(name)
            self.render(get_cached_batteries())

        menu.add_radiobutton(
            label=f"Auto-detect ({CATEGORY_LABELS[auto_category]})",
            variable=selected, value="", command=lambda: choose(None),
        )
        menu.add_separator()
        for category in CATEGORY_ORDER:
            menu.add_radiobutton(
                label=CATEGORY_LABELS[category], variable=selected, value=category,
                command=lambda c=category: choose(c),
            )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

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
    return "\n".join(f"{d['name']}: {format_battery_text(d)}" for d in shown)


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
