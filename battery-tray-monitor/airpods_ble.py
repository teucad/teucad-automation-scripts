"""AirPods Max battery via passive BLE advertisement scanning.

Windows has no PnP/WMI property for AirPods - Apple reports battery through
a proprietary, unencrypted prefix of the BLE "Proximity Pairing" advertisement
(manufacturer ID 0x004C, message type 0x07) rather than the standard BLE
Battery Service. This is the same mechanism iOS itself uses to show AirPods
battery without an active connection.

The byte layout below (model ID, battery nibble, charging bit) was
reverse-engineered live against a real AirPods Max, since public writeups of
this protocol focus on two-earbud AirPods and don't agree on how a
single-battery device like Max fills these fields. Bytes 0-10 are plaintext,
the rest is an encrypted rotating identifier we don't need. Bytes 3-4 are
the big-endian model ID (0x0A20 = Lightning, 0x1F20 = USB-C). Byte 6's low
nibble is the battery level, encoded as 0x0-0x9 = n*10%, 0xA-0xE = 100%,
0xF = unavailable. Byte 7 bit 0x10 is the charging flag, confirmed by
diffing a broadcast captured while on the charger (0x90) against one
captured immediately after unplugging (0x80). Byte 6's high nibble and the
rest of byte 7 are unused on Max (it has one battery, not two pods + a
case), unlike true earbud AirPods, so this module doesn't interpret them.
"""

import asyncio
import threading
import time

from bleak import BleakScanner

APPLE_COMPANY_ID = 0x004C
PROXIMITY_PAIRING_TYPE = 0x07

MODEL_NAMES = {
    0x0A20: "AirPods Max",
    0x1F20: "AirPods Max",
}

STALE_SECONDS = 45

_lock = threading.Lock()
_devices = {}
_started = False
_start_lock = threading.Lock()


def _nibble_to_pct(nibble):
    if nibble == 0x0F:
        return None
    if nibble >= 0x0A:
        return 100
    return nibble * 10


def _parse(data):
    if len(data) < 8 or data[0] != PROXIMITY_PAIRING_TYPE:
        return None
    model_id = (data[3] << 8) | data[4]
    name = MODEL_NAMES.get(model_id)
    if name is None:
        return None

    battery = _nibble_to_pct(data[6] & 0x0F)
    if battery is None:
        return None

    # Confirmed live: byte 7 is 0x90 while on the charger, 0x80 right after
    # unplugging - bit 0x10 is the charging flag.
    charging = bool(data[7] & 0x10)
    return {"name": name, "battery": battery, "charging": charging}


def _on_advertisement(device, advertisement_data):
    mfg = advertisement_data.manufacturer_data.get(APPLE_COMPANY_ID)
    if not mfg:
        return
    parsed = _parse(mfg)
    if parsed is None:
        return
    with _lock:
        _devices[device.address] = {**parsed, "seen": time.monotonic()}


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
        return [
            {"name": d["name"], "battery": d["battery"], "charging": d["charging"]}
            for d in _devices.values()
            if now - d["seen"] <= STALE_SECONDS
        ]
