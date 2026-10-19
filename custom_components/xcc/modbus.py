"""Optional read-only Modbus transport, isolated from XCC web polling."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import math

import voluptuous as vol

from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

from .const import (
    CONF_MODBUS_SCAN_INTERVAL,
    DEFAULT_MODBUS_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)
SERVICE_READ = "read_modbus"
READ_TYPES = {
    "holding": "read_holding_registers",
    "input": "read_input_registers",
    "coil": "read_coils",
    "discrete_input": "read_discrete_inputs",
}


def decode_register(raw: int, *, signed: bool, scale: float) -> float:
    """Decode a single 16-bit register; scale is a divisor, not an offset."""
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("Scale divisor must be finite and positive")
    return (raw - 65536 if signed and raw >= 32768 else raw) / scale


def validate_read(address: int, count: int, register_type: str) -> None:
    """Bound diagnostic reads, including calls that bypass the service schema."""
    if register_type not in READ_TYPES:
        raise ValueError("Only read-only Modbus register types are supported")
    if not 0 <= address <= 65535 or not 1 <= count <= 32 or address + count > 65536:
        raise ValueError("Address/count outside allowed range (maximum 32 values)")


class XCCModbusCoordinator(DataUpdateCoordinator):
    """One serialized TCP connection for polling and ad-hoc read diagnostics."""

    def __init__(self, hass, entry):
        interval = entry.options.get(
            CONF_MODBUS_SCAN_INTERVAL,
            entry.data.get(CONF_MODBUS_SCAN_INTERVAL, DEFAULT_MODBUS_SCAN_INTERVAL),
        )
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=f"{DOMAIN}_modbus",
            update_interval=timedelta(seconds=max(10, min(3600, int(interval)))),
        )
        self.host = entry.data["ip_address"]
        self._client = AsyncModbusTcpClient(
            self.host, port=502, timeout=3, retries=0, reconnect_delay=0,
        )
        self._io_lock = asyncio.Lock()
        self._closed = False

    async def _read_unlocked(self, address, count, register_type):
        if self._closed:
            raise UpdateFailed("XCC Modbus connection has been unloaded")
        if not self._client.connected and not await self._client.connect():
            raise UpdateFailed("Cannot connect to XCC Modbus TCP")
        response = await getattr(self._client, READ_TYPES[register_type])(
            address, count=count, device_id=1,
        )
        if response.isError():
            # An unsupported address must not poison unrelated telemetry.
            raise UpdateFailed(f"XCC rejected Modbus read: {response}")
        bits = register_type in ("coil", "discrete_input")
        values = response.bits if bits else response.registers
        if len(values) < count:
            raise UpdateFailed("Incomplete Modbus response")
        return list(values[:count])

    async def async_read(self, address, count=1, register_type="holding"):
        """Read only; never accepts a function code or a value to write."""
        validate_read(address, count, register_type)
        async with self._io_lock:
            try:
                async with asyncio.timeout(10):
                    return await self._read_unlocked(address, count, register_type)
            except (OSError, TimeoutError, ModbusException) as err:
                self._client.close()
                raise UpdateFailed(f"Modbus read failed: {err}") from err

    async def _async_update_data(self):
        # Publish one complete sample, not partial/stale values after failure.
        async with self._io_lock:
            try:
                async with asyncio.timeout(10):
                    flow = (await self._read_unlocked(1, 1, "holding"))[0]
                    returned = (await self._read_unlocked(284, 1, "holding"))[0]
                    rate = (await self._read_unlocked(360, 1, "holding"))[0]
            except (OSError, TimeoutError, ModbusException) as err:
                self._client.close()
                raise UpdateFailed(f"Modbus telemetry failed: {err}") from err
        return {
            "flow_temperature": decode_register(flow, signed=True, scale=100),
            "return_temperature": decode_register(returned, signed=True, scale=100),
            "water_flow_rate": decode_register(rate, signed=False, scale=100),
        }

    async def async_shutdown(self):
        """Stop scheduled work before closing the sole connection."""
        await super().async_shutdown()
        async with self._io_lock:
            self._closed = True
            self._client.close()


def async_register_diagnostics(hass):
    """Expose an admin-only response action using an existing XCC connection."""
    if hass.services.has_service(DOMAIN, SERVICE_READ):
        return

    async def read_modbus(call):
        entry_id = call.data["entry_id"]
        web = hass.data.get(DOMAIN, {}).get(entry_id)
        coordinator = getattr(web, "modbus_coordinator", None)
        if coordinator is None:
            raise ServiceValidationError("Enable Modbus telemetry on this XCC entry first")
        address = call.data["address"]
        count = call.data["count"]
        kind = call.data["register_type"]
        try:
            raw = await coordinator.async_read(address, count, kind)
        except (HomeAssistantError, ValueError) as err:
            raise ServiceValidationError(str(err)) from err
        try:
            decoded = raw if kind in ("coil", "discrete_input") else [
                decode_register(v, signed=call.data["signed"], scale=call.data["scale"])
                for v in raw
            ]
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        return {
            "entry_id": entry_id, "register_type": kind, "address": address,
            "count": count, "raw": raw, "values": decoded,
            "scale": call.data["scale"], "signed": call.data["signed"],
        }

    async_register_admin_service(
        hass, DOMAIN, SERVICE_READ, read_modbus,
        schema=vol.Schema({
            vol.Required("entry_id"): cv.string,
            vol.Required("address"): vol.All(vol.Coerce(int), vol.Range(min=0, max=65535)),
            vol.Optional("count", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=32)),
            vol.Optional("register_type", default="holding"): vol.In(READ_TYPES),
            vol.Optional("signed", default=False): cv.boolean,
            vol.Optional("scale", default=1): vol.All(vol.Coerce(float), vol.Range(min=0.000001, max=1000000)),
        }),
        supports_response=SupportsResponse.ONLY,
    )
