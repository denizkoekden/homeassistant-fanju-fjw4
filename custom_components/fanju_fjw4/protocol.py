"""Decoder for the FanJu FJW4 local UDP upload protocol.

The station uploads its sensor readings every ~60 s as a binary UDP datagram
(src+dst port 10000) to the EMaxLife cloud. The format was worked out by
capturing real uploads and cross-checking every field against the vendor cloud.

UDP payload layout::

    [ ~10-byte device/session prefix ]
    53 30            message type ("upload")
    01 00            flags
    32 00            body length (little-endian, = 50)
    <body>           the 50-byte body below
    <csum16> cc 3e   trailer

Body::

    [2 bytes ?] [YY MM DD HH MM SS]      timestamp
    [lead byte = 00]
    3-byte triplets [temp16_LE, hum8] ... grouped 3-per-channel (cur, high, low),
    channel 0 = indoor, channel 1 = outdoor; absent channels are 0xFF-filled.

Encodings (confirmed): temperature degF = raw / 10 - 90; humidity = raw byte.

The station does NOT transmit barometric pressure over this UDP link - only
temperature and humidity. (The vendor cloud fills its own pressure field from a
weather service keyed on the station's GPS location, not from the sensor - so it
isn't recoverable locally.) The parsed result is shaped to match the cloud
``getRealtime`` payload (``sensorDatas``).
"""

from __future__ import annotations

from typing import Any

from .const import (
    CHANNEL_INDOOR,
    CHANNEL_OUTDOOR,
    SENSOR_TYPE_HUMIDITY,
    SENSOR_TYPE_TEMPERATURE,
)

# Marker that starts the "local weather upload" message inside the UDP payload.
UPLOAD_MARKER = b"\x53\x30"

# A missing reading is 0xFFFF (temperature) / 0xFF (humidity) - same sentinels
# the cloud uses, already filtered out by the sensor platform.
_INVALID_TEMP_RAW = 0xFFFF
_INVALID_HUM = 0xFF

# Channel index -> cloud channel number, in the order triplets appear in the body.
_CHANNEL_ORDER = (CHANNEL_INDOOR, CHANNEL_OUTDOOR)


def _temp_f(raw: int) -> float:
    """Convert a raw 16-bit temperature to degrees Fahrenheit."""
    return round(raw / 10 - 90, 1)


def parse_upload(payload: bytes) -> dict[str, Any] | None:
    """Parse a station UDP upload datagram into a cloud-shaped reading dict.

    Args:
        payload: The raw UDP payload (including the device prefix).

    Returns:
        A dict with ``sensorDatas`` mirroring the cloud ``getRealtime`` content,
        plus ``device``, ``mac`` and ``timestamp`` extras; or ``None`` if the
        payload is not a recognizable 53:30 upload.
    """
    marker = payload.find(UPLOAD_MARKER)
    if marker < 0:
        return None
    device_prefix = payload[:marker].hex()
    # The station's MAC is the 6 bytes immediately before the message marker
    # (e.g. prefix aa3c5701|34eae78004ce -> MAC 34:EA:E7:80:04:CE). Use it as a
    # cloud-free device identity.
    mac = payload[marker - 6 : marker].hex().upper() if marker >= 6 else None
    msg = payload[marker:]
    if len(msg) < 6:
        return None
    body_len = int.from_bytes(msg[4:6], "little")
    body = msg[6 : 6 + body_len]
    if len(body) < 9:
        return None

    ts = body[2:8]
    timestamp = (
        f"20{ts[0]:02d}-{ts[1]:02d}-{ts[2]:02d} {ts[3]:02d}:{ts[4]:02d}:{ts[5]:02d}"
    )

    # Sensor section: lead byte, then 3-byte triplets until the 0xFF fill.
    sens = body[8:]
    triplets: list[tuple[int, int]] = []
    j = 1
    while j + 3 <= len(sens):
        raw = int.from_bytes(sens[j : j + 2], "little")
        hum = sens[j + 2]
        if raw == _INVALID_TEMP_RAW and hum == _INVALID_HUM:
            break
        triplets.append((raw, hum))
        j += 3

    # Triplets come in groups of three (current, high, low) per channel; we only
    # surface the current reading, matching the cloud's ``curVal``.
    sensor_datas: list[dict[str, Any]] = []
    for idx, channel in enumerate(_CHANNEL_ORDER):
        cur = idx * 3
        if cur >= len(triplets):
            break
        raw, hum = triplets[cur]
        if raw != _INVALID_TEMP_RAW:
            sensor_datas.append(
                {
                    "type": SENSOR_TYPE_TEMPERATURE,
                    "channel": channel,
                    "curVal": _temp_f(raw),
                }
            )
        if hum != _INVALID_HUM:
            sensor_datas.append(
                {"type": SENSOR_TYPE_HUMIDITY, "channel": channel, "curVal": hum}
            )

    return {
        "device": device_prefix,
        "mac": mac,
        "timestamp": timestamp,
        "sensorDatas": sensor_datas,
    }
