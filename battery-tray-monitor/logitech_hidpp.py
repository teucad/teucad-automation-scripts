"""Battery queries for Logitech wireless devices (Lightspeed/Bolt/Unifying
receivers, and direct-USB HID++ mice) via the HID++ 2.0 protocol.

Windows has no PnP/WMI property for these - Logitech reports battery over
vendor-defined HID feature reports, so we talk to the receiver directly.
Protocol reverse-engineered and cross-referenced against the open-source
Solaar project; verified live against a real LIGHTSPEED receiver + G Pro X2
Superstrike during development.
"""

import threading
import time

import hid

LOGITECH_VID = 0x046D
HIDPP_LONG_USAGE_PAGE = 0xFF00
HIDPP_LONG_USAGE = 0x0002
SWID = 0x0A

# The tray's periodic refresh and the popup's on-demand refresh can both call
# get_batteries() from different threads. Two open handles talking to the
# same physical receiver at once corrupts responses (crossed request/reply
# matching), so all HID++ traffic is serialized through this lock.
_hidpp_lock = threading.Lock()

FEATURE_ROOT = 0x0000
FEATURE_DEVICE_NAME = 0x0005
FEATURE_BATTERY_UNIFIED = 0x1004
FEATURE_BATTERY_LEGACY = 0x1000

DEVICE_INDICES = list(range(1, 7)) + [0xFF]


def _send(dev, device_index, feature_index, function_id, params=b""):
    msg = bytearray(20)
    msg[0] = 0x11
    msg[1] = device_index
    msg[2] = feature_index
    msg[3] = (function_id << 4) | SWID
    for i, b in enumerate(params[:16]):
        msg[4 + i] = b
    dev.write(bytes(msg))


def _read_matching(dev, device_index, feature_index, function_id, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = dev.read(20, timeout_ms=max(1, int((deadline - time.time()) * 1000)))
        if not data:
            continue
        if (
            len(data) >= 4
            and data[1] == device_index
            and data[2] == feature_index
            and (data[3] >> 4) == function_id
            and (data[3] & 0x0F) == SWID
        ):
            return data
        if len(data) >= 4 and data[1] == device_index and data[2] == 0x8F:
            return None  # HID++ error reply
    return None


def _get_feature_index(dev, device_index, feature_id, timeout=0.3):
    _send(dev, device_index, FEATURE_ROOT, 0x00, bytes([(feature_id >> 8) & 0xFF, feature_id & 0xFF, 0x00]))
    resp = _read_matching(dev, device_index, FEATURE_ROOT, 0x00, timeout)
    if resp and resp[4] != 0:
        return resp[4]
    return None


def _get_device_name(dev, device_index, name_feature_index):
    _send(dev, device_index, name_feature_index, 0x00)
    resp = _read_matching(dev, device_index, name_feature_index, 0x00, timeout=0.3)
    if not resp:
        return None
    length = resp[4]
    if not length:
        return None

    chars = bytearray()
    offset = 0
    while offset < length:
        _send(dev, device_index, name_feature_index, 0x01, bytes([offset]))
        chunk = _read_matching(dev, device_index, name_feature_index, 0x01, timeout=0.3)
        if not chunk:
            break
        take = min(16, length - offset)
        chars.extend(chunk[4:4 + take])
        offset += take
    return chars.decode("ascii", errors="ignore").strip() or None


def _get_battery(dev, device_index):
    # Unified Battery (0x1004): function 0 is GetCapabilities, function 1 is
    # GetStatus (SoC%, next reported level, charging status). Legacy Battery
    # Status (0x1000) uses function 0 for its single GetBatteryStatus call.
    for feature_id, function_id in ((FEATURE_BATTERY_UNIFIED, 0x01), (FEATURE_BATTERY_LEGACY, 0x00)):
        feat_idx = _get_feature_index(dev, device_index, feature_id)
        if feat_idx is None:
            continue
        _send(dev, device_index, feat_idx, function_id)
        resp = _read_matching(dev, device_index, feat_idx, function_id, timeout=0.3)
        if not resp:
            continue
        pct = resp[4]
        status = resp[6]
        if 0 <= pct <= 100:
            return pct, status in (1, 2)
    return None


def _probe_index(dev, device_index):
    battery = _get_battery(dev, device_index)
    if battery is None:
        return None
    pct, charging = battery
    name_feat = _get_feature_index(dev, device_index, FEATURE_DEVICE_NAME)
    name = _get_device_name(dev, device_index, name_feat) if name_feat else None
    return {"name": name or f"Logitech device ({device_index})", "battery": pct, "charging": charging}


def _probe_path_index(path, device_index):
    try:
        dev = hid.device()
        dev.open_path(path)
        dev.set_nonblocking(0)
    except OSError:
        return None
    try:
        return _probe_index(dev, device_index)
    finally:
        dev.close()


def _hidpp_paths():
    try:
        interfaces = hid.enumerate(LOGITECH_VID, 0)
    except Exception:
        return []
    seen, paths = set(), []
    for info in interfaces:
        if info.get("usage_page") != HIDPP_LONG_USAGE_PAGE or info.get("usage") != HIDPP_LONG_USAGE:
            continue
        path = info["path"]
        if path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def get_batteries():
    """Enumerate all Logitech HID++ receivers/devices and read their battery.

    A single mouse can expose more than one HID++ interface at once (e.g. its
    wireless receiver dongle *and* a direct USB-C cable for charging), and
    each interface uses a different device index depending on how it's wired
    up. Checking index 1 (the common case for both dedicated receivers and
    direct-USB connections) across every interface first keeps the normal
    case fast; the slow exhaustive scan across the rest of the index range
    only runs as a fallback if that finds nothing at all, since timing out on
    an absent index is expensive (~0.3-0.6s each).
    """
    with _hidpp_lock:
        paths = _hidpp_paths()
        results = []
        found_names = set()

        for path in paths:
            found = _probe_path_index(path, 1)
            if found and found["name"] not in found_names:
                results.append(found)
                found_names.add(found["name"])

        if results:
            return results

        for path in paths:
            for device_index in DEVICE_INDICES[1:]:
                found = _probe_path_index(path, device_index)
                if found and found["name"] not in found_names:
                    results.append(found)
                    found_names.add(found["name"])

        return results
