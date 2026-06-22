"""Tests for the Hi-Flying UDP discovery and AT response helpers."""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

_BASE = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "fanju_fjw4"


def _load_hiflying():
    pkg = types.ModuleType("_fjw4_hiflying")
    pkg.__path__ = [str(_BASE)]
    sys.modules["_fjw4_hiflying"] = pkg
    spec = importlib.util.spec_from_file_location(
        "_fjw4_hiflying.hiflying", _BASE / "hiflying.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_fjw4_hiflying.hiflying"] = mod
    spec.loader.exec_module(mod)
    return mod


hiflying = _load_hiflying()


def test_parse_discovery_response():
    station = hiflying.parse_discovery_response(
        b"192.168.178.20,34eae78004ce,HF-LPT230"
    )
    assert station.ip == "192.168.178.20"
    assert station.mac == "34EAE78004CE"
    assert station.model == "HF-LPT230"


def test_parse_invalid_discovery_response():
    assert hiflying.parse_discovery_response(b"not,a,station") is None
    assert hiflying.parse_discovery_response(b"\xff") is None


def test_parse_netp_response():
    netp = hiflying.parse_netp_response(
        b"+ok=UDP,Client,10000,app.emaxlife.net\r\n\r\n"
    )
    assert netp.protocol == "UDP"
    assert netp.mode == "Client"
    assert netp.port == 10000
    assert netp.host == "app.emaxlife.net"
    assert netp.command_value() == "UDP,Client,10000,app.emaxlife.net"


def test_parse_netp_response_rejects_unexpected_response():
    try:
        hiflying.parse_netp_response(b"+ERR=-1\r\n")
    except hiflying.HiflyingError:
        pass
    else:
        raise AssertionError("Expected HiflyingError")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all tests passed")
