"""Hydraulic telemetry entities with availability independent of the web API."""

from homeassistant.components.sensor import (
    SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass,
)
from homeassistant.const import UnitOfTemperature, UnitOfVolumeFlowRate
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LANGUAGE_ENGLISH

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
        parent = dr.async_get(coordinator.hass).async_get_device(
            identifiers={(DOMAIN, coordinator.host)}
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{coordinator.host}_STAVJED")},
            "name": "Unit Status" if coordinator.language == LANGUAGE_ENGLISH else "Stav jednotky",
            "manufacturer": "XCC",
            "model": "System Status Monitor" if coordinator.language == LANGUAGE_ENGLISH else "Monitor stavu systému",
        }
        if parent is not None:
            self._attr_device_info["via_device_id"] = parent.id

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get(self.entity_description.key)
