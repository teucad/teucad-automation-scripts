"""Apple AirPods battery via passive BLE advertisement scanning.

Windows has no PnP/WMI property for AirPods - Apple reports battery through
a proprietary, unencrypted prefix of the BLE "Proximity Pairing" advertisement
(manufacturer ID 0x004C, message type 0x07) rather than the standard BLE
Battery Service. This is the same mechanism iOS itself uses to show AirPods
battery without an active connection. Bytes 0-10 are plaintext, the rest is
an encrypted rotating identifier we don't need. Bytes 3-4 are the big-endian
model ID.

Two distinct layouts share this prefix, handled separately below:

- AirPods Max (single battery, no case): reverse-engineered live against a
  real unit, since public writeups of this protocol focus on two-earbud
  AirPods and don't agree on how a single-battery device fills these fields.
  Byte 6's low nibble is the battery level (0x0-0x9 = n*10%, 0xA-0xE = 100%,
  0xF = unavailable); byte 7 bit 0x10 is the charging flag, confirmed by
  diffing a broadcast captured while on the charger (0x90) against one
  captured right after unplugging (0x80). Byte 6's high nibble and the rest
  of byte 7 are unused on Max, unlike true earbud AirPods.
- AirPods / AirPods Pro (two pods + case): the well-established layout used
  by OpenPods/AirStatus and documented in the librepods project. Byte 5 bit
  0x02 says whether left or right is the "primary" (broadcasting) pod, which
  flips which nibble of byte 6 is which pod and which bit of byte 7's high
  nibble is which pod's charging flag. Byte 6's nibbles are the left/right
  battery, byte 7's low nibble is the case battery, byte 7's high nibble
  holds the three charging flags. Encoding is 0x0-0x9 = n*10+5%, 0xA = 100%,
  0xB-0xF = unavailable -- a different rounding convention than Max's, per
  that reverse-engineering. The two pods are reported as a single device (a
  "buds" list of per-pod readings, with the device's overall battery/charging
  taken as the worst-case/either-charging across whichever pods are actually
  out of the case) since they're one physical object to the user; the case
  stays a separate device.
"""

import asyncio
import threading
import time

from bleak import BleakScanner

APPLE_COMPANY_ID = 0x004C
PROXIMITY_PAIRING_TYPE = 0x07

MAX_MODEL_IDS = {0x0A20, 0x1F20}  # Lightning, USB-C

AIRPODS_MODEL_NAMES = {
    0x0220: "AirPods",
    0x0F20: "AirPods (2nd gen)",
    0x1320: "AirPods (3rd gen)",
    0x1920: "AirPods (4th gen)",
    0x1B20: "AirPods (4th gen, ANC)",
    0x0E20: "AirPods Pro",
    0x1420: "AirPods Pro (2nd gen)",
    0x2420: "AirPods Pro (2nd gen, USB-C)",
}

MODEL_NAMES = {
    0x0A20: "AirPods Max",
    0x1F20: "AirPods Max",
    **AIRPODS_MODEL_NAMES,
}

STALE_SECONDS = 45

_lock = threading.Lock()
_devices = {}
_started = False
_start_lock = threading.Lock()


def _max_nibble_to_pct(nibble):
    if nibble == 0x0F:
        return None
    if nibble >= 0x0A:
        return 100
    return nibble * 10


def _dualpod_nibble_to_pct(nibble):
    if nibble == 0x0A:
        return 100
    if nibble <= 0x09:
        return nibble * 10 + 5
    return None


def _parse(data):
    """Returns a list of 0-3 {"name", "battery", "charging"} dicts."""
    if len(data) < 8 or data[0] != PROXIMITY_PAIRING_TYPE:
        return []
    model_id = (data[3] << 8) | data[4]
    name = MODEL_NAMES.get(model_id)
    if name is None:
        return []

    if model_id in MAX_MODEL_IDS:
        battery = _max_nibble_to_pct(data[6] & 0x0F)
        if battery is None:
            return []
        # Confirmed live: byte 7 is 0x90 while on the charger, 0x80 right
        # after unplugging - bit 0x10 is the charging flag.
        charging = bool(data[7] & 0x10)
        return [{"name": name, "battery": battery, "charging": charging}]

    flip = (data[5] & 0x02) == 0
    left_nibble = (data[6] >> 4) if flip else (data[6] & 0x0F)
    right_nibble = (data[6] & 0x0F) if flip else (data[6] >> 4)
    case_nibble = data[7] & 0x0F
    charge_bits = (data[7] >> 4) & 0x0F
    charging_left = bool(charge_bits & (0x02 if flip else 0x01))
    charging_right = bool(charge_bits & (0x01 if flip else 0x02))
    charging_case = bool(charge_bits & 0x04)

    parts = []
    # Left and right report as one combined device - a "pair" of earbuds is
    # one physical object to the user, not two rows in the list. When only
    # one pod is out of the case (the other still charging inside, or left
    # behind), only that pod's reading is available and it becomes the
    # device's sole battery/charging value.
    buds = []
    left_pct = _dualpod_nibble_to_pct(left_nibble)
    if left_pct is not None:
        buds.append({"label": "L", "battery": left_pct, "charging": charging_left})
    right_pct = _dualpod_nibble_to_pct(right_nibble)
    if right_pct is not None:
        buds.append({"label": "R", "battery": right_pct, "charging": charging_right})
    if buds:
        parts.append({
            "name": name,
            "battery": min(b["battery"] for b in buds),
            "charging": any(b["charging"] for b in buds),
            "buds": buds,
        })

    case_pct = _dualpod_nibble_to_pct(case_nibble)
    if case_pct is not None:
        parts.append({"name": f"{name} (Case)", "battery": case_pct, "charging": charging_case})
    return parts


def _on_advertisement(device, advertisement_data):
    mfg = advertisement_data.manufacturer_data.get(APPLE_COMPANY_ID)
    if not mfg:
        return
    parts = _parse(mfg)
    if not parts:
        return
    with _lock:
        _devices[device.address] = {"parts": parts, "seen": time.monotonic()}


async def _run():
    scanner = BleakScanner(detection_callback=_on_advertisement)
    await scanner.start()
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await scanner.stop()


def _start_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    except Exception:
        pass


def start():
    """Starts the background BLE scan once. Safe to call repeatedly."""
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
        threading.Thread(target=_start_loop, daemon=True).start()


def get_batteries():
    now = time.monotonic()
    with _lock:
        result = []
        for d in _devices.values():
            if now - d["seen"] <= STALE_SECONDS:
                result.extend(d["parts"])
        return result
