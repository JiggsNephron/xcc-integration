"""Native control regression tests; all writes are mocked, never live."""
import ast
import asyncio
from datetime import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from .test_circuit_namespacing import _load_module, _xcc_client as client_module, _entity_helpers as helpers

controls = _load_module("_xcc_controls", "control_helpers.py")
parser_module = _load_module("descriptor_parser", "descriptor_parser.py")
writer = _load_module("_xcc_writer", "value_writer.py")
ROOT = Path(__file__).parents[1] / "custom_components" / "xcc"


@pytest.mark.parametrize("prop", ["TUVMINIMALNI", "TUVUTLUM", "TUVUTLUMMIN", "TO-HYSTEREZEPOKOJOVETEPLOTY", "OKRUH1-ADAPTACE-HYSTEREZEH"])
def test_temperature_precision(prop):
    assert controls.native_number_step(prop, {"step": 1}, {"internal_name": "__R123_REAL_.1f"}) == .1
    assert controls.native_number_step(prop, {"step": .5, "step_explicit": True}, {"internal_name": "__R123_REAL_.1f"}) == .5
    assert controls.native_number_step(prop, {"step": 1}, {"internal_name": "__R123_INT_d"}) == 1


def test_descriptor_integer_curve_and_actions():
    configs = parser_module.XCCDescriptorParser().parse_descriptor_files({"tuv1.xml": '''<page>
    <row><number prop="TO-EK101" digits="0"/><number prop="TUVMINIMALNI"/></row>
    <row><time prop="TSC-CAS"/><time prop="READONLY" config="readonly"/></row>
    <row><button prop="MAIN-PRIORIZATORSPOTREBY-PRITUV-SANITACE" value="0" text_en="Stop"/>
    <button prop="MAIN-PRIORIZATORSPOTREBY-PRITUV-SANITACE" value="1" text_en="Run"/></row></page>'''})
    assert configs["TO-EK101"]["step"] == 1
    assert configs["TO-EK101"]["unit"] == "°C"
    assert "point 11" in configs["TO-EK101"]["friendly_name_en"]
    assert configs["TSC-CAS"]["time_control"]
    assert not configs["READONLY"]["time_control"]
    sanitation = configs["MAIN-PRIORIZATORSPOTREBY-PRITUV-SANITACE"]
    assert sanitation["button_value"] == "1"
    assert [x["value"] for x in sanitation["button_actions"]] == ["0", "1"]


def test_curve_pipeline_preserves_both_circuits_and_ignores_floor_curing():
    raw = []
    for page, register in [("OKRUH20.XML", "__R10"), ("OKRUH21.XML", "__R20")]:
        raw += client_module.parse_xml_entities(f'<root><INPUT P="TO-EK00" NAME="{register}_REAL_.1f" VALUE="-13"/><INPUT P="TO-NATOP-START" NAME="__R30_BOOL_i" VALUE="1"/></root>', page)
    data, metadata = helpers.process_entities(raw, {"TO-EK00": {"entity_type": "number", "writable": True}}, "english")
    assert set(data["numbers"]) == {"xcc_to_ek00", "xcc_okruh1_ek00"}
    assert all(x["device"] == "OKRUH" for x in metadata.values())


def metadata(prop, writable=False, register="__R100_TIME_Thh:mm"):
    return {"prop": prop, "descriptor_config": {"time_control": writable}, "data": {"attributes": {"internal_name": register}}}


def test_clock_selection_and_duration_format():
    for prop in ["PAGE-OKRUH10-US-MON-TON1", "PAGE-OKRUH112-US-SUN-TOFF2", "PAGE-TUV11-US-TUE-TON2"]:
        assert controls.clock_control(metadata(prop))
    assert controls.clock_control(metadata("TSC-CAS", True))
    assert not controls.clock_control(metadata("TSC-CAS", False))
    assert not controls.clock_control(metadata("PAGE-TUV11-US-MON-TON1", register=""))
    assert not controls.clock_control(metadata("PAGE-TUV11-CS-MON-TON1"))
    assert not controls.clock_control(metadata("TO-ADAPTACE-DOCASNEBEZCIDLACAS", True))
    assert controls.duration_prop("OKRUH1-ADAPTACE-DOCASNEBEZCIDLACAS")
    assert controls.clock_value("08:10") == time(8, 10)
    assert controls.clock_value("24:00") is None
    assert controls.duration_minutes("27:30") == 1650
    assert controls.duration_value(90) == "01:30"
    with pytest.raises(ValueError):
        controls.duration_value(1.5)
    assert "period 2 end" in controls.schedule_name("PAGE-TUV11-US-MON-TOFF2")


@pytest.mark.asyncio
@pytest.mark.parametrize("prop,page,raw_prop", [
    ("TO-EK00", "OKRUH20.XML", "TO-EK00"),
    ("OKRUH1-EK111", "OKRUH21.XML", "TO-EK111"),
    ("OKRUH12-POSUN", "OKRUH212.XML", "TO-POSUN"),
    ("PAGE-OKRUH11-US-MON-TON1", "OKRUH11.XML", "US-MON-TON1"),
    ("PAGE-TUV11-US-SUN-TOFF2", "TUV11.XML", "US-SUN-TOFF2"),
    ("TSC-CAS", "TUV11.XML", "TSC-CAS"),
    ("TUVTPS-DAY10-ONTIME", "TUV13.XML", "TUVTPS-DAY10-ONTIME"),
    ("MAIN-PRIORIZATORSPOTREBY-PRITUV-SANITACE", "TUV11.XML", "MAIN-PRIORIZATORSPOTREBY-PRITUV-SANITACE"),
])
async def test_native_write_routes(prop, page, raw_prop):
    client = client_module.XCCClient("192.0.2.1", "test", "test")
    client.fetch_page = AsyncMock(return_value=f'<root><INPUT P="{raw_prop}" NAME="__R100_TIME_Thh:mm" VALUE="08:00"/></root>')
    response = MagicMock(status=200)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=False)
    client.session = MagicMock()
    client.session.post.return_value = context
    assert await client.set_value(prop, "0")
    client.fetch_page.assert_awaited_once_with(page)
    client.session.post.assert_called_once_with(f"http://192.0.2.1/{page}", data={"__R100_TIME_Thh:mm": "0"})
    assert await client.set_value("PAGE-TUV11-PAGENAME", "test") is False


@pytest.mark.asyncio
async def test_discovery_follows_enabled_circuits_and_curve_groups():
    client = client_module.XCCClient("192.0.2.1", "test", "test")
    client.discover_active_pages = AsyncMock(return_value={
        "okruh.xml?page=3": {"active": True, "enabled": True, "name": "Guest wing"},
        "okruh.xml?page=4": {"active": False, "enabled": False, "name": "Unused"},
    })
    client.discover_data_pages = AsyncMock(return_value={"okruh.xml": ["OKRUH10.XML", "OKRUH11.XML"]})
    client.fetch_page = AsyncMock(return_value="<root>" + " " * 120 + "</root>")
    descriptors, pages = await client.auto_discover_all_pages()
    assert "okruh.xml" in descriptors
    assert set(pages) == {"OKRUH13.XML", "OKRUH23.XML"}
    assert all(call.args[0] != "OKRUH24.XML" for call in client.fetch_page.await_args_list)


@pytest.mark.asyncio
async def test_declared_temperature_raising_page_is_discovered():
    client = client_module.XCCClient("192.0.2.1", "test", "test")
    async def fetch(page):
        if page == "tuv1.xml":
            return '<page><block data="TUV13"/><block data="TUV12"/></page>'
        if page == "TUV13.XML":
            return "<root>" + " " * 120 + "</root>"
        raise OSError("not installed")
    client.fetch_page = AsyncMock(side_effect=fetch)
    result = await client.discover_data_pages(["tuv1.xml"])
    assert result == {"tuv1.xml": ["TUV13.XML"]}


def test_time_entity_write_resolution_preserves_sensor_register():
    data = {"entities": [{"entity_id": "xcc_page_tuv11_us_mon_ton1", "prop": "PAGE-TUV11-US-MON-TON1", "attributes": {"internal_name": "__R39409_TIME_Thh:mm"}}]}
    resolved = writer.resolve_property("xcc_page_tuv11_us_mon_ton1", data, {})
    assert resolved.prop == "PAGE-TUV11-US-MON-TON1"
    assert resolved.internal_name == "__R39409_TIME_Thh:mm"


def test_time_platform_loads_once_and_preserves_identity():
    tree = ast.parse((ROOT / "time.py").read_text(encoding="utf-8"))
    source = (ROOT / "time.py").read_text(encoding="utf-8")
    assert "async_config_entry_first_refresh" not in source
    class Base:
        def __init__(self, coordinator, key):
            self.coordinator = coordinator
            self.entity_id_suffix = key
            self._entity_data = coordinator.get_entity_data(key)
            self._attr_unique_id = "ip_" + key
    class TimeEntity:
        pass
    class HAError(Exception):
        pass
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    ns = {"XCCEntity": Base, "TimeEntity": TimeEntity, "time": time, "schedule_name": controls.schedule_name,
          "clock_value": controls.clock_value, "HomeAssistantError": HAError}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "time.py", "exec"), ns)
    entry = {"prop": "PAGE-TUV11-US-MON-TON1", "data": {"state": "09:00"}}
    coord = SimpleNamespace(get_entity_data=lambda key: entry, last_update_success=True,
                            async_set_entity_value=AsyncMock(return_value=True))
    entity = ns["XCCTime"](coord, "xcc_page_tuv11_us_mon_ton1")
    assert entity.entity_id == "time.xcc_page_tuv11_us_mon_ton1"
    assert entity.native_value == time(9)
    asyncio.run(entity.async_set_value(time(10, 30)))
    coord.async_set_entity_value.assert_awaited_once_with("xcc_page_tuv11_us_mon_ton1", "10:30")
    entry["data"]["state"] = "10:30"
    assert entity.native_value == time(10, 30)
    entry["data"]["state"] = "unavailable"
    assert not entity.available
    coord.async_set_entity_value.return_value = False
    with pytest.raises(HAError):
        asyncio.run(entity.async_set_value(time(11)))
    with pytest.raises(HAError):
        asyncio.run(entity.async_set_value(time(11, 0, 30)))


def test_sanitation_stop_preserves_run_identity_and_action_values():
    tree = ast.parse((ROOT / "button.py").read_text(encoding="utf-8"))
    class Button:
        def __init__(self, coordinator, data):
            self.entity_id_suffix = data["entity_id"]
            self.entity_id = "button." + self.entity_id_suffix
            self._attr_unique_id = "ip_" + self.entity_id_suffix
            self._button_value = "1"
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "XCCSanitationStop")
    ns = {"XCCButton": Button}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "button.py", "exec"), ns)
    original = "xcc_main_priorizatorspotreby_prituv_sanitace"
    run = Button(None, {"entity_id": original})
    stop = ns["XCCSanitationStop"](None, {"entity_id": original})
    assert run.entity_id == "button." + original
    assert stop.entity_id == run.entity_id + "_stop"
    assert stop._attr_unique_id == run._attr_unique_id + "_stop"
    assert (run._button_value, stop._button_value) == ("1", "0")


@pytest.mark.asyncio
async def test_duration_command_success_failure_and_cancellation():
    tree = ast.parse((ROOT / "number.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "XCCDuration")
    node = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef))
    class HAError(Exception):
        pass
    ns = {"duration_value": controls.duration_value, "HomeAssistantError": HAError}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "number.py", "exec"), ns)
    command = AsyncMock(return_value=True)
    entity = SimpleNamespace(coordinator=SimpleNamespace(async_set_entity_value=command),
                             entity_id_suffix="xcc_tuvdobaklidu", native_max_value=1439)
    await ns["async_set_native_value"](entity, 45)
    command.assert_awaited_once_with("xcc_tuvdobaklidu", "00:45")
    for outcome in [False, OSError("offline"), asyncio.CancelledError()]:
        command.reset_mock()
        command.return_value = outcome
        command.side_effect = outcome if isinstance(outcome, BaseException) else None
        error = asyncio.CancelledError if isinstance(outcome, asyncio.CancelledError) else HAError
        with pytest.raises(error):
            await ns["async_set_native_value"](entity, 45)
    command.reset_mock()
    with pytest.raises(HAError):
        await ns["async_set_native_value"](entity, 1.5)
    command.assert_not_awaited()
