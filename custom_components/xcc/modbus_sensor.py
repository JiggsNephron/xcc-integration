"""Hydraulic telemetry entities with availability independent of the web API."""

from homeassistant.components.sensor import (
    SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass,
)
from homeassistant.const import UnitOfTemperature, UnitOfVolumeFlowRate
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

SENSORS = (
    SensorEntityDescription(
        key="flow_temperature", name="Modbus flow temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="return_temperature", name="Modbus return temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="water_flow_rate", name="Modbus water flow rate",
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        native_unit_of_measurement=UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=2,
    ),
)


class XCCModbusSensor(CoordinatorEntity, SensorEntity):
    """Use Modbus coordinator availability, never web coordinator availability."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, description):
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.host}_modbus_{description.key}"
        self.entity_id = f"sensor.xcc_modbus_{description.key}"
        self._attr_device_info = {"identifiers": {(DOMAIN, coordinator.host)}}

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get(self.entity_description.key)
