"""Constants for the FanJu FJW4 weather station integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "fanju_fjw4"

# Vendor cloud (EMaxLife / WeatherSense) used by the FanJu FJW4 station.
API_BASE_URL: Final = "https://app.emaxlife.net/V1.0"
# Static salt appended to the password before it is MD5 hashed for login.
MD5_KEY: Final = "emax@pwd123"

# Polling.
DEFAULT_SCAN_INTERVAL: Final = 600  # seconds
MIN_SCAN_INTERVAL: Final = 60  # seconds

# Connection mode (cloud polling vs. local UDP push).
CONF_MODE: Final = "mode"
MODE_CLOUD: Final = "cloud"
MODE_LOCAL: Final = "local"

# Local (UDP push) mode.
CONF_LISTEN_PORT: Final = "listen_port"
CONF_FORWARD: Final = "forward_to_cloud"
CONF_CONFIGURE_STATION: Final = "configure_station"
CONF_STATION_HOST: Final = "station_host"
CONF_STATION_MAC: Final = "station_mac"
CONF_TARGET_HOST: Final = "target_host"
CONF_CLOUD_UPLOAD_HOST: Final = "cloud_upload_host"
CONF_CLOUD_UPLOAD_PORT: Final = "cloud_upload_port"
# The station's HF-LPT230 module uploads to this host:port; in hybrid mode we
# relay each datagram on to it so the vendor cloud / app keep working.
DEFAULT_LISTEN_PORT: Final = 10000
CLOUD_UPLOAD_HOST: Final = "app.emaxlife.net"
CLOUD_UPLOAD_PORT: Final = 10000
CONFIG_CHECK_INTERVAL: Final = 300  # seconds

# Realtime sensor "type" values reported by the cloud.
SENSOR_TYPE_TEMPERATURE: Final = 1
SENSOR_TYPE_HUMIDITY: Final = 2

# Realtime sensor "channel" values reported by the cloud.
CHANNEL_INDOOR: Final = 0
CHANNEL_OUTDOOR: Final = 1

MANUFACTURER: Final = "FanJu"
MODEL: Final = "FJW4"
