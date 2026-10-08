"""Native XCC clock and attenuation schedule controls; retain old sensors."""
from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .control_helpers import clock_control, clock_value, schedule_name
from .entity import XCCEntity


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Use the already refreshed coordinator; no extra startup requests."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([
        XCCTime(coordinator, key)
        for key, metadata in coordinator.entities.items()
        if clock_control(metadata)
    ])


class XCCTime(XCCEntity, TimeEntity):
    """Minute-resolution control backed by the controller's live clock field."""
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator, entity_id):
        super().__init__(coordinator, entity_id)
        self.entity_id = f"time.{entity_id}"
        self._attr_unique_id += "_time_control"
        name = schedule_name(self._entity_data.get("prop", ""))
        if name:
            config = self._entity_data.get("descriptor_config", {})
            old_name = config.get("friendly_name_en", "")
            prefix = old_name.split(" — ")[0] if config.get("configured_name") else ""
            self._attr_name = f"{prefix} — {name}" if prefix else name

    @property
    def native_value(self):
        metadata = self.coordinator.get_entity_data(self.entity_id_suffix) or {}
        return clock_value(metadata.get("data", {}).get("state", ""))

    @property
    def available(self):
        return self.coordinator.last_update_success and self.native_value is not None

    @property
    def extra_state_attributes(self):
        return {**super().extra_state_attributes, "xcc_settable": True}

    async def async_set_value(self, value: time):
        if value.second or value.microsecond:
            raise HomeAssistantError("XCC clock controls have one-minute precision")
        try:
            success = await self.coordinator.async_set_entity_value(
                self.entity_id_suffix, value.strftime("%H:%M")
            )
        except Exception as err:
            raise HomeAssistantError("Unable to complete the XCC time change") from err
        if not success:
            raise HomeAssistantError("XCC did not confirm the requested time change")
