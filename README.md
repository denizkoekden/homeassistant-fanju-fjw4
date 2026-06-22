# FanJu FJW4 weather station for Home Assistant

A custom integration for the [FanJu FJW4](https://www.aliexpress.com/item/32955858516.html)
Wi-Fi weather station — the one you set up with the WeatherSense app (it also
shows up under a few other brand names with the same EMaxLife cloud behind it).

I started from the [homebridge-fanju-fjw4](https://github.com/slavvka/homebridge-fanju-fjw4)
plugin and rebuilt it as a native Home Assistant integration. It exposes the
indoor and outdoor temperature and humidity plus the barometer.

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

Temperature, humidity and pressure are all read straight out of the packets. The
pressure encoding is a little odd — the firmware stores it inverted — but it
lines up with the cloud, so you get the full set of readings without an account.

## Sensors

| Sensor | Source |
| --- | --- |
| Indoor temperature | main station |
| Indoor humidity | main station |
| Outdoor temperature | wireless 433 MHz sensor |
| Outdoor humidity | wireless 433 MHz sensor |
| Pressure | barometer |

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
