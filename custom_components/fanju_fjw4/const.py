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

# Realtime sensor "type" values reported by the cloud.
SENSOR_TYPE_TEMPERATURE: Final = 1
SENSOR_TYPE_HUMIDITY: Final = 2

# Realtime sensor "channel" values reported by the cloud.
CHANNEL_INDOOR: Final = 0
CHANNEL_OUTDOOR: Final = 1

MANUFACTURER: Final = "FanJu"
MODEL: Final = "FJW4"
