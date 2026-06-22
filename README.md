# FanJu FJW4 Weather Station for Home Assistant

A [Home Assistant](https://www.home-assistant.io/) custom integration for the
[FanJu FJW4 Wi-Fi Weather Station](https://www.aliexpress.com/item/32955858516.html).

It signs in to the same EMaxLife cloud the **WeatherSense** app uses and exposes
the station's indoor and outdoor sensors in Home Assistant.

> This is a port of the original
> [homebridge-fanju-fjw4](https://github.com/slavvka/homebridge-fanju-fjw4)
> plugin to a native Home Assistant integration.

## Sensors

The integration creates one device with the following sensors:

| Sensor | Source |
| --- | --- |
| Indoor temperature | main station (channel 0) |
| Indoor humidity | main station (channel 0) |
| Outdoor temperature | wireless sensor (channel 1) |
| Outdoor humidity | wireless sensor (channel 1) |
| Pressure | barometer (`atmos`) |

Temperatures are reported by the cloud in Fahrenheit; Home Assistant converts
them automatically to the unit configured for your system. You can assign each
entity to a different area (e.g. put the outdoor sensors on your balcony).

## Installation

### HACS (recommended)

1. In HACS, open the three-dot menu → **Custom repositories**.
2. Add `https://github.com/denizkoekden/homeassistant-fanju-fjw4` as an
   **Integration**.
3. Search for **FanJu FJW4 Weather Station**, install it, and restart Home
   Assistant.

### Manual

Copy `custom_components/fanju_fjw4` into your Home Assistant
`config/custom_components/` directory and restart Home Assistant.

## Configuration

Add the integration via the UI:

1. **Settings → Devices & services → Add integration**.
2. Search for **FanJu FJW4 Weather Station**.
3. Enter the **email** and **password** you use in the WeatherSense app.

The polling interval (default 600 s, minimum 60 s) can be changed at any time via
the integration's **Configure** button.

## License

Apache-2.0 — see [LICENSE](LICENSE).
