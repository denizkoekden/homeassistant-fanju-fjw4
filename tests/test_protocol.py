"""Tests for the FanJu FJW4 local UDP upload decoder.

The fixtures are real datagrams captured from a live station and cross-checked
against the vendor cloud. Runs without Home Assistant installed - the integration
package's __init__ (which imports homeassistant) is deliberately bypassed by
loading the leaf modules under a synthetic package.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

_BASE = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "fanju_fjw4"


def _load_protocol():
    pkg = types.ModuleType("_fjw4")
    pkg.__path__ = [str(_BASE)]
    sys.modules["_fjw4"] = pkg
    for name in ("const", "protocol"):
        spec = importlib.util.spec_from_file_location(f"_fjw4.{name}", _BASE / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"_fjw4.{name}"] = mod
        spec.loader.exec_module(mod)
    return sys.modules["_fjw4.protocol"]


protocol = _load_protocol()
parse_upload = protocol.parse_upload

# Real upload datagram captured 2026-06-22 17:04:39: device prefix + 53:30
# message + 50-byte body + trailer. Cloud at that moment reported indoor
# 82.4 degF / 66 %, outdoor 95.1 degF / 35 %.
_REAL_UPLOAD = bytes.fromhex(
    "aa3c570134eae78004ce"  # device/session prefix
    "533001003200"  # 53:30, flags 01:00, len 0x0032=50
    "010d1a061611042700"  # [2 ?][YY MM DD HH MM SS][lead=00]
    "bc0642be0644a7063e"  # indoor cur/high/low: (temp16_LE, hum8)
    "3b07233b0743720622"  # outdoor cur/high/low
    "ffffffffffffffffffffffffffffffffffff"  # absent channels
    "02fcffffff"  # pressure 0xFC02 (= 1020 hPa) + status
    "2f20cc3e"  # checksum + footer
)

# A second real upload captured later the same day, when the cloud reported
# 1022 hPa. Used together with _REAL_UPLOAD to pin the pressure encoding
# (0xFC02 -> 1020, 0xFC00 -> 1022; hPa = 0xFFFE - little-endian value).
_REAL_UPLOAD_1022 = bytes.fromhex(
    "aa3c570134eae78004ce"
    "533001003200"
    "010d1a061616392a00"  # ...22:57:42, lead 00
    "bf0648c90648a7063e"  # indoor cur/high/low
    "d8062f25072fd80624"  # outdoor cur/high/low
    "ffffffffffffffffffffffffffffffffffff"
    "00fcffffff"  # pressure 0xFC00 (= 1022 hPa)
    "6821cc3e"
)


def _by(data, sensor_type, channel):
    for s in data["sensorDatas"]:
        if s["type"] == sensor_type and s["channel"] == channel:
            return s["curVal"]
    return None


def test_parse_real_upload():
    out = parse_upload(_REAL_UPLOAD)
    assert out is not None
    assert out["timestamp"] == "2026-06-22 17:04:39"
    assert out["device"] == "aa3c570134eae78004ce"
    assert out["mac"] == "34EAE78004CE"  # matches cloud getBindedDevice
    # type 1 = temperature (degF), type 2 = humidity; channel 0/1 = indoor/outdoor
    assert _by(out, 1, 0) == 82.4
    assert _by(out, 2, 0) == 66
    assert _by(out, 1, 1) == 95.1
    assert _by(out, 2, 1) == 35
    assert out["atmos"] == 1020


def test_parse_pressure_second_reading():
    out = parse_upload(_REAL_UPLOAD_1022)
    assert out["timestamp"] == "2026-06-22 22:57:42"
    assert out["atmos"] == 1022  # 0xFFFE - 0xFC00
    assert _by(out, 1, 0) == 82.7  # indoor 0x06BF
    assert _by(out, 2, 0) == 72
    assert _by(out, 1, 1) == 85.2  # outdoor 0x06D8
    assert _by(out, 2, 1) == 47


def test_temp_formula():
    assert protocol._temp_f(1724) == 82.4
    assert protocol._temp_f(1851) == 95.1
    assert protocol._temp_f(900) == 0.0  # raw/10 - 90


def test_not_an_upload():
    assert parse_upload(b"\x00\x01\x02\x03nothing here") is None


def test_absent_channel_omitted():
    # Outdoor channel filled with sentinels -> only indoor sensors surface.
    payload = bytes.fromhex(
        "aa3c570134eae78004ce533001003200"
        "010d1a061611042700"
        "bc0642be0644a7063e"  # indoor present
        "ffffffffffffffffffffffffffffffffffffffffffffffffffff"  # everything else absent
    )
    out = parse_upload(payload)
    assert _by(out, 1, 0) == 82.4
    assert _by(out, 1, 1) is None  # outdoor absent
    assert _by(out, 2, 1) is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all tests passed")
