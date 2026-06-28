# FanJu FJW4 weather station for Home Assistant

A custom integration for the [FanJu FJW4](https://www.aliexpress.com/item/32955858516.html)
Wi-Fi weather station — the one you set up with the WeatherSense app (it also
shows up under a few other brand names with the same EMaxLife cloud behind it).

I started from the [homebridge-fanju-fjw4](https://github.com/slavvka/homebridge-fanju-fjw4)
plugin and rebuilt it as a native Home Assistant integration. It exposes the
indoor and outdoor temperature and humidity.

There are two ways to run it: through the cloud, or directly on your LAN.

## Cloud

The easy one. Give it the same email and password you use in the WeatherSense
app and it polls the EMaxLife cloud the app talks to. Default poll is every 10
minutes; change it under **Configure** (60s minimum).

One thing worth knowing: the vendor's TLS certificate has been expired for ages.
The integration skips verification for that single host, exactly like the app
does. Nothing else on your machine is affected.

## Local (no cloud)

I didn't love that a thermometer on my balcony had to round-trip through a server
in China to show up in my own house, so the integration can read the station
straight off the network instead.

The station's Wi-Fi is a Hi-Flying HF-LPT230 module. All it really does is take
whatever the station pushes over its serial port and fire it at the EMaxLife
cloud as a UDP packet on port 10000, about once a minute. Where it sends that is
just a setting in the module, and you can change it over the network — no web
login required.

So in local mode Home Assistant:

- listens on UDP 10000 and decodes the packets itself, and
- by default also forwards each one to the real cloud and hands the reply back,
  so the WeatherSense app keeps working as if nothing changed.

During setup it looks for the module on the LAN (UDP 48899) and, if you let it,
repoints the module at Home Assistant for you. Some of these modules forget that
after a power cut, so it re-checks every few minutes and sets it again if the
station has drifted back to the cloud.

Be patient after the first setup: it can take a while for the first reading to
show up — usually a few minutes, but give it **15–30 minutes** before worrying.
The module sometimes keeps sending to its previous target until it next cycles,
and the integration only re-checks every five minutes. Once data is flowing the
station reports about once a minute. That interval is fixed by the station's main
board, not the Wi-Fi module, so there's no setting to make it report faster.

A note on pressure: the station doesn't actually transmit a barometer reading
over the wire — only temperature and humidity go out. The pressure you see in the
WeatherSense app is the vendor cloud filling in a weather-service value for the
station's GPS location, not the device's own sensor, so there's no pressure
entity (in either mode). If you want local pressure, a regular Home Assistant
weather integration does the same thing, more honestly.

## Sensors

| Sensor | Source |
| --- | --- |
| Indoor temperature | main station |
| Indoor humidity | main station |
| Outdoor temperature | wireless 433 MHz sensor |
| Outdoor humidity | wireless 433 MHz sensor |

Temperatures arrive in Fahrenheit and Home Assistant converts them to whatever
your system uses. Each entity can sit in its own area, so the outdoor sensors can
live on the balcony while the rest stays inside.

## Installing

**HACS:** three-dot menu → Custom repositories → add
`https://github.com/denizkoekden/homeassistant-fanju-fjw4` as an Integration,
then install **FanJu FJW4 Weather Station** and restart.

**Manual:** drop `custom_components/fanju_fjw4` into your
`config/custom_components/` folder and restart.

## Setting it up

Go to Settings → Devices & services → Add integration, search for **FanJu FJW4**,
and pick **Cloud** or **Local**.

## License

Apache-2.0 — see [LICENSE](LICENSE).
