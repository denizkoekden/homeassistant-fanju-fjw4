"""Sensor platform for the FanJu FJW4 weather station."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfPressure, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CHANNEL_INDOOR,
    CHANNEL_OUTDOOR,
    DOMAIN,
    MANUFACTURER,
    MODEL,
    SENSOR_TYPE_HUMIDITY,
    SENSOR_TYPE_TEMPERATURE,
)
from .coordinator import FanjuConfigEntry, FanjuDataUpdateCoordinator


def _reading(data: dict[str, Any], sensor_type: int, channel: int) -> float | None:
    """Return ``curVal`` for the matching sensor type/channel, if present."""
    for sensor in data.get("sensorDatas") or []:
        if sensor.get("type") == sensor_type and sensor.get("channel") == channel:
            value = sensor.get("curVal")
            return float(value) if value is not None else None
    return None


@dataclass(frozen=True, kw_only=True)
class FanjuSensorEntityDescription(SensorEntityDescription):
    """Describes a FanJu FJW4 sensor and how to read its value."""

    value_fn: Callable[[dict[str, Any]], float | None]


# The cloud reports temperatures in Fahrenheit; Home Assistant converts to the
# user's configured unit automatically because the native unit is set to °F.
SENSOR_DESCRIPTIONS: tuple[FanjuSensorEntityDescription, ...] = (
    FanjuSensorEntityDescription(
        key="indoor_temperature",
        translation_key="indoor_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _reading(
            data, SENSOR_TYPE_TEMPERATURE, CHANNEL_INDOOR
        ),
    ),
    FanjuSensorEntityDescription(
        key="indoor_humidity",
        translation_key="indoor_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _reading(data, SENSOR_TYPE_HUMIDITY, CHANNEL_INDOOR),
    ),
    FanjuSensorEntityDescription(
        key="outdoor_temperature",
        translation_key="outdoor_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _reading(
            data, SENSOR_TYPE_TEMPERATURE, CHANNEL_OUTDOOR
        ),
    ),
    FanjuSensorEntityDescription(
        key="outdoor_humidity",
        translation_key="outdoor_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _reading(data, SENSOR_TYPE_HUMIDITY, CHANNEL_OUTDOOR),
    ),
    FanjuSensorEntityDescription(
        key="pressure",
        translation_key="pressure",
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        native_unit_of_measurement=UnitOfPressure.HPA,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: (
            float(data["atmos"]) if data.get("atmos") is not None else None
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FanjuConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up FanJu FJW4 sensors from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        FanjuSensor(coordinator, description) for description in SENSOR_DESCRIPTIONS
    )


class FanjuSensor(CoordinatorEntity[FanjuDataUpdateCoordinator], SensorEntity):
    """A single FanJu FJW4 sensor reading."""

    entity_description: FanjuSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: FanjuDataUpdateCoordinator,
        description: FanjuSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description

        device = coordinator.device
        identifier = str(
            device.get("sn") or device.get("mac") or coordinator.config_entry.entry_id
        )
        self._attr_unique_id = f"{identifier}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, identifier)},
            name=device.get("alias") or f"{MANUFACTURER} {MODEL}",
            manufacturer=MANUFACTURER,
            model=MODEL,
            serial_number=device.get("sn"),
        )

    @property
    def native_value(self) -> float | None:
        """Return the current value for this sensor."""
        return self.entity_description.value_fn(self.coordinator.data)
