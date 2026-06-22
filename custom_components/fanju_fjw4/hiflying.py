"""Hi-Flying HF-LPT230 UDP discovery and AT command helpers."""

from __future__ import annotations

from dataclasses import dataclass
import socket
import time
from typing import Final

DISCOVERY_PORT: Final = 48899
DISCOVERY_PAYLOAD: Final = b"HF-A11ASSISTHREAD"
AT_MODE_PAYLOAD: Final = b"+ok"

DEFAULT_TIMEOUT: Final = 2.0
COMMAND_QUIET_TIMEOUT: Final = 0.25


class HiflyingError(Exception):
    """Raised when a Hi-Flying module cannot be queried or configured."""


@dataclass(frozen=True)
class HiflyingStation:
    """A station found through the Hi-Flying UDP discovery handshake."""

    ip: str
    mac: str
    model: str


@dataclass(frozen=True)
class HiflyingNetp:
    """The module's primary network socket configuration."""

    protocol: str
    mode: str
    port: int
    host: str

    def command_value(self) -> str:
        """Return the value used by ``AT+NETP=...``."""
        return f"{self.protocol},{self.mode},{self.port},{self.host}"


@dataclass(frozen=True)
class HiflyingConfigureResult:
    """Result of ensuring the station upload target."""

    before: HiflyingNetp
    after: HiflyingNetp
    changed: bool


def parse_discovery_response(data: bytes) -> HiflyingStation | None:
    """Parse a ``HF-A11ASSISTHREAD`` discovery response."""
    try:
        text = data.decode("ascii").strip()
    except UnicodeDecodeError:
        return None

    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 3:
        return None

    ip, mac, model = parts
    if not ip or not mac or not model.startswith("HF-"):
        return None

    return HiflyingStation(ip=ip, mac=mac.upper(), model=model)


def parse_netp_response(data: bytes | str) -> HiflyingNetp:
    """Parse an ``AT+NETP`` response."""
    if isinstance(data, bytes):
        text = data.decode("ascii", "replace")
    else:
        text = data

    value = None
    for line in text.replace("\r", "\n").split("\n"):
        line = line.strip()
        if line.startswith("+ok="):
            value = line[4:]
            break

    if value is None:
        raise HiflyingError(f"AT+NETP did not return +ok: {text!r}")

    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4:
        raise HiflyingError(f"Unexpected AT+NETP response: {text!r}")

    protocol, mode, port, host = parts
    try:
        parsed_port = int(port)
    except ValueError as err:
        raise HiflyingError(f"Unexpected AT+NETP port: {text!r}") from err

    return HiflyingNetp(
        protocol=protocol,
        mode=mode,
        port=parsed_port,
        host=host,
    )


def discover_stations(timeout: float = DEFAULT_TIMEOUT) -> list[HiflyingStation]:
    """Discover Hi-Flying modules on the local network."""
    stations: dict[tuple[str, str], HiflyingStation] = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(timeout)
        sock.sendto(DISCOVERY_PAYLOAD, ("255.255.255.255", DISCOVERY_PORT))

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            sock.settimeout(max(0.05, deadline - time.monotonic()))
            try:
                data, addr = sock.recvfrom(1024)
            except TimeoutError:
                break
            except OSError:
                break

            station = parse_discovery_response(data)
            if station is None:
                continue
            stations[(station.mac, addr[0])] = station

    return list(stations.values())


def discover_station(host: str, timeout: float = DEFAULT_TIMEOUT) -> HiflyingStation | None:
    """Run the discovery handshake against a single host."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(DISCOVERY_PAYLOAD, (host, DISCOVERY_PORT))
        try:
            data, _addr = sock.recvfrom(1024)
        except TimeoutError:
            return None
        except OSError as err:
            raise HiflyingError(f"Discovery failed for {host}: {err}") from err
    return parse_discovery_response(data)


def local_source_ip_for(host: str, port: int = DISCOVERY_PORT) -> str:
    """Return the local IP address that would be used to reach ``host``."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((host, port))
        return sock.getsockname()[0]


def send_at_command(
    host: str,
    command: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> bytes:
    """Send a UDP AT command to a Hi-Flying module.

    The module only accepts AT commands after the discovery handshake and a dummy
    ``+ok`` packet. The dummy packet may return an error; that is expected and
    only used to switch the module into the UDP command parser.
    """
    payload = command.encode("ascii")
    if not payload.endswith(b"\r"):
        payload += b"\r"

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        addr = (host, DISCOVERY_PORT)

        sock.sendto(DISCOVERY_PAYLOAD, addr)
        _receive_until_quiet(sock, timeout=timeout, quiet_timeout=COMMAND_QUIET_TIMEOUT)

        sock.sendto(AT_MODE_PAYLOAD, addr)
        _receive_until_quiet(sock, timeout=COMMAND_QUIET_TIMEOUT, quiet_timeout=0.05)

        sock.sendto(payload, addr)
        responses = _receive_until_quiet(
            sock, timeout=timeout, quiet_timeout=COMMAND_QUIET_TIMEOUT
        )

    if not responses:
        raise HiflyingError(f"No response to {command!r} from {host}")
    return b"".join(responses)


def get_netp(host: str, timeout: float = DEFAULT_TIMEOUT) -> HiflyingNetp:
    """Return the module's current primary upload socket configuration."""
    return parse_netp_response(send_at_command(host, "AT+NETP", timeout=timeout))


def set_netp(
    host: str,
    netp: HiflyingNetp,
    timeout: float = DEFAULT_TIMEOUT,
) -> None:
    """Set the module's primary upload socket configuration."""
    response = send_at_command(host, f"AT+NETP={netp.command_value()}", timeout=timeout)
    if b"+ok" not in response:
        raise HiflyingError(f"AT+NETP set failed: {response!r}")


def ensure_upload_target(
    station_host: str,
    target_host: str,
    target_port: int,
    timeout: float = DEFAULT_TIMEOUT,
) -> HiflyingConfigureResult:
    """Ensure the station uploads via UDP client mode to ``target_host:port``."""
    desired = HiflyingNetp(
        protocol="UDP",
        mode="Client",
        port=target_port,
        host=target_host,
    )
    before = get_netp(station_host, timeout=timeout)
    if _same_netp(before, desired):
        return HiflyingConfigureResult(before=before, after=before, changed=False)

    set_netp(station_host, desired, timeout=timeout)
    after = get_netp(station_host, timeout=timeout)
    if not _same_netp(after, desired):
        raise HiflyingError(
            f"AT+NETP verification failed: expected {desired}, got {after}"
        )
    return HiflyingConfigureResult(before=before, after=after, changed=True)


def _receive_until_quiet(
    sock: socket.socket,
    *,
    timeout: float,
    quiet_timeout: float,
) -> list[bytes]:
    """Receive datagrams until the first timeout or a quiet period after data."""
    responses: list[bytes] = []
    deadline = time.monotonic() + timeout

    while True:
        now = time.monotonic()
        wait = quiet_timeout if responses else deadline - now
        if wait <= 0:
            break

        sock.settimeout(wait)
        try:
            data, _addr = sock.recvfrom(8192)
        except TimeoutError:
            break
        except OSError:
            break
        responses.append(data)

    return responses


def _same_netp(left: HiflyingNetp, right: HiflyingNetp) -> bool:
    """Return true when two NETP settings are equivalent."""
    return (
        left.protocol.upper() == right.protocol.upper()
        and left.mode.lower() == right.mode.lower()
        and left.port == right.port
        and left.host.lower() == right.host.lower()
    )
