"""Offline runtime tests; HA lifecycle is stubbed, PyModbus itself is real.

No test connects to an XCC controller. The wire test uses a loopback simulator.
These do not replace a staging test in the supported Home Assistant release.
"""

import asyncio
from dataclasses import dataclass
from enum import Enum
import importlib.util
from pathlib import Path
import struct
import sys
import types
from unittest.mock import AsyncMock, Mock

import pytest
import voluptuous as vol

ROOT = Path(__file__).parents[1] / "custom_components" / "xcc"


class HAError(Exception):
    pass


class Coordinator:
    def __init__(self, hass, logger, **kwargs):
        self.hass = hass
        self.data = None
        self.last_update_success = True
        self.update_interval = kwargs.get("update_interval")

    async def async_refresh(self):
        try:
            self.data = await self._async_update_data()
            self.last_update_success = True
        except HAError:
            self.last_update_success = False

    async def async_shutdown(self):
        pass


class CoordinatorEntity:
    def __init__(self, coordinator):
        self.coordinator = coordinator

    @property
    def available(self):
        return self.coordinator.last_update_success


class FakeClient:
    def __init__(self, *args, **kwargs):
        self.connected = False
        self.connect_ok = True
        self.calls = []
        self.active = 0
        self.max_active = 0
        self.fail_address = None
        self.short = False
        self.closed = False

    async def connect(self):
        self.connected = self.connect_ok
        return self.connected

    def close(self):
        self.connected = False
        self.closed = True

    async def read_holding_registers(self, address, *, count, device_id):
        self.calls.append((address, count, device_id))
        self.active += 1
        self.max_active = max(self.active, self.max_active)
        await asyncio.sleep(0)
        self.active -= 1
        if self.fail_address == address:
            return types.SimpleNamespace(isError=lambda: True)
        values = {1: 3022, 284: 2855, 285: 3210, 360: 180}
        return types.SimpleNamespace(
            isError=lambda: False,
            registers=[] if self.short else [values.get(address + i, 65535) for i in range(count)],
        )

    async def read_coils(self, address, *, count, device_id):
        self.calls.append((address, count, device_id))
        return types.SimpleNamespace(isError=lambda: False, bits=[True] * max(8, count))


@pytest.fixture
def env(monkeypatch):
    """Import only the modules under test, not the unrelated web integration."""
    def module(name, **attrs):
        mod = types.ModuleType(name)
        mod.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, mod)
        return mod

    for name in ("homeassistant", "homeassistant.helpers", "homeassistant.components"):
        module(name, __path__=[])
    registered = {}

    def register(hass, domain, service, handler, **kwargs):
        registered.update(handler=handler, **kwargs)

    class Response(Enum):
        ONLY = "only"

    module("homeassistant.core", SupportsResponse=Response, HomeAssistant=object)
    module("homeassistant.exceptions", HomeAssistantError=HAError,
           ServiceValidationError=HAError, ConfigEntryNotReady=HAError)
    module("homeassistant.helpers.config_validation", string=str, boolean=bool,
           config_entry_only_config_schema=lambda domain: Mock())
    module("homeassistant.helpers.service", async_register_admin_service=register)
    module("homeassistant.helpers.update_coordinator", DataUpdateCoordinator=Coordinator,
           UpdateFailed=HAError, CoordinatorEntity=CoordinatorEntity)
    class Platform(str, Enum):
        SENSOR = "sensor"
        BINARY_SENSOR = "binary_sensor"
        SWITCH = "switch"
        NUMBER = "number"
        SELECT = "select"
        BUTTON = "button"
        TIME = "time"
    module("homeassistant.const", Platform=Platform,
           UnitOfTemperature=types.SimpleNamespace(CELSIUS="°C"),
           UnitOfVolumeFlowRate=types.SimpleNamespace(CUBIC_METERS_PER_HOUR="m³/h"))
    @dataclass
    class Description:
        key: str
        name: str
        device_class: str
        native_unit_of_measurement: str
        state_class: str
        suggested_display_precision: int
    module("homeassistant.components.sensor", SensorEntity=type("SensorEntity", (), {}),
           SensorEntityDescription=Description,
           SensorDeviceClass=types.SimpleNamespace(TEMPERATURE="temperature", VOLUME_FLOW_RATE="volume_flow_rate"),
           SensorStateClass=types.SimpleNamespace(MEASUREMENT="measurement"))
    module("homeassistant.config_entries", ConfigEntry=object)
    module("_xcc_modbus_test", __path__=[str(ROOT)])

    def load(name):
        full = "_xcc_modbus_test." + name
        spec = importlib.util.spec_from_file_location(full, ROOT / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, full, mod)
        spec.loader.exec_module(mod)
        return mod

    modbus = load("modbus")
    client = FakeClient()
    factory = Mock(return_value=client)
    monkeypatch.setattr(modbus, "AsyncModbusTcpClient", factory)
    hass = types.SimpleNamespace(data={}, services=Mock())
    hass.services.has_service.return_value = False
    entry = types.SimpleNamespace(data={"ip_address": "192.0.2.1"}, options={}, entry_id="test")
    coord = modbus.XCCModbusCoordinator(hass, entry)
    return types.SimpleNamespace(module=modbus, client=client, factory=factory,
                                 coord=coord, hass=hass, entry=entry, registered=registered,
                                 load=load, monkeypatch=monkeypatch, make_module=module)


@pytest.mark.parametrize("raw,signed,scale,want", [
    (3210, True, 100, 32.1), (65506, True, 100, -0.3),
    (65535, False, 100, 655.35), (180, False, 100, 1.8),
])
def test_decoding(env, raw, signed, scale, want):
    assert env.module.decode_register(raw, signed=signed, scale=scale) == want


@pytest.mark.parametrize("address,count,kind", [
    (-1, 1, "holding"), (65536, 1, "holding"), (65535, 2, "holding"),
    (1, 0, "holding"), (1, 33, "holding"), (1, 1, "write_register"),
])
async def test_reject_invalid_reads_before_io(env, address, count, kind):
    with pytest.raises(ValueError):
        await env.coord.async_read(address, count, kind)
    assert not env.client.calls


async def test_poll_scaling_and_fixed_endpoint(env):
    await env.coord.async_refresh()
    assert env.coord.data == {"flow_temperature": 30.22, "return_temperature": 28.55, "water_flow_rate": 1.8}
    assert env.client.calls == [(1, 1, 1), (284, 1, 1), (360, 1, 1)]
    assert env.factory.call_args.args == ("192.0.2.1",)
    assert env.factory.call_args.kwargs["port"] == 502
    assert env.coord.update_interval.total_seconds() == 15


async def test_diagnostics_and_poll_share_serialized_client(env):
    await asyncio.gather(env.coord.async_refresh(), env.coord.async_read(285), env.coord.async_read(1))
    assert env.factory.call_count == 1
    assert env.client.max_active == 1


async def test_failure_recovery_and_diagnostic_error_isolation(env):
    await env.coord.async_refresh()
    old = env.coord.data.copy()
    env.client.fail_address = 284
    await env.coord.async_refresh()
    assert not env.coord.last_update_success
    assert env.coord.data == old  # no partial publication
    env.client.fail_address = 285
    await env.coord.async_refresh()
    assert env.coord.last_update_success
    with pytest.raises(HAError):
        await env.coord.async_read(285)
    assert env.coord.last_update_success  # optional unsupported probe does not poison telemetry
    await env.coord.async_refresh()
    assert env.coord.last_update_success


async def test_no_connection_and_shutdown(env):
    env.client.connect_ok = False
    await env.coord.async_refresh()
    assert not env.coord.last_update_success
    env.client.connect_ok = True
    await env.coord.async_refresh()
    assert env.coord.last_update_success
    await env.coord.async_shutdown()
    assert env.client.closed
    with pytest.raises(HAError):
        await env.coord.async_read(1)


async def test_short_response_rejected(env):
    env.client.short = True
    with pytest.raises(HAError, match="Incomplete"):
        await env.coord.async_read(1)


async def test_coils_trim_padding(env):
    assert await env.coord.async_read(33, 2, "coil") == [True, True]


async def test_response_action_is_admin_only_and_read_only(env):
    env.hass.data = {"xcc": {"test": types.SimpleNamespace(modbus_coordinator=env.coord)}}
    env.module.async_register_diagnostics(env.hass)
    schema = env.registered["schema"]
    payload = schema({"entry_id": "test", "address": 285, "signed": True, "scale": 100})
    response = await env.registered["handler"](types.SimpleNamespace(data=payload))
    assert response["raw"] == [3210]
    assert response["values"] == [32.1]
    assert env.registered["supports_response"].value == "only"
    for bad in ({"value": 1}, {"function_code": 6}, {"register_type": "write_register"}):
        with pytest.raises(vol.Invalid):
            schema({"entry_id": "test", "address": 1, **bad})
    env.hass.data = {}
    with pytest.raises(HAError, match="Enable Modbus"):
        await env.registered["handler"](types.SimpleNamespace(data=payload))


async def test_sensor_ids_units_and_independent_availability(env):
    mod = env.load("modbus_sensor")
    await env.coord.async_refresh()
    for desc in mod.SENSORS:
        sensor = mod.XCCModbusSensor(env.coord, desc)
        assert sensor.entity_id == f"sensor.xcc_modbus_{desc.key}"
        assert sensor._attr_device_info["identifiers"] == {("xcc", "192.0.2.1")}
        assert sensor.native_value == env.coord.data[desc.key]
        assert sensor.available
    env.coord.last_update_success = False
    assert not sensor.available


async def test_real_pymodbus_against_loopback_simulator(env, request):
    # HA's test plugin blocks all sockets unless explicitly enabled. Retain
    # its loopback-only destination restriction; never contact a controller.
    if importlib.util.find_spec("pytest_socket") is not None:
        request.getfixturevalue("socket_enabled")
    from pymodbus.client import AsyncModbusTcpClient
    requests = []
    async def serve(reader, writer):
        try:
            while True:
                header = await reader.readexactly(7)
                transaction, protocol, length, unit = struct.unpack(">HHHB", header)
                pdu = await reader.readexactly(length - 1)
                function, address, count = struct.unpack(">BHH", pdu)
                requests.append((function, address, count, unit))
                assert function == 3  # simulator refuses any writes
                values = {1: 3022, 284: 2855, 285: 3210, 360: 180}
                body = bytes([function, count * 2]) + b"".join(
                    struct.pack(">H", values.get(address + i, 0)) for i in range(count)
                )
                writer.write(struct.pack(">HHHB", transaction, protocol, len(body) + 1, unit) + body)
                await writer.drain()
        except asyncio.IncompleteReadError:
            pass
        finally:
            writer.close()
            await writer.wait_closed()
    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    env.coord._client = AsyncModbusTcpClient("127.0.0.1", port=port, retries=0)
    try:
        await env.coord.async_refresh()
        assert env.coord.last_update_success
        assert await env.coord.async_read(285) == [3210]
        assert requests == [(3, 1, 1, 1), (3, 284, 1, 1), (3, 360, 1, 1), (3, 285, 1, 1)]
    finally:
        await env.coord.async_shutdown()
        server.close()
        await server.wait_closed()


@pytest.mark.parametrize("web_ok,modbus_enabled,modbus_ok", [
    (True, False, True), (True, True, False), (False, True, True), (False, True, False),
])
async def test_startup_interfaces_are_independent(env, web_ok, modbus_enabled, modbus_ok):
    class Web:
        def __init__(self, hass, entry):
            self.ip_address = entry.data["ip_address"]
            self.device_info = {}
            self.modbus_coordinator = None
            self.loaded_platforms = []
            self.web_ready = False
            self.async_shutdown = AsyncMock()
        async def async_config_entry_first_refresh(self):
            if not web_ok:
                raise HAError("web unavailable")
    env.make_module("_xcc_modbus_test.coordinator", XCCDataUpdateCoordinator=Web)
    env.make_module("_xcc_modbus_test.entity", async_regenerate_entity_ids=Mock())
    registry = Mock()
    env.make_module("homeassistant.helpers.device_registry", async_get=lambda hass: registry)
    env.client.connect_ok = modbus_ok
    env.entry.options = {"modbus_enabled": modbus_enabled}
    env.entry.async_on_unload = Mock()
    env.entry.add_update_listener = Mock()
    # Close the deferred coroutine: its lifecycle is exercised separately below.
    env.entry.async_create_background_task = Mock(side_effect=lambda hass, coro, **kw: coro.close())
    env.hass.config_entries = types.SimpleNamespace(async_forward_entry_setups=AsyncMock())
    spec = importlib.util.spec_from_file_location(
        "_xcc_modbus_test.bootstrap", ROOT / "__init__.py"
    )
    bootstrap = importlib.util.module_from_spec(spec)
    bootstrap.__package__ = "_xcc_modbus_test"
    spec.submodule_search_locations = None
    spec.loader.exec_module(bootstrap)
    assert await bootstrap.async_setup_entry(env.hass, env.entry)
    web = env.hass.data["xcc"]["test"]
    assert web.web_ready is web_ok
    assert (web.modbus_coordinator is not None) is modbus_enabled
    assert web.loaded_platforms == (bootstrap.PLATFORMS_TO_SETUP if web_ok else ["sensor"])
    if modbus_enabled:
        assert web.modbus_coordinator.last_update_success is modbus_ok
        if not web_ok:
            # Web recovery adds deferred platforms without replacing Modbus.
            original = web.modbus_coordinator
            web.async_add_web_sensors = AsyncMock()
            web.last_update_success = False
            async def recover():
                web.last_update_success = True
            web.async_refresh = recover
            sleep = asyncio.sleep
            async def fast_sleep(seconds):
                await sleep(0)
            env.monkeypatch.setattr(bootstrap.asyncio, "sleep", fast_sleep)
            await bootstrap._async_retry_web_setup(env.hass, env.entry, web)
            assert web.web_ready
            assert web.modbus_coordinator is original
            assert set(web.loaded_platforms) == set(bootstrap.PLATFORMS_TO_SETUP)
            web.async_add_web_sensors.assert_awaited_once()
        await web.modbus_coordinator.async_shutdown()


async def test_options_flow_defaults_bounds_and_preserves_other_options(env):
    class Flow:
        def __init_subclass__(cls, **kwargs):
            pass
        def async_show_form(self, **kwargs):
            return kwargs
        def async_create_entry(self, **kwargs):
            return kwargs
    env.make_module("homeassistant.config_entries", ConfigEntry=object,
                    ConfigFlow=Flow, ConfigFlowResult=dict, OptionsFlow=Flow)
    core = sys.modules["homeassistant.core"]
    env.monkeypatch.setattr(core, "callback", lambda f: f, raising=False)
    const = sys.modules["homeassistant.const"]
    for name, value in (("CONF_IP_ADDRESS", "ip_address"), ("CONF_USERNAME", "username"),
                        ("CONF_PASSWORD", "password")):
        env.monkeypatch.setattr(const, name, value, raising=False)
    flow = env.load("config_flow")
    env.entry.options = {"unrelated_option": True}
    handler = flow.XCCOptionsFlowHandler(env.entry)
    form = await handler.async_step_init()
    validated = form["data_schema"]({})
    assert validated["modbus_enabled"] is False
    assert validated["modbus_scan_interval"] == 15
    for invalid in (0, 9, 3601):
        with pytest.raises(vol.Invalid):
            form["data_schema"]({"modbus_scan_interval": invalid})
    result = await handler.async_step_init({"modbus_enabled": True, "modbus_scan_interval": 30})
    assert result["data"] == {
        "unrelated_option": True, "modbus_enabled": True, "modbus_scan_interval": 30,
    }


@pytest.mark.parametrize("scale", [0, -1, float("nan"), float("inf")])
def test_invalid_scale(env, scale):
    with pytest.raises(ValueError):
        env.module.decode_register(3000, signed=True, scale=scale)
