"""The XCC Heat Pump Controller integration."""

from __future__ import annotations

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_ENTITY_TYPE,
    CONF_MODBUS_ENABLED,
    CONF_REGENERATE_ENTITY_IDS,
    DEFAULT_ENTITY_TYPE,
    DOMAIN,
    ENTITY_TYPE_INTEGRATION,
    PLATFORMS,
)
from .coordinator import XCCDataUpdateCoordinator
from .entity import async_regenerate_entity_ids

_LOGGER = logging.getLogger(__name__)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Supported platforms
PLATFORMS_TO_SETUP = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.BUTTON,
    Platform.TIME,
]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the read-only diagnostic action once for the integration."""
    from .modbus import async_register_diagnostics

    async_register_diagnostics(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up XCC Heat Pump Controller from a config entry."""
    # Log integration version for debugging
    from .const import VERSION
    from homeassistant.helpers import device_registry as dr

    _LOGGER.info(
        "Setting up XCC integration v%s for %s", VERSION, entry.data.get("ip_address")
    )
    _LOGGER.debug("Setting up XCC integration for %s", entry.data.get("ip_address"))

    # Create data update coordinator
    coordinator = XCCDataUpdateCoordinator(hass, entry)

    # Store coordinator in hass data BEFORE first refresh
    # This allows the coordinator to be accessed during setup
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    if entry.options.get(CONF_MODBUS_ENABLED, entry.data.get(CONF_MODBUS_ENABLED, False)):
        from .modbus import XCCModbusCoordinator

        coordinator.modbus_coordinator = XCCModbusCoordinator(hass, entry)
        # A failed Modbus refresh must not prevent the web side from loading.
        await coordinator.modbus_coordinator.async_refresh()

    # Fetch initial data BEFORE setting up platforms
    # This ensures data is available when entities are created
    # With Modbus enabled, failed web discovery is retried independently.
    try:
        _LOGGER.debug("Performing initial data fetch before platform setup")
        await asyncio.wait_for(
            coordinator.async_config_entry_first_refresh(),
            timeout=60 if coordinator.modbus_coordinator is not None else None,
        )
        coordinator.web_ready = True
        _LOGGER.info("✅ Initial data fetch successful")
    except asyncio.CancelledError:
        await coordinator.async_shutdown()
        if coordinator.modbus_coordinator is not None:
            await coordinator.modbus_coordinator.async_shutdown()
        hass.data[DOMAIN].pop(entry.entry_id)
        raise
    except Exception as err:
        if coordinator.modbus_coordinator is None:
            await coordinator.async_shutdown()
            hass.data[DOMAIN].pop(entry.entry_id)
            raise ConfigEntryNotReady(f"Error fetching initial data: {err}") from err
        _LOGGER.warning("Web startup unavailable; keeping Modbus independent: %s", err)
        coordinator.data = {}
        coordinator.last_update_success = False

    device_info = coordinator.device_info or {
        "identifiers": {(DOMAIN, coordinator.ip_address)},
        "name": f"XCC Controller ({coordinator.ip_address})",
        "manufacturer": "XCC",
        "model": "Heat Pump Controller",
        "configuration_url": f"http://{coordinator.ip_address}",
    }

    # Register the main XCC controller device BEFORE setting up platforms
    # This ensures the device exists when sub-devices try to reference it via via_device
    device_registry = dr.async_get(hass)
    if device_info:
        _LOGGER.debug("Registering main XCC controller device in device registry")
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers=device_info["identifiers"],
            name=device_info["name"],
            manufacturer=device_info["manufacturer"],
            model=device_info["model"],
            sw_version=device_info.get("sw_version"),
            configuration_url=device_info.get("configuration_url"),
        )
        _LOGGER.info("✅ Main XCC controller device registered")
    else:
        _LOGGER.warning("⚠️  Coordinator device_info not available, device registration skipped")

    # Get entity type preference from config
    entity_type = entry.data.get(CONF_ENTITY_TYPE, DEFAULT_ENTITY_TYPE)
    _LOGGER.info("XCC integration configured for %s entities", entity_type)

    # Did the user opt in to entity-ID regeneration? The flag can live in
    # either ``entry.data`` (checkbox on the initial user step) or
    # ``entry.options`` (later toggle in Configure). Either turns both the
    # registry-wide sweep below AND the per-entity migration in
    # ``XCCEntity._migrate_legacy_entity_id`` on for this setup only.
    should_regenerate = bool(
        entry.data.get(CONF_REGENERATE_ENTITY_IDS)
        or entry.options.get(CONF_REGENERATE_ENTITY_IDS)
    )
    # Stash on the coordinator so entities can read it during
    # ``async_added_to_hass`` (platform setup below) without another lookup.
    # Entities must consult this attribute rather than the entry flags, which
    # we clear below to make the regeneration a one-shot operation.
    coordinator.regenerate_entity_ids = should_regenerate

    if should_regenerate:
        stats = async_regenerate_entity_ids(
            hass, entry.entry_id, entry.data.get("ip_address", "")
        )
        _LOGGER.info("🧹 Regenerated entity IDs for %s: %s", entry.title, stats)
        # Clear the one-shot flag(s) *before* wiring the update listener so
        # async_update_entry doesn't cascade into a reload of the entry we
        # are still setting up.
        if entry.data.get(CONF_REGENERATE_ENTITY_IDS):
            hass.config_entries.async_update_entry(
                entry,
                data={**entry.data, CONF_REGENERATE_ENTITY_IDS: False},
            )
        if entry.options.get(CONF_REGENERATE_ENTITY_IDS):
            hass.config_entries.async_update_entry(
                entry,
                options={**entry.options, CONF_REGENERATE_ENTITY_IDS: False},
            )

    # Register an update listener so that later changes to the options
    # (e.g. the user toggling the regenerate flag again) trigger a reload.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Set up integration platforms (sensors, binary_sensors, etc.)
    # Web platforms need discovered metadata; Modbus sensors do not.
    _LOGGER.debug("Setting up integration entities")
    _LOGGER.info("Setting up platforms: %s", [p.value for p in PLATFORMS_TO_SETUP])
    platforms = PLATFORMS_TO_SETUP if coordinator.web_ready else [Platform.SENSOR]
    await hass.config_entries.async_forward_entry_setups(entry, platforms)
    coordinator.loaded_platforms.extend(platforms)
    if not coordinator.web_ready:
        entry.async_create_background_task(
            hass, _async_retry_web_setup(hass, entry, coordinator),
            name=f"XCC web startup retry {entry.entry_id}",
        )

    _LOGGER.info("✅ XCC integration setup complete for %s", entry.data.get("ip_address"))

    return True


async def _async_retry_web_setup(hass, entry, coordinator):
    """Recover web entities without reloading or interrupting Modbus sensors."""
    while not coordinator.web_ready:
        await asyncio.sleep(30)
        try:
            await asyncio.wait_for(coordinator.async_refresh(), timeout=60)
            if not coordinator.last_update_success:
                continue
            await coordinator.async_add_web_sensors()
            for platform in PLATFORMS_TO_SETUP:
                if platform not in coordinator.loaded_platforms:
                    await hass.config_entries.async_forward_entry_setups(entry, [platform])
                    coordinator.loaded_platforms.append(platform)
            coordinator.web_ready = True
        except Exception:
            _LOGGER.exception("XCC web startup retry failed; Modbus remains independent")


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading XCC integration for %s", entry.data.get("ip_address"))

    # Get coordinator and entity type
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entity_type = entry.data.get(CONF_ENTITY_TYPE, DEFAULT_ENTITY_TYPE)

    unload_ok = True

    # Unload integration platforms
    _LOGGER.debug("Unloading integration entities")
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, coordinator.loaded_platforms
    )

    if not unload_ok:
        return False

    # Clean up coordinator resources
    try:
        if coordinator.modbus_coordinator is not None:
            await coordinator.modbus_coordinator.async_shutdown()
        await coordinator.async_shutdown()
    except Exception as err:
        _LOGGER.error("Error shutting down coordinator: %s", err)

    # Remove coordinator from hass data
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
